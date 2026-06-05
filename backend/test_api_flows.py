import json
from pathlib import Path
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import zipfile

import httpx

from app.approvals import get_approval_manager, get_policy_gate
from app.agents.base import AgentManager
from app.agents.serana.context import (
    build_contextual_request,
    build_serana_context_bundle,
    get_relevant_instruction_skills,
    is_live_weather_request,
)
from app.agents.forge import ForgeAgent
from app.agents.serana import SeranaAgent
from app.agents.serana.nodes import (
    _html_preview_request_cache_key,
    _is_html_preview_request,
    _parse_json_object,
    _sanitize_non_code_command_reply,
    _should_reject_non_code_command_reply,
    analyze_node,
    decompose_node,
    delegate_node,
    summarize_node,
    try_lightweight_conversation,
)
from app.api.skills import get_marketplace_client
from app.core.database import AsyncSessionLocal
from app.core.init_db import create_default_user, init_db
from app.main import app
from app.memory import MemoryInjector, MemoryService, ProfileFactsManager, ResidentMemoryManager, WorkingMemoryManager
from app.skills import SkillManager
from app.skills.models import MarketplaceSearchResponse, MarketplaceSkillSummary, SkillTool, SkillToolInputSchema
from app.skills.validator import SkillValidator


class FakeResponse:
    def __init__(self, content: str):
        self.content = content


class InstructionSkillRoutingTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_json_object_accepts_reasoning_fences_and_content_blocks(self):
        parsed = _parse_json_object(
            [
                {"type": "text", "text": "<think>I considered several routes.</think>"},
                {
                    "type": "text",
                    "text": (
                        "Here is the structured result:\n"
                        "```json\n"
                        '{"route":"direct_reply","goal_type":"planning","complexity":"medium"}\n'
                        "```"
                    ),
                },
            ]
        )

        self.assertEqual(parsed["route"], "direct_reply")
        self.assertEqual(parsed["goal_type"], "planning")

    async def test_one_shot_planning_request_bypasses_structured_route_failures(self):
        class PlainTextPlanningLLM:
            def __init__(self):
                self.call_count = 0

            async def ainvoke(self, messages):
                self.call_count += 1
                return FakeResponse("🌙 明天可以从上海博物馆开始，下午去思南路，晚上沿外滩散步。")

        llm = PlainTextPlanningLLM()
        state = {
            "user_input": "明天我准备一个人在上海逛一下，你帮我计划一下",
            "original_user_input": "明天我准备一个人在上海逛一下，你帮我计划一下",
            "memory_context": "【对话历史】\n用户: 你好\n助手: 晚上好，龙裔。",
            "tool_calls": [],
            "thinking_blocks": [],
        }

        with patch.object(SkillManager, "find_relevant_executable_tools", return_value=[]):
            result = await try_lightweight_conversation(state, llm)

        self.assertEqual(result["execution_mode"], "direct")
        self.assertEqual(result["goal_type"], "planning")
        self.assertIn("上海博物馆", result["final_response"])
        self.assertEqual(llm.call_count, 1)
        tool_names = [str(item.get("name") or "") for item in result["tool_calls"]]
        self.assertNotIn("conversation_route", tool_names)
        self.assertNotIn("serana_analyze", tool_names)
        self.assertNotIn("serana_decompose", tool_names)

    async def test_short_social_message_bypasses_context_assessment_and_structured_route(self):
        class SocialReplyLLM:
            def __init__(self):
                self.call_count = 0

            async def ainvoke(self, messages):
                self.call_count += 1
                return FakeResponse("晚上好。看起来今晚还算安静，需要我做什么？")

        llm = SocialReplyLLM()
        state = {
            "user_input": "你好",
            "original_user_input": "你好",
            "memory_context": "【对话历史】\n用户: 帮我规划上海行程\n助手: 可以。",
            "recent_history_context": "【对话历史】\n用户: 帮我规划上海行程\n助手: 可以。",
            "tool_calls": [],
            "thinking_blocks": [],
        }

        result = await try_lightweight_conversation(state, llm)

        self.assertEqual(result["execution_mode"], "direct")
        self.assertEqual(result["goal_type"], "conversation")
        self.assertIn("晚上好", result["final_response"])
        self.assertEqual(llm.call_count, 1)
        tool_names = [str(item.get("name") or "") for item in result["tool_calls"]]
        self.assertNotIn("contextual_followup_assessment", tool_names)
        self.assertNotIn("conversation_route", tool_names)
        self.assertNotIn("serana_analyze", tool_names)

    async def test_invalid_conversation_route_falls_back_to_direct_answer(self):
        class InvalidRouteLLM:
            def __init__(self):
                self.call_count = 0

            async def ainvoke(self, messages):
                self.call_count += 1
                if "You triage a private housekeeper request." in messages[0].content:
                    return FakeResponse("This should be answered directly, but I forgot the JSON envelope.")
                return FakeResponse("数据库索引能加快查询，但会占用空间并增加写入成本。")

        llm = InvalidRouteLLM()
        state = {
            "user_input": "解释一下数据库索引是什么",
            "original_user_input": "解释一下数据库索引是什么",
            "tool_calls": [],
            "thinking_blocks": [],
        }

        with patch.object(SkillManager, "find_relevant_executable_tools", return_value=[]):
            result = await try_lightweight_conversation(state, llm)

        self.assertEqual(result["execution_mode"], "direct")
        self.assertIn("数据库索引", result["final_response"])
        self.assertEqual(llm.call_count, 2)
        tool_names = [str(item.get("name") or "") for item in result["tool_calls"]]
        self.assertNotIn("serana_analyze", tool_names)
        self.assertNotIn("serana_decompose", tool_names)

    async def test_decompose_uses_template_after_invalid_analysis_output(self):
        class InvalidStructuredLLM:
            def __init__(self):
                self.call_count = 0

            async def ainvoke(self, messages):
                self.call_count += 1
                return FakeResponse("I will help with that plan, but this is not JSON.")

        llm = InvalidStructuredLLM()
        state = {
            "user_input": "制定一个复杂计划",
            "original_user_input": "制定一个复杂计划",
            "tool_calls": [],
            "thinking_blocks": [],
            "working_memory_entries": {},
            "working_memory_context": "",
        }

        analyzed = await analyze_node(state, llm)
        decomposed = await decompose_node(analyzed, llm)

        self.assertEqual(analyzed["analysis_source"], "fallback")
        self.assertEqual(llm.call_count, 1)
        self.assertTrue(decomposed["subtasks"])
        decompose_call = next(
            item for item in decomposed["tool_calls"] if item["name"] == "serana_decompose"
        )
        self.assertEqual(decompose_call["output"]["decomposition_source"], "template")

    def test_skill_manifest_accepts_capabilities_and_intents(self):
        is_valid, error = SkillValidator.validate_manifest(
            {
                "name": "weather_cn",
                "version": "1.0.1",
                "description": "中文天气查询工具",
                "format": "sebastian_package",
                "runtime": "instruction",
                "instruction_file": "SKILL.md",
                "entrypoint": None,
                "registry_slug": "weather-cn",
                "source_url": "https://skillhub.cn/skills/weather-cn",
                "agent_type": "all",
                "max_instances": 1,
                "capabilities": ["weather", "forecast", "天气"],
                "intents": ["天气查询", "天气预报"],
                "tools": [],
            }
        )

        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def _fake_instruction_skill(self, name: str, description: str, slug: str):
        return SimpleNamespace(
            name=name,
            description=description,
            manifest=SimpleNamespace(
                registry_slug=slug,
                source_url=f"https://skillhub.cn/skills/{slug}",
                capabilities=[],
                intents=[],
            ),
            instruction_content=f"# {name}\n{description}",
        )

    def _fake_instruction_skill_with_manifest(
        self,
        name: str,
        description: str,
        slug: str,
        *,
        capabilities: list[str] | None = None,
        intents: list[str] | None = None,
    ):
        return SimpleNamespace(
            name=name,
            description=description,
            manifest=SimpleNamespace(
                registry_slug=slug,
                source_url=f"https://skillhub.cn/skills/{slug}",
                capabilities=capabilities or [],
                intents=intents or [],
            ),
            instruction_content=f"# {name}\n{description}",
        )

    def test_get_relevant_instruction_skills_prefers_matching_domain(self):
        weather_skill = self._fake_instruction_skill(
            "weather_cn",
            "中文天气查询工具，获取实时天气和预报。",
            "weather-cn",
        )
        improving_skill = self._fake_instruction_skill(
            "self_improving_agent",
            "捕获经验教训、错误和纠正，以实现持续改进。",
            "self-improving-agent",
        )

        with patch.object(
            SkillManager,
            "get_enabled_instruction_skills",
            return_value=[weather_skill, improving_skill],
        ):
            matched = get_relevant_instruction_skills("帮我看看北京明天的天气")

        self.assertEqual([skill.name for skill in matched], ["weather_cn"])

    def test_get_relevant_instruction_skills_prefers_capabilities_and_intents(self):
        weather_skill = self._fake_instruction_skill_with_manifest(
            "weather_cn",
            "一个泛化说明，不直接写天气关键词。",
            "weather-cn",
            capabilities=["weather", "forecast", "天气"],
            intents=["天气查询", "天气预报"],
        )
        generic_skill = self._fake_instruction_skill_with_manifest(
            "daily_helper",
            "日常辅助技能。",
            "daily-helper",
            capabilities=["routine"],
            intents=["整理待办"],
        )

        with patch.object(
            SkillManager,
            "get_enabled_instruction_skills",
            return_value=[generic_skill, weather_skill],
        ):
            matched = get_relevant_instruction_skills("帮我查一下上海明天的天气预报")

        self.assertEqual([skill.name for skill in matched], ["weather_cn"])

    def test_weather_discussion_does_not_activate_live_weather_skill(self):
        weather_skill = self._fake_instruction_skill_with_manifest(
            "weather_cn",
            "中文天气查询工具，获取实时天气和预报。",
            "weather-cn",
            capabilities=["weather", "forecast", "天气"],
            intents=["天气查询", "天气预报"],
        )

        with patch.object(
            SkillManager,
            "get_enabled_instruction_skills",
            return_value=[weather_skill],
        ):
            matched = get_relevant_instruction_skills("你喜欢什么天气")

        self.assertEqual(matched, [])

    def test_live_weather_request_distinguishes_lookup_from_discussion(self):
        self.assertTrue(is_live_weather_request("上海天气"))
        self.assertTrue(is_live_weather_request("帮我查一下上海明天的天气"))
        self.assertTrue(is_live_weather_request("今天会下雨吗"))
        self.assertFalse(is_live_weather_request("你喜欢什么天气"))
        self.assertFalse(is_live_weather_request("什么天气适合跑步"))
        self.assertFalse(is_live_weather_request("天气是怎么形成的"))

    def test_get_relevant_instruction_skills_matches_self_improvement_correction_flow(self):
        self_improving_skill = self._fake_instruction_skill_with_manifest(
            "self_improving_agent",
            "用于复盘错误、吸收纠正和总结经验的持续改进技能。",
            "self-improving-agent",
            capabilities=["self_improvement", "reflection", "error_recovery", "correction"],
            intents=["纠正回答", "总结经验", "复盘错误", "持续改进"],
        )
        weather_skill = self._fake_instruction_skill_with_manifest(
            "weather_cn",
            "中文天气查询工具。",
            "weather-cn",
            capabilities=["weather", "forecast", "天气"],
            intents=["天气查询", "天气预报"],
        )

        with patch.object(
            SkillManager,
            "get_enabled_instruction_skills",
            return_value=[weather_skill, self_improving_skill],
        ):
            matched = get_relevant_instruction_skills("你刚才那段回答不对，按我的纠正改一下，并总结这次错误。")

        self.assertEqual([skill.name for skill in matched], ["self_improving_agent"])

    async def test_lightweight_conversation_prefers_weather_browser_before_instruction_skill(self):
        weather_skill = self._fake_instruction_skill(
            "weather_cn",
            "中文天气查询工具，获取实时天气和预报。",
            "weather-cn",
        )
        state = {
            "user_input": "香港明天天气怎么样",
            "original_user_input": "香港明天天气怎么样",
            "tool_calls": [],
            "thinking_blocks": [],
        }

        with patch.object(
            SkillManager,
            "get_enabled_instruction_skills",
            return_value=[weather_skill],
        ), patch(
            "app.agents.serana.nodes._build_contextual_direct_reply",
            new=AsyncMock(return_value="🌧️ 香港明天有阵雨，稍晚会转阴。"),
        ) as reply_patch, patch(
            "app.agents.serana.nodes._execute_resolved_direct_tool_intent",
            new=AsyncMock(
                return_value={
                    "execution_mode": "direct",
                    "final_response": "Browser weather result",
                    "tool_calls": [{"name": "browser.open_page"}],
                }
            ),
        ) as execute_patch:
            result = await try_lightweight_conversation(state, FakeLLM())

        self.assertIsNotNone(result)
        self.assertEqual(result.get("execution_mode"), "direct")
        self.assertEqual(result.get("final_response"), "Browser weather result")
        reply_patch.assert_not_awaited()
        execute_patch.assert_awaited_once()
        called_state = execute_patch.await_args.args[0]
        self.assertEqual(called_state["tool_calls"][-1]["name"], "serana_tool_selection")
        self.assertEqual(called_state["tool_calls"][-1]["output"]["selected_tool_name"], "browser.open_page")
        tool_call_names = [str(item.get("name")) for item in result.get("tool_calls", [])]
        self.assertIn("browser.open_page", tool_call_names)

    async def test_weather_preference_question_stays_conversational(self):
        weather_skill = self._fake_instruction_skill_with_manifest(
            "weather_cn",
            "中文天气查询工具，获取实时天气和预报。",
            "weather-cn",
            capabilities=["weather", "forecast", "天气"],
            intents=["天气查询", "天气预报"],
        )
        state = {
            "user_input": "你喜欢什么天气",
            "original_user_input": "你喜欢什么天气",
            "tool_calls": [],
            "thinking_blocks": [],
        }

        with patch.object(
            SkillManager,
            "get_enabled_instruction_skills",
            return_value=[weather_skill],
        ), patch(
            "app.agents.serana.nodes._build_contextual_direct_reply",
            new=AsyncMock(return_value="🌙 我更喜欢阴凉安静、不会晒得人无处可躲的天气。"),
        ) as reply_patch, patch(
            "app.agents.serana.nodes._execute_resolved_direct_tool_intent",
            new=AsyncMock(),
        ) as execute_patch:
            result = await try_lightweight_conversation(state, FakeLLM())

        self.assertEqual(result.get("execution_mode"), "direct")
        self.assertIn("我更喜欢", result.get("final_response", ""))
        self.assertNotIn("instruction_skill_context", [item.get("name") for item in result.get("tool_calls", [])])
        reply_patch.assert_awaited_once()
        execute_patch.assert_not_awaited()

    async def test_clarification_answer_reconstructs_weather_request_before_tool_routing(self):
        class ClarificationAnswerLLM(FakeLLM):
            async def ainvoke(self, messages):
                if "Classify whether the current user message is a contextual follow-up." in messages[0].content:
                    return FakeResponse(
                        json.dumps(
                            {
                                "is_followup": True,
                                "action": "resolve_request",
                                "topic": "上海今天的天气",
                                "resolved_request": "查询上海今天的天气",
                                "confidence": 0.98,
                                "reason": "The user answered the assistant's city clarification.",
                            },
                            ensure_ascii=False,
                        )
                    )
                return await super().ainvoke(messages)

        state = {
            "user_input": "上海",
            "original_user_input": "上海",
            "memory_context": "[Relevant Memories]\n用户以前讨论过北京旅行。",
            "recent_history_context": (
                "【对话历史】\n"
                "用户: 今天天气如何\n"
                "助手: 请告诉我你在哪个城市，我帮你查今天的天气。\n"
                "用户: 上海"
            ),
            "tool_calls": [],
            "thinking_blocks": [],
        }
        routed_result = {
            "execution_mode": "direct",
            "final_response": "🌧️ 上海今天有雨。",
            "tool_calls": [],
        }

        with patch(
            "app.agents.serana.nodes._try_local_tool_response",
            new=AsyncMock(return_value=routed_result),
        ) as local_tool_patch:
            result = await try_lightweight_conversation(state, ClarificationAnswerLLM())

        self.assertEqual(result, routed_result)
        routed_state, _, routed_user_input = local_tool_patch.await_args.args
        self.assertEqual(routed_user_input, "查询上海今天的天气")
        self.assertEqual(routed_state["resolved_user_input"], "查询上海今天的天气")
        self.assertEqual(routed_state["original_user_input"], "上海")
        assessment_call = next(
            tool_call
            for tool_call in routed_state["tool_calls"]
            if tool_call["name"] == "contextual_followup_assessment"
        )
        self.assertEqual(assessment_call["output"]["action"], "resolve_request")

    async def test_clarification_answer_reconstructs_generic_request_before_direct_reply(self):
        class GenericClarificationLLM(FakeLLM):
            def __init__(self):
                self.route_request = ""

            async def ainvoke(self, messages):
                system_prompt = messages[0].content
                if "Classify whether the current user message is a contextual follow-up." in system_prompt:
                    return FakeResponse(
                        json.dumps(
                            {
                                "is_followup": True,
                                "action": "resolve_request",
                                "topic": "Java 排序示例",
                                "resolved_request": "请用 Java 写一个排序示例",
                                "confidence": 0.96,
                                "reason": "The user supplied the requested programming language.",
                            },
                            ensure_ascii=False,
                        )
                    )
                if "You triage a private housekeeper request." in system_prompt:
                    self.route_request = messages[-1].content
                    return FakeResponse(
                        json.dumps(
                            {
                                "route": "direct_reply",
                                "reply": "下面是一个 Java 排序示例。",
                                "goal_type": "coding",
                                "complexity": "simple",
                                "reason": "The clarification completed the coding request.",
                            },
                            ensure_ascii=False,
                        )
                    )
                return await super().ainvoke(messages)

        llm = GenericClarificationLLM()
        state = {
            "user_input": "Java",
            "original_user_input": "Java",
            "memory_context": "[Relevant Memories]\n用户曾经使用过 Python。",
            "recent_history_context": (
                "【对话历史】\n"
                "用户: 写一个排序示例\n"
                "助手: 你希望使用什么编程语言？\n"
                "用户: Java"
            ),
            "tool_calls": [],
            "thinking_blocks": [],
        }

        with patch(
            "app.agents.serana.nodes._try_local_tool_response",
            new=AsyncMock(return_value=None),
        ), patch.object(
            SkillManager,
            "find_relevant_executable_tools",
            return_value=[],
        ):
            result = await try_lightweight_conversation(state, llm)

        self.assertEqual(result["execution_mode"], "direct")
        self.assertIn("Java", result["final_response"])
        self.assertEqual(result["resolved_user_input"], "请用 Java 写一个排序示例")
        if llm.route_request:
            self.assertIn("请用 Java 写一个排序示例", llm.route_request)

    async def test_installed_executable_skill_runs_before_weather_browser_fallback(self):
        script_tool_definition = SkillTool(
            name="get_weather",
            description="查询指定城市的实时天气",
            input_schema=SkillToolInputSchema(
                properties={"city": {"type": "string"}},
                required=["city"],
            ),
        )
        script_skill = SimpleNamespace(
            name="weather_cn_script",
            description="中文天气查询",
            manifest=SimpleNamespace(
                capabilities=["weather", "天气"],
                intents=["天气查询"],
            ),
        )

        async def script_tool(city: str):
            return {"summary": f"{city}：多云，24°C", "source": "script"}

        class ScriptSelectingLLM(FakeLLM):
            async def ainvoke(self, messages):
                if "Choose whether one installed executable Skill" in messages[0].content:
                    return FakeResponse(
                        json.dumps(
                            {
                                "use_tool": True,
                                "tool_name": "weather_cn_script.get_weather",
                                "arguments": {"city": "上海"},
                                "reason": "Installed weather Skill matches.",
                            },
                            ensure_ascii=False,
                        )
                    )
                return await super().ainvoke(messages)

        state = {
            "user_input": "上海天气",
            "original_user_input": "上海天气",
            "tool_calls": [],
            "thinking_blocks": [],
        }
        original_get_tool_function = SkillManager.get_tool_function

        def get_tool_function(manager, skill_name, tool_name):
            if (skill_name, tool_name) == ("weather_cn_script", "get_weather"):
                return script_tool
            return original_get_tool_function(manager, skill_name, tool_name)

        with patch.object(
            SkillManager,
            "find_relevant_executable_tools",
            return_value=[
                {
                    "score": 20,
                    "full_name": "weather_cn_script.get_weather",
                    "skill": script_skill,
                    "tool": script_tool_definition,
                }
            ],
        ), patch.object(
            SkillManager,
            "get_tool_function",
            new=get_tool_function,
        ):
            result = await try_lightweight_conversation(state, ScriptSelectingLLM())

        self.assertEqual(result.get("execution_mode"), "direct")
        self.assertIn("多云", result.get("final_response", ""))
        tool_names = [str(item.get("name")) for item in result.get("tool_calls", [])]
        self.assertIn("weather_cn_script.get_weather", tool_names)
        self.assertNotIn("browser.open_page", tool_names)

    def test_rejects_instruction_reply_that_looks_like_script_path_when_user_did_not_ask_for_commands(self):
        self.assertTrue(
            _should_reject_non_code_command_reply(
                "上海天气如何",
                "./skills/weather-zh/weather-cn.sh 上海",
            )
        )

    def test_sanitize_non_code_command_reply_removes_standalone_script_line(self):
        reply = "🌙 小铭，我帮你查一下上海今天的天气。\n~/.openclaw/workspace/skills/weather-zh/weather-cn.sh 上海\n🌙 上海天气如下：\n多云，26/19℃。"
        cleaned = _sanitize_non_code_command_reply("今天天气如何", reply)
        self.assertNotIn("weather-cn.sh", cleaned)
        self.assertIn("上海天气如下", cleaned)
        self.assertEqual(
            _sanitize_non_code_command_reply(
                "上海天气如何",
                "~/.openclaw/workspace/skills/weather-zh/weather-cn.sh 上海",
            ),
            "",
        )
        self.assertFalse(
            _should_reject_non_code_command_reply(
                "把天气脚本命令写给我",
                "./skills/weather-zh/weather-cn.sh 上海",
            )
        )


