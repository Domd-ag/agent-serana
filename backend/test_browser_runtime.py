import json
import unittest
from unittest.mock import patch

from app.agents.serana.nodes import _execute_browser_session_flow
from app.skills import SkillManager
from skills_store import browser


class FakeResponse:
    def __init__(self, content: str):
        self.content = content


class RepeatingObserveLLM:
    def __init__(self):
        self.call_count = 0

    async def ainvoke(self, messages):
        self.call_count += 1
        system_prompt = str(messages[0].content)
        if "Decide the next browser step for Serana." in system_prompt:
            return FakeResponse(json.dumps({"action": "observe_page", "arguments": {"max_chars": 5000}}))
        return FakeResponse("网页内容已经整理好了。")


class BrowserRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await browser.close_browser()

    async def test_open_page_blocks_local_network_addresses(self):
        result = await browser.open_page("http://127.0.0.1:8000/private")

        self.assertIn("error", result)
        self.assertEqual(result["browser_state"]["status"], "blocked")
        self.assertFalse(result["browser_state"]["page_open"])

    async def test_observe_page_returns_recoverable_missing_page_state(self):
        await browser.close_browser()

        result = await browser.observe_page()

        self.assertIn("error", result)
        self.assertTrue(result["recoverable"])
        self.assertEqual(result["browser_state"]["status"], "missing_page")
        self.assertEqual(result["browser_state"]["next_actions"], ["open_page"])

    async def test_browser_session_stops_after_failed_open_without_observing(self):
        observe_calls = 0

        async def failed_open(url: str):
            return {
                "url": url,
                "error": "HTTP 500",
                "summary": "这个网页暂时无法打开（HTTP 500）。",
                "recoverable": True,
                "browser_state": {"status": "failed", "page_open": False},
            }

        async def observe_page(max_chars: int = 5000):
            nonlocal observe_calls
            observe_calls += 1
            return {"content": "should not run"}

        manager = SkillManager()
        original_get_tool_function = SkillManager.get_tool_function

        def patched_get_tool_function(self, skill_name: str, tool_name: str):
            if skill_name == "browser" and tool_name == "observe_page":
                return observe_page
            return original_get_tool_function(self, skill_name, tool_name)

        state = {"tool_calls": [], "tool_results": [], "thinking_blocks": []}
        llm = RepeatingObserveLLM()
        with patch.object(SkillManager, "get_tool_function", patched_get_tool_function):
            result = await _execute_browser_session_flow(
                state,
                llm,
                user_input="打开测试页面",
                tool_intent={
                    "full_name": "browser.open_page",
                    "skill_name": "browser",
                    "tool_name": "open_page",
                    "arguments": {"url": "https://example.com"},
                    "callable": failed_open,
                },
            )

        self.assertEqual(observe_calls, 0)
        self.assertEqual(llm.call_count, 0)
        self.assertEqual(result["tool_results"][0]["schema_version"], "serana.tool_result.v1")
        self.assertEqual(result["tool_results"][0]["status"], "failed")
        self.assertNotIn("https://example.com", result["final_response"])

    async def test_browser_session_stops_repeating_the_same_observation(self):
        observe_calls = 0

        async def open_page(url: str):
            return {
                "url": url,
                "title": "Example",
                "content": "Useful public content.",
                "summary": "已打开网页：Example",
                "browser_state": {"status": "opened", "page_open": True},
            }

        async def observe_page(max_chars: int = 5000):
            nonlocal observe_calls
            observe_calls += 1
            return {
                "url": "https://example.com",
                "title": "Example",
                "content": "Useful public content.",
                "summary": "已查看网页内容：Example",
                "browser_state": {"status": "observed", "page_open": True},
            }

        original_get_tool_function = SkillManager.get_tool_function

        def patched_get_tool_function(self, skill_name: str, tool_name: str):
            if skill_name == "browser" and tool_name == "observe_page":
                return observe_page
            return original_get_tool_function(self, skill_name, tool_name)

        state = {"tool_calls": [], "tool_results": [], "thinking_blocks": []}
        llm = RepeatingObserveLLM()
        with patch.object(SkillManager, "get_tool_function", patched_get_tool_function):
            result = await _execute_browser_session_flow(
                state,
                llm,
                user_input="看看这个网页讲了什么",
                tool_intent={
                    "full_name": "browser.open_page",
                    "skill_name": "browser",
                    "tool_name": "open_page",
                    "arguments": {"url": "https://example.com"},
                    "callable": open_page,
                },
            )

        self.assertEqual(observe_calls, 1)
        self.assertEqual(llm.call_count, 2)
        self.assertEqual(result["final_response"], "🌙 网页内容已经整理好了。")
        self.assertEqual(len(result["tool_results"]), 2)


if __name__ == "__main__":
    unittest.main()
