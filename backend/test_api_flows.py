import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.agents.aide import AideAgent
from app.agents.base import AgentManager
from app.agents.serana.context import build_contextual_request
from app.agents.forge import ForgeAgent
from app.agents.serana import SeranaAgent
from app.api.skills import get_marketplace_client
from app.core.database import AsyncSessionLocal
from app.core.init_db import create_default_user, init_db
from app.main import app
from app.memory import MemoryInjector, MemoryService, ProfileFactsManager, ResidentMemoryManager, WorkingMemoryManager
from app.skills import SkillManager
from app.skills.models import MarketplaceSearchResponse, MarketplaceSkillSummary


class FakeResponse:
    def __init__(self, content: str):
        self.content = content


class FakeLLM:
    async def ainvoke(self, messages):
        prompt = messages[-1].content
        system_prompt = messages[0].content
        if "You triage a personal butler request." in system_prompt:
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

        if "You triage a personal butler request." in system_prompt:
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
        if "You triage a personal butler request." in system_prompt:
            raise ValueError("Force regex fallback for natural working-memory phrases")
        return await super().ainvoke(messages)


class FallbackOnlyGateway:
    def get_llm(self, user_config=None, use_backend_default=False):
        return FallbackOnlyLLM()


class InstructionAwareLLM(CleanFakeLLM):
    async def ainvoke(self, messages):
        prompt = messages[-1].content
        system_prompt = messages[0].content
        if "You triage a personal butler request." in system_prompt and "Installed instruction skills:" in prompt:
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
                    canonical_url="https://clawhub.ai/steipete/weather",
                    download_url="https://clawhub.ai/api/v1/download?slug=weather",
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
            "owner_handle": "steipete",
            "owner_display_name": "Peter",
            "latest_version": "1.0.0",
            "canonical_url": "https://clawhub.ai/steipete/weather",
            "download_url": "https://clawhub.ai/api/v1/download?slug=weather",
            "skill_md_preview": "# Weather",
            "installed": manager.get_skill("weather") is not None,
            "local_skill_name": "weather" if manager.get_skill("weather") is not None else None,
        }

    def install_skill(self, slug: str, manager: SkillManager, version=None, tag=None):
        return manager.get_skill("weather")


class ApiFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        async with AsyncSessionLocal() as session:
            user = await create_default_user(session)
            self.default_user_id = str(user.id)
        self.transport = httpx.ASGITransport(app=app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://test")

    async def asyncTearDown(self):
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
        self.assertNotIn("aide_execute", tool_names)
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
        self.assertIn("conversation_route", tool_names)
        self.assertIn("time_manager.get_current_time", tool_names)
        self.assertNotIn("serana_summarize", tool_names)
        self.assertIn("当前时间是", payload["assistant_message"]["content"])

    @patch("app.api.chat.get_llm_gateway", return_value=FakeGateway())
    async def test_chat_uses_calculator_for_direct_math_request(self, _gateway):
        response = await self.client.post(
            "/api/v1/chat/message",
            json={"content": "37*18 等于几？", "stream": False},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["execution_mode"], "direct")
        tool_names = [tool_call["name"] for tool_call in payload["assistant_message"]["tool_calls"]]
        self.assertIn("conversation_route", tool_names)
        self.assertIn("calculator.multiply", tool_names)
        self.assertIn("37 * 18 = 666", payload["assistant_message"]["content"])

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
        self.assertIn("conversation_route", tool_names)
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
        self.assertIn("conversation_route", tool_names)
        self.assertIn("weather.get_current_weather", tool_names)
        self.assertIn("北京", payload["assistant_message"]["content"])
        self.assertIn("24", payload["assistant_message"]["content"])

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
            self.assertIn("稳定用户信息：偏好", snapshot)
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
        self.assertIsNotNone(consolidation_record)
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
        self.assertGreaterEqual(payload["delegation_plan"]["parallel_aides"], 2)
        self.assertGreaterEqual(payload["delegation_plan"]["parallel_forges"], 2)
        tool_names = [tool_call["name"] for tool_call in payload["assistant_message"]["tool_calls"]]
        self.assertIn("aide_execute", tool_names)
        self.assertIn("forge_execute", tool_names)
        self.assertIn("serana_delegate", tool_names)
        self.assertIn("working_memory_update", tool_names)

        timeline_response = await self.client.get(
            "/api/v1/audit/timeline",
            params={"entity_type": "chat_session", "entity_id": payload["session_id"]},
        )
        self.assertEqual(timeline_response.status_code, 200)
        timeline = timeline_response.json()
        self.assertIn("analysis", timeline["insights"]["task_types"])
        self.assertIn("insight_lens", timeline["insights"]["tool_names"])
        self.assertIn("delegated", timeline["insights"]["lightweight_routes"])
        self.assertIn("graph", timeline["insights"]["loop_transition_targets"])
        self.assertEqual(
            timeline["insights"]["loop_stages"],
            ["graph_complete", "graph_start", "lightweight_complete", "lightweight_start"],
        )
        self.assertEqual(
            timeline["insights"]["graph_stages"],
            ["analyze", "decompose", "delegate", "summarize"],
        )
        self.assertGreaterEqual(max(timeline["insights"]["parallel_forges"]), 2)

        debug_summary_response = await self.client.get(
            "/api/v1/audit/debug-summary",
            params={"entity_type": "chat_session", "entity_id": payload["session_id"]},
        )
        self.assertEqual(debug_summary_response.status_code, 200)
        debug_summary = debug_summary_response.json()
        self.assertIn("analysis", debug_summary["task_types"])
        self.assertIn("insight_lens", debug_summary["tool_names"])
        self.assertIn("aide_execute", debug_summary["event_counts"])
        self.assertIn("delegated", debug_summary["lightweight_routes"])
        self.assertIn("graph", debug_summary["loop_transition_targets"])
        self.assertEqual(
            debug_summary["loop_stages"],
            ["graph_complete", "graph_start", "lightweight_complete", "lightweight_start"],
        )
        self.assertEqual(
            debug_summary["graph_stages"],
            ["analyze", "decompose", "delegate", "summarize"],
        )

        debug_response = await self.client.get(f"/api/v1/chat/sessions/{payload['session_id']}/debug")
        self.assertEqual(debug_response.status_code, 200)
        debug_payload = debug_response.json()
        self.assertEqual(debug_payload["session"]["id"], payload["session_id"])
        self.assertEqual(len(debug_payload["messages"]), 2)
        self.assertEqual(debug_payload["audit_timeline"]["entity_type"], "chat_session")
        self.assertIn("analysis", debug_payload["audit_summary"]["task_types"])
        self.assertIn("insight_lens", debug_payload["audit_summary"]["tool_names"])
        self.assertIn("delegated", debug_payload["audit_summary"]["lightweight_routes"])
        self.assertIn("graph", debug_payload["audit_summary"]["loop_transition_targets"])

    @patch("app.api.chat.get_llm_gateway", return_value=InstructionAwareGateway())
    async def test_chat_applies_instruction_skill_context_to_prompt(self, _gateway):
        fake_instruction_skill = SimpleNamespace(
            name="travel_helper",
            description="Help with calm, low-stress travel planning.",
            instruction_content="# Travel Helper\nPrefer calm pacing, buffer time, and low-stress suggestions.",
            manifest=SimpleNamespace(source_url="https://clawhub.ai/demo/travel-helper"),
        )

        with patch.object(SkillManager, "get_enabled_instruction_skills", return_value=[fake_instruction_skill]):
            response = await self.client.post(
                "/api/v1/chat/message",
                json={"content": "Quick question: suggest a calm travel day.", "stream": False},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["assistant_message"]["content"], "Applied imported skill guidance.")
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
        self.assertTrue(payload["results"][0]["installed"])
        self.assertEqual(payload["results"][0]["local_skill_name"], "weather")

    async def test_marketplace_install_returns_local_skill_package(self):
        app.dependency_overrides[get_marketplace_client] = lambda: FakeMarketplaceClient()

        response = await self.client.post(
            "/api/v1/skills/marketplace/install",
            json={"slug": "weather"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["name"], "weather")
        self.assertEqual(payload["manifest"]["registry_slug"], "weather")

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
        self.assertIn("aide_execute", event_types)
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
            manifest=SimpleNamespace(source_url="https://clawhub.ai/demo/travel-helper"),
        )

        with patch.object(SkillManager, "get_enabled_instruction_skills", return_value=[fake_instruction_skill]):
            response = await self.client.post(
                "/api/v1/goals",
                json={"description": "Plan a relaxed travel day with buffer time"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["planning_summary"], "Applied imported skill guidance.")
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
        self.assertIn("aide_execute", audit_event_types)
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
        self.assertIn("analysis", timeline["insights"]["task_types"])
        self.assertIn("insight_lens", timeline["insights"]["tool_names"])
        self.assertIn("graph", timeline["insights"]["loop_transition_targets"])
        self.assertEqual(
            timeline["insights"]["loop_stages"],
            ["graph_complete", "graph_start", "lightweight_complete", "lightweight_start"],
        )
        self.assertEqual(
            timeline["insights"]["graph_stages"],
            ["analyze", "decompose", "delegate", "summarize"],
        )
        self.assertGreaterEqual(max(timeline["insights"]["parallel_forges"]), 2)

        debug_summary_response = await self.client.get(
            "/api/v1/audit/debug-summary",
            params={"entity_type": "goal", "entity_id": goal_id},
        )
        self.assertEqual(debug_summary_response.status_code, 200)
        debug_summary = debug_summary_response.json()
        self.assertIn("analysis", debug_summary["task_types"])
        self.assertIn("insight_lens", debug_summary["tool_names"])
        self.assertIn("forge_execute", debug_summary["event_counts"])
        self.assertIn("graph", debug_summary["loop_transition_targets"])
        self.assertEqual(
            debug_summary["loop_stages"],
            ["graph_complete", "graph_start", "lightweight_complete", "lightweight_start"],
        )
        self.assertEqual(
            debug_summary["graph_stages"],
            ["analyze", "decompose", "delegate", "summarize"],
        )

        debug_response = await self.client.get(f"/api/v1/goals/{goal_id}/debug")
        self.assertEqual(debug_response.status_code, 200)
        debug_payload = debug_response.json()
        self.assertEqual(debug_payload["goal"]["id"], goal_id)
        self.assertEqual(debug_payload["audit_timeline"]["entity_type"], "goal")
        self.assertIn("analysis", debug_payload["audit_summary"]["task_types"])
        self.assertIn("insight_lens", debug_payload["audit_summary"]["tool_names"])
        self.assertIn("graph", debug_payload["audit_summary"]["loop_transition_targets"])

    @patch("app.api.goals.get_llm_gateway", return_value=FakeGateway())
    async def test_simple_goal_stays_direct(self, _gateway):
        response = await self.client.post(
            "/api/v1/goals",
            json={"description": "Quick question: what should I study tonight?"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["subtasks"]), 1)
        self.assertTrue(payload["subtasks"][0]["description"].startswith("Handle directly with Serana:"))
        audit_event_types = [record["event_type"] for record in payload["audit_records"]]
        self.assertIn("conversation_route", audit_event_types)
        self.assertIn("serana_direct_reply", audit_event_types)
        self.assertNotIn("aide_execute", audit_event_types)
        self.assertNotIn("forge_execute", audit_event_types)

    async def test_aide_and_forge_execute_cleanly(self):
        llm = FakeLLM()
        forge = ForgeAgent(llm)
        forge_result = await forge.execute({"description": "Run a concrete task"})
        self.assertTrue(forge_result["success"])
        self.assertEqual(forge_result["result"]["status"], "completed")
        self.assertGreaterEqual(len(forge.state.thinking_blocks), 2)
        self.assertEqual(forge_result["result"]["strategy"], "general_execution")
        self.assertEqual(forge_result["result"]["tool_name"], "task_runner")

        aide = AideAgent(llm)
        aide_result = await aide.execute({"description": "Delegate a concrete task"})
        self.assertTrue(aide_result["success"])
        self.assertEqual(aide_result["result"]["status"], "completed")
        self.assertTrue(aide_result["result"]["worker_assigned"])
        self.assertEqual(aide_result["result"]["task_type"], "task")
        self.assertEqual(aide_result["result"]["batches_planned"], 1)

    async def test_agent_manager_reuses_idle_aide_and_forge(self):
        llm = FakeLLM()
        agent_manager = AgentManager()
        agent_manager.initialize(llm)

        first_aide = await agent_manager.get_agent("aide")
        first_aide_result = await first_aide.execute({"description": "Coordinate task A"})
        self.assertTrue(first_aide_result["success"])

        reused_aide = await agent_manager.get_agent("aide")
        self.assertIs(first_aide, reused_aide)
        reused_aide_result = await reused_aide.execute({"description": "Coordinate task B"})
        self.assertTrue(reused_aide_result["success"])
        self.assertEqual(reused_aide.state.status, "idle")
        self.assertEqual(reused_aide.state.current_task, None)

        first_forge = await agent_manager.get_agent("forge")
        first_forge_result = await first_forge.execute({"description": "Execute task A"})
        self.assertTrue(first_forge_result["success"])

        reused_forge = await agent_manager.get_agent("forge")
        self.assertIs(first_forge, reused_forge)
        reused_forge_result = await reused_forge.execute({"description": "Execute task B"})
        self.assertTrue(reused_forge_result["success"])
        self.assertEqual(reused_forge.state.status, "idle")
        self.assertEqual(reused_forge.state.current_task, None)
        self.assertEqual(agent_manager.agent_counts["aide"], 1)
        self.assertEqual(agent_manager.agent_counts["forge"], 1)

    async def test_aide_classifies_batches_and_retries(self):
        llm = FakeLLM()
        aide = AideAgent(llm)
        task = {
            "description": "Research study resources",
            "task_type": "research",
            "items": ["math", "physics", "chemistry"],
            "batch_size": 2,
            "max_retries": 1,
            "failures_before_success": 1,
        }

        aide_result = await aide.execute(task)

        self.assertTrue(aide_result["success"])
        result = aide_result["result"]
        self.assertEqual(result["task_type"], "research")
        self.assertEqual(result["retry_limit"], 1)
        self.assertEqual(result["batches_planned"], 2)
        self.assertEqual(len(result["batch_results"]), 2)
        self.assertTrue(all(batch["status"] == "completed" for batch in result["batch_results"]))
        self.assertTrue(all(batch["attempts"] == 2 for batch in result["batch_results"]))
        self.assertGreaterEqual(result["parallel_forges"], 2)

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
        self.assertNotIn("aide_execute", tool_names)
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
        self.assertIn("Analyzing", events[0]["content"])

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
        self.assertGreaterEqual(result["delegation_plan"]["parallel_aides"], 2)
        self.assertGreaterEqual(result["delegation_plan"]["parallel_forges"], 2)
        delegate_call = next(
            tool_call for tool_call in result["tool_calls"] if tool_call["name"] == "serana_delegate"
        )
        self.assertGreaterEqual(delegate_call["output"]["parallel_slots"], 2)
        self.assertGreaterEqual(delegate_call["output"]["actual_aide_agents"], 2)
        self.assertGreaterEqual(delegate_call["output"]["actual_forge_agents"], 2)
        tool_names = [tool_call["name"] for tool_call in result["tool_calls"]]
        self.assertIn("serana_loop_transition", tool_names)
        graph_stages = [
            tool_call["output"]["stage"]
            for tool_call in result["tool_calls"]
            if tool_call["name"] == "serana_graph_stage"
        ]
        self.assertEqual(graph_stages, ["analyze", "decompose", "delegate", "summarize"])

    async def test_serana_goal_keeps_planning_requests_out_of_lightweight_time_route(self):
        llm = FakeLLM()
        agent = SeranaAgent(llm)

        result = await agent.execute_goal("Plan a relaxed travel day with buffer time")

        self.assertTrue(result["success"])
        self.assertEqual(result["execution_mode"], "delegated")
        tool_names = [tool_call["name"] for tool_call in result["tool_calls"]]
        self.assertIn("serana_loop_transition", tool_names)
        self.assertIn("serana_delegate", tool_names)
        self.assertNotIn("time_manager.get_current_time", tool_names)
        self.assertNotIn("time_manager.get_day_info", tool_names)


if __name__ == "__main__":
    unittest.main()
