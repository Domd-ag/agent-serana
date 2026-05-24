import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.agents.base import AgentManager, get_agent_limit
from app.agents.serana.context import (
    build_state_request_context,
    clear_working_memory_entries,
    ensure_instruction_skill_context,
    get_primary_user_input,
    remove_working_memory_entry,
    set_working_memory_entry,
)
from app.agents.serana.persona import build_serana_system_prompt
from app.core.logger import get_logger
from app.skills import SkillManager
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage


logger = get_logger(__name__)


def _record_working_memory_update(
    state: dict[str, Any],
    *,
    key: str,
    value: str,
    reason: str,
) -> dict[str, Any]:
    state = set_working_memory_entry(state, key, value)
    return add_tool_call(
        state,
        "working_memory_update",
        {"key": key, "reason": reason},
        {"value": value, "context_preview": str(state.get("working_memory_context") or "")[:240]},
    )


def add_thinking_block(state: dict[str, Any], title: str, content: str) -> dict[str, Any]:
    thinking_blocks = list(state.get("thinking_blocks", []))
    thinking_blocks.append(
        {
            "id": str(uuid.uuid4()),
            "title": title,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {**state, "thinking_blocks": thinking_blocks}


def add_tool_call(
    state: dict[str, Any],
    name: str,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
    status: str = "completed",
) -> dict[str, Any]:
    tool_calls = list(state.get("tool_calls", []))
    tool_calls.append(
        {
            "id": str(uuid.uuid4()),
            "name": name,
            "input": input_payload,
            "output": output_payload,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {**state, "tool_calls": tool_calls}


def _append_tool_result(state: dict[str, Any], tool_result: dict[str, Any]) -> dict[str, Any]:
    tool_results = list(state.get("tool_results", []))
    tool_results.append(tool_result)
    return {**state, "tool_results": tool_results}


def _normalize_complexity(raw_value: Any) -> str:
    value = str(raw_value or "").strip().lower()
    if value in {"simple", "low", "easy", "small"}:
        return "simple"
    if value in {"complex", "high", "hard", "large"}:
        return "high"
    return "medium"


def _infer_goal_type(user_input: str) -> str:
    raw_text = user_input.strip()
    text = raw_text.lower()
    if "?" in text or "？" in raw_text or text.startswith(("what", "why", "how", "when", "where", "who")):
        return "question"
    if any(keyword in raw_text or keyword in text for keyword in ["天气", "气温", "下雨", "weather"]):
        return "weather_inquiry"
    if any(keyword in text for keyword in ["research", "compare", "investigate"]):
        return "research"
    if any(keyword in text for keyword in ["plan", "schedule", "organize", "roadmap"]):
        return "planning"
    if any(keyword in text for keyword in ["build", "implement", "develop", "code", "refactor"]):
        return "build"
    if any(keyword in text for keyword in ["analyze", "audit", "review", "evaluate"]):
        return "analysis"
    return "task"

def _should_delegate(goal_type: str, complexity: str, user_input: str) -> bool:
    if complexity == "high":
        return True
    if goal_type in {"research", "planning", "build", "analysis"}:
        return True

    text = user_input.strip().lower()
    if len(text) > 120:
        return True
    return any(
        keyword in text
        for keyword in ["step by step", "multi-step", "project", "workflow", "schedule", "plan", "build"]
    )


def _build_delegation_plan(
    goal_type: str,
    complexity: str,
    user_input: str,
    subtask_count: int = 0,
) -> dict[str, Any]:
    aide_limit = get_agent_limit("aide") or 3
    forge_limit = get_agent_limit("forge") or 5

    if not _should_delegate(goal_type, complexity, user_input):
        return {
            "execution_mode": "direct",
            "parallel_aides": 0,
            "parallel_forges": 0,
            "parallel_slots": 0,
        }

    aides_by_complexity = {"simple": 1, "medium": 1, "high": 2}
    forges_by_complexity = {"simple": 1, "medium": 2, "high": 3}
    aides = aides_by_complexity.get(complexity, 1)
    forges = forges_by_complexity.get(complexity, 2)

    if goal_type == "research":
        aides += 1
        forges += 2
    elif goal_type == "planning":
        aides += 1
        forges += 1
    elif goal_type == "build":
        aides += 1
        forges += 2
    elif goal_type == "analysis":
        aides += 1
        forges += 1

    aides = min(aide_limit, max(1, aides))
    forges = min(forge_limit, max(1, forges))

    if subtask_count > 0:
        aides = min(aides, subtask_count)
        forges = min(forges, subtask_count)

    parallel_slots = min(max(subtask_count, 1), aides, forges)

    return {
        "execution_mode": "delegated",
        "parallel_aides": aides,
        "parallel_forges": forges,
        "parallel_slots": parallel_slots,
    }


def _extract_math_operation(user_input: str) -> dict[str, Any] | None:
    text = user_input.strip().lower()
    patterns = [
        (r"(-?\d+(?:\.\d+)?)\s*\+\s*(-?\d+(?:\.\d+)?)", "add", "+"),
        (r"(-?\d+(?:\.\d+)?)\s*加\s*(-?\d+(?:\.\d+)?)", "add", "+"),
        (r"(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)", "subtract", "-"),
        (r"(-?\d+(?:\.\d+)?)\s*减\s*(-?\d+(?:\.\d+)?)", "subtract", "-"),
        (r"(-?\d+(?:\.\d+)?)\s*(?:\*|x|×)\s*(-?\d+(?:\.\d+)?)", "multiply", "*"),
        (r"(-?\d+(?:\.\d+)?)\s*(?:乘以|乘)\s*(-?\d+(?:\.\d+)?)", "multiply", "*"),
        (r"(-?\d+(?:\.\d+)?)\s*(?:/|÷)\s*(-?\d+(?:\.\d+)?)", "divide", "/"),
        (r"(-?\d+(?:\.\d+)?)\s*(?:除以|除)\s*(-?\d+(?:\.\d+)?)", "divide", "/"),
    ]
    for pattern, operation, symbol in patterns:
        match = re.search(pattern, text)
        if match:
            a = float(match.group(1))
            b = float(match.group(2))
            return {
                "tool_name": operation,
                "symbol": symbol,
                "a": a,
                "b": b,
            }
    return None

def _resolve_time_tool(user_input: str) -> tuple[str, dict[str, Any]] | None:
    raw_text = user_input.strip()
    text = raw_text.lower()
    if any(keyword in raw_text or keyword in text for keyword in ["星期几", "周几", "what day", "day of week", "今天几号", "几号"]):
        return "get_day_info", {}
    if any(keyword in raw_text or keyword in text for keyword in ["几点", "时间", "time", "现在几点", "current time", "what time"]):
        return "get_current_time", {"timezone": "Asia/Shanghai", "format": "full"}
    return None

def _extract_weather_location(user_input: str) -> str | None:
    raw_text = user_input.strip()
    lowered = raw_text.lower()

    english_patterns = [
        r"weather in ([a-zA-Z\s\-]+)",
        r"forecast for ([a-zA-Z\s\-]+)",
        r"temperature in ([a-zA-Z\s\-]+)",
        r"([a-zA-Z\s\-]+) weather",
    ]
    for pattern in english_patterns:
        match = re.search(pattern, lowered)
        if match:
            return match.group(1).strip(" ?!.,")

    chinese_patterns = [
        r"(.+?)今天.*天气",
        r"(.+?)明天.*天气",
        r"(.+?)什么天气",
        r"(.+?)天气啥样",
        r"(.+?)天气怎么样",
        r"(.+?)天气如何",
        r"(.+?)天气",
    ]
    for pattern in chinese_patterns:
        match = re.search(pattern, raw_text)
        if match:
            location = match.group(1).strip(" ，。？?的")
            for prefix in ("今天", "明天", "后天", "现在", "当前"):
                if location.startswith(prefix):
                    location = location[len(prefix):].strip()
            for suffix in ("什么", "啥样", "怎么样", "如何", "天气"):
                if location.endswith(suffix):
                    location = location[: -len(suffix)].strip()
            if location:
                return location

    if "上海" in raw_text:
        return "上海"
    if "北京" in raw_text:
        return "北京"
    if "beijing" in lowered:
        return "Beijing"
    if "shanghai" in lowered:
        return "Shanghai"
    return None

def _resolve_weather_tool(user_input: str) -> tuple[str, dict[str, Any]] | None:
    raw_text = user_input.strip()
    lowered = raw_text.lower()
    weather_keywords = ["天气", "气温", "下雨", "weather", "forecast", "temperature"]
    if not any(keyword in raw_text or keyword in lowered for keyword in weather_keywords):
        return None

    location = _extract_weather_location(raw_text)
    if not location:
        return None

    if any(keyword in raw_text or keyword in lowered for keyword in ["forecast", "预报", "未来", "明天", "后天"]):
        return "get_forecast", {"location": location, "days": 1, "units": "metric"}
    return "get_current_weather", {"location": location, "units": "metric"}

def _resolve_memory_tool(user_input: str) -> tuple[str, dict[str, Any]] | None:
    raw_text = user_input.strip()
    lowered = raw_text.lower()

    working_save_prefixes = ["先记一下", "记一个", "暂时记住", "先写下"]
    for prefix in working_save_prefixes:
        if raw_text.startswith(prefix):
            remainder = raw_text[len(prefix):].strip()
            separator = "是" if "是" in remainder else ("为" if "为" in remainder else "")
            if separator:
                key, value = remainder.split(separator, 1)
                key = key.strip(" ，。！？；:.!?;")
                value = value.strip(" ，。！？；:.!?;")
                if key and value:
                    return "working_memory_save", {"key": key, "value": value, "scope": "conversation"}

    working_clear_keywords = [
        "把这轮临时笔记清掉",
        "清空这轮临时笔记",
        "清掉当前临时笔记",
        "清空当前临时笔记",
        "clear the working memory",
        "clear this temporary note",
    ]
    if any(keyword in raw_text or keyword in lowered for keyword in working_clear_keywords):
        return "working_memory_clear", {"scope": "conversation"}

    save_patterns = [
        r"(?:记住|帮我记住|请记住)[:：]?\s*(.+?)(?:是|为)\s*(.+)",
        r"(?:remember|save)\s+that\s+my\s+(.+?)\s+is\s+(.+)",
    ]
    for pattern in save_patterns:
        match = re.search(pattern, raw_text, re.IGNORECASE)
        if not match:
            continue
        key = match.group(1).strip(" ，。！？；:.!?;")
        value = match.group(2).strip(" ，。！？；:.!?;")
        if key and value:
            category = "preference" if any(keyword in key.lower() for keyword in ["喜欢", "偏好", "drink", "food"]) else ""
            return "memory_save", {"key": key, "value": value, "category": category}

    search_keywords = ["我之前说过", "我喜欢什么", "我偏好什么", "what did i say", "what do i prefer", "what do i like"]
    if any(keyword in raw_text or keyword in lowered for keyword in search_keywords):
        query = (
            raw_text.replace("我之前说过", "")
            .replace("吗", "")
            .replace("？", "")
            .replace("?", "")
            .strip()
        )
        if not query:
            query = raw_text
        return "memory_search", {"query": query, "limit": 5}

    return None

def _normalize_planned_tool_name(tool_name: Any) -> str:
    raw_name = str(tool_name or "").strip().lower()
    aliases = {
        "weather": "weather.get_current_weather",
        "weather.current": "weather.get_current_weather",
        "weather.current_weather": "weather.get_current_weather",
        "current_weather": "weather.get_current_weather",
        "get_current_weather": "weather.get_current_weather",
        "weather.forecast": "weather.get_forecast",
        "weather.get_forecast": "weather.get_forecast",
        "forecast": "weather.get_forecast",
        "get_forecast": "weather.get_forecast",
        "time": "time_manager.get_current_time",
        "current_time": "time_manager.get_current_time",
        "get_current_time": "time_manager.get_current_time",
        "day_info": "time_manager.get_day_info",
        "get_day_info": "time_manager.get_day_info",
        "calculator.add": "calculator.add",
        "add": "calculator.add",
        "calculator.subtract": "calculator.subtract",
        "subtract": "calculator.subtract",
        "calculator.multiply": "calculator.multiply",
        "multiply": "calculator.multiply",
        "calculator.divide": "calculator.divide",
        "divide": "calculator.divide",
        "memory_search": "memory_manager.memory_search",
        "memory.manager.search": "memory_manager.memory_search",
        "memory_manager.memory_search": "memory_manager.memory_search",
        "memory_save": "memory_manager.memory_save",
        "memory.manager.save": "memory_manager.memory_save",
        "memory_manager.memory_save": "memory_manager.memory_save",
        "working_memory_save": "memory_manager.working_memory_save",
        "memory.manager.working_save": "memory_manager.working_memory_save",
        "memory_manager.working_memory_save": "memory_manager.working_memory_save",
        "working_memory_clear": "memory_manager.working_memory_clear",
        "memory.manager.working_clear": "memory_manager.working_memory_clear",
        "memory_manager.working_memory_clear": "memory_manager.working_memory_clear",
    }
    return aliases.get(raw_name, raw_name)


def _normalize_direct_tool_arguments(tool_name: str, arguments: Any, user_input: str) -> dict[str, Any] | None:
    if not isinstance(arguments, dict):
        arguments = {}

    normalized = dict(arguments)
    if tool_name.startswith("weather."):
        location = str(
            normalized.get("location")
            or normalized.get("city")
            or normalized.get("place")
            or ""
        ).strip()
        if not location:
            location = _extract_weather_location(user_input) or ""
        if not location:
            return None
        normalized["location"] = location
        normalized["units"] = str(normalized.get("units") or "metric").lower()
        if normalized["units"] not in {"metric", "us"}:
            normalized["units"] = "metric"
        if tool_name == "weather.get_forecast":
            try:
                normalized["days"] = max(1, min(int(normalized.get("days") or 1), 3))
            except (TypeError, ValueError):
                normalized["days"] = 1
        return normalized

    if tool_name == "time_manager.get_current_time":
        normalized["timezone"] = str(normalized.get("timezone") or "Asia/Shanghai")
        normalized["format"] = str(normalized.get("format") or "full")
        return normalized

    if tool_name == "time_manager.get_day_info":
        return {}

    if tool_name.startswith("calculator."):
        if not normalized:
            operation = _extract_math_operation(user_input)
            if operation:
                return {"a": operation["a"], "b": operation["b"]}
            return None
        try:
            normalized["a"] = float(normalized.get("a"))
            normalized["b"] = float(normalized.get("b"))
        except (TypeError, ValueError):
            operation = _extract_math_operation(user_input)
            if operation:
                return {"a": operation["a"], "b": operation["b"]}
            return None
        return normalized

    if tool_name == "memory_manager.memory_search":
        query = str(normalized.get("query") or user_input).strip()
        if not query:
            return None
        try:
            normalized["limit"] = max(1, min(int(normalized.get("limit") or 5), 8))
        except (TypeError, ValueError):
            normalized["limit"] = 5
        normalized["query"] = query
        return normalized

    if tool_name == "memory_manager.memory_save":
        key = str(normalized.get("key") or "").strip()
        value = str(normalized.get("value") or "").strip()
        category = str(normalized.get("category") or "").strip()
        if not key or not value:
            save_match = re.search(r"(?:记住|帮我记住|请记住)[:：]?\s*(.+?)(?:是|为)\s*(.+)", user_input)
            if save_match:
                key = key or save_match.group(1).strip()
                value = value or save_match.group(2).strip(" ，。！？；:.!?; ")
        if not key or not value:
            return None
        normalized["key"] = key
        normalized["value"] = value
        if category:
            normalized["category"] = category
        else:
            normalized.pop("category", None)
        return normalized

    if tool_name == "memory_manager.working_memory_save":
        key = str(normalized.get("key") or "").strip()
        value = str(normalized.get("value") or "").strip()
        scope = str(normalized.get("scope") or "conversation").strip().lower()
        if scope not in {"conversation", "goal"}:
            scope = "conversation"
        if not key or not value:
            save_match = re.search(r"(?:先记一下|记一个|暂时记住|先写下)\s*(.+?)(?:是|为)\s*(.+)", user_input)
            if save_match:
                key = key or save_match.group(1).strip()
                value = value or save_match.group(2).strip(" ，。！？；:.!?; ")
        if not key or not value:
            return None
        normalized["key"] = key
        normalized["value"] = value
        normalized["scope"] = scope
        return normalized

    if tool_name == "memory_manager.working_memory_clear":
        scope = str(normalized.get("scope") or "conversation").strip().lower()
        if scope not in {"conversation", "goal"}:
            scope = "conversation"
        return {"scope": scope}

    return None

def _format_direct_tool_response(tool_name: str, tool_args: dict[str, Any], tool_output: dict[str, Any]) -> str | None:
    summary = tool_output.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary

    if "error" in tool_output:
        return str(tool_output["error"])

    if tool_name == "time_manager.get_day_info":
        return (
            f"今天是 {tool_output['date']}，{tool_output['weekday']}。"
            f"{' 今天是周末。' if tool_output['is_weekend'] else ' 今天是工作日。'}"
        )

    if tool_name == "time_manager.get_current_time":
        return f"当前时间是 {tool_output['time_str']}。时区：{tool_output['timezone']}。"

    if tool_name.startswith("calculator.") and "result" in tool_output:
        symbol_map = {
            "calculator.add": "+",
            "calculator.subtract": "-",
            "calculator.multiply": "*",
            "calculator.divide": "/",
        }
        display_a = int(tool_args["a"]) if float(tool_args["a"]).is_integer() else tool_args["a"]
        display_b = int(tool_args["b"]) if float(tool_args["b"]).is_integer() else tool_args["b"]
        result = tool_output["result"]
        display_result = int(result) if isinstance(result, float) and result.is_integer() else result
        return f"{display_a} {symbol_map.get(tool_name, '=')} {display_b} = {display_result}"

    if tool_name in {
        "memory_manager.memory_search",
        "memory_manager.memory_save",
        "memory_manager.working_memory_save",
        "memory_manager.working_memory_clear",
    }:
        summary = tool_output.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary

    if "result" in tool_output:
        return str(tool_output["result"])

    return None

def _attach_memory_scope_arguments(
    state: dict[str, Any],
    tool_name: str,
    tool_args: dict[str, Any],
) -> dict[str, Any]:
    if tool_name == "memory_manager.working_memory_save":
        scope = str(tool_args.get("scope") or "conversation").lower()
        if scope == "goal":
            if state.get("current_goal"):
                tool_args.setdefault("goal_id", str(state.get("session_id") or ""))
        else:
            tool_args.setdefault("session_id", str(state.get("session_id") or ""))
        return tool_args

    if tool_name == "memory_manager.working_memory_clear":
        scope = str(tool_args.get("scope") or "conversation").lower()
        if scope == "goal":
            if state.get("current_goal"):
                tool_args.setdefault("goal_id", str(state.get("session_id") or ""))
        else:
            tool_args.setdefault("session_id", str(state.get("session_id") or ""))
        return tool_args

    return tool_args



async def _try_local_tool_response(
    state: dict[str, Any],
    user_input: str,
) -> dict[str, Any] | None:
    skill_manager = SkillManager()
    skill_manager.ensure_initialized()


    weather_tool = _resolve_weather_tool(user_input)
    if weather_tool:
        tool_name, tool_input = weather_tool
        tool = skill_manager.get_tool_function("weather", tool_name)
        if tool:
            try:
                tool_output = await tool(**tool_input)
                final_response = tool_output.get("summary") or "暂时无法获取天气数据。"
                next_state = add_thinking_block(state, "工具", f"已调用本地工具 weather.{tool_name}。")
                next_state = add_tool_call(
                    next_state,
                    f"weather.{tool_name}",
                    tool_input,
                    tool_output,
                )
                next_state = _append_tool_result(
                    next_state,
                    {
                        "skill": "weather",
                        "tool": tool_name,
                        "input": tool_input,
                        "output": tool_output,
                    },
                )
                return {
                    **next_state,
                    "final_response": final_response,
                    "serana_status": "idle",
                }
            except Exception as exc:
                logger.warning("Weather skill failed for %s: %s", tool_input.get("location"), exc)

    memory_tool = _resolve_memory_tool(user_input)
    if memory_tool:
        tool_name, tool_input = memory_tool
        tool_input = _attach_memory_scope_arguments(state, f"memory_manager.{tool_name}", tool_input)
        tool = skill_manager.get_tool_function("memory_manager", tool_name)
        if tool:
            try:
                tool_output = await tool(**tool_input)
                final_response = tool_output.get("summary") or "我暂时无法处理这条记忆请求。"
                next_state = add_thinking_block(state, "工具", f"已调用本地工具 memory_manager.{tool_name}。")
                next_state = add_tool_call(
                    next_state,
                    f"memory_manager.{tool_name}",
                    tool_input,
                    tool_output,
                )
                next_state = _append_tool_result(
                    next_state,
                    {
                        "skill": "memory_manager",
                        "tool": tool_name,
                        "input": tool_input,
                        "output": tool_output,
                    },
                )
                return {
                    **next_state,
                    "final_response": final_response,
                    "serana_status": "idle",
                }
            except Exception as exc:
                logger.warning("Memory skill failed for %s: %s", tool_name, exc)

    time_tool = _resolve_time_tool(user_input)
    if time_tool:
        tool_name, tool_input = time_tool
        tool = skill_manager.get_tool_function("time_manager", tool_name)
        if tool:
            tool_output = await tool(**tool_input)
            if tool_name == "get_day_info":
                final_response = (
                    f"今天是 {tool_output['date']}，{tool_output['weekday']}。"
                    f"{' 今天是周末。' if tool_output['is_weekend'] else ' 今天是工作日。'}"
                )
            else:
                final_response = (
                    f"当前时间是 {tool_output['time_str']}。"
                    f" 时区：{tool_output['timezone']}。"
                )
            next_state = add_thinking_block(state, "工具", f"已调用本地工具 time_manager.{tool_name}。")
            next_state = add_tool_call(
                next_state,
                f"time_manager.{tool_name}",
                tool_input,
                tool_output,
            )
            next_state = _append_tool_result(
                next_state,
                {
                    "skill": "time_manager",
                    "tool": tool_name,
                    "input": tool_input,
                    "output": tool_output,
                },
            )
            return {
                **next_state,
                "final_response": final_response,
                "serana_status": "idle",
            }

    math_operation = _extract_math_operation(user_input)
    if math_operation:
        tool_name = str(math_operation["tool_name"])
        tool = skill_manager.get_tool_function("calculator", tool_name)
        if tool:
            tool_input = {"a": math_operation["a"], "b": math_operation["b"]}
            tool_output = await tool(**tool_input)
            if "error" in tool_output:
                final_response = tool_output["error"]
                status = "failed"
            else:
                result = tool_output["result"]
                display_a = int(tool_input["a"]) if tool_input["a"].is_integer() else tool_input["a"]
                display_b = int(tool_input["b"]) if tool_input["b"].is_integer() else tool_input["b"]
                display_result = int(result) if isinstance(result, float) and result.is_integer() else result
                final_response = f"{display_a} {math_operation['symbol']} {display_b} = {display_result}"
                status = "completed"
            next_state = add_thinking_block(state, "工具", f"已调用本地工具 calculator.{tool_name}。")
            next_state = add_tool_call(
                next_state,
                f"calculator.{tool_name}",
                tool_input,
                tool_output,
                status=status,
            )
            next_state = _append_tool_result(
                next_state,
                {
                    "skill": "calculator",
                    "tool": tool_name,
                    "input": tool_input,
                    "output": tool_output,
                },
            )
            return {
                **next_state,
                "final_response": final_response,
                "serana_status": "idle",
            }

    return None


async def _plan_conversation_route(
    state: dict[str, Any],
    llm: BaseChatModel,
    user_input: str,
) -> dict[str, Any] | None:
    memory_context = str(state.get("memory_context") or "").strip()
    instruction_skill_context = str(state.get("instruction_skill_context") or "").strip()
    request_content = user_input
    if memory_context:
        request_content = f"User message:\n{user_input}\n\nRelevant memory context:\n{memory_context}"
    if instruction_skill_context:
        request_content = (
            f"{request_content}\n\nInstalled instruction skills:\n{instruction_skill_context}"
        )

    prompt = (
        "You triage a personal butler request.\n"
        "Return JSON only, with no markdown fences and no extra text.\n"
        "Choose one route:\n"
        '- {"route":"direct_tool","tool_name":"...","arguments":{},"reason":"..."}\n'
        '- {"route":"direct_reply","reply":"...","goal_type":"...","complexity":"simple|medium","reason":"..."}\n'
        '- {"route":"delegated","goal_type":"...","summary":"...","complexity":"medium|high","reason":"..."}\n'
        "Use direct_tool for weather, time/date, simple arithmetic, explicit memory save/search, and temporary working-memory notes.\n"
        "Use direct_reply for ordinary conversational questions that can be answered in one reply.\n"
        "Use delegated only for genuinely multi-step work, planning, research, analysis, or implementation.\n"
        "Keep internal implementation details hidden from the user.\n"
        "Examples:\n"
        '- User: "What time is it?" -> {"route":"direct_tool","tool_name":"time_manager.get_current_time","arguments":{"timezone":"Asia/Shanghai","format":"full"},"reason":"Time lookup"}\n'
        '- User: "37*18 equals what?" -> {"route":"direct_tool","tool_name":"calculator.multiply","arguments":{"a":37,"b":18},"reason":"Arithmetic"}\n'
        '- User: "帮我记住我喜欢黑咖啡" -> {"route":"direct_tool","tool_name":"memory_manager.memory_save","arguments":{"key":"preferred_drink","value":"黑咖啡","category":"preference"},"reason":"Explicit memory save"}\n'
        '- User: "我之前说过我喜欢什么饮料？" -> {"route":"direct_tool","tool_name":"memory_manager.memory_search","arguments":{"query":"喜欢什么饮料","limit":5},"reason":"Memory lookup"}\n'
        '- User: "先记一下这次旅行预算是 5000 元" -> {"route":"direct_tool","tool_name":"memory_manager.working_memory_save","arguments":{"key":"这次旅行预算","value":"5000 元","scope":"conversation"},"reason":"Temporary working note"}\n'
        '- User: "把这轮临时笔记清掉" -> {"route":"direct_tool","tool_name":"memory_manager.working_memory_clear","arguments":{"scope":"conversation"},"reason":"Clear working memory for this conversation"}\n'
        '- User: "What should I study tonight?" -> {"route":"direct_reply","reply":"Focus on one or two high-impact topics tonight and keep the session manageable.","goal_type":"question","complexity":"simple","reason":"Single-turn advice"}\n'
        '- User: "Research and build a weekly study plan" -> {"route":"delegated","goal_type":"research","summary":"Create a weekly study plan with research and structure.","complexity":"high","reason":"Needs planning and decomposition"}'
    )

    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content=prompt),
                HumanMessage(content=request_content),
            ]
        )
        parsed = _parse_json_object(str(response.content))
    except Exception as exc:
        logger.warning("Conversation route planning failed: %s", exc)
        return None

    route = str(parsed.get("route") or "").strip().lower()
    if route not in {"direct_tool", "direct_reply", "delegated"}:
        return None

    next_state = add_tool_call(
        state,
        "conversation_route",
        {"user_input": user_input},
        {
            "route": route,
            "goal_type": parsed.get("goal_type"),
            "complexity": parsed.get("complexity"),
            "reason": parsed.get("reason"),
        },
    )

    return {
        **next_state,
        "conversation_route": {
            "route": route,
            "tool_name": parsed.get("tool_name"),
            "arguments": parsed.get("arguments") or {},
            "reply": parsed.get("reply"),
            "goal_type": parsed.get("goal_type"),
            "summary": parsed.get("summary"),
            "complexity": parsed.get("complexity"),
            "reason": parsed.get("reason"),
        },
    }

def _execute_planned_tool_intent(
    state: dict[str, Any],
    skill_name: str,
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: dict[str, Any],
) -> dict[str, Any] | None:
    final_response = _format_direct_tool_response(f"{skill_name}.{tool_name}", tool_input, tool_output)
    if not final_response:
        return None

    next_state = add_thinking_block(
        state,
        "Tool",
        f"Handled this request with the local tool {skill_name}.{tool_name}.",
    )
    next_state = add_tool_call(
        next_state,
        f"{skill_name}.{tool_name}",
        tool_input,
        tool_output,
        status="failed" if "error" in tool_output else "completed",
    )
    next_state = _append_tool_result(
        next_state,
        {
            "skill": skill_name,
            "tool": tool_name,
            "input": tool_input,
            "output": tool_output,
        },
    )
    return {
        **next_state,
        "execution_mode": "direct",
        "final_response": final_response,
        "serana_status": "idle",
    }


def _record_tool_selection(
    state: dict[str, Any],
    *,
    requested_tool_name: Any,
    selected_tool_name: str | None,
    arguments: dict[str, Any] | None,
    reason: Any,
    status: str,
    detail: str,
) -> dict[str, Any]:
    return add_tool_call(
        state,
        "serana_tool_selection",
        {
            "requested_tool_name": requested_tool_name,
            "reason": reason,
        },
        {
            "selected_tool_name": selected_tool_name,
            "arguments": arguments or {},
            "status": status,
            "detail": detail,
        },
        status="completed" if status == "selected" else "failed",
    )


async def try_lightweight_conversation(
    state: dict[str, Any],
    llm: BaseChatModel,
) -> dict[str, Any] | None:
    state = ensure_instruction_skill_context(state)
    user_input = get_primary_user_input(state)
    if not user_input:
        return None

    planned_state = await _plan_conversation_route(state, llm, user_input)
    if planned_state is None:
        return await _try_local_tool_response(state, user_input)

    route_info = dict(planned_state.get("conversation_route") or {})
    route = str(route_info.get("route") or "")

    if route == "direct_tool":
        planned_tool_name = _normalize_planned_tool_name(route_info.get("tool_name"))
        planned_args = _normalize_direct_tool_arguments(
            planned_tool_name,
            route_info.get("arguments") or {},
            user_input,
        )
        if planned_args is not None:
            planned_args = _attach_memory_scope_arguments(planned_state, planned_tool_name, planned_args)
        if not planned_tool_name or planned_args is None or "." not in planned_tool_name:
            _record_tool_selection(
                planned_state,
                requested_tool_name=route_info.get("tool_name"),
                selected_tool_name=planned_tool_name or None,
                arguments=planned_args,
                reason=route_info.get("reason"),
                status="rejected",
                detail="The LLM route did not normalize to a supported tool call.",
            )
            return None

        skill_name, tool_name = planned_tool_name.split(".", 1)
        skill_manager = SkillManager()
        skill_manager.ensure_initialized()
        tool = skill_manager.get_tool_function(skill_name, tool_name)
        if not tool:
            _record_tool_selection(
                planned_state,
                requested_tool_name=route_info.get("tool_name"),
                selected_tool_name=planned_tool_name,
                arguments=planned_args,
                reason=route_info.get("reason"),
                status="unavailable",
                detail="The selected tool is not installed or enabled.",
            )
            return None

        planned_state = _record_tool_selection(
            planned_state,
            requested_tool_name=route_info.get("tool_name"),
            selected_tool_name=planned_tool_name,
            arguments=planned_args,
            reason=route_info.get("reason"),
            status="selected",
            detail="The LLM route selected an available local tool.",
        )

        try:
            tool_output = await tool(**planned_args)
        except Exception as exc:
            logger.warning("Lightweight planned tool call failed for %s: %s", planned_tool_name, exc)
            return await _try_local_tool_response(planned_state, user_input)

        tool_result_state = _execute_planned_tool_intent(
            planned_state,
            skill_name,
            tool_name,
            planned_args,
            tool_output,
        )
        if tool_result_state is not None:
            return tool_result_state
        return await _try_local_tool_response(planned_state, user_input)

    if route == "direct_reply":
        memory_fallback = await _try_local_tool_response(planned_state, user_input)
        if memory_fallback is not None:
            return memory_fallback
        reply = str(route_info.get("reply") or "").strip()
        if not reply:
            return None
        next_state = add_thinking_block(
            planned_state,
            "Reply",
            "Handled this request directly without delegation.",
        )
        next_state = add_tool_call(
            next_state,
            "serana_direct_reply",
            {"user_input": user_input},
            {"reply_preview": reply[:200]},
        )
        return {
            **next_state,
            "goal_type": route_info.get("goal_type") or _infer_goal_type(user_input),
            "complexity": _normalize_complexity(route_info.get("complexity") or "simple"),
            "execution_mode": "direct",
            "delegation_plan": {
                "execution_mode": "direct",
                "parallel_aides": 0,
                "parallel_forges": 0,
                "parallel_slots": 0,
            },
            "final_response": reply,
            "serana_status": "idle",
        }

    return None


async def analyze_node(state: dict[str, Any], llm: BaseChatModel) -> dict[str, Any]:
    state = ensure_instruction_skill_context(state)
    user_input = get_primary_user_input(state)
    original_user_input = user_input
    instruction_skill_context = state.get("instruction_skill_context", "")
    analysis_input = build_state_request_context(state, label="User request")
    state = add_thinking_block(state, "Analyze", f"Reviewing the request: {original_user_input[:120]}")

    system_prompt = build_serana_system_prompt(
        "Analyze the user's request and return JSON with goal_type, summary, and complexity. "
        "Keep the analysis grounded in the user's real intention and optimize for helpful, practical assistance.",
        include_instruction_skills=bool(instruction_skill_context),
    )

    summary = user_input
    goal_type = _infer_goal_type(user_input)
    complexity = "medium"
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=analysis_input),
            ]
        )
        parsed = _parse_json_object(str(response.content))
        summary = str(parsed.get("summary") or original_user_input)
        goal_type = str(parsed.get("goal_type") or goal_type)
        complexity = _normalize_complexity(parsed.get("complexity"))
        state = add_thinking_block(state, "Analyze", f"Detected complexity: {complexity}")
    except ValueError as exc:
        logger.warning("Serana analyze node received invalid model output: %s", exc)
        complexity = "medium"
        state = add_thinking_block(state, "Analyze", "Used fallback analysis because the model output was invalid.")
    except Exception:
        logger.exception("Unexpected failure in Serana analyze node")
        complexity = "medium"
        state = add_thinking_block(state, "Analyze", "Used fallback analysis.")

    delegation_plan = _build_delegation_plan(goal_type, complexity, original_user_input)
    execution_mode = str(delegation_plan["execution_mode"])
    route_summary = (
        f"Routing mode: {execution_mode}; goal type: {goal_type}; "
        f"parallel aides: {delegation_plan['parallel_aides']}; "
        f"parallel forges: {delegation_plan['parallel_forges']}"
    )
    state = add_thinking_block(state, "Routing", route_summary)
    state = add_tool_call(
        state,
        "serana_analyze",
        {"user_input": user_input[:200]},
        {
            "summary": summary,
            "goal_type": goal_type,
            "complexity": complexity,
            "execution_mode": execution_mode,
            "delegation_plan": delegation_plan,
        },
    )
    if execution_mode == "delegated":
        state = _record_working_memory_update(
            state,
            key="active_goal",
            value=summary,
            reason="analysis_summary",
        )
        state = _record_working_memory_update(
            state,
            key="routing_decision",
            value=f"{goal_type} · {complexity} · delegated",
            reason="analysis_route",
        )

    return {
        **state,
        "current_goal": summary,
        "goal_type": goal_type,
        "complexity": complexity,
        "execution_mode": execution_mode,
        "delegation_plan": delegation_plan,
        "serana_status": "analyzing",
    }


