from collections.abc import Awaitable, Callable
from typing import Any, Optional, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel


class AgentState(TypedDict):
    user_input: str
    original_user_input: str
    resident_memory_context: str
    working_memory_context: str
    working_memory_entries: dict[str, str]
    memory_context: str
    session_id: str
    thinking_blocks: list[dict[str, Any]]
    current_goal: Optional[str]
    goal_type: Optional[str]
    complexity: Optional[str]
    execution_mode: str
    delegation_plan: dict[str, Any]
    subtasks: list[dict[str, Any]]
    serana_status: str
    aide_sessions: list[dict[str, Any]]
    forge_sessions: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    conversation_route: dict[str, Any]
    instruction_skill_names: list[str]
    instruction_skill_context: str
    final_response: Optional[str]
    llm: Optional[BaseChatModel]
    approval_runtime: dict[str, Any]
    event_emitter: Optional[Callable[[dict[str, Any]], Awaitable[None]]]

def create_initial_state(
    user_input: str,
    session_id: str,
    llm: BaseChatModel,
    memory_context: str = "",
    resident_memory_context: str = "",
    working_memory_context: str = "",
    approval_runtime: Optional[dict[str, Any]] = None,
    event_emitter: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None,
) -> AgentState:
    return AgentState(
        user_input=user_input,
        original_user_input=user_input,
        resident_memory_context=resident_memory_context,
        working_memory_context=working_memory_context,
        working_memory_entries={},
        memory_context=memory_context,
        session_id=session_id,
        thinking_blocks=[],
        current_goal=None,
        goal_type=None,
        complexity=None,
        execution_mode="delegated",
        delegation_plan={},
        subtasks=[],
        serana_status="idle",
        aide_sessions=[],
        forge_sessions=[],
        tool_calls=[],
        tool_results=[],
        conversation_route={},
        instruction_skill_names=[],
        instruction_skill_context="",
        final_response=None,
        llm=llm,
        approval_runtime=dict(approval_runtime or {}),
        event_emitter=event_emitter,
    )
