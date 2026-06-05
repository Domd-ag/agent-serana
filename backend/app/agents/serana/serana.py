from typing import Any, AsyncGenerator, Dict, Optional
import uuid

from langchain_core.language_models.chat_models import BaseChatModel

from app.approvals import get_approval_manager, get_approval_reviewer, get_policy_gate
from app.agents.base import AgentState
from app.agents.serana.graph import create_initial_state
from app.agents.serana.loop import execute_planning_flow, execute_serana_loop, stream_serana_loop
from app.core.logger import get_logger


request_logger = get_logger("app.request.serana")


class SeranaAgent:
    _instance: Optional["SeranaAgent"] = None

    def __new__(cls, llm: BaseChatModel):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, llm: BaseChatModel):
        if not hasattr(self, "agent_id"):
            self.agent_id = "serana-001"
            self.state = AgentState(
                agent_id=self.agent_id,
                agent_name="Serana",
                status="idle",
            )
        self.llm = llm

    def _build_initial_state(
        self,
        user_input: str,
        session_id: str,
        *,
        memory_context: str = "",
        recent_history_context: str = "",
        resident_memory_context: str = "",
        working_memory_context: str = "",
        interactive_approval: bool = False,
    ) -> Dict[str, Any]:
        return create_initial_state(
            user_input,
            session_id,
            self.llm,
            memory_context=memory_context,
            recent_history_context=recent_history_context,
            resident_memory_context=resident_memory_context,
            working_memory_context=working_memory_context,
            approval_runtime={
                "interactive": interactive_approval,
                "timeout_seconds": 300.0,
                "policy_gate": get_policy_gate(),
                "reviewer": get_approval_reviewer(),
                "manager": get_approval_manager(),
            },
        )

    def _format_success_result(
        self,
        user_input: str,
        result: Dict[str, Any],
        *,
        default_execution_mode: str,
    ) -> Dict[str, Any]:
        return {
            "success": True,
            "goal": user_input,
            "goal_type": result.get("goal_type"),
            "complexity": result.get("complexity"),
            "execution_mode": result.get("execution_mode", default_execution_mode),
            "delegation_plan": result.get("delegation_plan", {}),
            "subtasks": result.get("subtasks", []),
            "forge_sessions": result.get("forge_sessions", []),
            "thinking_blocks": result.get("thinking_blocks", []),
            "tool_calls": result.get("tool_calls", []),
            "summary": result.get("final_response", "Completed."),
        }

    def _format_failure_result(self, user_input: str, exc: Exception) -> Dict[str, Any]:
        return {
            "success": False,
            "goal": user_input,
            "goal_type": None,
            "complexity": None,
            "execution_mode": "delegated",
            "delegation_plan": {},
            "subtasks": [],
            "forge_sessions": [],
            "thinking_blocks": [],
            "tool_calls": [],
            "summary": f"Execution failed: {str(exc)}",
        }

    def _should_accept_lightweight_goal_result(self, result: Optional[Dict[str, Any]]) -> bool:
        if result is None:
            return False
        if str(result.get("execution_mode") or "direct") != "direct":
            return False

        user_input = str(result.get("original_user_input") or result.get("user_input") or "").lower()
        if any(
            keyword in user_input
            for keyword in (
                "plan",
                "research",
                "build",
                "implement",
                "develop",
                "analyze",
                "review",
                "规划",
                "计划",
                "研究",
                "开发",
                "实现",
                "分析",
            )
        ):
            return False

        route_info = dict(result.get("conversation_route") or {})
        route = str(route_info.get("route") or "").strip().lower()
        if route == "direct_reply":
            return (
                str(result.get("goal_type") or route_info.get("goal_type") or "") in {"question", "weather_inquiry", "task"}
                and str(result.get("complexity") or route_info.get("complexity") or "simple") == "simple"
            )

        if route == "direct_tool":
            tool_names = [
                str(tool_call.get("name") or "")
                for tool_call in list(result.get("tool_calls", []))
                if isinstance(tool_call, dict)
            ]
            safe_tool_prefixes = (
                "calculator.",
                "time_manager.",
                "weather.",
                "memory_manager.",
            )
            return any(
                tool_name.startswith(safe_tool_prefixes)
                for tool_name in tool_names
            )

        return str(result.get("goal_type") or "") in {"question", "weather_inquiry"} and str(
            result.get("complexity") or "simple"
        ) == "simple"

    async def execute(
        self,
        user_input: str,
        session_id: Optional[str] = None,
        memory_context: str = "",
        recent_history_context: str = "",
        resident_memory_context: str = "",
        working_memory_context: str = "",
    ) -> Dict[str, Any]:
        request_logger.info("Starting Serana conversation execution: %s", user_input)

        if session_id is None:
            session_id = str(uuid.uuid4())

        self.state.status = "working"
        self.state.current_task = user_input

        initial_state = self._build_initial_state(
            user_input,
            session_id,
            memory_context=memory_context,
            recent_history_context=recent_history_context,
            resident_memory_context=resident_memory_context,
            working_memory_context=working_memory_context,
            interactive_approval=False,
        )

        try:
            result, default_execution_mode = await execute_serana_loop(
                initial_state,
                self.llm,
                self._execute_planning,
            )
            return self._format_success_result(
                user_input,
                result,
                default_execution_mode=default_execution_mode,
            )

        except Exception as exc:
            request_logger.exception("Error executing Serana conversation: %s", user_input)
            return self._format_failure_result(user_input, exc)
        finally:
            self.state.status = "idle"
            self.state.current_task = None

    async def execute_goal(
        self,
        goal: str,
        session_id: Optional[str] = None,
        memory_context: str = "",
        recent_history_context: str = "",
        resident_memory_context: str = "",
        working_memory_context: str = "",
    ) -> Dict[str, Any]:
        request_logger.info("Starting Serana goal execution: %s", goal)

        if session_id is None:
            session_id = str(uuid.uuid4())

        self.state.status = "working"
        self.state.current_task = goal

        initial_state = self._build_initial_state(
            goal,
            session_id,
            memory_context=memory_context,
            recent_history_context=recent_history_context,
            resident_memory_context=resident_memory_context,
            working_memory_context=working_memory_context,
            interactive_approval=False,
        )

        try:
            result, default_execution_mode = await execute_serana_loop(
                initial_state,
                self.llm,
                self._execute_planning,
                lightweight_acceptor=self._should_accept_lightweight_goal_result,
            )
            return self._format_success_result(
                goal,
                result,
                default_execution_mode=default_execution_mode,
            )
        except Exception as exc:
            request_logger.exception("Error executing Serana goal: %s", goal)
            return self._format_failure_result(goal, exc)
        finally:
            self.state.status = "idle"
            self.state.current_task = None

    async def execute_stream(
        self,
        goal: str,
        session_id: Optional[str] = None,
        memory_context: str = "",
        recent_history_context: str = "",
        resident_memory_context: str = "",
        working_memory_context: str = "",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        request_logger.info("Starting Serana stream execution: %s", goal)

        if session_id is None:
            session_id = str(uuid.uuid4())

        self.state.status = "working"
        self.state.current_task = goal

        initial_state = self._build_initial_state(
            goal,
            session_id,
            memory_context=memory_context,
            recent_history_context=recent_history_context,
            resident_memory_context=resident_memory_context,
            working_memory_context=working_memory_context,
            interactive_approval=True,
        )

        try:
            async for event in stream_serana_loop(
                initial_state,
                self.llm,
                self._execute_planning,
                session_id=session_id,
            ):
                yield event

        except Exception as exc:
            request_logger.exception("Error in Serana stream execution: %s", goal)
            yield {
                "type": "error",
                "content": str(exc),
            }
        finally:
            self.state.status = "idle"
            self.state.current_task = None

    async def _execute_planning(self, initial_state: Dict[str, Any]) -> Dict[str, Any]:
        return await execute_planning_flow(initial_state, self.llm)

    def get_status(self) -> AgentState:
        return self.state