async def decompose_node(state: dict[str, Any], llm: BaseChatModel) -> dict[str, Any]:
    state = ensure_instruction_skill_context(state)
    user_input = get_primary_user_input(state)
    original_user_input = user_input
    instruction_skill_context = state.get("instruction_skill_context", "")
    decomposition_input = build_state_request_context(state, label="User request")
    goal_type = str(state.get("goal_type") or _infer_goal_type(original_user_input))
    complexity = _normalize_complexity(state.get("complexity"))
    state = add_thinking_block(state, "Decompose", "Breaking the request into actionable subtasks.")

    default_subtasks = [
        "Clarify the objective and constraints",
        "Prepare a concise execution plan",
        "Carry out the plan and report the result",
    ]

    subtask_descriptions = default_subtasks
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(
                    content=build_serana_system_prompt(
                        "Break the request into 2 to 5 practical subtasks and return JSON like "
                        '{"subtasks":[{"description":"...","order":1}]}. '
                        "Make the plan calm, orderly, and useful for a personal butler helping a real user.",
                        include_instruction_skills=bool(instruction_skill_context),
                    )
                ),
                HumanMessage(content=decomposition_input),
            ]
        )
        parsed = _parse_json_object(str(response.content))
        parsed_subtasks = parsed.get("subtasks")
        if isinstance(parsed_subtasks, list):
            cleaned = []
            for item in parsed_subtasks:
                if isinstance(item, dict) and item.get("description"):
                    cleaned.append(str(item["description"]))
            if cleaned:
                subtask_descriptions = cleaned[:5]
    except ValueError as exc:
        logger.warning("Serana decompose node received invalid model output: %s", exc)
        state = add_thinking_block(state, "Decompose", "Used fallback subtask plan because the model output was invalid.")
    except Exception:
        logger.exception("Unexpected failure in Serana decompose node")
        state = add_thinking_block(state, "Decompose", "Used fallback subtask plan.")

    subtasks = [
        {
            "id": str(uuid.uuid4()),
            "description": description,
            "status": "pending",
            "order": index,
        }
        for index, description in enumerate(subtask_descriptions, start=1)
    ]

    delegation_plan = _build_delegation_plan(goal_type, complexity, original_user_input, len(subtasks))
    state = add_thinking_block(
        state,
        "Decompose",
        f"Prepared {len(subtasks)} subtasks with {delegation_plan['parallel_slots']} parallel slots.",
    )
    state = add_tool_call(
        state,
        "serana_decompose",
        {"user_input": user_input[:200]},
        {
            "subtask_count": len(subtasks),
            "subtask_descriptions": [task["description"] for task in subtasks],
            "delegation_plan": delegation_plan,
        },
    )
    state = _record_working_memory_update(
        state,
        key="subtask_plan",
        value=" | ".join(task["description"] for task in subtasks),
        reason="decomposition_plan",
    )
    state = _record_working_memory_update(
        state,
        key="next_step_focus",
        value=subtasks[0]["description"] if subtasks else "Prepare final response",
        reason="decomposition_focus",
    )
    return {
        **state,
        "subtasks": subtasks,
        "delegation_plan": delegation_plan,
        "execution_mode": delegation_plan["execution_mode"],
        "serana_status": "decomposing",
    }