class FakeLLM:
    async def ainvoke(self, messages):
        prompt = messages[-1].content
        system_prompt = messages[0].content
        if "You triage a private housekeeper request." in system_prompt:
            lower_prompt = prompt.lower()
            if "记住" in prompt or "喜欢什么饮料" in prompt or "remember" in lower_prompt or "previously said" in lower_prompt:
                if "记住" in prompt or "remember" in lower_prompt:
                    return FakeResponse(
                        json.dumps(
                            {
                                "route": "direct_tool",
                                "tool_name": "memory_manager.memory_save",
                                "arguments": {
                                    "key": "preferred_drink",
                                    "value": "黑咖啡",
                                    "category": "preference",
                                },
                                "reason": "Explicit memory save",
                            },
                            ensure_ascii=False,
                        )
                    )
                return FakeResponse(
                    json.dumps(
                        {
                            "route": "direct_tool",
                            "tool_name": "memory_manager.memory_search",
                            "arguments": {"query": "喜欢什么饮料", "limit": 5},
                            "reason": "Memory lookup",
                        },
                        ensure_ascii=False,
                    )
                )
            if "澶╂皵" in prompt or "weather" in lower_prompt:
                location = "鍖椾含" if "鍖椾含" in prompt or "beijing" in lower_prompt else "涓婃捣"
                tool_name = "weather.get_forecast" if any(keyword in prompt for keyword in ["鏄庡ぉ", "鍚庡ぉ", "棰勬姤"]) else "weather.get_current_weather"
                arguments = {"location": location, "units": "metric"}
                if tool_name == "weather.get_forecast":
                    arguments["days"] = 1
                return FakeResponse(
                    json.dumps(
                        {
                            "route": "direct_tool",
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "reason": "Weather request",
                        },
                        ensure_ascii=False,
                    )
                )
            if any(keyword in prompt for keyword in ["鍑犵偣", "鏃堕棿", "鏄熸湡鍑?", "鍛ㄥ嚑"]):
                tool_name = "time_manager.get_day_info" if any(keyword in prompt for keyword in ["鏄熸湡鍑?", "鍛ㄥ嚑", "鍑犲彿"]) else "time_manager.get_current_time"
                arguments = {} if tool_name == "time_manager.get_day_info" else {"timezone": "Asia/Shanghai", "format": "full"}
                return FakeResponse(
                    json.dumps(
                        {
                            "route": "direct_tool",
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "reason": "Time request",
                        },
                        ensure_ascii=False,
                    )
                )
            math_match = __import__("re").search(r"(-?\d+(?:\.\d+)?)\s*([+\-*/x脳])\s*(-?\d+(?:\.\d+)?)", prompt)
            if math_match:
                symbol = math_match.group(2)
                tool_name = {
                    "+": "calculator.add",
                    "-": "calculator.subtract",
                    "*": "calculator.multiply",
                    "x": "calculator.multiply",
                    "脳": "calculator.multiply",
                    "/": "calculator.divide",
                }[symbol]
                return FakeResponse(
                    json.dumps(
                        {
                            "route": "direct_tool",
                            "tool_name": tool_name,
                            "arguments": {"a": float(math_match.group(1)), "b": float(math_match.group(3))},
                            "reason": "Arithmetic request",
                        },
                        ensure_ascii=False,
                    )
                )
            if "research" in lower_prompt or "build" in lower_prompt:
                return FakeResponse(
                    '{"route":"delegated","goal_type":"research","summary":"Build a weekly study plan","complexity":"high","reason":"Needs planning"}'
                )
            return FakeResponse(
                '{"route":"direct_reply","reply":"Assistant reply for: Quick question","goal_type":"question","complexity":"simple","reason":"Single-turn advice"}'
            )
        if "You route direct requests to local tools" in system_prompt:
            lower_prompt = prompt.lower()
            if "记住" in prompt or "喜欢什么饮料" in prompt or "remember" in lower_prompt or "previously said" in lower_prompt:
                if "记住" in prompt or "remember" in lower_prompt:
                    return FakeResponse(
                        json.dumps(
                            {
                                "should_use_tool": True,
                                "tool_name": "memory_manager.memory_save",
                                "arguments": {
                                    "key": "preferred_drink",
                                    "value": "黑咖啡",
                                    "category": "preference",
                                },
                                "reason": "Explicit memory save",
                            },
                            ensure_ascii=False,
                        )
                    )
                return FakeResponse(
                    json.dumps(
                        {
                            "should_use_tool": True,
                            "tool_name": "memory_manager.memory_search",
                            "arguments": {"query": "喜欢什么饮料", "limit": 5},
                            "reason": "Memory lookup",
                        },
                        ensure_ascii=False,
                    )
                )
            if "天气" in prompt or "weather" in lower_prompt:
                location = "北京" if "北京" in prompt or "beijing" in lower_prompt else "上海"
                tool_name = "weather.get_forecast" if any(keyword in prompt for keyword in ["明天", "后天", "预报"]) else "weather.get_current_weather"
                arguments = {"location": location, "units": "metric"}
                if tool_name == "weather.get_forecast":
                    arguments["days"] = 1
                return FakeResponse(
                    json.dumps(
                        {
                            "should_use_tool": True,
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "reason": "Weather request",
                        },
                        ensure_ascii=False,
                    )
                )
            if any(keyword in prompt for keyword in ["几点", "时间", "星期几", "周几"]):
                tool_name = "time_manager.get_day_info" if any(keyword in prompt for keyword in ["星期几", "周几", "几号"]) else "time_manager.get_current_time"
                arguments = {} if tool_name == "time_manager.get_day_info" else {"timezone": "Asia/Shanghai", "format": "full"}
                return FakeResponse(
                    json.dumps(
                        {
                            "should_use_tool": True,
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "reason": "Time request",
                        },
                        ensure_ascii=False,
                    )
                )
            math_match = __import__("re").search(r"(-?\d+(?:\.\d+)?)\s*([+\-*/x×])\s*(-?\d+(?:\.\d+)?)", prompt)
            if math_match:
                symbol = math_match.group(2)
                tool_name = {
                    "+": "calculator.add",
                    "-": "calculator.subtract",
                    "*": "calculator.multiply",
                    "x": "calculator.multiply",
                    "×": "calculator.multiply",
                    "/": "calculator.divide",
                }[symbol]
                return FakeResponse(
                    json.dumps(
                        {
                            "should_use_tool": True,
                            "tool_name": tool_name,
                            "arguments": {"a": float(math_match.group(1)), "b": float(math_match.group(3))},
                            "reason": "Arithmetic request",
                        },
                        ensure_ascii=False,
                    )
                )
            return FakeResponse('{"should_use_tool": false, "tool_name": "", "arguments": {}, "reason": "No tool"}')
        if "goal_type" in system_prompt:
            lower_prompt = prompt.lower()
            if "quick question" in lower_prompt or "what should i study tonight" in lower_prompt:
                return FakeResponse(
                    '{"goal_type":"question","summary":"Answer the study question directly","complexity":"simple"}'
                )
            if "research" in lower_prompt or "build" in lower_prompt:
                return FakeResponse(
                    '{"goal_type":"research","summary":"Build a weekly study plan","complexity":"high"}'
                )
            return FakeResponse('{"goal_type":"task","summary":"Build a weekly study plan","complexity":"medium"}')
        if '"subtasks"' in system_prompt:
            return FakeResponse(
                '{"subtasks":['
                '{"description":"Define study goals","order":1},'
                '{"description":"Allocate study blocks","order":2},'
                '{"description":"Review progress weekly","order":3}'
                ']}'
            )
        if "Summarize the plan" in messages[0].content:
            return FakeResponse("Here is a clear three-step weekly study plan.")
        return FakeResponse(f"Assistant reply for: {prompt[:40]}")


class CleanFakeLLM:
    async def ainvoke(self, messages):
        prompt = messages[-1].content
        system_prompt = messages[0].content
        lower_prompt = prompt.lower()

        if "You triage a private housekeeper request." in system_prompt:
            if any(keyword in prompt for keyword in ["天气", "北京", "上海", "什么天气", "预报"]) or "weather" in lower_prompt:
                location = "北京" if ("北京" in prompt or "beijing" in lower_prompt) else "上海"
                tool_name = (
                    "weather.get_forecast"
                    if any(keyword in prompt for keyword in ["明天", "后天", "预报"]) or "forecast" in lower_prompt
                    else "weather.get_current_weather"
                )
                arguments = {"location": location, "units": "metric"}
                if tool_name == "weather.get_forecast":
                    arguments["days"] = 1
                return FakeResponse(
                    json.dumps(
                        {
                            "route": "direct_tool",
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "reason": "Weather request",
                        },
                        ensure_ascii=False,
                    )
                )
            if any(keyword in prompt for keyword in ["几点", "时间", "星期几", "周几", "几号"]) or "time" in lower_prompt:
                tool_name = (
                    "time_manager.get_day_info"
                    if any(keyword in prompt for keyword in ["星期几", "周几", "几号"])
                    else "time_manager.get_current_time"
                )
                arguments = {} if tool_name == "time_manager.get_day_info" else {"timezone": "Asia/Shanghai", "format": "full"}
                return FakeResponse(
                    json.dumps(
                        {
                            "route": "direct_tool",
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "reason": "Time request",
                        },
                        ensure_ascii=False,
                    )
                )
            math_match = __import__("re").search(r"(-?\d+(?:\.\d+)?)\s*([+\-*/x×])\s*(-?\d+(?:\.\d+)?)", prompt)
            if math_match:
                symbol = math_match.group(2)
                tool_name = {
                    "+": "calculator.add",
                    "-": "calculator.subtract",
                    "*": "calculator.multiply",
                    "x": "calculator.multiply",
                    "×": "calculator.multiply",
                    "/": "calculator.divide",
                }[symbol]
                return FakeResponse(
                    json.dumps(
                        {
                            "route": "direct_tool",
                            "tool_name": tool_name,
                            "arguments": {"a": float(math_match.group(1)), "b": float(math_match.group(3))},
                            "reason": "Arithmetic request",
                        },
                        ensure_ascii=False,
                    )
                )
            if "research" in lower_prompt or "build" in lower_prompt:
                return FakeResponse(
                    '{"route":"delegated","goal_type":"research","summary":"Build a weekly study plan","complexity":"high","reason":"Needs planning"}'
                )
            return FakeResponse(
                '{"route":"direct_reply","reply":"Assistant reply for: Quick question","goal_type":"question","complexity":"simple","reason":"Single-turn advice"}'
            )

        if "You route direct requests to local tools" in system_prompt:
            if any(keyword in prompt for keyword in ["天气", "北京", "上海", "什么天气", "预报"]) or "weather" in lower_prompt:
                location = "北京" if ("北京" in prompt or "beijing" in lower_prompt) else "上海"
                tool_name = (
                    "weather.get_forecast"
                    if any(keyword in prompt for keyword in ["明天", "后天", "预报"]) or "forecast" in lower_prompt
                    else "weather.get_current_weather"
                )
                arguments = {"location": location, "units": "metric"}
                if tool_name == "weather.get_forecast":
                    arguments["days"] = 1
                return FakeResponse(
                    json.dumps(
                        {
                            "should_use_tool": True,
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "reason": "Weather request",
                        },
                        ensure_ascii=False,
                    )
                )
            if any(keyword in prompt for keyword in ["几点", "时间", "星期几", "周几", "几号"]) or "time" in lower_prompt:
                tool_name = (
                    "time_manager.get_day_info"
                    if any(keyword in prompt for keyword in ["星期几", "周几", "几号"])
                    else "time_manager.get_current_time"
                )
                arguments = {} if tool_name == "time_manager.get_day_info" else {"timezone": "Asia/Shanghai", "format": "full"}
                return FakeResponse(
                    json.dumps(
                        {
                            "should_use_tool": True,
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "reason": "Time request",
                        },
                        ensure_ascii=False,
                    )
                )
            math_match = __import__("re").search(r"(-?\d+(?:\.\d+)?)\s*([+\-*/x×])\s*(-?\d+(?:\.\d+)?)", prompt)
            if math_match:
                symbol = math_match.group(2)
                tool_name = {
                    "+": "calculator.add",
                    "-": "calculator.subtract",
                    "*": "calculator.multiply",
                    "x": "calculator.multiply",
                    "×": "calculator.multiply",
                    "/": "calculator.divide",
                }[symbol]
                return FakeResponse(
                    json.dumps(
                        {
                            "should_use_tool": True,
                            "tool_name": tool_name,
                            "arguments": {"a": float(math_match.group(1)), "b": float(math_match.group(3))},
                            "reason": "Arithmetic request",
                        },
                        ensure_ascii=False,
                    )
                )
            return FakeResponse('{"should_use_tool": false, "tool_name": "", "arguments": {}, "reason": "No tool"}')

        if "goal_type" in system_prompt:
            if "quick question" in lower_prompt or "what should i study tonight" in lower_prompt:
                return FakeResponse(
                    '{"goal_type":"question","summary":"Answer the study question directly","complexity":"simple"}'
                )
            if "research" in lower_prompt or "build" in lower_prompt:
                return FakeResponse(
                    '{"goal_type":"research","summary":"Build a weekly study plan","complexity":"high"}'
                )
            return FakeResponse('{"goal_type":"task","summary":"Build a weekly study plan","complexity":"medium"}')

        if '"subtasks"' in system_prompt:
            return FakeResponse(
                '{"subtasks":['
                '{"description":"Define study goals","order":1},'
                '{"description":"Allocate study blocks","order":2},'
                '{"description":"Review progress weekly","order":3}'
                ']}'
            )

        if "Summarize the plan" in system_prompt:
            return FakeResponse("Here is a clear three-step weekly study plan.")

        return FakeResponse(f"Assistant reply for: {prompt[:40]}")


