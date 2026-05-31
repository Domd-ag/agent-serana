import asyncio
import base64
import inspect
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents.base import AgentManager, get_agent_limit
from app.agents.serana.context import (
    build_serana_context_bundle,
    build_state_request_context,
    build_state_system_prompt,
    clear_working_memory_entries,
    ensure_instruction_skill_context,
    get_primary_user_input,
    remove_working_memory_entry,
    set_working_memory_entry,
)
from app.core.logger import get_logger
from app.core.tool_results import (
    append_tool_result,
    attach_tool_result,
    build_tool_result,
)
from app.skills import SkillManager
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage


logger = get_logger(__name__)

_MAX_BROWSER_LOOK_IMAGE_BYTES = 8 * 1024 * 1024
_HTML_PREVIEW_PLACEHOLDER_PATTERN = re.compile(
    r"offline demo script here|"
    r"javascript code for [^<\n\r]+|"
    r"css styles for visualization|"
    r"\bplaceholder\b|"
    r"\btodo\b",
    re.IGNORECASE,
)
_HTML_PREVIEW_INTERACTIVE_KEYWORDS = (
    "演示",
    "动画",
    "排序",
    "交互",
    "可视化",
    "demo",
    "animation",
    "interactive",
    "visual",
    "sort",
)
_HTML_PREVIEW_CONTROL_PATTERN = re.compile(
    r"<\s*(button|input|select|textarea)\b|"
    r"\brole\s*=\s*['\"]button['\"]",
    re.IGNORECASE,
)
_HTML_PREVIEW_EVENT_BINDING_PATTERN = re.compile(
    r"\baddEventListener\s*\(|"
    r"\bon(click|change|input|submit|keydown|keyup)\s*=|"
    r"\.on(click|change|input|submit|keydown|keyup)\s*=",
    re.IGNORECASE,
)


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


def _build_standard_tool_result(
    *,
    skill_name: str,
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: dict[str, Any],
    status: str,
    user_summary: str | None = None,
) -> dict[str, Any]:
    return build_tool_result(
        skill_name=skill_name,
        tool_name=tool_name,
        tool_input=tool_input,
        tool_output=tool_output,
        status=status,
        user_summary=user_summary,
    )


def _tool_output_with_standard_result(
    tool_output: dict[str, Any],
    standard_result: dict[str, Any],
) -> dict[str, Any]:
    return attach_tool_result(tool_output, standard_result)


def _append_tool_result(state: dict[str, Any], tool_result: dict[str, Any]) -> dict[str, Any]:
    return append_tool_result(state, tool_result)


async def _emit_runtime_event(state: dict[str, Any], event: dict[str, Any]) -> None:
    event_emitter = state.get("event_emitter")
    if not callable(event_emitter):
        return
    result = event_emitter(event)
    if inspect.isawaitable(result):
        await result