async def delegate_node(state: dict[str, Any], llm: BaseChatModel) -> dict[str, Any]:
    subtasks = state.get("subtasks", [])
    delegation_plan = dict(state.get("delegation_plan", {}))
    parallel_slots = int(delegation_plan.get("parallel_slots") or 1)
    state = add_thinking_block(
        state,
        "Delegate",
        f"Assigning {len(subtasks)} subtasks with up to {parallel_slots} parallel agent slots.",
    )
    state = _record_working_memory_update(
        state,
        key="execution_stage",
        value=f"Delegating {len(subtasks)} subtasks",
        reason="delegate_start",
    )

    delegated_subtasks: list[dict[str, Any]] = []
    aide_sessions = list(state.get("aide_sessions", []))
    forge_sessions = list(state.get("forge_sessions", []))
    agent_manager = AgentManager()
    if agent_manager.llm is None:
        agent_manager.initialize(llm)
    else:
        agent_manager.llm = llm

    semaphore = asyncio.Semaphore(parallel_slots)

    async def _run_subtask(index: int, subtask: dict[str, Any]):
        async with semaphore:
            aide = await agent_manager.get_agent("aide")
            aide_result = await aide.execute(subtask)
            worker_result = aide_result.get("result", {}).get("worker_result", {})
            return index, subtask, aide_result, worker_result

    results = await asyncio.gather(
        *[_run_subtask(index, subtask) for index, subtask in enumerate(subtasks)],
    )

    aide_agent_ids: set[str] = set()
    forge_agent_ids: set[str] = set()
    for index, subtask, aide_result, worker_result in sorted(results, key=lambda item: item[0]):
        aide_agent_id = str(aide_result.get("agent_id") or "")
        batch_results = list(aide_result.get("result", {}).get("batch_results") or [])
        batch_forge_agent_ids = [
            str(batch_result.get("worker_result", {}).get("agent_id") or "")
            for batch_result in batch_results
            if batch_result.get("worker_result", {}).get("agent_id")
        ]
        forge_agent_id = str(worker_result.get("agent_id") or (batch_forge_agent_ids[0] if batch_forge_agent_ids else ""))
        if aide_agent_id:
            aide_agent_ids.add(aide_agent_id)
        for item in batch_forge_agent_ids:
            if item:
                forge_agent_ids.add(item)
        if forge_agent_id:
            forge_agent_ids.add(forge_agent_id)

        aide_success = bool(aide_result.get("success", False))
        forge_success = str(worker_result.get("status") or "").lower() == "completed"
        subtask_status = "completed" if aide_success and forge_success else "failed"

        aide_sessions.append(
            {
                "agent_id": aide_agent_id,
                "task_description": subtask.get("description"),
                "success": aide_success,
                "task_type": aide_result.get("result", {}).get("task_type"),
                "batches_planned": aide_result.get("result", {}).get("batches_planned"),
            }
        )
        for batch_result in batch_results or [{"worker_result": {"agent_id": forge_agent_id}, "status": worker_result.get("status")}]:
            batch_worker = batch_result.get("worker_result", {})
            forge_sessions.append(
                {
                    "agent_id": batch_worker.get("agent_id"),
                    "task_description": subtask.get("description"),
                    "success": batch_result.get("status") == "completed",
                    "batch_index": batch_result.get("batch_index"),
                    "attempts": batch_result.get("attempts"),
                    "strategy": batch_worker.get("result", {}).get("strategy"),
                    "tool_name": batch_worker.get("result", {}).get("tool_name"),
                }
            )
        state = add_tool_call(
            state,
            "aide_execute",
            {"subtask_description": subtask.get("description")},
            {
                "agent_id": aide_agent_id,
                "success": aide_success,
                "thinking_block_count": len(aide_result.get("thinking_blocks", [])),
                "task_type": aide_result.get("result", {}).get("task_type"),
                "batches_planned": aide_result.get("result", {}).get("batches_planned"),
                "retry_limit": aide_result.get("result", {}).get("retry_limit"),
            },
            status="completed" if aide_success else "failed",
        )
        state = add_tool_call(
            state,
            "forge_execute",
            {"subtask_description": subtask.get("description")},
            {
                "agent_id": forge_agent_id,
                "agent_ids": worker_result.get("agent_ids", batch_forge_agent_ids),
                "success": forge_success,
                "batch_count": worker_result.get("batch_count"),
                "attempts": worker_result.get("attempts"),
                "strategy": worker_result.get("strategy"),
                "tool_name": worker_result.get("tool_name"),
            },
            status="completed" if forge_success else "failed",
        )
        delegated_subtasks.append(
            {
                **subtask,
                "status": subtask_status,
            }
        )

    completed_count = sum(1 for task in delegated_subtasks if task["status"] == "completed")
    failed_count = sum(1 for task in delegated_subtasks if task["status"] == "failed")
    state = _record_working_memory_update(
        state,
        key="delegation_outcome",
        value=f"completed={completed_count}; failed={failed_count}",
        reason="delegate_result",
    )
    state = remove_working_memory_entry(state, "next_step_focus")
    state = add_thinking_block(
        state,
        "Delegate",
        f"Completed {len(delegated_subtasks)} subtasks using {len(aide_agent_ids)} aides and {len(forge_agent_ids)} forges.",
    )
    state = add_tool_call(
        state,
        "serana_delegate",
        {"subtask_count": len(subtasks)},
        {
            "completed_subtask_count": sum(1 for task in delegated_subtasks if task["status"] == "completed"),
            "failed_subtask_count": sum(1 for task in delegated_subtasks if task["status"] == "failed"),
            "subtask_statuses": [task["status"] for task in delegated_subtasks],
            "parallel_aides": delegation_plan.get("parallel_aides", 0),
            "parallel_forges": delegation_plan.get("parallel_forges", 0),
            "parallel_slots": parallel_slots,
            "actual_aide_agents": len(aide_agent_ids),
            "actual_forge_agents": len(forge_agent_ids),
        },
        status="completed" if all(task["status"] == "completed" for task in delegated_subtasks) else "failed",
    )
    return {
        **state,
        "subtasks": delegated_subtasks,
        "aide_sessions": aide_sessions,
        "forge_sessions": forge_sessions,
        "serana_status": "delegating",
    }