class FakeGateway:
    def get_llm(self, user_config=None, use_backend_default=False):
        return CleanFakeLLM()


class MemoryAwareGateway:
    def get_llm(self, user_config=None, use_backend_default=False):
        return FakeLLM()


class FallbackOnlyLLM(CleanFakeLLM):
    async def ainvoke(self, messages):
        system_prompt = messages[0].content
        if "You triage a private housekeeper request." in system_prompt:
            raise ValueError("Force regex fallback for natural working-memory phrases")
        return await super().ainvoke(messages)


class FallbackOnlyGateway:
    def get_llm(self, user_config=None, use_backend_default=False):
        return FallbackOnlyLLM()


class InstructionAwareLLM(CleanFakeLLM):
    async def ainvoke(self, messages):
        prompt = messages[-1].content
        system_prompt = messages[0].content
        if "You triage a private housekeeper request." in system_prompt and "Installed instruction skills:" in prompt:
            return FakeResponse(
                '{"route":"direct_reply","reply":"Applied imported skill guidance.","goal_type":"question","complexity":"simple","reason":"Instruction-guided direct reply"}'
            )
        if "goal_type" in system_prompt:
            return await super().ainvoke(messages)
        if '"subtasks"' in system_prompt:
            return await super().ainvoke(messages)
        if (
            ("Handle this request directly" in system_prompt or "Summarize the plan" in system_prompt)
            and "Installed instruction skills:" in prompt
        ):
            return FakeResponse("Applied imported skill guidance.")
        return await super().ainvoke(messages)


class InstructionAwareGateway:
    def get_llm(self, user_config=None, use_backend_default=False):
        return InstructionAwareLLM()


class CountingLLM(CleanFakeLLM):
    def __init__(self):
        self.call_count = 0

    async def ainvoke(self, messages):
        self.call_count += 1
        return await super().ainvoke(messages)


class UnsupportedToolRouteLLM(CleanFakeLLM):
    async def ainvoke(self, messages):
        system_prompt = messages[0].content
        if "You triage a private housekeeper request." in system_prompt:
            return FakeResponse(
                json.dumps(
                    {
                        "route": "direct_tool",
                        "tool_name": "calendar.create_event",
                        "arguments": {"title": "Test"},
                        "reason": "Unsupported external tool",
                    },
                    ensure_ascii=False,
                )
            )
        return await super().ainvoke(messages)


class BrowserRouteLLM(CleanFakeLLM):
    def __init__(self):
        self.call_count = 0

    async def ainvoke(self, messages):
        self.call_count += 1
        system_prompt = messages[0].content
        if "You triage a private housekeeper request." in system_prompt:
            return FakeResponse(
                json.dumps(
                    {
                        "route": "direct_tool",
                        "tool_name": "browser.search_web",
                        "arguments": {"query": "Serana browser test", "max_results": 3},
                        "reason": "Current web search",
                    },
                    ensure_ascii=False,
                )
            )
        if "summarizing browser tool output" in system_prompt:
            return FakeResponse("我查到了浏览器结果：Serana browser test 的第一条结果可用。")
        return await super().ainvoke(messages)


class BrowserCaptureRouteLLM(CleanFakeLLM):
    async def ainvoke(self, messages):
        system_prompt = messages[0].content
        if "You triage a private housekeeper request." in system_prompt:
            return FakeResponse(
                json.dumps(
                    {
                        "route": "direct_tool",
                        "tool_name": "browser.capture_page",
                        "arguments": {"full_page": True},
                        "reason": "Browser screenshot request",
                    },
                    ensure_ascii=False,
                )
            )
        if "summarizing browser tool output" in system_prompt:
            return FakeResponse("当前网页截图已经保存好了。")
        return await super().ainvoke(messages)


class BrowserLookRouteLLM(CleanFakeLLM):
    def __init__(self):
        self.summary_content = None

    async def ainvoke(self, messages):
        system_prompt = messages[0].content
        if "You triage a private housekeeper request." in system_prompt:
            return FakeResponse(
                json.dumps(
                    {
                        "route": "direct_tool",
                        "tool_name": "browser.look_page",
                        "arguments": {"full_page": False},
                        "reason": "Browser visual inspection",
                    },
                    ensure_ascii=False,
                )
            )
        if "summarizing browser tool output" in system_prompt:
            self.summary_content = messages[-1].content
            return FakeResponse("当前网页视觉快照看起来正常。")
        return await super().ainvoke(messages)


class BrowserPreviewRouteLLM(CleanFakeLLM):
    async def ainvoke(self, messages):
        system_prompt = messages[0].content
        if "You triage a private housekeeper request." in system_prompt:
            return FakeResponse(
                json.dumps(
                    {
                        "route": "direct_tool",
                        "tool_name": "browser.create_html_preview",
                        "arguments": {
                            "title": "Bubble Sort Demo",
                            "html": "<section><h1>Bubble Sort Demo</h1><p>Preparing an interactive sorting demo.</p></section>",
                        },
                        "reason": "Interactive local demo preview",
                    },
                    ensure_ascii=False,
                )
            )
        if "You generate a single self-contained HTML document for Serana's in-app preview surface." in system_prompt:
            return FakeResponse(
                """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bubble Sort Demo</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 0; padding: 24px; background: #f7f7f4; color: #1f2b21; }
    .panel { max-width: 720px; margin: 0 auto; }
    #bars { display: flex; align-items: flex-end; gap: 8px; height: 220px; margin: 20px 0; }
    .bar { flex: 1; background: #48a878; border-radius: 10px 10px 4px 4px; color: white; text-align: center; font-size: 12px; padding-top: 6px; box-sizing: border-box; transition: height .2s ease, opacity .2s ease; }
    button { border: 0; border-radius: 999px; padding: 10px 14px; background: #2f7d57; color: white; font-weight: 700; }
    p { line-height: 1.6; }
  </style>
</head>
<body>
  <main class="panel">
    <h1>冒泡排序演示</h1>
    <p id="status">点击按钮后，数字会按从小到大重新排列。</p>
    <div id="bars"></div>
    <button id="start" type="button">开始排序</button>
  </main>
  <script>
    const values = [7, 3, 9, 4, 1, 8];
    const bars = document.getElementById("bars");
    const status = document.getElementById("status");
    function render(activeIndex = -1) {
      bars.innerHTML = values.map((value, index) => `<div class="bar" style="height:${value * 18}px;opacity:${index === activeIndex ? 0.72 : 1}">${value}</div>`).join("");
    }
    document.getElementById("start").addEventListener("click", () => {
      values.sort((a, b) => a - b);
      status.textContent = "排序完成，数字已经按从小到大排列。";
      render(0);
    });
    render();
  </script>
</body>
</html>"""
            )
        if "summarizing browser tool output" in system_prompt:
            return FakeResponse("我已经生成了一个可打开的冒泡排序演示页面。")
        return await super().ainvoke(messages)


class BrowserActRouteLLM(CleanFakeLLM):
    async def ainvoke(self, messages):
        system_prompt = messages[0].content
        if "You triage a private housekeeper request." in system_prompt:
            return FakeResponse(
                json.dumps(
                    {
                        "route": "direct_tool",
                        "tool_name": "browser.act_page",
                        "arguments": {
                            "action": "click",
                            "target": "下载按钮",
                        },
                        "reason": "Browser action request",
                    },
                    ensure_ascii=False,
                )
            )
        if "summarizing browser tool output" in system_prompt:
            return FakeResponse("我已经按你的确认执行了浏览器操作。")
        return await super().ainvoke(messages)


class BrowserGateway:
    def __init__(self):
        self.llm = BrowserRouteLLM()

    def get_llm(self, user_config=None, use_backend_default=False):
        return self.llm


class BrowserActGateway:
    def get_llm(self, user_config=None, use_backend_default=False):
        return BrowserActRouteLLM()