async def _authorize_tool_call(
    state: dict[str, Any],
    *,
    tool_name: str,
    tool_input: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    approval_runtime = dict(state.get("approval_runtime") or {})
    policy_gate = approval_runtime.get("policy_gate")
    if policy_gate is None:
        return state, {"allowed": True, "requires_approval": False}

    decision = policy_gate.evaluate(tool_name=tool_name, arguments=tool_input)
    gate_output = {
        "tool_name": tool_name,
        "operation": decision.operation,
        "risk_level": decision.risk_level,
        "requires_approval": decision.requires_approval,
        "reason": decision.reason,
        "details": decision.details,
    }

    if not decision.requires_approval:
        next_state = add_tool_call(
            state,
            "serana_policy_gate",
            {"tool_name": tool_name, "arguments": tool_input},
            {**gate_output, "decision": "allowed"},
        )
        return next_state, {"allowed": True, "requires_approval": False, "decision": decision}

    reviewer = approval_runtime.get("reviewer")
    manager = approval_runtime.get("manager")
    interactive = bool(approval_runtime.get("interactive"))
    session_id = str(state.get("session_id") or "")

    if reviewer is None or manager is None:
        interactive = False

    if manager is not None and await manager.is_granted(
        tool_name=tool_name,
        operation=decision.operation,
        risk_level=decision.risk_level,
        details=decision.details,
    ):
        next_state = add_tool_call(
            state,
            "serana_policy_gate",
            {"tool_name": tool_name, "arguments": tool_input},
            {**gate_output, "decision": "allowed_by_persistent_approval"},
        )
        return next_state, {
            "allowed": True,
            "requires_approval": False,
            "approval_scope": "always",
            "decision": decision,
        }

    if not interactive:
        next_state = add_tool_call(
            state,
            "serana_policy_gate",
            {"tool_name": tool_name, "arguments": tool_input},
            {
                **gate_output,
                "decision": "blocked",
                "detail": "Interactive approval is unavailable in this execution mode.",
            },
            status="failed",
        )
        return next_state, {
            "allowed": False,
            "requires_approval": True,
            "user_message": "这个操作需要你的确认。请在支持交互审批的聊天流程里重试。",
        }

    approval_request = reviewer.build_request(
        session_id=session_id,
        tool_name=tool_name,
        arguments=tool_input,
        policy_decision=decision,
        source="chat",
        entity_type="chat_session",
        entity_id=session_id,
    )
    await manager.register(approval_request)
    state = add_tool_call(
        state,
        "serana_approval_requested",
        {"tool_name": tool_name, "arguments": tool_input},
        {
            "request_id": approval_request.request_id,
            "operation": approval_request.operation,
            "risk_level": approval_request.risk_level,
            "title": approval_request.title,
            "summary": approval_request.summary,
            "reason": approval_request.reason,
            "approval_options": approval_request.approval_options,
        },
    )
    await _emit_runtime_event(
        state,
        {
            "type": "approval_requested",
            "content": approval_request.model_dump(mode="json"),
        },
    )
    resolution = await manager.wait_for_resolution(
        approval_request.request_id,
        timeout_seconds=float(approval_runtime.get("timeout_seconds") or 300.0),
    )
    await _emit_runtime_event(
        state,
        {
            "type": "approval_resolved",
            "content": resolution.model_dump(mode="json"),
        },
    )

    state = add_tool_call(
        state,
        "serana_approval_resolved",
        {"request_id": approval_request.request_id},
        {
            "approved": resolution.approved,
            "reviewer": resolution.reviewer,
            "note": resolution.note,
            "approval_scope": resolution.approval_scope,
        },
        status="completed" if resolution.approved else "failed",
    )

    next_state = add_tool_call(
        state,
        "serana_policy_gate",
        {"tool_name": tool_name, "arguments": tool_input},
        {
            **gate_output,
            "decision": "approved" if resolution.approved else "denied",
            "request_id": approval_request.request_id,
            "reviewer": resolution.reviewer,
            "note": resolution.note,
            "approval_scope": resolution.approval_scope,
        },
        status="completed" if resolution.approved else "failed",
    )
    if resolution.approved:
        return next_state, {
            "allowed": True,
            "requires_approval": True,
            "request_id": approval_request.request_id,
            "approval_scope": resolution.approval_scope,
        }
    return next_state, {
        "allowed": False,
        "requires_approval": True,
        "request_id": approval_request.request_id,
        "user_message": resolution.note or "我没有执行这个操作，因为它没有通过审批。",
    }


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

    text = user_input.strip().lower()
    if any(
        keyword in text
        for keyword in [
            "delegate",
            "multi-agent",
            "use aide",
            "use forge",
            "并行",
            "委派",
            "多代理",
        ]
    ):
        return True
    if len(text) > 300 and goal_type in {"research", "planning", "build", "analysis"}:
        return True
    return any(
        keyword in text
        for keyword in ["multi-step project", "full project", "完整项目", "大型项目"]
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
        execution_mode = "direct" if complexity == "simple" and goal_type in {"question", "weather_inquiry"} else "planned"
        return {
            "execution_mode": execution_mode,
            "parallel_aides": 0,
            "parallel_forges": 0,
            "parallel_slots": 0,
            "decision_reasons": ["Request can be handled without sub-agent delegation."],
            "agent_selection": {
                "coordinator": "serana",
                "worker": None,
                "strategy": execution_mode,
            },
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
        "decision_reasons": [
            f"Goal type '{goal_type}' with {complexity} complexity benefits from sub-agent work.",
            f"Use up to {parallel_slots} parallel slot(s) across Aide coordination and Forge execution.",
        ],
        "agent_selection": {
            "coordinator": "aide",
            "worker": "forge",
            "strategy": f"{goal_type}_delegation",
        },
    }


def _infer_delegated_task_type(description: str, fallback_goal_type: str) -> str:
    text = description.lower()
    if any(keyword in text for keyword in ["research", "compare", "investigate", "source", "资料", "调研", "比较"]):
        return "research"
    if any(keyword in text for keyword in ["plan", "schedule", "roadmap", "organize", "计划", "规划", "安排"]):
        return "planning"
    if any(keyword in text for keyword in ["build", "implement", "develop", "code", "refactor", "实现", "开发", "编写"]):
        return "build"
    if any(keyword in text for keyword in ["analyze", "audit", "review", "evaluate", "分析", "审查", "评估"]):
        return "analysis"
    if "?" in description or any(keyword in text for keyword in ["what", "why", "how", "什么", "为什么", "如何"]):
        return "question"
    return fallback_goal_type if fallback_goal_type in {"research", "planning", "build", "analysis", "question"} else "task"


def _build_subtask_assignment(
    *,
    index: int,
    subtask: dict[str, Any],
    goal_type: str,
    delegation_plan: dict[str, Any],
) -> dict[str, Any]:
    description = str(subtask.get("description") or "")
    task_type = _infer_delegated_task_type(description, goal_type)
    retry_by_type = {
        "research": 1,
        "planning": 1,
        "build": 2,
        "analysis": 1,
        "question": 0,
        "task": 1,
    }
    batch_size_by_type = {
        "research": 2,
        "planning": 2,
        "build": 1,
        "analysis": 2,
        "question": 1,
        "task": 1,
    }
    max_worker_parallelism_by_type = {
        "research": 3,
        "planning": 2,
        "build": 2,
        "analysis": 2,
        "question": 1,
        "task": 1,
    }
    parallel_forges = min(
        int(delegation_plan.get("parallel_forges") or 1),
        max_worker_parallelism_by_type.get(task_type, 1),
    )
    priority = "high" if index == 0 or task_type in {"research", "build"} else "normal"
    return {
        "subtask_id": subtask.get("id"),
        "subtask_order": subtask.get("order", index + 1),
        "task_type": task_type,
        "coordinator": "aide",
        "worker": "forge",
        "priority": priority,
        "parallel_forges": max(1, parallel_forges),
        "max_retries": retry_by_type.get(task_type, 1),
        "batch_size": batch_size_by_type.get(task_type, 1),
        "decision_reason": f"Use Aide to coordinate a {task_type} subtask and Forge to execute concrete batches.",
    }


def _build_agent_lifecycle_output(
    *,
    agent_type: str,
    status: str,
    subtask: dict[str, Any],
    assignment: dict[str, Any],
    agent_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "agent_type": agent_type,
        "agent_id": agent_id,
        "status": status,
        "subtask_id": subtask.get("id"),
        "subtask_order": subtask.get("order"),
        "subtask_description": subtask.get("description"),
        "task_type": assignment.get("task_type"),
        "priority": assignment.get("priority"),
        **dict(details or {}),
    }


def _default_subtasks_for_goal(goal_type: str) -> list[str]:
    if goal_type == "research":
        return [
            "Clarify the research question and success criteria",
            "Gather and compare the most relevant findings",
            "Synthesize the findings into a practical recommendation",
        ]
    if goal_type == "planning":
        return [
            "Clarify the objective, constraints, and preferred pace",
            "Draft a practical step-by-step plan",
            "Review the plan for gaps, timing, and next actions",
        ]
    if goal_type == "build":
        return [
            "Clarify the expected behavior and implementation boundaries",
            "Implement the core change in the smallest useful slice",
            "Verify the result and note any follow-up work",
        ]
    if goal_type == "analysis":
        return [
            "Inspect the current state and identify the key signals",
            "Compare options, risks, and trade-offs",
            "Summarize the conclusion with recommended next steps",
        ]
    return [
        "Clarify the objective and constraints",
        "Prepare a concise execution plan",
        "Carry out the plan and report the result",
    ]


def _format_local_delegated_summary(
    *,
    user_input: str,
    subtasks: list[dict[str, Any]],
    completed_count: int,
    failed_count: int,
    execution_mode: str = "delegated",
) -> str:
    if not subtasks:
        return f"我已经处理了这个请求：{user_input}"

    if execution_mode == "planned":
        status_line = f"我已经把这件事整理成 {len(subtasks)} 个可执行步骤。"
    else:
        status_line = f"我已经把这件事拆成 {len(subtasks)} 个步骤并完成了执行。"
    if failed_count:
        status_line = f"我已经推进了这件事：完成 {completed_count} 项，仍有 {failed_count} 项需要继续处理。"

    lines = [status_line, "", "主要步骤："]
    for task in subtasks[:5]:
        description = str(task.get("description") or "").strip()
        if not description:
            continue
        status = str(task.get("status") or "pending")
        status_label = {
            "completed": "已完成",
            "failed": "未完成",
            "in_progress": "进行中",
            "pending": "待处理",
        }.get(status, status)
        lines.append(f"- {description}（{status_label}）")

    if execution_mode == "planned":
        lines.extend(["", "可以从第一步开始推进，我会根据进度继续更新计划。"])
    elif failed_count:
        lines.extend(["", "我建议下一步先处理未完成项，再把结果汇总给你。"])
    else:
        lines.extend(["", "整体已经处理完毕，可以继续根据这个结果做下一步安排。"])

    return "\n".join(lines)


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
        "browser": "browser.search_web",
        "web": "browser.search_web",
        "web_search": "browser.search_web",
        "search_web": "browser.search_web",
        "browser.search": "browser.search_web",
        "browser.search_web": "browser.search_web",
        "browser.open": "browser.open_page",
        "browser.open_page": "browser.open_page",
        "open_page": "browser.open_page",
        "browser.observe": "browser.observe_page",
        "browser.observe_page": "browser.observe_page",
        "observe_page": "browser.observe_page",
        "browser.act": "browser.act_page",
        "browser.act_page": "browser.act_page",
        "act_page": "browser.act_page",
        "browser.capture": "browser.capture_page",
        "browser.capture_page": "browser.capture_page",
        "capture_page": "browser.capture_page",
        "browser.look": "browser.look_page",
        "browser.look_page": "browser.look_page",
        "look_page": "browser.look_page",
        "browser.downloads": "browser.browser_downloads",
        "browser.browser_downloads": "browser.browser_downloads",
        "browser_downloads": "browser.browser_downloads",
        "downloads": "browser.browser_downloads",
        "browser.preview": "browser.create_html_preview",
        "browser.html_preview": "browser.create_html_preview",
        "browser.create_html_preview": "browser.create_html_preview",
        "create_html_preview": "browser.create_html_preview",
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

    if tool_name == "browser.search_web":
        query = str(normalized.get("query") or normalized.get("q") or user_input).strip()
        if not query:
            return None
        try:
            max_results = max(1, min(int(normalized.get("max_results") or 5), 8))
        except (TypeError, ValueError):
            max_results = 5
        return {"query": query, "max_results": max_results}

    if tool_name == "browser.open_page":
        url = str(normalized.get("url") or normalized.get("href") or "").strip()
        if not url:
            url_match = re.search(r"https?://\S+|(?:www\.)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/\S*)?", user_input)
            if url_match:
                url = url_match.group(0).strip("，。！？,.!?")
        if not url:
            return None
        try:
            max_chars = max(500, min(int(normalized.get("max_chars") or 4000), 12000))
        except (TypeError, ValueError):
            max_chars = 4000
        return {"url": url, "max_chars": max_chars}

    if tool_name == "browser.observe_page":
        try:
            max_chars = max(500, min(int(normalized.get("max_chars") or 4000), 12000))
        except (TypeError, ValueError):
            max_chars = 4000
        return {"max_chars": max_chars}

    if tool_name == "browser.act_page":
        action = str(normalized.get("action") or "").strip().lower()
        if not action:
            return None
        tool_input: dict[str, Any] = {"action": action}
        target = str(normalized.get("target") or "").strip()
        value = str(normalized.get("value") or "").strip()
        if target:
            tool_input["target"] = target
        if value:
            tool_input["value"] = value
        return tool_input

    if tool_name == "browser.capture_page":
        return {"full_page": bool(normalized.get("full_page") or False)}

    if tool_name == "browser.look_page":
        return {"full_page": bool(normalized.get("full_page") or False)}

    if tool_name == "browser.browser_downloads":
        action = str(normalized.get("action") or "list").strip().lower()
        if action not in {"list", "send"}:
            action = "list"
        result: dict[str, Any] = {"action": action}
        filename = str(normalized.get("filename") or "").strip()
        if filename:
            result["filename"] = filename
        return result

    if tool_name == "browser.create_html_preview":
        title = str(normalized.get("title") or "Serana 演示").strip()
        html = str(normalized.get("html") or "").strip()
        return {"title": title[:80] or "Serana 演示", "html": html}

    return None


def _strip_markdown_fences(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:html)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_html_preview_document(raw_text: str) -> str:
    text = _strip_markdown_fences(raw_text)
    if not text:
        return ""
    lowered = text.lower()
    doctype_index = lowered.find("<!doctype html")
    if doctype_index != -1:
        return text[doctype_index:].strip()
    html_index = lowered.find("<html")
    if html_index != -1:
        return text[html_index:].strip()
    return text


def _html_preview_has_placeholder_code(html: str) -> bool:
    return bool(_HTML_PREVIEW_PLACEHOLDER_PATTERN.search(str(html or "")))


def _html_preview_requires_inline_script(user_input: str, title: str, html: str) -> bool:
    intent_text = f"{user_input}\n{title}"
    asks_for_interaction = any(keyword in intent_text for keyword in ("演示", "动画", "排序", "交互", "可视化")) or any(
        keyword in intent_text.lower() for keyword in ("demo", "animation", "interactive", "visual", "sort")
    )
    return asks_for_interaction and "<script" not in str(html or "").lower()


def _html_preview_has_unwired_controls(html: str) -> bool:
    text = str(html or "")
    return bool(_HTML_PREVIEW_CONTROL_PATTERN.search(text)) and not bool(
        _HTML_PREVIEW_EVENT_BINDING_PATTERN.search(text)
    )


async def _generate_html_preview_arguments(
    llm: BaseChatModel,
    *,
    user_input: str,
    tool_input: dict[str, Any],
) -> dict[str, Any] | None:
    title = str(tool_input.get("title") or "Serana 演示").strip()[:80] or "Serana 演示"
    draft_html = str(tool_input.get("html") or "").strip()
    repair_feedback = ""

    system_prompt = (
        "You generate a single self-contained HTML document for Serana's in-app preview surface.\n"
        "Return HTML only, with no markdown fences and no commentary.\n"
        "Requirements:\n"
        "- Output one complete HTML document, or a complete body fragment that can run as-is once wrapped.\n"
        "- Use inline CSS and inline JavaScript only.\n"
        "- No placeholder comments, TODO markers, or missing-code scaffolds.\n"
        "- No external URLs, imports, fetch, XMLHttpRequest, WebSocket, EventSource, forms, or iframes.\n"
        "- The page must work inside a mobile WebView.\n"
        "- Render visible content immediately.\n"
        "- If there are visible controls, wire each one to a real behavior.\n"
        "- Any button, input, select, textarea, or role=button control must have an inline event binding such as addEventListener or onclick.\n"
        "- Use Chinese UI copy unless the user explicitly asked for another language."
    )

    for _ in range(2):
        prompt = (
            f"User request:\n{user_input}\n\n"
            f"Preview title:\n{title}\n\n"
            "Current draft from the routing step (may be incomplete):\n"
            f"{draft_html or '(empty draft)'}\n\n"
            f"{repair_feedback}"
            "Return the final HTML now."
        )
        try:
            response = await llm.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=prompt),
                ]
            )
        except Exception as exc:
            logger.warning("HTML preview generation failed: %s", exc)
            return None

        candidate_html = _extract_html_preview_document(str(response.content))
        if not candidate_html:
            repair_feedback = (
                "The previous output was empty. Generate a real HTML document with visible content and working interaction.\n\n"
            )
            continue
        if _html_preview_has_placeholder_code(candidate_html):
            repair_feedback = (
                "The previous output still contained placeholder code or comments. Replace every placeholder with real runnable HTML, CSS, and JavaScript.\n\n"
            )
            continue
        if _html_preview_requires_inline_script(user_input, title, candidate_html):
            repair_feedback = (
                "The request needs an interactive page, but the previous output did not include working inline JavaScript. Add real interaction logic.\n\n"
            )
            continue
        if _html_preview_has_unwired_controls(candidate_html):
            repair_feedback = (
                "The previous output had visible controls, but no event binding was detected. Wire every control to real inline JavaScript behavior.\n\n"
            )
            continue
        return {"title": title, "html": candidate_html}

    if (
        draft_html
        and not _html_preview_has_placeholder_code(draft_html)
        and not _html_preview_has_unwired_controls(draft_html)
    ):
        return {"title": title, "html": draft_html}
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