async def summarize_node(state: dict[str, Any], llm: BaseChatModel) -> dict[str, Any]:
    state = ensure_instruction_skill_context(state)
    user_input = get_primary_user_input(state)
    original_user_input = user_input
    instruction_skill_context = state.get("instruction_skill_context", "")
    subtasks = state.get("subtasks", [])
    execution_mode = str(state.get("execution_mode") or "delegated")
    state = add_thinking_block(state, "Summarize", "Preparing the final response.")

    if execution_mode == "direct":
        final_response = "I handled this request directly."
        try:
            response = await llm.ainvoke(
                [
                    SystemMessage(
                        content=build_serana_system_prompt(
                            "Handle this request directly. Reply helpfully, naturally, and concisely without "
                            "inventing unnecessary multi-step delegation. Keep internal implementation details hidden "
                            "unless the user explicitly asks for them.",
                            include_instruction_skills=bool(instruction_skill_context),
                    )
                ),
                HumanMessage(content=build_state_request_context(state, label="User request")),
            ]
        )
            content = str(response.content).strip()
            if content:
                final_response = content
        except Exception:
            logger.exception("Unexpected failure in Serana direct summary node")

        state = add_tool_call(
            state,
            "serana_summarize",
            {"execution_mode": execution_mode},
            {"final_response_preview": final_response[:200]},
        )
        state = clear_working_memory_entries(state)
        return {
            **state,
            "final_response": final_response,
            "serana_status": "idle",
        }

    subtask_lines = "\n".join(f"- {task['description']}" for task in subtasks)
    final_response = f"I've broken this down and prepared {len(subtasks)} steps."
    completed_count = sum(1 for task in subtasks if task.get("status") == "completed")
    failed_count = sum(1 for task in subtasks if task.get("status") == "failed")
    state = _record_working_memory_update(
        state,
        key="summary_ready",
        value=f"completed={completed_count}; failed={failed_count}; subtasks={len(subtasks)}",
        reason="summarize_prep",
    )

    try:
        response = await llm.ainvoke(
            [
                SystemMessage(
                    content=build_serana_system_prompt(
                        "Summarize the plan in a helpful, concise reply. Mention the main steps without unnecessary "
                        "detail, and make the result feel calm, competent, and personally supportive.",
                        include_instruction_skills=bool(instruction_skill_context),
                    )
                ),
                HumanMessage(
                    content=(
                        f"{build_state_request_context(state, label='Request')}\n\n"
                        f"Subtasks:\n{subtask_lines}"
                    )
                ),
            ]
        )
        content = str(response.content).strip()
        if content:
            final_response = content
    except Exception:
        logger.exception("Unexpected failure in Serana delegated summary node")

    state = add_tool_call(
        state,
        "serana_summarize",
        {"execution_mode": execution_mode, "subtask_count": len(subtasks)},
        {"final_response_preview": final_response[:200]},
    )
    state = clear_working_memory_entries(state)

    return {
        **state,
        "final_response": final_response,
        "serana_status": "idle",
    }


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    raw_text = raw_text.strip()
    if not raw_text:
        return {}

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw_text[start : end + 1])
            except json.JSONDecodeError:
                raise ValueError("Model output did not contain valid JSON") from None
    raise ValueError("Model output did not contain valid JSON")
