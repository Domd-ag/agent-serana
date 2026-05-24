from typing import Any, AsyncGenerator, Dict, Optional
import uuid

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.base import AgentState
from app.agents.serana.graph import create_initial_state, create_serana_graph
from app.agents.serana.loop import execute_serana_loop, stream_serana_loop
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
        self.graph = create_serana_graph(llm)

    def _build_initial_state(
        self,
        user_input: str,
        session_id: str,
        *,
        memory_context: str = "",
        resident_memory_context: str = "",
        working_memory_context: str = "",
    ) -> Dict[str, Any]:
        return create_initial_state(
            user_input,
            session_id,
            self.llm,
            memory_context=memory_context,
            resident_memory_context=resident_memory_context,
            working_memory_context=working_memory_context,
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
            "aide_sessions": result.get("aide_sessions", []),
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
            "aide_sessions": [],
            "forge_sessions": [],
            "thinking_blocks": [],
            "tool_calls": [],
            "summary": f"Execution failed: {str(exc)}",
        }

    def _should_accept_lightweight_goal_result(self, result: Optional[Dict[str, Any]]) -> bool:
        if result is None:
            return False
        return (
            str(result.get("execution_mode") or "direct") == "direct"
            and str(result.get("goal_type") or "") in {"question", "weather_inquiry"}
            and str(result.get("complexity") or "simple") == "simple"
        )

    async def execute(
        self,
        user_input: str,
        session_id: Optional[str] = None,
        memory_context: str = "",
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
            resident_memory_context=resident_memory_context,
            working_memory_context=working_memory_context,
        )

        try:
            result, default_execution_mode = await execute_serana_loop(
                initial_state,
                self.llm,
                self._execute_graph,
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
            resident_memory_context=resident_memory_context,
            working_memory_context=working_memory_context,
        )

        try:
            result, default_execution_mode = await execute_serana_loop(
                initial_state,
                self.llm,
                self._execute_graph,
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
            resident_memory_context=resident_memory_context,
            working_memory_context=working_memory_context,
        )

        try:
            async for event in stream_serana_loop(
                initial_state,
                self.llm,
                self._execute_graph,
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

    async def _execute_graph(self, initial_state: Dict[str, Any]) -> Dict[str, Any]:
        compiled_graph = self.graph.compile()
        result = await compiled_graph.ainvoke(initial_state)
        return result

    def get_status(self) -> AgentState:
        return self.state