def _browser_look_image_content(tool_output: dict[str, Any]) -> dict[str, Any] | None:
    observation = tool_output.get("model_observation")
    if not isinstance(observation, dict):
        return None
    image_path = observation.get("image_path")
    if not isinstance(image_path, str) or not image_path.strip():
        return None
    path = Path(image_path)
    try:
        resolved = path.resolve()
    except OSError:
        return None
    screenshot_root = (
        Path(__file__).resolve().parents[3] / "skills_store" / "browser" / "screenshots"
    ).resolve()
    if not resolved.is_relative_to(screenshot_root):
        return None
    try:
        data = resolved.read_bytes()
    except OSError:
        return None
    if not data or len(data) > _MAX_BROWSER_LOOK_IMAGE_BYTES:
        return None
    if observation.get("runtime_only") is True:
        try:
            resolved.unlink()
        except OSError:
            pass
    mime_type = str(observation.get("mime_type") or tool_output.get("mime_type") or "image/png")
    encoded = base64.b64encode(data).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{mime_type};base64,{encoded}",
        },
    }


async def _summarize_browser_tool_result(
    state: dict[str, Any],
    llm: BaseChatModel,
    *,
    user_input: str,
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: dict[str, Any],
) -> str:
    if "error" in tool_output:
        return str(tool_output.get("summary") or tool_output["error"])

    content = str(tool_output.get("content") or "").strip()
    results = tool_output.get("results") if isinstance(tool_output.get("results"), list) else []
    source = {
        "tool": tool_name,
        "input": tool_input,
        "url": tool_output.get("url"),
        "title": tool_output.get("title"),
        "artifact": tool_output.get("artifact"),
        "artifact_url": tool_output.get("artifact_url"),
        "dimensions": tool_output.get("dimensions"),
        "model_observation": tool_output.get("model_observation"),
        "results": results[:8],
        "downloads": tool_output.get("downloads"),
        "count": tool_output.get("count"),
        "content": content[:6000],
    }
    text_prompt = (
        f"用户问题：{user_input}\n\n"
        f"浏览器结果 JSON：\n{json.dumps(source, ensure_ascii=False)}"
    )
    image_content = (
        _browser_look_image_content(tool_output)
        if tool_name == "browser.look_page"
        else None
    )
    human_content: Any = text_prompt
    if image_content is not None:
        human_content = [
            {
                "type": "text",
                "text": (
                    f"{text_prompt}\n\n"
                    "请直接观察随附的浏览器截图，并结合 JSON 元数据回答用户。"
                ),
            },
            image_content,
        ]
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(
                    content=build_state_system_prompt(
                        state,
                        "You are summarizing browser tool output for a Chinese personal butler. "
                        "Answer the user's question directly in Chinese. Use only the browser result below; "
                        "if the result is insufficient, say what is missing and suggest the next precise browser step. "
                        "Keep the answer concise and do not expose internal tool names.",
                    )
                ),
                HumanMessage(content=human_content),
            ]
        )
        content = str(response.content).strip()
        if content:
            return content
    except Exception:
        logger.exception("Unexpected failure while summarizing browser result")

    title = tool_output.get("title") or tool_output.get("url") or "网页"
    snippet = str(tool_output.get("content") or "")[:500]
    return f"我已读取 {title}。{snippet}"

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