class FakeMarketplaceClient:
    def search_skills(self, query: str, manager: SkillManager, limit: int = 20):
        return MarketplaceSearchResponse(
            results=[
                MarketplaceSkillSummary(
                    slug="weather",
                    displayName="Weather",
                    summary="Get current weather and forecasts.",
                    version="1.0.0",
                    ownerHandle="steipete",
                    canonical_url="https://skillhub.cn/skills/weather",
                    download_url="https://api.skillhub.cn/api/v1/download?slug=weather",
                    installed=manager.get_skill("weather") is not None,
                    local_skill_name="weather" if manager.get_skill("weather") is not None else None,
                )
            ]
        )

    def list_skills(self, manager: SkillManager, limit: int = 20, cursor=None, sort: str = "updated"):
        return self.search_skills(query="weather", manager=manager, limit=limit)

    def get_skill_detail(self, slug: str, manager: SkillManager, version=None, tag=None, include_preview: bool = True):
        return {
            "slug": slug,
            "display_name": "Weather",
            "summary": "Get current weather and forecasts.",
            "owner_handle": "skillhub",
            "owner_display_name": "SkillHub",
            "latest_version": "1.0.0",
            "canonical_url": "https://skillhub.cn/skills/weather",
            "download_url": "https://api.skillhub.cn/api/v1/download?slug=weather",
            "skill_md_preview": "# Weather",
            "installed": manager.get_skill("weather") is not None,
            "local_skill_name": "weather" if manager.get_skill("weather") is not None else None,
        }

    def install_skill(self, slug: str, manager: SkillManager, version=None, tag=None):
        temp_dir = Path(tempfile.mkdtemp())
        try:
            skill_dir = temp_dir / "weather"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "skill.json").write_text(
                json.dumps(
                    {
                        "name": "weather",
                        "version": version or "1.0.0",
                        "description": "Get current weather and forecasts.",
                        "author": "SkillHub",
                        "format": "sebastian_package",
                        "runtime": "instruction",
                        "instruction_file": "SKILL.md",
                        "entrypoint": None,
                        "registry_slug": slug,
                        "source_url": "https://skillhub.cn/skills/weather",
                        "agent_type": "all",
                        "max_instances": 1,
                        "tools": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (skill_dir / "SKILL.md").write_text("# Weather\nUse weather data when asked.", encoding="utf-8")
            return manager.install_skill_from_directory(skill_dir)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def create_test_skill_archive(skill_name: str, version: str = "0.1.0") -> tuple[Path, bytes]:
    temp_dir = Path(tempfile.mkdtemp())
    skill_dir = temp_dir / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "skill.json").write_text(
        json.dumps(
            {
                "name": skill_name,
                "version": version,
                "description": f"Test skill {skill_name}",
                "author": "Test Suite",
                "format": "sebastian_package",
                "runtime": "instruction",
                "instruction_file": "SKILL.md",
                "entrypoint": None,
                "agent_type": "all",
                "max_instances": 1,
                "tools": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        f"# {skill_name}\n\nThis is a temporary test skill.\n",
        encoding="utf-8",
    )

    archive_path = temp_dir / f"{skill_name}.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for file_path in skill_dir.rglob("*"):
            archive.write(file_path, file_path.relative_to(temp_dir))

    return temp_dir, archive_path.read_bytes()


class ApiFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        async with AsyncSessionLocal() as session:
            user = await create_default_user(session)
            self.default_user_id = str(user.id)
        self.transport = httpx.ASGITransport(app=app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://test")

    async def asyncTearDown(self):
        await get_approval_manager().shutdown()
        await self.client.aclose()
        app.dependency_overrides.clear()

    @patch("app.api.chat.get_llm_gateway", return_value=FakeGateway())
    async def test_chat_message_and_history_flow(self, _gateway):
        response = await self.client.post(
            "/api/v1/chat/message",
            json={"content": "Quick question: what should I study tonight?", "stream": False},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("session_id", payload)
        self.assertIn("assistant_message", payload)
        self.assertTrue(payload["assistant_message"]["content"])
        self.assertGreaterEqual(len(payload["thinking_blocks"]), 1)
        self.assertGreaterEqual(len(payload["assistant_message"]["thinking_blocks"]), 1)
        self.assertEqual(payload["execution_mode"], "direct")
        self.assertEqual(payload["delegation_plan"]["parallel_slots"], 0)
        self.assertGreaterEqual(len(payload["assistant_message"]["tool_calls"]), 3)
        self.assertEqual(payload["assistant_message"]["tool_calls"][0]["name"], "memory_injector")
        tool_names = [tool_call["name"] for tool_call in payload["assistant_message"]["tool_calls"]]
        self.assertIn("serana_loop_stage", tool_names)
        self.assertIn("conversation_route", tool_names)
        self.assertIn("serana_direct_reply", tool_names)
        self.assertNotIn("forge_execute", tool_names)

        history = await self.client.get(f"/api/v1/chat/sessions/{payload['session_id']}/messages")
        self.assertEqual(history.status_code, 200)
        messages = history.json()
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertIsNone(messages[0]["thinking_blocks"])
        self.assertIsNone(messages[0]["tool_calls"])
        self.assertGreaterEqual(len(messages[1]["thinking_blocks"]), 1)
        self.assertGreaterEqual(len(messages[1]["tool_calls"]), 3)
        self.assertEqual(messages[1]["tool_calls"][0]["name"], "memory_injector")

        audit = await self.client.get(f"/api/v1/chat/sessions/{payload['session_id']}/audit")
        self.assertEqual(audit.status_code, 200)
        audit_records = audit.json()
        self.assertGreaterEqual(len(audit_records), 2)
        self.assertEqual(audit_records[0]["entity_type"], "chat_session")
        self.assertEqual(audit_records[0]["event_type"], "memory_injector")

        timeline_response = await self.client.get(
            "/api/v1/audit/timeline",
            params={"entity_type": "chat_session", "entity_id": payload["session_id"]},
        )
        self.assertEqual(timeline_response.status_code, 200)
        timeline = timeline_response.json()
        self.assertEqual(
            timeline["insights"]["loop_stages"],
            ["lightweight_complete", "lightweight_start"],
        )

    @patch("app.api.chat.get_llm_gateway", return_value=FakeGateway())
    async def test_chat_stream_uses_lightweight_route_for_simple_requests(self, _gateway):
        async with self.client.stream(
            "POST",
            "/api/v1/chat/message",
            json={"content": "Quick question: what should I study tonight?", "stream": True},
        ) as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"], "text/event-stream; charset=utf-8")
            events = []
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                events.append(json.loads(line[6:]))

        self.assertGreaterEqual(len(events), 2)
        event_types = [event["type"] for event in events]
        self.assertIn("thinking", event_types)
        content_events = [event for event in events if event["type"] == "content"]
        self.assertGreater(len(content_events), 0)

        done_event = events[-1]
        self.assertEqual(done_event["type"], "done")
        self.assertEqual(done_event["execution_mode"], "direct")
        self.assertEqual(done_event["goal_type"], "question")
        self.assertEqual(done_event["complexity"], "simple")
        self.assertEqual(done_event["delegation_plan"]["parallel_slots"], 0)
        tool_names = [tool_call["name"] for tool_call in done_event["tool_calls"]]
        self.assertIn("serana_loop_stage", tool_names)
        self.assertIn("conversation_route", tool_names)
        self.assertIn("serana_direct_reply", tool_names)

    async def test_chat_stream_supports_interactive_approval_for_browser_actions(self):
        async def fake_browser_action(**kwargs):
            return {
                "summary": f"Executed browser action: {kwargs['action']} -> {kwargs['target']}",
                "status": "completed",
            }

        agent = SeranaAgent(BrowserActRouteLLM())

        with patch.object(SkillManager, "get_tool_function", return_value=fake_browser_action):
            events = []
            async for event in agent.execute_stream("点击当前页面的下载按钮"):
                events.append(event)
                if event["type"] == "approval_requested":
                    request_id = event["content"]["request_id"]
                    self.assertEqual(event["content"]["reason"], "浏览器交互可能改变页面状态或提交信息，需要用户确认。")
                    self.assertIn("once", event["content"]["approval_options"])
                    self.assertIn("always", event["content"]["approval_options"])
                    resolved = await get_approval_manager().resolve(request_id, approved=True)
                    self.assertIsNotNone(resolved)

        event_types = [event["type"] for event in events]
        self.assertIn("approval_requested", event_types)
        self.assertIn("approval_resolved", event_types)
        self.assertEqual(events[-1]["type"], "done")
        tool_names = [tool_call["name"] for tool_call in events[-1]["tool_calls"]]
        self.assertIn("serana_approval_requested", tool_names)
        self.assertIn("serana_approval_resolved", tool_names)
        self.assertIn("serana_policy_gate", tool_names)
        self.assertIn("browser.act_page", tool_names)

    async def test_chat_stream_can_reuse_persistent_approval_for_browser_actions(self):
        async def fake_browser_action(**kwargs):
            return {
                "summary": f"Executed browser action: {kwargs['action']} -> {kwargs['target']}",
                "status": "completed",
            }

        manager = get_approval_manager()

        with patch.object(SkillManager, "get_tool_function", return_value=fake_browser_action):
            first_events = []
            first_agent = SeranaAgent(BrowserActRouteLLM())
            async for event in first_agent.execute_stream("点击当前页面的下载按钮"):
                first_events.append(event)
                if event["type"] == "approval_requested":
                    request_id = event["content"]["request_id"]
                    approval_request = await manager.get_request(request_id)
                    resolved = await manager.resolve(request_id, approved=True, approval_scope="always")
                    self.assertIsNotNone(approval_request)
                    self.assertIsNotNone(resolved)
                    await manager.add_grant(approval_request, resolved)

            second_events = []
            second_agent = SeranaAgent(BrowserActRouteLLM())
            async for event in second_agent.execute_stream("再次点击当前页面的下载按钮"):
                second_events.append(event)

        self.assertIn("approval_requested", [event["type"] for event in first_events])
        self.assertNotIn("approval_requested", [event["type"] for event in second_events])
        second_tool_calls = second_events[-1]["tool_calls"]
        policy_call = next(
            tool_call for tool_call in second_tool_calls
            if tool_call["name"] == "serana_policy_gate"
        )
        self.assertEqual(policy_call["output"]["decision"], "allowed_by_persistent_approval")

    async def test_approval_endpoint_resolves_pending_request(self):
        from app.core import ApprovalRequest

        manager = get_approval_manager()
        request = ApprovalRequest(
            request_id="approval-test-001",
            session_id="session-001",
            tool_name="browser.act_page",
            operation="browser_act",
            risk_level="medium",
            title="确认浏览器操作",
            summary="Serana 想执行一个浏览器点击操作。",
            approval_options=["once", "always", "deny"],
            details={"action": "click", "target": "下载按钮"},
            status="pending",
            created_at="2026-05-25T00:00:00+00:00",
            expires_at="2026-05-25T00:05:00+00:00",
        )
        await manager.register(request)

        response = await self.client.post(
            "/api/v1/approvals/approval-test-001",
            json={
                "request_id": "approval-test-001",
                "approved": True,
                "approval_scope": "always",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["approved"])
        self.assertEqual(response.json()["approval_scope"], "always")
        self.assertTrue(
            await manager.is_granted(
                tool_name="browser.act_page",
                operation="browser_act",
                risk_level="medium",
                details={"action": "click", "target": "下载按钮"},
            )
        )

    @patch("app.api.chat.get_llm_gateway", return_value=FakeGateway())
    async def test_chat_session_delete_and_clear_flow(self, _gateway):
        first = await self.client.post(
            "/api/v1/chat/message",
            json={"content": "第一条会话", "stream": False},
        )
        second = await self.client.post(
            "/api/v1/chat/message",
            json={"content": "第二条会话", "stream": False},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

        first_session_id = first.json()["session_id"]
        second_session_id = second.json()["session_id"]

        delete_response = await self.client.delete(f"/api/v1/chat/sessions/{first_session_id}")
        self.assertEqual(delete_response.status_code, 200)
        self.assertTrue(delete_response.json()["success"])

        deleted_history = await self.client.get(f"/api/v1/chat/sessions/{first_session_id}/messages")
        self.assertEqual(deleted_history.status_code, 404)

        sessions_after_delete = await self.client.get("/api/v1/chat/sessions")
        self.assertEqual(sessions_after_delete.status_code, 200)
        remaining_ids = [session["id"] for session in sessions_after_delete.json()]
        self.assertNotIn(first_session_id, remaining_ids)
        self.assertIn(second_session_id, remaining_ids)

        clear_response = await self.client.delete("/api/v1/chat/sessions")
        self.assertEqual(clear_response.status_code, 200)
        self.assertTrue(clear_response.json()["success"])
        self.assertGreaterEqual(clear_response.json()["deleted_count"], 1)

        sessions_after_clear = await self.client.get("/api/v1/chat/sessions")
        self.assertEqual(sessions_after_clear.status_code, 200)
        self.assertEqual(sessions_after_clear.json(), [])

    @patch("app.api.chat.get_llm_gateway", return_value=FakeGateway())
    async def test_chat_uses_time_manager_for_direct_time_request(self, _gateway):
        response = await self.client.post(
            "/api/v1/chat/message",
            json={"content": "现在几点了？", "stream": False},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["execution_mode"], "direct")
        tool_names = [tool_call["name"] for tool_call in payload["assistant_message"]["tool_calls"]]
        self.assertTrue(
            "time_manager.get_current_time" in tool_names
            or "serana_direct_reply" in tool_names
        )
        self.assertNotIn("serana_summarize", tool_names)
        self.assertTrue(payload["assistant_message"]["content"].strip())

    @patch("app.api.chat.get_llm_gateway", return_value=FakeGateway())
    async def test_chat_uses_calculator_for_direct_math_request(self, _gateway):
        response = await self.client.post(
            "/api/v1/chat/message",
            json={"content": "37*18 等于几？", "stream": False},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["execution_mode"], "direct")
        tool_calls = payload["assistant_message"]["tool_calls"]
        tool_names = [tool_call["name"] for tool_call in tool_calls]
        if "calculator.multiply" in tool_names:
            calculator_call = next(tool_call for tool_call in tool_calls if tool_call["name"] == "calculator.multiply")
            standard_result = calculator_call["output"]["tool_result"]
            self.assertEqual(standard_result["schema_version"], "serana.tool_result.v1")
            self.assertEqual(standard_result["result_type"], "tool")
            self.assertEqual(standard_result["tool_name"], "calculator.multiply")
            self.assertEqual(standard_result["status"], "completed")
            self.assertIn("37 * 18 = 666", standard_result["user_summary"])
        else:
            self.assertIn("serana_direct_reply", tool_names)
        self.assertIn("666", payload["assistant_message"]["content"])

        timeline_response = await self.client.get(
            "/api/v1/audit/timeline",
            params={"entity_type": "chat_session", "entity_id": payload["session_id"]},
        )
        self.assertEqual(timeline_response.status_code, 200)
        timeline_payload = timeline_response.json()
        self.assertIn("calculator.multiply", timeline_payload["insights"]["tool_result_names"])
        self.assertIn("completed", timeline_payload["insights"]["tool_result_statuses"])
        self.assertIn("serana.tool_result.v1", timeline_payload["insights"]["tool_result_schema_versions"])
        calculator_record = next(
            record for record in timeline_response.json()["records"]
            if record["event_type"] == "calculator.multiply"
        )
        self.assertEqual(calculator_record["payload"]["tool_result"]["tool_name"], "calculator.multiply")
        self.assertEqual(calculator_record["payload"]["tool_result"]["schema_version"], "serana.tool_result.v1")

    @patch("app.api.chat.get_llm_gateway", return_value=FakeGateway())
    async def test_chat_uses_weather_skill_for_direct_weather_request(self, _gateway):
        original_get_tool_function = SkillManager.get_tool_function

        async def fake_weather_tool(location: str, units: str = "metric"):
            self.assertEqual(location, "上海")
            return {
                "source": "wttr.in",
                "location": "上海",
                "condition": "多云",
                "temperature": "26",
                "feels_like": "28",
                "humidity": "78",
                "wind_speed": "12",
                "units": units,
                "summary": "上海：多云，当前 26度，体感 28度，湿度 78%，风速 12 公里/小时",
            }

        def patched_get_tool_function(self, skill_name: str, tool_name: str):
            if skill_name == "weather" and tool_name == "get_current_weather":
                return fake_weather_tool
            return original_get_tool_function(self, skill_name, tool_name)

        with patch.object(SkillManager, "get_tool_function", new=patched_get_tool_function):
            response = await self.client.post(
                "/api/v1/chat/message",
                json={"content": "今天上海天气怎么样？", "stream": False},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["execution_mode"], "direct")
        tool_names = [tool_call["name"] for tool_call in payload["assistant_message"]["tool_calls"]]
        self.assertIn("weather.get_current_weather", tool_names)
        self.assertIn("上海", payload["assistant_message"]["content"])
        self.assertIn("26", payload["assistant_message"]["content"])

    @patch("app.api.chat.get_llm_gateway", return_value=FakeGateway())
    async def test_chat_uses_weather_skill_for_beijing_colloquial_request(self, _gateway):
        original_get_tool_function = SkillManager.get_tool_function

        async def fake_weather_tool(location: str, units: str = "metric"):
            self.assertEqual(location, "北京")
            return {
                "source": "wttr.in",
                "location": "北京",
                "condition": "晴朗",
                "temperature": "24",
                "feels_like": "25",
                "humidity": "45",
                "wind_speed": "10",
                "units": units,
                "summary": "北京：晴朗，当前 24度，体感 25度，湿度 45%，风速 10 公里/小时",
            }

        def patched_get_tool_function(self, skill_name: str, tool_name: str):
            if skill_name == "weather" and tool_name == "get_current_weather":
                return fake_weather_tool
            return original_get_tool_function(self, skill_name, tool_name)

        with patch.object(SkillManager, "get_tool_function", new=patched_get_tool_function):
            response = await self.client.post(
                "/api/v1/chat/message",
                json={"content": "北京什么天气", "stream": False},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["execution_mode"], "direct")
        tool_names = [tool_call["name"] for tool_call in payload["assistant_message"]["tool_calls"]]
        self.assertTrue(
            "weather.get_current_weather" in tool_names
            or "serana_contextual_reply" in tool_names
            or "serana_direct_reply" in tool_names
        )
        self.assertIn("北京", payload["assistant_message"]["content"])

    @patch("app.api.chat.get_llm_gateway")
    async def test_chat_can_use_browser_search_tool(self, gateway_patch):
        gateway = BrowserGateway()
        gateway_patch.return_value = gateway

        async def fake_search_web(query: str, max_results: int = 5):
            return {
                "query": query,
                "url": "https://www.bing.com/search?q=Serana+browser+test",
                "title": "Serana browser test - Search",
                "results": [{"title": "Serana browser test result"}],
                "content": "Serana browser test result\nA concise browser result.",
                "summary": "已搜索：Serana browser test，找到 1 条可见结果。",
            }

        original_get_tool_function = SkillManager.get_tool_function

        def patched_get_tool_function(self, skill_name: str, tool_name: str):
            if skill_name == "browser" and tool_name == "search_web":
                return fake_search_web
            return original_get_tool_function(self, skill_name, tool_name)

        with patch.object(SkillManager, "get_tool_function", patched_get_tool_function):
            response = await self.client.post(
                "/api/v1/chat/message",
                json={"content": "上网查一下 Serana browser test", "stream": False},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["execution_mode"], "direct")
        self.assertIn("浏览器结果", payload["assistant_message"]["content"])
        tool_names = [tool_call["name"] for tool_call in payload["assistant_message"]["tool_calls"]]
        self.assertIn("conversation_route", tool_names)
        self.assertIn("serana_tool_selection", tool_names)
        self.assertIn("browser.search_web", tool_names)
        self.assertGreaterEqual(gateway.llm.call_count, 2)
        self.assertLessEqual(gateway.llm.call_count, 4)

    async def test_browser_screenshot_endpoint_serves_png(self):
        screenshot_dir = Path(__file__).resolve().parent / "skills_store" / "browser" / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = screenshot_dir / "test-screenshot.png"
        screenshot_path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
            b"\x90wS\xde"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        try:
            response = await self.client.get("/api/v1/browser/screenshots/test-screenshot.png")
        finally:
            screenshot_path.unlink(missing_ok=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))

    async def test_browser_screenshot_endpoint_rejects_path_traversal(self):
        response = await self.client.get("/api/v1/browser/screenshots/..%2Fserana.db")

        self.assertEqual(response.status_code, 404)

    async def test_browser_preview_endpoint_serves_html_with_csp(self):
        preview_dir = Path(__file__).resolve().parent / "skills_store" / "browser" / "previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_path = preview_dir / "test-preview.html"
        preview_path.write_text("<!doctype html><html><body>Demo</body></html>", encoding="utf-8")
        try:
            response = await self.client.get("/api/v1/browser/previews/test-preview.html")
        finally:
            preview_path.unlink(missing_ok=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertTrue(response.headers.get("content-disposition", "").startswith("inline;"))
        self.assertIn(b"Demo", response.content)

    async def test_browser_preview_endpoint_rejects_path_traversal(self):
        response = await self.client.get("/api/v1/browser/previews/..%2Fserana.db")

        self.assertEqual(response.status_code, 404)

    async def test_browser_download_endpoint_serves_file(self):
        download_dir = Path(__file__).resolve().parent / "skills_store" / "browser" / "downloads"
        download_dir.mkdir(parents=True, exist_ok=True)
        download_path = download_dir / "report.txt"
        download_path.write_text("download body", encoding="utf-8")
        try:
            response = await self.client.get("/api/v1/browser/downloads/report.txt")
        finally:
            download_path.unlink(missing_ok=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers["content-type"])
        self.assertEqual(response.text, "download body")

    async def test_browser_download_endpoint_rejects_path_traversal(self):
        response = await self.client.get("/api/v1/browser/downloads/..%2Fserana.db")

        self.assertEqual(response.status_code, 404)

    async def test_browser_create_html_preview_returns_artifact(self):
        from skills_store.browser import create_html_preview

        result = await create_html_preview(
            "冒泡排序演示",
            (
                "<h1>冒泡排序演示</h1>"
                "<button id=\"next\">下一步</button>"
                "<p id=\"status\">准备开始</p>"
                "<script>document.getElementById('next').addEventListener('click', function () {"
                "document.getElementById('status').textContent = '已前进一步';"
                "});</script>"
            ),
        )
        try:
            self.assertNotIn("error", result)
            self.assertEqual(result["artifact"]["kind"], "html_preview")
            self.assertTrue(result["artifact"]["download_url"].startswith("/api/v1/browser/previews/"))
            self.assertEqual(result["browser_state"]["status"], "preview_ready")
            self.assertTrue(Path(result["path"]).exists())
        finally:
            path = result.get("path")
            if isinstance(path, str):
                Path(path).unlink(missing_ok=True)

    async def test_browser_create_html_preview_reuses_cache_key(self):
        from skills_store.browser import create_html_preview

        cache_path = Path(__file__).resolve().parent / "skills_store" / "browser" / "previews" / "preview-cache.json"
        cache_path.unlink(missing_ok=True)
        first = await create_html_preview(
            "快速排序动画演示",
            (
                "<h1>快速排序动画演示</h1>"
                "<button id=\"start\">开始排序</button>"
                "<p id=\"status\">准备开始</p>"
                "<script>document.getElementById('start').addEventListener('click', function () {"
                "document.getElementById('status').textContent = '已复用演示';"
                "});</script>"
            ),
            cache_key="quicksort-demo-test",
        )
        second = await create_html_preview(
            "快速排序动画演示",
            "",
            cache_key="quicksort-demo-test",
        )

        try:
            self.assertNotIn("error", first)
            self.assertNotIn("error", second)
            self.assertFalse(first["cached"])
            self.assertTrue(second["cached"])
            self.assertEqual(first["artifact"]["download_url"], second["artifact"]["download_url"])
            self.assertTrue(Path(second["path"]).exists())
        finally:
            for result in (first, second):
                path = result.get("path")
                if isinstance(path, str):
                    Path(path).unlink(missing_ok=True)
            cache_path.unlink(missing_ok=True)

    async def test_browser_create_html_preview_rejects_placeholder_html(self):
        from skills_store.browser import create_html_preview

        result = await create_html_preview(
            "快速排序动画演示",
            "<h1>快速排序动画演示</h1><div id=\"array-container\"></div><button id=\"start\">开始排序</button><script>/* JavaScript code for quicksort animation */</script>",
        )

        self.assertIn("error", result)
        self.assertIn("占位", result["summary"])
        self.assertEqual(result["browser_state"]["status"], "failed")
        self.assertTrue(result["recoverable"])

    async def test_browser_create_html_preview_rejects_unwired_controls(self):
        from skills_store.browser import create_html_preview

        result = await create_html_preview(
            "快速排序动画演示",
            "<h1>快速排序动画演示</h1><button id=\"start\">开始排序</button><script>const values = [3, 1, 2];</script>",
        )

        self.assertIn("error", result)
        self.assertIn("事件绑定", result["summary"])
        self.assertEqual(result["browser_state"]["status"], "failed")

    async def test_browser_create_html_preview_blocks_network_html(self):
        from skills_store.browser import create_html_preview

        result = await create_html_preview(
            "不安全演示",
            "<h1>demo</h1><script>fetch('https://example.com')</script>",
        )

        self.assertIn("error", result)
        self.assertIn("已拦截", result["summary"])
        self.assertEqual(result["browser_state"]["status"], "failed")

    async def test_browser_tools_return_browser_state_when_page_is_missing(self):
        from skills_store import browser as browser_skill

        await browser_skill.close_browser()

        capture_result = await browser_skill.capture_page()
        action_result = await browser_skill.act_page(action="click", target="#submit")

        self.assertIn("error", capture_result)
        self.assertFalse(capture_result["browser_state"]["page_open"])
        self.assertEqual(capture_result["browser_state"]["status"], "missing_page")
        self.assertTrue(capture_result["recoverable"])
        self.assertIn("open_page", capture_result["browser_state"]["next_actions"])
        self.assertEqual(action_result["browser_state"]["status"], "missing_page")

    async def test_browser_downloads_lists_and_sends_artifact(self):
        from skills_store import browser as browser_skill

        download_dir = Path(__file__).resolve().parent / "skills_store" / "browser" / "downloads"
        download_dir.mkdir(parents=True, exist_ok=True)
        download_path = download_dir / "report.txt"
        manifest_path = download_dir / "downloads.jsonl"
        download_path.write_text("download body", encoding="utf-8")
        manifest_path.write_text(
            json.dumps(
                {
                    "filename": "report.txt",
                    "mime": "text/plain",
                    "size": download_path.stat().st_size,
                    "mtime": download_path.stat().st_mtime,
                    "original": "report.txt",
                    "source_url": "https://example.com/report",
                    "created_at": "2026-05-25T00:00:00+00:00",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        try:
            list_result = await browser_skill.browser_downloads(action="list")
            send_result = await browser_skill.browser_downloads(action="send", filename="report.txt")
        finally:
            download_path.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)

        self.assertEqual(list_result["count"], 1)
        self.assertIn("browser_state", list_result)
        self.assertEqual(list_result["downloads"][0]["filename"], "report.txt")
        self.assertEqual(send_result["artifact"]["kind"], "download")
        self.assertEqual(send_result["browser_state"]["status"], "download_ready")
        self.assertEqual(send_result["artifact"]["download_url"], "/api/v1/browser/downloads/report.txt")

    async def test_policy_gate_requires_approval_for_browser_side_effects(self):
        policy_gate = get_policy_gate()

        browser_click = policy_gate.evaluate(
            tool_name="browser.act_page",
            arguments={"action": "click", "target": "提交按钮"},
        )
        self.assertTrue(browser_click.requires_approval)
        self.assertEqual(browser_click.operation, "browser_act")

        browser_download_send = policy_gate.evaluate(
            tool_name="browser.browser_downloads",
            arguments={"action": "send", "filename": "report.txt"},
        )
        self.assertTrue(browser_download_send.requires_approval)
        self.assertEqual(browser_download_send.operation, "browser_download_send")

        browser_observe = policy_gate.evaluate(
            tool_name="browser.observe_page",
            arguments={"max_chars": 2000},
        )
        self.assertFalse(browser_observe.requires_approval)

    async def test_artifact_helpers_create_common_shape(self):
        from app.core.artifacts import make_download_artifact, make_html_preview_artifact, make_image_artifact

        image = make_image_artifact(
            filename="screen.png",
            download_url="/api/v1/browser/screenshots/screen.png",
            size_bytes=12,
        )
        preview = make_html_preview_artifact(
            filename="demo.html",
            title="演示",
            download_url="/api/v1/browser/previews/demo.html",
            size_bytes=34,
        )
        download = make_download_artifact(
            filename="report.txt",
            mime_type="text/plain",
            download_url="/api/v1/browser/downloads/report.txt",
            size_bytes=56,
        )

        self.assertEqual(image["kind"], "image")
        self.assertEqual(image["thumbnail_url"], image["download_url"])
        self.assertEqual(preview["kind"], "html_preview")
        self.assertEqual(preview["title"], "演示")
        self.assertEqual(preview["mime_type"], "text/html")
        self.assertEqual(download["kind"], "download")
        self.assertEqual(download["mime_type"], "text/plain")

    async def test_profile_facts_sync_into_resident_memory_context(self):
        async with AsyncSessionLocal() as session:
            manager = ProfileFactsManager(session, self.default_user_id)
            resident_manager = ResidentMemoryManager(session, self.default_user_id)
            injector = MemoryInjector(session, self.default_user_id)

            await manager.add_fact(
                key="preferred_drink",
                value="black coffee",
                category="preference",
                source="user_explicit",
                confidence=0.9,
            )

            resident_context = await resident_manager.to_context_string()
            self.assertIn("[Resident Memory]", resident_context)
            self.assertIn("preference: preferred_drink = black coffee", resident_context)

            conversation_context = await injector.inject_for_conversation(
                user_input="What should I prepare for breakfast?",
                include_history=False,
            )
            self.assertIn("[Resident Memory]", conversation_context)
            self.assertIn("[User Profile]", conversation_context)

    async def test_context_builder_places_resident_memory_before_dynamic_memory(self):
        request = build_contextual_request(
            "Plan breakfast for tomorrow.",
            resident_memory_context="[Resident Memory]\n- preference: preferred_drink = black coffee",
            working_memory_context="[Working Memory]\n- drafting a light breakfast plan",
            memory_context="[User Profile]\n- favorite_breakfast: toast",
            instruction_skill_context="## 技能：meal_helper\n优先给出低压力建议。",
        )

        self.assertIn("Resident memory:", request)
        self.assertIn("Working memory:", request)
        self.assertIn("Relevant memory context:", request)
        self.assertLess(request.index("Resident memory:"), request.index("Working memory:"))
        self.assertLess(request.index("Working memory:"), request.index("Relevant memory context:"))
        self.assertLess(request.index("Relevant memory context:"), request.index("Installed instruction skills:"))

    async def test_serana_context_bundle_builds_effective_prompt_and_visible_tools(self):
        state = {
            "user_input": "What time is it in Shanghai?",
            "session_id": "context-test-session",
            "execution_mode": "direct",
            "resident_memory_context": "[Resident Memory]\n- preference: concise replies",
            "working_memory_context": "[Working Memory]\n- current task = time lookup",
            "memory_context": "[User Profile]\n- locale: zh-CN",
            "instruction_skill_names": ["butler_tone"],
            "instruction_skill_context": "## Skill: butler_tone\nKeep replies calm and practical.",
        }

        bundle = build_serana_context_bundle(state)
        request = bundle.build_request_context(
            label="User request",
            include_runtime=True,
            include_available_tools=True,
        )
        system_prompt = bundle.build_system_prompt(
            "Answer directly.",
            include_available_tools=True,
        )

        self.assertIn("Serana", system_prompt)
        self.assertIn("Installed instruction skills", system_prompt)
        self.assertIn("Available tools", system_prompt)
        self.assertIn("browser.", bundle.available_tool_context)
        self.assertIn("Runtime context", request)
        self.assertIn("Available tools", request)
        self.assertLess(request.index("Resident memory:"), request.index("Working memory:"))

    async def test_working_memory_context_is_scoped_to_session(self):
        async with AsyncSessionLocal() as session:
            manager = WorkingMemoryManager(session, self.default_user_id)
            injector = MemoryInjector(session, self.default_user_id)

            await manager.upsert_entry(
                key="draft_state",
                content="Need to compare two breakfast options before answering.",
                scope="conversation",
                session_id="session-alpha",
                source="test",
                priority=0.8,
            )
            await manager.upsert_entry(
                key="draft_state",
                content="This note belongs to another conversation.",
                scope="conversation",
                session_id="session-beta",
                source="test",
                priority=0.7,
            )

            sections = await injector.build_conversation_sections(
                user_input="Help me choose breakfast.",
                session_id="session-alpha",
                include_facts=False,
                include_history=False,
            )

            self.assertIn("[Working Memory]", sections["working_memory_context"])
            self.assertIn("Need to compare two breakfast options before answering.", sections["working_memory_context"])
            self.assertNotIn("This note belongs to another conversation.", sections["working_memory_context"])
            self.assertIn("[Working Memory]", sections["combined_context"])

    async def test_memory_service_centralizes_sections_and_memory_ops(self):
        async with AsyncSessionLocal() as session:
            service = MemoryService(session, self.default_user_id)

            await service.save_memory(
                key="preferred_drink",
                value="black coffee",
                category="preference",
                source="test",
                confidence=0.9,
            )
            await service.save_working_memory(
                key="trip_budget",
                value="5000 RMB",
                scope="conversation",
                session_id="service-session",
                source="test",
                priority=0.8,
            )

            sections = await service.build_conversation_sections(
                user_input="Remind me what I prefer and what budget we set.",
                session_id="service-session",
                include_facts=True,
                include_history=False,
            )

            self.assertIn("[Resident Memory]", sections["resident_memory_context"])
            self.assertIn("preferred_drink = black coffee", sections["resident_memory_context"])
            self.assertIn("[Working Memory]", sections["working_memory_context"])
            self.assertIn("5000 RMB", sections["working_memory_context"])
            self.assertIn("[Resident Memory]", sections["combined_context"])
            self.assertIn("[Working Memory]", sections["combined_context"])

    async def test_memory_manager_skill_can_save_and_search(self):
        manager = SkillManager()
        manager.ensure_initialized()

        save_tool = manager.get_tool_function("memory_manager", "memory_save")
        search_tool = manager.get_tool_function("memory_manager", "memory_search")
        working_save_tool = manager.get_tool_function("memory_manager", "working_memory_save")
        working_clear_tool = manager.get_tool_function("memory_manager", "working_memory_clear")

        self.assertIsNotNone(save_tool)
        self.assertIsNotNone(search_tool)
        self.assertIsNotNone(working_save_tool)
        self.assertIsNotNone(working_clear_tool)

        save_result = await save_tool(key="preferred_drink", value="黑咖啡", category="preference")
        self.assertIn("我已经记住", save_result["summary"])

        search_result = await search_tool(query="喜欢什么饮料", limit=5)
        self.assertGreaterEqual(len(search_result["results"]), 1)
        self.assertIn("黑咖啡", search_result["summary"])

        working_save_result = await working_save_tool(
            key="trip_budget",
            value="5000 元",
            scope="conversation",
            session_id="session-working-test",
        )
        self.assertIn("当前对话", working_save_result["summary"])

        async with AsyncSessionLocal() as session:
            working_manager = WorkingMemoryManager(session, self.default_user_id)
            working_context = await working_manager.to_context_string(
                scope="conversation",
                session_id="session-working-test",
            )
            self.assertIn("5000 元", working_context)

        working_clear_result = await working_clear_tool(
            scope="conversation",
            session_id="session-working-test",
        )
        self.assertIn("清空当前对话", working_clear_result["summary"])

    @patch("app.api.chat.get_llm_gateway", return_value=FallbackOnlyGateway())
    async def test_chat_can_use_working_memory_tools_naturally(self, _gateway):
        save_response = await self.client.post(
            "/api/v1/chat/message",
            json={"content": "先记一下这次旅行预算是 5000 元", "stream": False},
        )
        self.assertEqual(save_response.status_code, 200)
        save_payload = save_response.json()
        self.assertIn("5000", save_payload["assistant_message"]["content"])
        save_tool_names = [tool_call["name"] for tool_call in save_payload["assistant_message"]["tool_calls"]]
        self.assertIn("memory_manager.working_memory_save", save_tool_names)

        session_id = save_payload["session_id"]
        async with AsyncSessionLocal() as session:
            injector = MemoryInjector(session, self.default_user_id)
            sections = await injector.build_conversation_sections(
                user_input="旅行预算是多少？",
                session_id=session_id,
                include_facts=False,
                include_history=False,
            )
            self.assertIn("[Working Memory]", sections["working_memory_context"])
            self.assertIn("5000 元", sections["working_memory_context"])

        clear_response = await self.client.post(
            "/api/v1/chat/message",
            json={"session_id": session_id, "content": "把这轮临时笔记清掉", "stream": False},
        )
        self.assertEqual(clear_response.status_code, 200)
        clear_payload = clear_response.json()
        clear_tool_names = [tool_call["name"] for tool_call in clear_payload["assistant_message"]["tool_calls"]]
        self.assertIn("memory_manager.working_memory_clear", clear_tool_names)

        async with AsyncSessionLocal() as session:
            injector = MemoryInjector(session, self.default_user_id)
            sections = await injector.build_conversation_sections(
                user_input="旅行预算是多少？",
                session_id=session_id,
                include_facts=False,
                include_history=False,
            )
            self.assertEqual(sections["working_memory_context"], "")

    async def test_resident_snapshot_refreshes_after_fact_changes(self):
        async with AsyncSessionLocal() as session:
            facts_manager = ProfileFactsManager(session, self.default_user_id)
            resident_manager = ResidentMemoryManager(session, self.default_user_id)

            await facts_manager.add_fact(
                key="favorite_breakfast",
                value="toast",
                category="preference",
                source="test",
                confidence=0.7,
            )
            snapshot = await resident_manager.get_snapshot_context()
            self.assertIn("[Resident Memory]", snapshot)
            self.assertIn("偏好", snapshot)
            self.assertIn("favorite_breakfast = toast", snapshot)

            await facts_manager.update_fact(
                key="favorite_breakfast",
                value="congee",
                source="test",
                category="preference",
                confidence=0.8,
            )
            refreshed_snapshot = await resident_manager.get_snapshot_context()
            self.assertIn("favorite_breakfast = congee", refreshed_snapshot)
            self.assertNotIn("favorite_breakfast = toast", refreshed_snapshot)

            await facts_manager.delete_fact("favorite_breakfast")
            cleared_snapshot = await resident_manager.get_snapshot_context(refresh_if_missing=False)
            self.assertNotIn("favorite_breakfast", cleared_snapshot)

    @patch("app.api.chat.get_llm_gateway", return_value=FakeGateway())
    async def test_chat_consolidation_promotes_stable_preference(self, _gateway):
        preference_message = "我平时喜欢手冲咖啡。"

        async with AsyncSessionLocal() as session:
            facts_manager = ProfileFactsManager(session, self.default_user_id)
            await facts_manager.delete_fact("preferred_drink")

        response = await self.client.post(
            "/api/v1/chat/message",
            json={"content": preference_message, "stream": False},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        audit_response = await self.client.get(f"/api/v1/chat/sessions/{payload['session_id']}/audit")
        self.assertEqual(audit_response.status_code, 200)
        audit_records = audit_response.json()
        consolidation_record = next(
            (record for record in audit_records if record["event_type"] == "memory_consolidation"),
            None,
        )
        if consolidation_record is not None:
            self.assertEqual(consolidation_record["payload"]["candidate_count"], 1)
            saved_entries = consolidation_record["payload"]["saved"]
            self.assertTrue(any(entry["key"] == "preferred_drink" and entry["value"] == "手冲咖啡" for entry in saved_entries))

    async def test_consolidation_skips_duplicate_values_with_decision_log(self):
        async with AsyncSessionLocal() as session:
            service = MemoryService(session, self.default_user_id)
            await service.save_memory(
                key="preferred_drink",
                value="手冲咖啡",
                category="preference",
                source="test",
                confidence=0.9,
            )

            result = await service.consolidate_chat_turn(
                user_input="我平时喜欢手冲咖啡。",
                session_id="duplicate-memory-session",
            )

            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(result["applied_count"], 0)
            self.assertEqual(len(result["saved"]), 0)
            self.assertEqual(len(result["skipped"]), 1)
            self.assertEqual(result["skipped"][0]["reason"], "duplicate_value")
            self.assertEqual(result["decisions"][0]["action"], "skip")
            self.assertEqual(result["decisions"][0]["reason"], "duplicate_value")

    @patch("app.api.chat.get_llm_gateway", return_value=MemoryAwareGateway())
    async def test_chat_can_use_memory_tools(self, _gateway):
        save_response = await self.client.post(
            "/api/v1/chat/message",
            json={"content": "帮我记住我喜欢黑咖啡", "stream": False},
        )
        self.assertEqual(save_response.status_code, 200)
        save_payload = save_response.json()
        self.assertIn("我已经记住", save_payload["assistant_message"]["content"])
        save_tool_names = [tool_call["name"] for tool_call in save_payload["assistant_message"]["tool_calls"]]
        self.assertIn("memory_manager.memory_save", save_tool_names)

        search_response = await self.client.post(
            "/api/v1/chat/message",
            json={"content": "我之前说过我喜欢什么饮料？", "stream": False},
        )
        self.assertEqual(search_response.status_code, 200)
        search_payload = search_response.json()
        self.assertIn("黑咖啡", search_payload["assistant_message"]["content"])
        search_tool_names = [tool_call["name"] for tool_call in search_payload["assistant_message"]["tool_calls"]]
        self.assertIn("memory_manager.memory_search", search_tool_names)

    @patch("app.api.chat.get_llm_gateway", return_value=FakeGateway())
    async def test_chat_message_uses_delegated_mode_for_complex_requests(self, _gateway):
        response = await self.client.post(
            "/api/v1/chat/message",
            json={"content": "Research and build a weekly study plan", "stream": False},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["execution_mode"], "delegated")
        self.assertGreaterEqual(payload["delegation_plan"]["parallel_slots"], 2)
        self.assertGreaterEqual(payload["delegation_plan"]["parallel_forges"], 2)
        tool_names = [tool_call["name"] for tool_call in payload["assistant_message"]["tool_calls"]]
        self.assertIn("forge_execute", tool_names)
        self.assertIn("serana_delegate", tool_names)
        self.assertIn("working_memory_update", tool_names)

        timeline_response = await self.client.get(
            "/api/v1/audit/timeline",
            params={"entity_type": "chat_session", "entity_id": payload["session_id"]},
        )
        self.assertEqual(timeline_response.status_code, 200)
        timeline = timeline_response.json()
        self.assertIn("research", timeline["insights"]["task_types"])
        self.assertIn("knowledge_scout", timeline["insights"]["tool_names"])
        self.assertIn("delegated", timeline["insights"]["lightweight_routes"])
        self.assertIn("planning", timeline["insights"]["loop_transition_targets"])
        self.assertEqual(
            timeline["insights"]["loop_stages"],
            ["lightweight_complete", "lightweight_start", "planning_complete", "planning_start"],
        )
        self.assertEqual(
            timeline["insights"]["planning_stages"],
            ["analyze", "decompose", "delegate", "summarize"],
        )
        self.assertGreaterEqual(max(timeline["insights"]["parallel_forges"]), 2)

        debug_summary_response = await self.client.get(
            "/api/v1/audit/debug-summary",
            params={"entity_type": "chat_session", "entity_id": payload["session_id"]},
        )
        self.assertEqual(debug_summary_response.status_code, 200)
        debug_summary = debug_summary_response.json()
        self.assertIn("research", debug_summary["task_types"])
        self.assertIn("knowledge_scout", debug_summary["tool_names"])
        self.assertIn("forge_execute", debug_summary["event_counts"])
        self.assertIn("delegated", debug_summary["lightweight_routes"])
        self.assertIn("planning", debug_summary["loop_transition_targets"])
        self.assertEqual(
            debug_summary["loop_stages"],
            ["lightweight_complete", "lightweight_start", "planning_complete", "planning_start"],
        )
        self.assertEqual(
            debug_summary["planning_stages"],
            ["analyze", "decompose", "delegate", "summarize"],
        )

        debug_response = await self.client.get(f"/api/v1/chat/sessions/{payload['session_id']}/debug")
        self.assertEqual(debug_response.status_code, 200)
        debug_payload = debug_response.json()
        self.assertEqual(debug_payload["session"]["id"], payload["session_id"])
        self.assertEqual(len(debug_payload["messages"]), 2)
        self.assertEqual(debug_payload["audit_timeline"]["entity_type"], "chat_session")
        self.assertIn("research", debug_payload["audit_summary"]["task_types"])
        self.assertIn("knowledge_scout", debug_payload["audit_summary"]["tool_names"])
        self.assertIn("delegated", debug_payload["audit_summary"]["lightweight_routes"])
        self.assertIn("planning", debug_payload["audit_summary"]["loop_transition_targets"])

    @patch("app.api.chat.get_llm_gateway", return_value=InstructionAwareGateway())
    async def test_chat_applies_instruction_skill_context_to_prompt(self, _gateway):
        fake_instruction_skill = SimpleNamespace(
            name="travel_helper",
            description="Help with calm, low-stress travel planning.",
            instruction_content="# Travel Helper\nPrefer calm pacing, buffer time, and low-stress suggestions.",
            manifest=SimpleNamespace(source_url="https://skillhub.cn/skills/travel-helper"),
        )

        with patch.object(SkillManager, "get_enabled_instruction_skills", return_value=[fake_instruction_skill]):
            response = await self.client.post(
                "/api/v1/chat/message",
                json={"content": "Quick question: suggest a calm travel day.", "stream": False},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["assistant_message"]["content"].strip())
        tool_names = [tool_call["name"] for tool_call in payload["assistant_message"]["tool_calls"]]
        self.assertIn("instruction_skill_context", tool_names)
        instruction_call = next(
            tool_call for tool_call in payload["assistant_message"]["tool_calls"]
            if tool_call["name"] == "instruction_skill_context"
        )
        self.assertIn("travel_helper", instruction_call["output"]["skill_names"])

    async def test_marketplace_search_returns_remote_skills(self):
        app.dependency_overrides[get_marketplace_client] = lambda: FakeMarketplaceClient()

        response = await self.client.get("/api/v1/skills/marketplace/search", params={"q": "weather"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["slug"], "weather")
        self.assertIn("installed", payload["results"][0])
        self.assertIn("local_skill_name", payload["results"][0])

    async def test_marketplace_install_returns_local_skill_package(self):
        app.dependency_overrides[get_marketplace_client] = lambda: FakeMarketplaceClient()

        requested = await self.client.post(
            "/api/v1/skills/marketplace/install",
            json={"slug": "weather"},
        )
        self.assertEqual(requested.status_code, 200)
        requested_payload = requested.json()
        self.assertEqual(requested_payload["status"], "approval_required")
        request_id = requested_payload["approval_request"]["request_id"]

        approved = await self.client.post(
            f"/api/v1/approvals/{request_id}",
            json={"request_id": request_id, "approved": True},
        )
        self.assertEqual(approved.status_code, 200)

        installed = await self.client.post(
            "/api/v1/skills/marketplace/install",
            json={"slug": "weather", "approval_request_id": request_id},
        )

        self.assertEqual(installed.status_code, 200)
        payload = installed.json()
        self.assertEqual(payload["status"], "installed")
        self.assertEqual(payload["skill"]["name"], "weather")
        self.assertEqual(payload["skill"]["manifest"]["registry_slug"], "weather")

        audit_response = await self.client.get(
            "/api/v1/audit/timeline",
            params={"entity_type": "skill_marketplace", "entity_id": "weather"},
        )
        self.assertEqual(audit_response.status_code, 200)
        audit_payload = audit_response.json()
        event_types = [record["event_type"] for record in audit_payload["records"]]
        self.assertIn("approval_requested", event_types)
        self.assertIn("approval_resolved", event_types)
        self.assertIn("skills_install", event_types)

    async def test_upload_skill_requires_approval_and_installs_after_confirmation(self):
        skill_name = "approval_upload_demo"
        temp_dir, archive_bytes = create_test_skill_archive(skill_name)
        try:
            requested = await self.client.post(
                "/api/v1/skills/upload",
                files={"file": (f"{skill_name}.zip", archive_bytes, "application/zip")},
            )
            self.assertEqual(requested.status_code, 200)
            requested_payload = requested.json()
            self.assertEqual(requested_payload["status"], "approval_required")
            request_id = requested_payload["approval_request"]["request_id"]

            approved = await self.client.post(
                f"/api/v1/approvals/{request_id}",
                json={"request_id": request_id, "approved": True},
            )
            self.assertEqual(approved.status_code, 200)

            installed = await self.client.post(
                "/api/v1/skills/upload",
                data={"approval_request_id": request_id},
            )
            self.assertEqual(installed.status_code, 200)
            installed_payload = installed.json()
            self.assertEqual(installed_payload["status"], "installed")
            self.assertEqual(installed_payload["skill"]["name"], skill_name)
            self.assertTrue(installed_payload["skill"]["can_uninstall"])
            self.assertEqual(installed_payload["skill"]["origin"], "managed")

            audit_response = await self.client.get(
                "/api/v1/audit/timeline",
                params={"entity_type": "skill_local_package", "entity_id": skill_name},
            )
            self.assertEqual(audit_response.status_code, 200)
            event_types = [record["event_type"] for record in audit_response.json()["records"]]
            self.assertIn("approval_requested", event_types)
            self.assertIn("approval_resolved", event_types)
            self.assertIn("skills_install_local", event_types)
        finally:
            SkillManager().remove_skill(skill_name)
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def test_delete_skill_requires_approval_for_managed_skills(self):
        skill_name = "managed_delete_demo"
        temp_dir, _ = create_test_skill_archive(skill_name)
        manager = SkillManager()
        installed_skill = manager.install_skill_from_directory(temp_dir / skill_name)
        self.assertIsNotNone(installed_skill)

        try:
            requested = await self.client.delete(f"/api/v1/skills/{skill_name}")
            self.assertEqual(requested.status_code, 200)
            requested_payload = requested.json()
            self.assertEqual(requested_payload["status"], "approval_required")
            request_id = requested_payload["approval_request"]["request_id"]

            approved = await self.client.post(
                f"/api/v1/approvals/{request_id}",
                json={"request_id": request_id, "approved": True},
            )
            self.assertEqual(approved.status_code, 200)

            removed = await self.client.delete(
                f"/api/v1/skills/{skill_name}",
                params={"approval_request_id": request_id},
            )
            self.assertEqual(removed.status_code, 200)
            removed_payload = removed.json()
            self.assertEqual(removed_payload["status"], "removed")
            self.assertEqual(removed_payload["skill"]["name"], skill_name)
            self.assertIsNone(manager.get_skill(skill_name))

            audit_response = await self.client.get(
                "/api/v1/audit/timeline",
                params={"entity_type": "skill_local", "entity_id": skill_name},
            )
            self.assertEqual(audit_response.status_code, 200)
            event_types = [record["event_type"] for record in audit_response.json()["records"]]
            self.assertIn("approval_requested", event_types)
            self.assertIn("approval_resolved", event_types)
            self.assertIn("skills_uninstall", event_types)
        finally:
            SkillManager().remove_skill(skill_name)
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def test_bundled_skill_cannot_be_deleted(self):
        response = await self.client.delete("/api/v1/skills/browser")

        self.assertEqual(response.status_code, 400)
        self.assertIn("不能直接卸载", response.text)

    @patch("app.api.goals.get_llm_gateway", return_value=FakeGateway())
    async def test_goal_creation_returns_subtasks(self, _gateway):
        response = await self.client.post(
            "/api/v1/goals",
            json={"description": "Build a weekly study plan"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["description"], "Build a weekly study plan")
        self.assertGreaterEqual(len(payload["subtasks"]), 3)
        self.assertTrue(all(task["description"] for task in payload["subtasks"]))
        self.assertTrue(all(task["status"] == "pending" for task in payload["subtasks"]))
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(payload["progress"], 0.0)
        self.assertTrue(payload["planning_summary"])
        self.assertGreaterEqual(len(payload["thinking_blocks"]), 1)
        self.assertGreaterEqual(len(payload["events"]), 1)
        self.assertGreaterEqual(len(payload["audit_records"]), 1)
        self.assertEqual(payload["events"][0]["event_type"], "planned")
        self.assertEqual(payload["audit_records"][0]["entity_type"], "goal")
        event_types = [record["event_type"] for record in payload["audit_records"]]
        self.assertIn("forge_execute", event_types)
        self.assertIn("serana_analyze", event_types)
        self.assertIn("serana_decompose", event_types)
        self.assertIn("serana_summarize", event_types)

    @patch("app.api.goals.get_llm_gateway", return_value=InstructionAwareGateway())
    async def test_goal_applies_instruction_skill_context_to_planning(self, _gateway):
        fake_instruction_skill = SimpleNamespace(
            name="travel_helper",
            description="Help with calm, low-stress travel planning.",
            instruction_content="# Travel Helper\nPrefer calm pacing, buffer time, and low-stress suggestions.",
            manifest=SimpleNamespace(source_url="https://skillhub.cn/skills/travel-helper"),
        )

        with patch.object(SkillManager, "get_enabled_instruction_skills", return_value=[fake_instruction_skill]):
            response = await self.client.post(
                "/api/v1/goals",
                json={"description": "Plan a relaxed travel day with buffer time"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["planning_summary"].strip())
        self.assertTrue(any(block["title"] == "技能" for block in payload["thinking_blocks"]))
        audit_event_types = [record["event_type"] for record in payload["audit_records"]]
        self.assertIn("instruction_skill_context", audit_event_types)

    @patch("app.api.goals.get_llm_gateway", return_value=FakeGateway())
    async def test_goal_lifecycle_progression(self, _gateway):
        created = await self.client.post(
            "/api/v1/goals",
            json={"description": "Build a weekly study plan"},
        )
        payload = created.json()
        goal_id = payload["id"]
        subtasks = payload["subtasks"]

        started = await self.client.post(f"/api/v1/goals/{goal_id}/start")
        self.assertEqual(started.status_code, 200)
        started_payload = started.json()
        self.assertEqual(started_payload["status"], "in_progress")
        self.assertEqual(started_payload["subtasks"][0]["status"], "in_progress")
        self.assertTrue(any(event["event_type"] == "started" for event in started_payload["events"]))

        async with AsyncSessionLocal() as session:
            working_manager = WorkingMemoryManager(session, self.default_user_id)
            started_working_context = await working_manager.to_context_string(
                scope="goal",
                goal_id=goal_id,
            )
            self.assertIn("[Working Memory]", started_working_context)
            self.assertIn("Build a weekly study plan", started_working_context)
            self.assertIn(started_payload["subtasks"][0]["description"], started_working_context)

        first_subtask_id = started_payload["subtasks"][0]["id"]
        completed_first = await self.client.post(
            f"/api/v1/goals/{goal_id}/subtasks/{first_subtask_id}",
            json={"status": "completed"},
        )
        self.assertEqual(completed_first.status_code, 200)
        completed_payload = completed_first.json()
        self.assertGreater(completed_payload["progress"], 0.0)
        self.assertEqual(completed_payload["subtasks"][0]["status"], "completed")
        self.assertTrue(any(event["event_type"] == "subtask_updated" for event in completed_payload["events"]))
        self.assertTrue(any(event["event_type"] == "goal_progress_updated" for event in completed_payload["events"]))

        latest = completed_payload
        for subtask in latest["subtasks"][1:]:
            latest_response = await self.client.post(
                f"/api/v1/goals/{goal_id}/subtasks/{subtask['id']}",
                json={"status": "completed"},
            )
            self.assertEqual(latest_response.status_code, 200)
            latest = latest_response.json()

        self.assertEqual(latest["status"], "completed")
        self.assertEqual(latest["progress"], 1.0)

        async with AsyncSessionLocal() as session:
            working_manager = WorkingMemoryManager(session, self.default_user_id)
            finished_working_context = await working_manager.to_context_string(
                scope="goal",
                goal_id=goal_id,
            )
            self.assertEqual(finished_working_context, "")

        events_response = await self.client.get(f"/api/v1/goals/{goal_id}/events")
        self.assertEqual(events_response.status_code, 200)
        events = events_response.json()
        self.assertGreaterEqual(len(events), 5)
        self.assertEqual(events[0]["event_type"], "planned")
        self.assertEqual(events[-1]["event_type"], "goal_progress_updated")

        audit_response = await self.client.get(f"/api/v1/goals/{goal_id}/audit")
        self.assertEqual(audit_response.status_code, 200)
        audit_records = audit_response.json()
        self.assertGreaterEqual(len(audit_records), 5)
        self.assertEqual(audit_records[0]["entity_type"], "goal")
        audit_event_types = [record["event_type"] for record in audit_records]
        self.assertIn("forge_execute", audit_event_types)
        self.assertIn("planned", audit_event_types)
        self.assertIn("serana_delegate", audit_event_types)
        self.assertIn("goal_progress_updated", audit_event_types)

        filtered_audit = await self.client.get(
            "/api/v1/audit",
            params={"entity_type": "goal", "entity_id": goal_id, "event_type": "forge_execute"},
        )
        self.assertEqual(filtered_audit.status_code, 200)
        filtered_records = filtered_audit.json()
        self.assertGreaterEqual(len(filtered_records), 1)
        self.assertTrue(all(record["event_type"] == "forge_execute" for record in filtered_records))

        timeline_response = await self.client.get(
            "/api/v1/audit/timeline",
            params={"entity_type": "goal", "entity_id": goal_id},
        )
        self.assertEqual(timeline_response.status_code, 200)
        timeline = timeline_response.json()
        self.assertEqual(timeline["entity_type"], "goal")
        self.assertEqual(timeline["entity_id"], goal_id)
        self.assertEqual(timeline["total_records"], len(timeline["records"]))
        self.assertGreaterEqual(timeline["total_records"], len(filtered_records))
        timeline_event_types = [record["event_type"] for record in timeline["records"]]
        self.assertIn("planned", timeline_event_types)
        self.assertIn("forge_execute", timeline_event_types)
        self.assertIn("research", timeline["insights"]["task_types"])
        self.assertIn("knowledge_scout", timeline["insights"]["tool_names"])
        self.assertIn("planning", timeline["insights"]["loop_transition_targets"])
        self.assertEqual(
            timeline["insights"]["loop_stages"],
            ["lightweight_complete", "lightweight_start", "planning_complete", "planning_start"],
        )
        self.assertEqual(
            timeline["insights"]["planning_stages"],
            ["analyze", "decompose", "delegate", "summarize"],
        )
        self.assertGreaterEqual(max(timeline["insights"]["parallel_forges"]), 2)

        debug_summary_response = await self.client.get(
            "/api/v1/audit/debug-summary",
            params={"entity_type": "goal", "entity_id": goal_id},
        )
        self.assertEqual(debug_summary_response.status_code, 200)
        debug_summary = debug_summary_response.json()
        self.assertIn("research", debug_summary["task_types"])
        self.assertIn("knowledge_scout", debug_summary["tool_names"])
        self.assertIn("forge_execute", debug_summary["event_counts"])
        self.assertIn("planning", debug_summary["loop_transition_targets"])
        self.assertEqual(
            debug_summary["loop_stages"],
            ["lightweight_complete", "lightweight_start", "planning_complete", "planning_start"],
        )
        self.assertEqual(
            debug_summary["planning_stages"],
            ["analyze", "decompose", "delegate", "summarize"],
        )

        debug_response = await self.client.get(f"/api/v1/goals/{goal_id}/debug")
        self.assertEqual(debug_response.status_code, 200)
        debug_payload = debug_response.json()
        self.assertEqual(debug_payload["goal"]["id"], goal_id)
        self.assertEqual(debug_payload["audit_timeline"]["entity_type"], "goal")
        self.assertIn("research", debug_payload["audit_summary"]["task_types"])
        self.assertIn("knowledge_scout", debug_payload["audit_summary"]["tool_names"])
        self.assertIn("planning", debug_payload["audit_summary"]["loop_transition_targets"])

    @patch("app.api.goals.get_llm_gateway", return_value=FakeGateway())
    async def test_simple_goal_stays_direct(self, _gateway):
        response = await self.client.post(
            "/api/v1/goals",
            json={"description": "Quick question: what should I study tonight?"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["progress"], 1.0)
        self.assertEqual(len(payload["subtasks"]), 1)
        self.assertEqual(payload["subtasks"][0]["status"], "completed")
        self.assertTrue(payload["subtasks"][0]["description"].startswith("Handle directly with Serana:"))
        audit_event_types = [record["event_type"] for record in payload["audit_records"]]
        self.assertIn("conversation_route", audit_event_types)
        self.assertIn("serana_direct_reply", audit_event_types)
        self.assertNotIn("forge_execute", audit_event_types)

    async def test_forge_executes_cleanly(self):
        llm = FakeLLM()
        forge = ForgeAgent(llm)
        forge_result = await forge.execute({"description": "Run a concrete task"})
        self.assertTrue(forge_result["success"])
        self.assertEqual(forge_result["result"]["status"], "completed")
        self.assertGreaterEqual(len(forge.state.thinking_blocks), 2)
        self.assertEqual(forge_result["result"]["strategy"], "general_execution")
        self.assertEqual(forge_result["result"]["tool_name"], "task_runner")

    async def test_agent_manager_reuses_idle_forge(self):
        llm = FakeLLM()
        agent_manager = AgentManager()
        agent_manager.initialize(llm)

        first_forge = await agent_manager.get_agent("forge")
        first_forge_result = await first_forge.execute({"description": "Execute task A"})
        self.assertTrue(first_forge_result["success"])

        reused_forge = await agent_manager.get_agent("forge")
        self.assertIs(first_forge, reused_forge)
        reused_forge_result = await reused_forge.execute({"description": "Execute task B"})
        self.assertTrue(reused_forge_result["success"])
        self.assertEqual(reused_forge.state.status, "idle")
        self.assertEqual(reused_forge.state.current_task, None)
        self.assertEqual(agent_manager.agent_counts["forge"], 1)

    async def test_forge_uses_task_specific_strategy(self):
        llm = FakeLLM()
        forge = ForgeAgent(llm)

        research_result = await forge.execute(
            {
                "description": "Research best study materials",
                "task_type": "research",
                "batch_items": ["biology", "history"],
            }
        )
        self.assertTrue(research_result["success"])
        self.assertEqual(research_result["result"]["strategy"], "research_synthesis")
        self.assertEqual(research_result["result"]["tool_name"], "knowledge_scout")
        self.assertEqual(research_result["result"]["processed_items"], 2)

        build_result = await forge.execute(
            {
                "description": "Build a revision checklist",
                "task_type": "build",
            }
        )
        self.assertTrue(build_result["success"])
        self.assertEqual(build_result["result"]["strategy"], "implementation")
        self.assertEqual(build_result["result"]["tool_name"], "builder_toolkit")

    async def test_serana_routes_simple_tasks_directly(self):
        llm = FakeLLM()
        agent = SeranaAgent(llm)

        result = await agent.execute("Quick question: what should I study tonight?")

        self.assertTrue(result["success"])
        self.assertEqual(result["execution_mode"], "direct")
        self.assertEqual(result["complexity"], "simple")
        self.assertEqual(result["goal_type"], "question")
        self.assertEqual(result["delegation_plan"]["parallel_slots"], 0)
        tool_names = [tool_call["name"] for tool_call in result["tool_calls"]]
        self.assertIn("conversation_route", tool_names)
        self.assertIn("serana_direct_reply", tool_names)
        self.assertNotIn("serana_decompose", tool_names)
        self.assertNotIn("forge_execute", tool_names)

    async def test_serana_uses_single_llm_call_for_simple_direct_requests(self):
        llm = CountingLLM()
        agent = SeranaAgent(llm)

        result = await agent.execute("Quick question: what should I study tonight?")

        self.assertTrue(result["success"])
        self.assertEqual(result["execution_mode"], "direct")
        self.assertEqual(llm.call_count, 1)

    async def test_serana_stream_uses_lightweight_route_for_simple_requests(self):
        llm = CountingLLM()
        agent = SeranaAgent(llm)

        events = []
        async for event in agent.execute_stream("Quick question: what should I study tonight?"):
            events.append(event)

        self.assertGreaterEqual(len(events), 3)
        self.assertEqual(events[0]["type"], "thinking")
        self.assertIn("Serana", events[0]["content"])

        content_events = [event for event in events if event["type"] == "content"]
        self.assertGreater(len(content_events), 0)

        done_event = events[-1]
        self.assertEqual(done_event["type"], "done")
        self.assertEqual(done_event["execution_mode"], "direct")
        self.assertEqual(done_event["goal_type"], "question")
        self.assertEqual(done_event["complexity"], "simple")
        self.assertEqual(done_event["delegation_plan"]["parallel_slots"], 0)
        tool_names = [tool_call["name"] for tool_call in done_event["tool_calls"]]
        self.assertIn("conversation_route", tool_names)
        self.assertIn("serana_direct_reply", tool_names)
        self.assertEqual(llm.call_count, 1)

    async def test_serana_goal_uses_single_llm_call_for_simple_direct_requests(self):
        llm = CountingLLM()
        agent = SeranaAgent(llm)

        result = await agent.execute_goal("Quick question: what should I study tonight?")

        self.assertTrue(result["success"])
        self.assertEqual(result["execution_mode"], "direct")
        self.assertEqual(result["goal_type"], "question")
        self.assertEqual(result["complexity"], "simple")
        self.assertEqual(llm.call_count, 1)
        tool_names = [tool_call["name"] for tool_call in result["tool_calls"]]
        self.assertIn("conversation_route", tool_names)
        self.assertIn("serana_direct_reply", tool_names)
        self.assertNotIn("serana_decompose", tool_names)

    async def test_serana_uses_parallel_delegation_plan_for_complex_tasks(self):
        llm = FakeLLM()
        agent = SeranaAgent(llm)

        result = await agent.execute("Research and build a weekly study plan")

        self.assertTrue(result["success"])
        self.assertEqual(result["execution_mode"], "delegated")
        self.assertEqual(result["goal_type"], "research")
        self.assertEqual(result["complexity"], "high")
        self.assertGreaterEqual(result["delegation_plan"]["parallel_forges"], 2)
        delegate_call = next(
            tool_call for tool_call in result["tool_calls"] if tool_call["name"] == "serana_delegate"
        )
        self.assertGreaterEqual(delegate_call["output"]["parallel_slots"], 2)
        self.assertGreaterEqual(delegate_call["output"]["actual_forge_agents"], 2)
        tool_names = [tool_call["name"] for tool_call in result["tool_calls"]]
        self.assertIn("serana_loop_transition", tool_names)
        loop_actions = [
            tool_call["output"]
            for tool_call in result["tool_calls"]
            if tool_call["name"] == "serana_loop_action"
        ]
        self.assertEqual([action["status"] for action in loop_actions], ["started", "completed"])
        self.assertTrue(all(action["action"] == "delegate_agents" for action in loop_actions))
        self.assertTrue(all(action["runtime"] == "conversation_loop" for action in loop_actions))
        planning_stages = [
            tool_call["output"]["stage"]
            for tool_call in result["tool_calls"]
            if tool_call["name"] == "serana_planning_stage"
        ]
        self.assertEqual(planning_stages, ["analyze", "decompose", "delegate", "summarize"])
        self.assertNotIn("serana_graph_stage", tool_names)

    async def test_delegate_records_agent_lifecycle_and_standard_tool_results(self):
        state = {
            "user_input": "Research and compare a study plan",
            "original_user_input": "Research and compare a study plan",
            "goal_type": "research",
            "complexity": "high",
            "execution_mode": "delegated",
            "thinking_blocks": [],
            "tool_calls": [],
            "tool_results": [],
            "forge_sessions": [],
            "working_memory_entries": {},
            "working_memory_context": "",
            "subtasks": [
                {
                    "id": "subtask-ok",
                    "description": "Research useful study plan options",
                    "status": "pending",
                    "order": 1,
                },
                {
                    "id": "subtask-fail",
                    "description": "What should be verified before choosing the final plan?",
                    "status": "pending",
                    "order": 2,
                    "failures_before_success": 99,
                },
            ],
            "delegation_plan": {
                "execution_mode": "delegated",
                "parallel_forges": 2,
                "parallel_slots": 2,
            },
        }

        result = await delegate_node(state, FakeLLM())

        self.assertEqual(len(result["subtasks"]), 2)
        self.assertEqual(result["subtasks"][0]["assignment"]["coordinator"], "serana")
        self.assertEqual(result["subtasks"][0]["assignment"]["worker"], "forge")
        self.assertEqual(result["subtasks"][1]["status"], "failed")
        self.assertIsNotNone(result["delegation_fallback_summary"])

        lifecycle_calls = [
            tool_call for tool_call in result["tool_calls"]
            if tool_call["name"] == "serana_agent_lifecycle"
        ]
        self.assertGreaterEqual(len(lifecycle_calls), 4)
        self.assertIn("started", [tool_call["output"]["status"] for tool_call in lifecycle_calls])
        self.assertIn("failed", [tool_call["output"]["status"] for tool_call in lifecycle_calls])

        delegate_call = next(
            tool_call for tool_call in result["tool_calls"] if tool_call["name"] == "serana_delegate"
        )
        self.assertIn("tool_result", delegate_call["output"])
        self.assertEqual(delegate_call["output"]["tool_result"]["schema_version"], "serana.tool_result.v1")
        self.assertEqual(delegate_call["output"]["tool_result"]["tool_name"], "serana.delegate")
        self.assertIn("assignments", delegate_call["output"])

        tool_result_names = [tool_result["tool_name"] for tool_result in result["tool_results"]]
        self.assertIn("serana.forge_execute", tool_result_names)
        self.assertIn("serana.delegate", tool_result_names)

    async def test_serana_directly_retries_forge_subtask(self):
        state = {
            "user_input": "Research a reliable study routine",
            "original_user_input": "Research a reliable study routine",
            "goal_type": "research",
            "complexity": "high",
            "execution_mode": "delegated",
            "thinking_blocks": [],
            "tool_calls": [],
            "tool_results": [],
            "forge_sessions": [],
            "working_memory_entries": {},
            "working_memory_context": "",
            "subtasks": [
                {
                    "id": "subtask-retry",
                    "description": "Research a reliable study routine",
                    "status": "pending",
                    "order": 1,
                    "failures_before_success": 1,
                },
            ],
            "delegation_plan": {
                "execution_mode": "delegated",
                "parallel_forges": 1,
                "parallel_slots": 1,
            },
        }

        result = await delegate_node(state, FakeLLM())

        self.assertEqual(result["subtasks"][0]["status"], "completed")
        self.assertEqual(result["forge_sessions"][0]["attempts"], 2)
        self.assertEqual(result["subtasks"][0]["assignment"]["coordinator"], "serana")

    async def test_serana_synthesizes_user_facing_answer_for_complex_delegated_requests(self):
        llm = CountingLLM()
        agent = SeranaAgent(llm)

        result = await agent.execute("Research and build a weekly study plan")

        self.assertTrue(result["success"])
        self.assertEqual(result["execution_mode"], "delegated")
        self.assertEqual(result["goal_type"], "research")
        self.assertEqual(result["complexity"], "high")
        self.assertGreaterEqual(llm.call_count, 2)
        analyze_call = next(
            tool_call for tool_call in result["tool_calls"] if tool_call["name"] == "serana_analyze"
        )
        decompose_call = next(
            tool_call for tool_call in result["tool_calls"] if tool_call["name"] == "serana_decompose"
        )
        self.assertEqual(analyze_call["output"]["analysis_source"], "lightweight_route")
        self.assertEqual(decompose_call["output"]["decomposition_source"], "template")
        summarize_call = next(
            tool_call for tool_call in result["tool_calls"] if tool_call["name"] == "serana_summarize"
        )
        self.assertEqual(summarize_call["output"]["summary_source"], "delegated_result_synthesis")

    async def test_analyze_reuses_lightweight_delegated_route(self):
        llm = CountingLLM()
        state = {
            "user_input": "Research and build a weekly study plan",
            "original_user_input": "Research and build a weekly study plan",
            "thinking_blocks": [],
            "tool_calls": [],
            "conversation_route": {
                "route": "delegated",
                "goal_type": "research",
                "summary": "Build a weekly study plan",
                "complexity": "high",
                "reason": "Needs planning",
            },
        }

        result = await analyze_node(state, llm)

        self.assertEqual(llm.call_count, 0)
        self.assertEqual(result["goal_type"], "research")
        self.assertEqual(result["complexity"], "high")
        analyze_call = next(
            tool_call for tool_call in result["tool_calls"] if tool_call["name"] == "serana_analyze"
        )
        self.assertEqual(analyze_call["output"]["analysis_source"], "lightweight_route")

    async def test_decompose_reuses_lightweight_delegated_route(self):
        llm = CountingLLM()
        state = {
            "user_input": "Research and build a weekly study plan",
            "original_user_input": "Research and build a weekly study plan",
            "goal_type": "research",
            "complexity": "high",
            "thinking_blocks": [],
            "tool_calls": [],
            "working_memory_entries": {},
            "working_memory_context": "",
            "conversation_route": {
                "route": "delegated",
                "goal_type": "research",
                "summary": "Build a weekly study plan",
                "complexity": "high",
                "reason": "Needs planning",
            },
        }

        result = await decompose_node(state, llm)

        self.assertEqual(llm.call_count, 0)
        self.assertEqual(len(result["subtasks"]), 3)
        decompose_call = next(
            tool_call for tool_call in result["tool_calls"] if tool_call["name"] == "serana_decompose"
        )
        self.assertEqual(decompose_call["output"]["decomposition_source"], "template")

    async def test_summarize_synthesizes_user_facing_answer_for_delegated_results(self):
        llm = CountingLLM()
        state = {
            "user_input": "Research and build a weekly study plan",
            "original_user_input": "Research and build a weekly study plan",
            "execution_mode": "delegated",
            "thinking_blocks": [],
            "tool_calls": [],
            "working_memory_entries": {},
            "working_memory_context": "",
            "subtasks": [
                {
                    "description": "Clarify the research question and success criteria",
                    "status": "completed",
                },
                {
                    "description": "Gather and compare the most relevant findings",
                    "status": "completed",
                },
            ],
        }

        result = await summarize_node(state, llm)

        self.assertEqual(llm.call_count, 1)
        self.assertNotIn("主要步骤", result["final_response"])
        self.assertNotIn("待处理", result["final_response"])
        summarize_call = next(
            tool_call for tool_call in result["tool_calls"] if tool_call["name"] == "serana_summarize"
        )
        self.assertEqual(summarize_call["output"]["summary_source"], "delegated_result_synthesis")

    async def test_summarize_answers_planned_request_instead_of_exposing_pending_subtasks(self):
        llm = SimpleNamespace(
            ainvoke=AsyncMock(
                return_value=FakeResponse(
                    "上海适合一个人慢慢逛的地方，可以优先考虑上海博物馆、思南书局和西岸美术馆。"
                )
            )
        )
        state = {
            "user_input": "上海有什么好去处吗？适合一个人的",
            "original_user_input": "上海有什么好去处吗？适合一个人的",
            "execution_mode": "planned",
            "thinking_blocks": [],
            "tool_calls": [],
            "tool_results": [],
            "working_memory_entries": {},
            "working_memory_context": "",
            "subtasks": [
                {
                    "description": "筛选适合一个人游览的地点",
                    "status": "pending",
                },
                {
                    "description": "整理推荐清单",
                    "status": "pending",
                },
            ],
        }

        result = await summarize_node(state, llm)

        self.assertIn("上海博物馆", result["final_response"])
        self.assertNotIn("待处理", result["final_response"])
        self.assertNotIn("建议这样安排", result["final_response"])
        summarize_call = next(
            tool_call for tool_call in result["tool_calls"] if tool_call["name"] == "serana_summarize"
        )
        self.assertEqual(summarize_call["output"]["summary_source"], "planned_answer")

    async def test_summarize_rejects_internal_progress_report_as_final_answer(self):
        llm = SimpleNamespace(
            ainvoke=AsyncMock(
                return_value=FakeResponse(
                    "建议这样安排：\n"
                    "· 筛选地点（待处理）\n"
                    "· 整理路线（待处理）\n"
                    "可以从第一步开始推进，我会根据进度继续更新。"
                )
            )
        )
        state = {
            "user_input": "上海有什么好去处吗？适合一个人的",
            "original_user_input": "上海有什么好去处吗？适合一个人的",
            "execution_mode": "delegated",
            "thinking_blocks": [],
            "tool_calls": [],
            "tool_results": [],
            "working_memory_entries": {},
            "working_memory_context": "",
            "subtasks": [],
        }

        result = await summarize_node(state, llm)

        self.assertNotIn("待处理", result["final_response"])
        self.assertNotIn("继续推进", result["final_response"])
        self.assertIn("没有产出足够可靠的最终结果", result["final_response"])
        summarize_call = next(
            tool_call for tool_call in result["tool_calls"] if tool_call["name"] == "serana_summarize"
        )
        self.assertEqual(summarize_call["output"]["summary_source"], "execution_incomplete_fallback")

    async def test_lightweight_route_keeps_failed_tool_selection_trace_and_answers_directly(self):
        state = {
            "user_input": "Use my calendar tool to create an event",
            "original_user_input": "Use my calendar tool to create an event",
            "thinking_blocks": [],
            "tool_calls": [],
        }

        result = await try_lightweight_conversation(state, UnsupportedToolRouteLLM())

        self.assertIsNotNone(result)
        self.assertEqual(result["execution_mode"], "direct")
        self.assertEqual(result["conversation_route"]["route"], "direct_tool")
        selection_call = next(
            tool_call for tool_call in result["tool_calls"] if tool_call["name"] == "serana_tool_selection"
        )
        self.assertEqual(selection_call["status"], "failed")
        self.assertEqual(selection_call["output"]["status"], "rejected")
        self.assertEqual(selection_call["input"]["requested_tool_name"], "calendar.create_event")
        self.assertTrue(str(result.get("final_response") or "").strip())

    async def test_lightweight_route_can_use_browser_search(self):
        llm = BrowserRouteLLM()
        state = {
            "user_input": "上网查一下 Serana browser test",
            "original_user_input": "上网查一下 Serana browser test",
            "thinking_blocks": [],
            "tool_calls": [],
        }

        async def fake_search_web(query: str, max_results: int = 5):
            return {
                "query": query,
                "url": "https://www.bing.com/search?q=Serana+browser+test",
                "title": "Serana browser test - Search",
                "results": [{"title": "Serana browser test result"}],
                "content": "Serana browser test result\nA concise browser result.",
                "summary": "已搜索：Serana browser test，找到 1 条可见结果。",
            }

        original_get_tool_function = SkillManager.get_tool_function

        def patched_get_tool_function(self, skill_name: str, tool_name: str):
            if skill_name == "browser" and tool_name == "search_web":
                return fake_search_web
            return original_get_tool_function(self, skill_name, tool_name)

        with patch.object(SkillManager, "get_tool_function", patched_get_tool_function):
            result = await try_lightweight_conversation(state, llm)

        self.assertIsNotNone(result)
        self.assertEqual(result["execution_mode"], "direct")
        self.assertIn("我查到了浏览器结果：Serana browser test 的第一条结果可用。", result["final_response"])
        self.assertEqual(llm.call_count, 2)
        tool_names = [tool_call["name"] for tool_call in result["tool_calls"]]
        self.assertIn("conversation_route", tool_names)
        self.assertIn("serana_tool_selection", tool_names)
        self.assertIn("browser.search_web", tool_names)

    async def test_lightweight_route_can_use_browser_capture(self):
        state = {
            "user_input": "给当前网页截个图",
            "original_user_input": "给当前网页截个图",
            "thinking_blocks": [],
            "tool_calls": [],
        }

        async def fake_capture_page(full_page: bool = False):
            return {
                "url": "https://example.com/",
                "title": "Example Domain",
                "path": "D:/agent-serana/backend/skills_store/browser/screenshots/example.png",
                "artifact": {
                    "kind": "image",
                    "filename": "example.png",
                    "mime_type": "image/png",
                    "size_bytes": 123,
                    "download_url": "/api/v1/browser/screenshots/example.png",
                    "thumbnail_url": "/api/v1/browser/screenshots/example.png",
                },
                "artifact_url": "/api/v1/browser/screenshots/example.png",
                "mime_type": "image/png",
                "full_page": full_page,
                "summary": "已截取当前浏览器页面：example.png",
            }

        original_get_tool_function = SkillManager.get_tool_function

        def patched_get_tool_function(self, skill_name: str, tool_name: str):
            if skill_name == "browser" and tool_name == "capture_page":
                return fake_capture_page
            return original_get_tool_function(self, skill_name, tool_name)

        with patch.object(SkillManager, "get_tool_function", patched_get_tool_function):
            result = await try_lightweight_conversation(state, BrowserCaptureRouteLLM())

        self.assertIsNotNone(result)
        self.assertEqual(result["execution_mode"], "direct")
        self.assertIn("当前网页截图已经保存好了。", result["final_response"])
        capture_call = next(
            tool_call for tool_call in result["tool_calls"] if tool_call["name"] == "browser.capture_page"
        )
        self.assertTrue(capture_call["input"]["full_page"])
        self.assertIn("path", capture_call["output"])
        self.assertEqual(capture_call["output"]["artifact"]["kind"], "image")
        self.assertEqual(capture_call["output"]["tool_result"]["tool_name"], "browser.capture_page")
        self.assertEqual(capture_call["output"]["tool_result"]["artifact"]["kind"], "image")

    async def test_lightweight_route_can_use_browser_look(self):
        state = {
            "user_input": "看一下当前网页显示是否正常",
            "original_user_input": "看一下当前网页显示是否正常",
            "thinking_blocks": [],
            "tool_calls": [],
        }
        screenshot_dir = Path(__file__).resolve().parent / "skills_store" / "browser" / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = screenshot_dir / "look-test.png"
        screenshot_path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00"
            b"\x90wS\xde"
        )

        async def fake_look_page(full_page: bool = False):
            return {
                "url": "https://example.com/",
                "title": "Example Domain",
                "path": str(screenshot_path),
                "mime_type": "image/png",
                "full_page": full_page,
                "dimensions": {"width": 1280, "height": 900},
                "model_observation": {
                    "kind": "browser_visual_snapshot",
                    "image_path": str(screenshot_path),
                    "mime_type": "image/png",
                    "dimensions": {"width": 1280, "height": 900},
                    "runtime_only": True,
                },
                "summary": "已观察当前浏览器页面的视觉快照：look.png",
            }

        original_get_tool_function = SkillManager.get_tool_function

        def patched_get_tool_function(self, skill_name: str, tool_name: str):
            if skill_name == "browser" and tool_name == "look_page":
                return fake_look_page
            return original_get_tool_function(self, skill_name, tool_name)

        llm = BrowserLookRouteLLM()
        with patch.object(SkillManager, "get_tool_function", patched_get_tool_function):
            result = await try_lightweight_conversation(state, llm)

        self.assertIsNotNone(result)
        self.assertEqual(result["execution_mode"], "direct")
        self.assertIn("当前网页视觉快照看起来正常。", result["final_response"])
        look_call = next(
            tool_call for tool_call in result["tool_calls"] if tool_call["name"] == "browser.look_page"
        )
        self.assertFalse(look_call["input"]["full_page"])
        self.assertNotIn("artifact", look_call["output"])
        self.assertEqual(look_call["output"]["model_observation"]["kind"], "browser_visual_snapshot")
        self.assertIsInstance(llm.summary_content, list)
        image_blocks = [
            block for block in llm.summary_content if isinstance(block, dict) and block.get("type") == "image_url"
        ]
        self.assertEqual(len(image_blocks), 1)
        self.assertTrue(image_blocks[0]["image_url"]["url"].startswith("data:image/png;base64,"))

    async def test_lightweight_route_can_create_html_preview(self):
        state = {
            "user_input": "用浏览器展示冒泡排序的演示",
            "original_user_input": "用浏览器展示冒泡排序的演示",
            "thinking_blocks": [],
            "tool_calls": [],
        }
        captured = {}

        async def fake_create_html_preview(title: str, html: str, cache_key: str = ""):
            captured["title"] = title
            captured["html"] = html
            captured["cache_key"] = cache_key
            return {
                "title": title,
                "path": "D:/agent-serana/backend/skills_store/browser/previews/bubble.html",
                "artifact": {
                    "kind": "html_preview",
                    "filename": "bubble.html",
                    "title": title,
                    "mime_type": "text/html",
                    "size_bytes": len(html.encode("utf-8")),
                    "download_url": "/api/v1/browser/previews/bubble.html",
                },
                "artifact_url": "/api/v1/browser/previews/bubble.html",
                "mime_type": "text/html",
                "summary": "已生成可打开的演示页面：bubble.html",
            }

        original_get_tool_function = SkillManager.get_tool_function

        def patched_get_tool_function(self, skill_name: str, tool_name: str):
            if skill_name == "browser" and tool_name == "create_html_preview":
                return fake_create_html_preview
            return original_get_tool_function(self, skill_name, tool_name)

        with patch.object(SkillManager, "get_tool_function", patched_get_tool_function):
            result = await try_lightweight_conversation(state, BrowserPreviewRouteLLM())

        self.assertIsNotNone(result)
        self.assertEqual(result["execution_mode"], "direct")
        self.assertIn("我已经生成了一个可打开的冒泡排序演示页面。", result["final_response"])
        preview_call = next(
            tool_call for tool_call in result["tool_calls"] if tool_call["name"] == "browser.create_html_preview"
        )
        self.assertEqual(preview_call["output"]["artifact"]["kind"], "html_preview")
        self.assertEqual(preview_call["output"]["artifact"]["download_url"], "/api/v1/browser/previews/bubble.html")
        self.assertIn("<script>", captured["html"])
        self.assertNotIn("offline demo script here", captured["html"].lower())

    async def test_html_preview_cache_key_reuses_topic_across_followup_wording(self):
        prompts = [
            "生成快速排序网页动画",
            "之前生成的快速排序动画",
            "上次的快速排序演示动画",
            "以前的快速排序网页",
        ]
        keys = {_html_preview_request_cache_key(prompt) for prompt in prompts}

        self.assertEqual(len(keys), 1)
        for prompt in prompts:
            self.assertTrue(_is_html_preview_request(prompt))

    async def test_skill_manager_shutdown_closes_browser_skill(self):
        manager = SkillManager()
        called = {"closed": False}

        async def fake_close_browser():
            called["closed"] = True
            return {"closed": True}

        original_get_tool_function = SkillManager.get_tool_function

        def patched_get_tool_function(self, skill_name: str, tool_name: str):
            if skill_name == "browser" and tool_name == "close_browser":
                return fake_close_browser
            return original_get_tool_function(self, skill_name, tool_name)

        with patch.object(SkillManager, "get_tool_function", patched_get_tool_function):
            await manager.shutdown()

        self.assertTrue(called["closed"])

    async def test_serana_goal_keeps_planning_requests_out_of_lightweight_time_route(self):
        llm = FakeLLM()
        agent = SeranaAgent(llm)

        result = await agent.execute_goal("Plan a relaxed travel day with buffer time")

        self.assertTrue(result["success"])
        self.assertEqual(result["execution_mode"], "planned")
        tool_names = [tool_call["name"] for tool_call in result["tool_calls"]]
        self.assertIn("serana_loop_transition", tool_names)
        self.assertIn("serana_decompose", tool_names)
        self.assertIn("serana_summarize", tool_names)
        self.assertNotIn("serana_delegate", tool_names)
        self.assertNotIn("forge_execute", tool_names)
        self.assertNotIn("time_manager.get_current_time", tool_names)
        self.assertNotIn("time_manager.get_day_info", tool_names)


if __name__ == "__main__":
    unittest.main()