def _resolve_local_fallback_tool_intent(
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
            return {
                "full_name": f"weather.{tool_name}",
                "skill_name": "weather",
                "tool_name": tool_name,
                "arguments": tool_input,
                "callable": tool,
                "source": "local_fallback",
            }

    memory_tool = _resolve_memory_tool(user_input)
    if memory_tool:
        tool_name, tool_input = memory_tool
        tool_input = _attach_memory_scope_arguments(state, f"memory_manager.{tool_name}", tool_input)
        tool = skill_manager.get_tool_function("memory_manager", tool_name)
        if tool:
            return {
                "full_name": f"memory_manager.{tool_name}",
                "skill_name": "memory_manager",
                "tool_name": tool_name,
                "arguments": tool_input,
                "callable": tool,
                "source": "local_fallback",
            }

    math_operation = _extract_math_operation(user_input)
    if math_operation:
        tool_name = str(math_operation["tool_name"])
        tool = skill_manager.get_tool_function("calculator", tool_name)
        if tool:
            tool_input = {"a": math_operation["a"], "b": math_operation["b"]}
            return {
                "full_name": f"calculator.{tool_name}",
                "skill_name": "calculator",
                "tool_name": tool_name,
                "arguments": tool_input,
                "callable": tool,
                "source": "local_fallback",
            }

    time_tool = _resolve_time_tool(user_input)
    if time_tool:
        tool_name, tool_input = time_tool
        tool = skill_manager.get_tool_function("time_manager", tool_name)
        if tool:
            return {
                "full_name": f"time_manager.{tool_name}",
                "skill_name": "time_manager",
                "tool_name": tool_name,
                "arguments": tool_input,
                "callable": tool,
                "source": "local_fallback",
            }

    return None


async def _try_local_tool_response(
    state: dict[str, Any],
    llm: BaseChatModel,
    user_input: str,
) -> dict[str, Any] | None:
    tool_intent = _resolve_local_fallback_tool_intent(state, user_input)
    if tool_intent is None:
        return None

    selected_tool_name = str(tool_intent["full_name"])
    state = _record_tool_selection(
        state,
        requested_tool_name="local_fallback",
        selected_tool_name=selected_tool_name,
        arguments=dict(tool_intent["arguments"]),
        reason="Regex fallback matched a local safe tool after the planner could not complete the request.",
        status="selected",
        detail="Local fallback selected a safe tool and will execute through the shared direct tool executor.",
    )
    return await _execute_resolved_direct_tool_intent(
        state,
        llm,
        user_input=user_input,
        tool_intent=tool_intent,
    )


async def _plan_conversation_route(
    state: dict[str, Any],
    llm: BaseChatModel,
    user_input: str,
) -> dict[str, Any] | None:
    context_bundle = build_serana_context_bundle(state, user_input=user_input)
    request_content = context_bundle.build_request_context(
        label="User message",
        include_resident_memory=False,
        include_working_memory=False,
        include_memory=False,
        include_instruction_skills=True,
        include_runtime=False,
        include_available_tools=False,
    )

    prompt = (
        "You triage a personal butler request.\n"
        "Return JSON only, with no markdown fences and no extra text.\n"
        "Choose one route:\n"
        '- {"route":"direct_tool","tool_name":"...","arguments":{},"reason":"..."}\n'
        '- {"route":"direct_reply","reply":"...","goal_type":"...","complexity":"simple|medium","reason":"..."}\n'
        '- {"route":"delegated","goal_type":"...","summary":"...","complexity":"medium|high","reason":"..."}\n'
        "Use direct_tool for weather, time/date, simple arithmetic, explicit memory save/search, temporary working-memory notes, explicit browser/web page inspection, and self-contained HTML demo previews.\n"
        "Use direct_reply for ordinary conversational questions that can be answered in one reply.\n"
        "Use delegated only for genuinely multi-step work, planning, research, analysis, or implementation.\n"
        "Prefer local domain skills before browser. Use browser.search_web only when the user asks to browse/search the web, asks about a public page, or the answer requires current web information that no local skill covers. Use browser.act_page only for small safe page actions on an already-open page. Use browser.capture_page when the user asks for a screenshot of the current browser page. Use browser.look_page when Serana needs to visually inspect the current browser page before answering. Use browser.browser_downloads to list browser downloads or send a listed download file to the user. Use browser.create_html_preview when the user asks to show an interactive demo or visual explanation as a self-contained page. The html argument must be a real HTML draft, never placeholder comments like /* offline demo script here */ or 'JavaScript code for ...'. The runtime will expand the draft into the final mobile-friendly page, so include the real intended structure, controls, and behavior.\n"
        "Keep internal implementation details hidden from the user.\n"
        "Examples:\n"
        '- User: "What time is it?" -> {"route":"direct_tool","tool_name":"time_manager.get_current_time","arguments":{"timezone":"Asia/Shanghai","format":"full"},"reason":"Time lookup"}\n'
        '- User: "37*18 equals what?" -> {"route":"direct_tool","tool_name":"calculator.multiply","arguments":{"a":37,"b":18},"reason":"Arithmetic"}\n'
        '- User: "帮我记住我喜欢黑咖啡" -> {"route":"direct_tool","tool_name":"memory_manager.memory_save","arguments":{"key":"preferred_drink","value":"黑咖啡","category":"preference"},"reason":"Explicit memory save"}\n'
        '- User: "我之前说过我喜欢什么饮料？" -> {"route":"direct_tool","tool_name":"memory_manager.memory_search","arguments":{"query":"喜欢什么饮料","limit":5},"reason":"Memory lookup"}\n'
        '- User: "先记一下这次旅行预算是 5000 元" -> {"route":"direct_tool","tool_name":"memory_manager.working_memory_save","arguments":{"key":"这次旅行预算","value":"5000 元","scope":"conversation"},"reason":"Temporary working note"}\n'
        '- User: "把这轮临时笔记清掉" -> {"route":"direct_tool","tool_name":"memory_manager.working_memory_clear","arguments":{"scope":"conversation"},"reason":"Clear working memory for this conversation"}\n'
        '- User: "帮我看看 https://example.com 这个页面讲什么" -> {"route":"direct_tool","tool_name":"browser.open_page","arguments":{"url":"https://example.com","max_chars":4000},"reason":"Public web page inspection"}\n'
        '- User: "上网查一下 OpenAI 最新消息" -> {"route":"direct_tool","tool_name":"browser.search_web","arguments":{"query":"OpenAI 最新消息","max_results":5},"reason":"Current web search"}\n'
        '- User: "给当前网页截个图" -> {"route":"direct_tool","tool_name":"browser.capture_page","arguments":{"full_page":false},"reason":"Browser screenshot request"}\n'
        '- User: "看一下当前网页显示是否正常" -> {"route":"direct_tool","tool_name":"browser.look_page","arguments":{"full_page":false},"reason":"Browser visual inspection"}\n'
        '- User: "把浏览器下载的文件发给我" -> {"route":"direct_tool","tool_name":"browser.browser_downloads","arguments":{"action":"list"},"reason":"List browser downloads before sending"}\n'
        '- User: "用浏览器展示冒泡排序的演示" -> {"route":"direct_tool","tool_name":"browser.create_html_preview","arguments":{"title":"冒泡排序演示","html":"<section><h1>冒泡排序演示</h1><div id=\\"bars\\"></div><button id=\\"start\\">开始演示</button><p id=\\"status\\">展示每一步比较与交换。</p></section>"},"reason":"Interactive local demo preview"}\n'
        '- User: "What should I study tonight?" -> {"route":"direct_reply","reply":"Focus on one or two high-impact topics tonight and keep the session manageable.","goal_type":"question","complexity":"simple","reason":"Single-turn advice"}\n'
        '- User: "Research and build a weekly study plan" -> {"route":"delegated","goal_type":"research","summary":"Create a weekly study plan with research and structure.","complexity":"high","reason":"Needs planning and decomposition"}'
    )
    prompt = context_bundle.build_system_prompt(
        prompt,
        include_instruction_skills=False,
        include_available_tools=True,
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
    status = "failed" if "error" in tool_output else "completed"
    standard_result = _build_standard_tool_result(
        skill_name=skill_name,
        tool_name=tool_name,
        tool_input=tool_input,
        tool_output=tool_output,
        status=status,
        user_summary=final_response,
    )

    next_state = add_thinking_block(
        state,
        "Tool",
        f"Handled this request with the local tool {skill_name}.{tool_name}.",
    )
    next_state = add_tool_call(
        next_state,
        f"{skill_name}.{tool_name}",
        tool_input,
        _tool_output_with_standard_result(tool_output, standard_result),
        status=status,
    )
    next_state = _append_tool_result(next_state, standard_result)
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


def _route_after_tool_selection_failure(
    state: dict[str, Any],
    *,
    goal_type: Any = None,
    complexity: Any = None,
) -> dict[str, Any]:
    return {
        **state,
        "goal_type": goal_type or _infer_goal_type(get_primary_user_input(state)),
        "complexity": _normalize_complexity(complexity or "medium"),
        "execution_mode": "delegated",
        "serana_status": "routing",
    }


def _resolve_planned_tool_intent(
    planned_state: dict[str, Any],
    route_info: dict[str, Any],
    user_input: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    planned_tool_name = _normalize_planned_tool_name(route_info.get("tool_name"))
    math_operation = _extract_math_operation(user_input)
    if math_operation and not planned_tool_name.startswith("calculator."):
        planned_tool_name = f"calculator.{math_operation['tool_name']}"
        route_info = {
            **route_info,
            "arguments": {"a": math_operation["a"], "b": math_operation["b"]},
            "reason": "Explicit arithmetic expression overrides an ambiguous routed tool.",
        }
    planned_args = _normalize_direct_tool_arguments(
        planned_tool_name,
        route_info.get("arguments") or {},
        user_input,
    )
    if planned_args is not None:
        planned_args = _attach_memory_scope_arguments(planned_state, planned_tool_name, planned_args)

    if not planned_tool_name or planned_args is None or "." not in planned_tool_name:
        planned_state = _record_tool_selection(
            planned_state,
            requested_tool_name=route_info.get("tool_name"),
            selected_tool_name=planned_tool_name or None,
            arguments=planned_args,
            reason=route_info.get("reason"),
            status="rejected",
            detail="The LLM route did not normalize to a supported tool call.",
        )
        return planned_state, None

    skill_name, tool_name = planned_tool_name.split(".", 1)
    skill_manager = SkillManager()
    skill_manager.ensure_initialized()
    tool = skill_manager.get_tool_function(skill_name, tool_name)
    if not tool:
        planned_state = _record_tool_selection(
            planned_state,
            requested_tool_name=route_info.get("tool_name"),
            selected_tool_name=planned_tool_name,
            arguments=planned_args,
            reason=route_info.get("reason"),
            status="unavailable",
            detail="The selected tool is not installed or enabled.",
        )
        return planned_state, None

    planned_state = _record_tool_selection(
        planned_state,
        requested_tool_name=route_info.get("tool_name"),
        selected_tool_name=planned_tool_name,
        arguments=planned_args,
        reason=route_info.get("reason"),
        status="selected",
        detail="The LLM route selected an available local tool.",
    )
    return planned_state, {
        "full_name": planned_tool_name,
        "skill_name": skill_name,
        "tool_name": tool_name,
        "arguments": planned_args,
        "callable": tool,
    }


def _build_html_preview_failure_state(
    planned_state: dict[str, Any],
    *,
    planned_tool_name: str,
    skill_name: str,
    tool_name: str,
    planned_args: dict[str, Any],
) -> dict[str, Any]:
    tool_output = {
        "error": "Could not generate a complete interactive HTML preview.",
        "summary": "生成演示页面失败：这次拿到的 HTML 仍然是不完整草稿，所以我先没有把空白演示发给你。",
    }
    standard_result = _build_standard_tool_result(
        skill_name=skill_name,
        tool_name=tool_name,
        tool_input=planned_args,
        tool_output=tool_output,
        status="failed",
        user_summary=tool_output["summary"],
    )
    next_state = add_thinking_block(
        planned_state,
        "Preview",
        "The HTML preview draft was incomplete, so I stopped before sending a blank demo page.",
    )
    next_state = add_tool_call(
        next_state,
        planned_tool_name,
        planned_args,
        _tool_output_with_standard_result(tool_output, standard_result),
        status="failed",
    )
    next_state = _append_tool_result(next_state, standard_result)
    return {
        **next_state,
        "execution_mode": "direct",
        "final_response": "这次的演示页代码还是半成品，所以我先拦住了，没有再把一个空白页面发给你。接下来会继续让模型生成完整可运行的页面。",
        "serana_status": "idle",
    }


def _build_approval_denied_state(
    planned_state: dict[str, Any],
    *,
    planned_tool_name: str,
    skill_name: str,
    tool_name: str,
    planned_args: dict[str, Any],
    approval_result: dict[str, Any],
) -> dict[str, Any]:
    user_message = str(approval_result.get("user_message") or "Approval denied.")
    tool_output = {
        "error": user_message,
        "approval_required": True,
        "request_id": approval_result.get("request_id"),
    }
    standard_result = _build_standard_tool_result(
        skill_name=skill_name,
        tool_name=tool_name,
        tool_input=planned_args,
        tool_output=tool_output,
        status="failed",
        user_summary=user_message,
    )
    next_state = add_thinking_block(
        planned_state,
        "Approval",
        str(approval_result.get("user_message") or "The requested action did not pass approval."),
    )
    next_state = add_tool_call(
        next_state,
        planned_tool_name,
        planned_args,
        _tool_output_with_standard_result(tool_output, standard_result),
        status="failed",
    )
    next_state = _append_tool_result(next_state, standard_result)
    return {
        **next_state,
        "execution_mode": "direct",
        "final_response": str(approval_result.get("user_message") or "I did not execute that action."),
        "serana_status": "idle",
    }


async def _execute_resolved_direct_tool_intent(
    planned_state: dict[str, Any],
    llm: BaseChatModel,
    *,
    user_input: str,
    tool_intent: dict[str, Any],
) -> dict[str, Any] | None:
    planned_tool_name = str(tool_intent["full_name"])
    skill_name = str(tool_intent["skill_name"])
    tool_name = str(tool_intent["tool_name"])
    planned_args = dict(tool_intent["arguments"])
    tool = tool_intent["callable"]

    if planned_tool_name == "browser.create_html_preview":
        generated_preview_args = await _generate_html_preview_arguments(
            llm,
            user_input=user_input,
            tool_input=planned_args,
        )
        if generated_preview_args is None:
            return _build_html_preview_failure_state(
                planned_state,
                planned_tool_name=planned_tool_name,
                skill_name=skill_name,
                tool_name=tool_name,
                planned_args=planned_args,
            )
        planned_args = generated_preview_args

    planned_state, approval_result = await _authorize_tool_call(
        planned_state,
        tool_name=planned_tool_name,
        tool_input=planned_args,
    )
    if not approval_result.get("allowed", False):
        return _build_approval_denied_state(
            planned_state,
            planned_tool_name=planned_tool_name,
            skill_name=skill_name,
            tool_name=tool_name,
            planned_args=planned_args,
            approval_result=approval_result,
        )

    try:
        tool_output = await tool(**planned_args)
    except Exception as exc:
        logger.warning("Lightweight planned tool call failed for %s: %s", planned_tool_name, exc)
        return None

    if skill_name == "browser":
        final_response = await _summarize_browser_tool_result(
            planned_state,
            llm,
            user_input=user_input,
            tool_name=planned_tool_name,
            tool_input=planned_args,
            tool_output=tool_output,
        )
        status = "failed" if "error" in tool_output else "completed"
        standard_result = _build_standard_tool_result(
            skill_name=skill_name,
            tool_name=tool_name,
            tool_input=planned_args,
            tool_output=tool_output,
            status=status,
            user_summary=final_response,
        )
        next_state = add_thinking_block(
            planned_state,
            "Browser",
            "已读取网页内容并整理为面向用户的回复。",
        )
        next_state = add_tool_call(
            next_state,
            planned_tool_name,
            planned_args,
            _tool_output_with_standard_result(tool_output, standard_result),
            status=status,
        )
        next_state = _append_tool_result(next_state, standard_result)
        return {
            **next_state,
            "execution_mode": "direct",
            "final_response": final_response,
            "serana_status": "idle",
        }

    return _execute_planned_tool_intent(
        planned_state,
        skill_name,
        tool_name,
        planned_args,
        tool_output,
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
        return await _try_local_tool_response(state, llm, user_input)

    route_info = dict(planned_state.get("conversation_route") or {})
    route = str(route_info.get("route") or "")

    if route == "direct_tool":
        planned_state, tool_intent = _resolve_planned_tool_intent(
            planned_state,
            route_info,
            user_input,
        )
        if tool_intent is None:
            fallback_state = await _try_local_tool_response(planned_state, llm, user_input)
            if fallback_state is not None:
                return fallback_state
            return _route_after_tool_selection_failure(
                planned_state,
                goal_type=route_info.get("goal_type"),
                complexity=route_info.get("complexity"),
            )

        tool_result_state = await _execute_resolved_direct_tool_intent(
            planned_state,
            llm,
            user_input=user_input,
            tool_intent=tool_intent,
        )
        if tool_result_state is not None:
            return tool_result_state

        fallback_state = await _try_local_tool_response(planned_state, llm, user_input)
        if fallback_state is not None:
            return fallback_state
        return _route_after_tool_selection_failure(
            planned_state,
            goal_type=route_info.get("goal_type"),
            complexity=route_info.get("complexity"),
        )

    if route == "direct_reply":
        memory_fallback = await _try_local_tool_response(planned_state, llm, user_input)
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

    if route == "delegated":
        return {
            **planned_state,
            "goal_type": route_info.get("goal_type") or _infer_goal_type(user_input),
            "complexity": _normalize_complexity(route_info.get("complexity") or "medium"),
            "execution_mode": "delegated",
            "delegation_plan": _build_delegation_plan(
                str(route_info.get("goal_type") or _infer_goal_type(user_input)),
                _normalize_complexity(route_info.get("complexity") or "medium"),
                user_input,
            ),
            "serana_status": "routing",
        }

    return None


async def analyze_node(state: dict[str, Any], llm: BaseChatModel) -> dict[str, Any]:
    state = ensure_instruction_skill_context(state)
    user_input = get_primary_user_input(state)
    original_user_input = user_input
    instruction_skill_context = state.get("instruction_skill_context", "")
    analysis_input = build_state_request_context(state, label="User request")
    state = add_thinking_block(state, "Analyze", f"Reviewing the request: {original_user_input[:120]}")

    summary = user_input
    goal_type = _infer_goal_type(user_input)
    complexity = "medium"
    analysis_source = "planning_llm"
    route_info = dict(state.get("conversation_route") or {})

    if str(route_info.get("route") or "").strip().lower() == "delegated":
        summary = str(route_info.get("summary") or original_user_input)
        goal_type = str(route_info.get("goal_type") or goal_type)
        complexity = _normalize_complexity(route_info.get("complexity") or complexity)
        analysis_source = "lightweight_route"
        state = add_thinking_block(
            state,
            "Analyze",
            f"Reused lightweight route analysis with complexity: {complexity}",
        )
    else:
        system_prompt = build_state_system_prompt(
            state,
            "Analyze the user's request and return JSON with goal_type, summary, and complexity. "
            "Keep the analysis grounded in the user's real intention and optimize for helpful, practical assistance.",
            include_instruction_skills=bool(instruction_skill_context),
        )

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
            analysis_source = "fallback"
            state = add_thinking_block(state, "Analyze", "Used fallback analysis because the model output was invalid.")
        except Exception:
            logger.exception("Unexpected failure in Serana analyze node")
            complexity = "medium"
            analysis_source = "fallback"
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
            "analysis_source": analysis_source,
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

    subtask_descriptions = _default_subtasks_for_goal(goal_type)
    decomposition_source = "template"
    route_info = dict(state.get("conversation_route") or {})
    route_summary = str(route_info.get("summary") or "").strip()
    can_use_route_template = (
        str(route_info.get("route") or "").strip().lower() == "delegated"
        and route_summary
        and complexity in {"medium", "high"}
    )

    if can_use_route_template:
        state = add_thinking_block(
            state,
            "Decompose",
            "Used the lightweight route summary to prepare a standard Butler task plan.",
        )
    else:
        decomposition_source = "planning_llm"
        try:
            response = await llm.ainvoke(
                [
                    SystemMessage(
                        content=build_state_system_prompt(
                            state,
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
            decomposition_source = "fallback"
            state = add_thinking_block(state, "Decompose", "Used fallback subtask plan because the model output was invalid.")
        except Exception:
            logger.exception("Unexpected failure in Serana decompose node")
            decomposition_source = "fallback"
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
            "decomposition_source": decomposition_source,
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
    goal_type = str(state.get("goal_type") or "task")
    parallel_slots = max(1, int(delegation_plan.get("parallel_slots") or 1))
    assignments = [
        _build_subtask_assignment(
            index=index,
            subtask=subtask,
            goal_type=goal_type,
            delegation_plan=delegation_plan,
        )
        for index, subtask in enumerate(subtasks)
    ]
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

    for subtask, assignment in zip(subtasks, assignments):
        state = add_tool_call(
            state,
            "serana_agent_lifecycle",
            {"subtask_id": subtask.get("id"), "agent_type": "aide"},
            _build_agent_lifecycle_output(
                agent_type="aide",
                status="started",
                subtask=subtask,
                assignment=assignment,
                details={
                    "coordinator": assignment["coordinator"],
                    "worker": assignment["worker"],
                    "parallel_forges": assignment["parallel_forges"],
                    "max_retries": assignment["max_retries"],
                },
            ),
        )

    async def _run_subtask(index: int, subtask: dict[str, Any], assignment: dict[str, Any]):
        async with semaphore:
            try:
                aide = await agent_manager.get_agent("aide")
                assigned_subtask = {
                    **subtask,
                    "task_type": assignment["task_type"],
                    "max_retries": assignment["max_retries"],
                    "batch_size": assignment["batch_size"],
                    "parallel_forges": assignment["parallel_forges"],
                    "delegation_assignment": assignment,
                }
                aide_result = await aide.execute(assigned_subtask)
                worker_result = aide_result.get("result", {}).get("worker_result", {})
                return index, subtask, assignment, aide_result, worker_result, None
            except Exception as exc:
                logger.exception("Serana delegation failed for subtask %s", subtask.get("id"))
                return index, subtask, assignment, {}, {}, str(exc)

    results = await asyncio.gather(
        *[
            _run_subtask(index, subtask, assignment)
            for index, (subtask, assignment) in enumerate(zip(subtasks, assignments))
        ],
    )

    aide_agent_ids: set[str] = set()
    forge_agent_ids: set[str] = set()
    for index, subtask, assignment, aide_result, worker_result, error in sorted(results, key=lambda item: item[0]):
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
        subtask_error = error or str(aide_result.get("result", {}).get("error") or worker_result.get("error") or "")

        aide_sessions.append(
            {
                "agent_id": aide_agent_id,
                "task_description": subtask.get("description"),
                "success": aide_success,
                "task_type": aide_result.get("result", {}).get("task_type"),
                "batches_planned": aide_result.get("result", {}).get("batches_planned"),
                "assignment": assignment,
                "error": subtask_error or None,
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
                    "task_type": assignment.get("task_type"),
                    "error": batch_result.get("error") or None,
                }
            )
            state = add_tool_call(
                state,
                "serana_agent_lifecycle",
                {"subtask_id": subtask.get("id"), "agent_type": "forge"},
                _build_agent_lifecycle_output(
                    agent_type="forge",
                    agent_id=str(batch_worker.get("agent_id") or forge_agent_id or "") or None,
                    status="completed" if batch_result.get("status") == "completed" else "failed",
                    subtask=subtask,
                    assignment=assignment,
                    details={
                        "batch_index": batch_result.get("batch_index"),
                        "attempts": batch_result.get("attempts"),
                        "strategy": batch_worker.get("result", {}).get("strategy"),
                        "tool_name": batch_worker.get("result", {}).get("tool_name"),
                        "error": batch_result.get("error") or None,
                    },
                ),
                status="completed" if batch_result.get("status") == "completed" else "failed",
            )
        state = add_tool_call(
            state,
            "serana_agent_lifecycle",
            {"subtask_id": subtask.get("id"), "agent_type": "aide"},
            _build_agent_lifecycle_output(
                agent_type="aide",
                agent_id=aide_agent_id or None,
                status="completed" if aide_success else "failed",
                subtask=subtask,
                assignment=assignment,
                details={
                    "batches_planned": aide_result.get("result", {}).get("batches_planned"),
                    "retry_limit": aide_result.get("result", {}).get("retry_limit"),
                    "error": subtask_error or None,
                },
            ),
            status="completed" if aide_success else "failed",
        )
        aide_output = {
            "agent_id": aide_agent_id,
            "success": aide_success,
            "thinking_block_count": len(aide_result.get("thinking_blocks", [])),
            "task_type": aide_result.get("result", {}).get("task_type"),
            "batches_planned": aide_result.get("result", {}).get("batches_planned"),
            "retry_limit": aide_result.get("result", {}).get("retry_limit"),
            "assignment": assignment,
            "error": subtask_error or None,
        }
        aide_tool_result = _build_standard_tool_result(
            skill_name="serana",
            tool_name="aide_execute",
            tool_input={"subtask_description": subtask.get("description"), "assignment": assignment},
            tool_output=aide_output,
            status="completed" if aide_success else "failed",
            user_summary=(
                f"Aide 已协调子任务：{subtask.get('description')}"
                if aide_success
                else f"Aide 协调子任务失败：{subtask.get('description')}"
            ),
        )
        state = add_tool_call(
            state,
            "aide_execute",
            {"subtask_description": subtask.get("description")},
            _tool_output_with_standard_result(aide_output, aide_tool_result),
            status="completed" if aide_success else "failed",
        )
        state = _append_tool_result(state, aide_tool_result)

        forge_output = {
            "agent_id": forge_agent_id,
            "agent_ids": worker_result.get("agent_ids", batch_forge_agent_ids),
            "success": forge_success,
            "batch_count": worker_result.get("batch_count"),
            "attempts": worker_result.get("attempts"),
            "strategy": worker_result.get("strategy"),
            "tool_name": worker_result.get("tool_name"),
            "task_type": assignment.get("task_type"),
            "error": subtask_error or None,
        }
        forge_tool_result = _build_standard_tool_result(
            skill_name="serana",
            tool_name="forge_execute",
            tool_input={"subtask_description": subtask.get("description"), "assignment": assignment},
            tool_output=forge_output,
            status="completed" if forge_success else "failed",
            user_summary=(
                f"Forge 已执行子任务：{subtask.get('description')}"
                if forge_success
                else f"Forge 执行子任务失败：{subtask.get('description')}"
            ),
        )
        state = add_tool_call(
            state,
            "forge_execute",
            {"subtask_description": subtask.get("description")},
            _tool_output_with_standard_result(forge_output, forge_tool_result),
            status="completed" if forge_success else "failed",
        )
        state = _append_tool_result(state, forge_tool_result)
        delegated_subtasks.append(
            {
                **subtask,
                "status": subtask_status,
                "assignment": assignment,
                "error": subtask_error or None,
            }
        )

    completed_count = sum(1 for task in delegated_subtasks if task["status"] == "completed")
    failed_count = sum(1 for task in delegated_subtasks if task["status"] == "failed")
    fallback_summary = None
    if failed_count:
        fallback_summary = (
            f"Delegation completed with partial results: {completed_count} completed, "
            f"{failed_count} failed. Serana will summarize completed work and surface remaining gaps."
        )
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
    delegate_output = {
        "completed_subtask_count": completed_count,
        "failed_subtask_count": failed_count,
        "subtask_statuses": [task["status"] for task in delegated_subtasks],
        "parallel_aides": delegation_plan.get("parallel_aides", 0),
        "parallel_forges": delegation_plan.get("parallel_forges", 0),
        "parallel_slots": parallel_slots,
        "actual_aide_agents": len(aide_agent_ids),
        "actual_forge_agents": len(forge_agent_ids),
        "assignments": assignments,
        "fallback_summary": fallback_summary,
    }
    delegate_tool_result = _build_standard_tool_result(
        skill_name="serana",
        tool_name="delegate",
        tool_input={"subtask_count": len(subtasks), "assignments": assignments},
        tool_output=delegate_output,
        status="completed" if failed_count == 0 else "partial" if completed_count > 0 else "failed",
        user_summary=(
            "子代理已完成全部委派任务。"
            if failed_count == 0
            else f"子代理完成 {completed_count} 项，{failed_count} 项需要继续处理。"
        ),
    )
    state = add_tool_call(
        state,
        "serana_delegate",
        {"subtask_count": len(subtasks)},
        _tool_output_with_standard_result(delegate_output, delegate_tool_result),
        status="completed" if all(task["status"] == "completed" for task in delegated_subtasks) else "failed",
    )
    state = _append_tool_result(state, delegate_tool_result)
    return {
        **state,
        "subtasks": delegated_subtasks,
        "aide_sessions": aide_sessions,
        "forge_sessions": forge_sessions,
        "delegation_result": delegate_tool_result,
        "delegation_fallback_summary": fallback_summary,
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
                        content=build_state_system_prompt(
                            state,
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

    completed_count = sum(1 for task in subtasks if task.get("status") == "completed")
    failed_count = sum(1 for task in subtasks if task.get("status") == "failed")
    summary_source = "local_template"
    final_response = _format_local_delegated_summary(
        user_input=original_user_input,
        subtasks=subtasks,
        completed_count=completed_count,
        failed_count=failed_count,
        execution_mode=execution_mode,
    )
    state = _record_working_memory_update(
        state,
        key="summary_ready",
        value=f"completed={completed_count}; failed={failed_count}; subtasks={len(subtasks)}",
        reason="summarize_prep",
    )

    if instruction_skill_context:
        subtask_lines = "\n".join(f"- {task['description']}" for task in subtasks)
        summary_source = "planning_llm"
        try:
            response = await llm.ainvoke(
                [
                    SystemMessage(
                        content=build_state_system_prompt(
                            state,
                            "Summarize the plan in a helpful, concise reply. Mention the main steps without unnecessary "
                            "detail, and make the result feel calm, competent, and personally supportive.",
                            include_instruction_skills=True,
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
            summary_source = "local_template"

    state = add_tool_call(
        state,
        "serana_summarize",
        {"execution_mode": execution_mode, "subtask_count": len(subtasks)},
        {
            "final_response_preview": final_response[:200],
            "summary_source": summary_source,
        },
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
