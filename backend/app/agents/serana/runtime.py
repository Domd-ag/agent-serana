from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import AgentManager
from app.agents.serana.serana import SeranaAgent
from app.core import ThinkingBlock, ToolCall, User, get_llm_gateway
from app.memory import MemoryService


MemoryScope = Literal["chat", "goal"]


@dataclass
class SeranaRuntimeContext:
    serana_agent: SeranaAgent
    memory_service: MemoryService
    memory_context: str
    recent_history_context: str
    resident_memory_context: str
    working_memory_context: str
    memory_context_included: bool
    resident_memory_included: bool
    working_memory_included: bool
    thinking_blocks: list[ThinkingBlock]
    tool_calls: list[ToolCall]
    timestamp: str


def _build_memory_trace(
    *,
    session_id: str | None,
    goal_id: str | None,
    include_history: bool,
    memory_sections: dict[str, str],
    timestamp: str,
) -> tuple[list[ThinkingBlock], list[ToolCall], dict[str, bool]]:
    resident_memory_context = memory_sections["resident_memory_context"]
    working_memory_context = memory_sections["working_memory_context"]
    memory_context = memory_sections["dynamic_memory_context"]
    combined_memory_context = memory_sections["combined_context"]
    memory_flags = {
        "memory_context_included": bool(memory_context.strip()),
        "resident_memory_included": bool(resident_memory_context.strip()),
        "working_memory_included": bool(working_memory_context.strip()),
    }

    tool_calls = [
        ToolCall(
            id="memory-injector",
            name="memory_injector",
            input={
                "session_id": session_id,
                "goal_id": goal_id,
                "include_facts": True,
                "include_history": include_history,
            },
            output={
                **memory_flags,
                "resident_preview": resident_memory_context[:200],
                "working_preview": working_memory_context[:200],
                "context_preview": combined_memory_context[:200],
            },
            status="completed",
            timestamp=timestamp,
        )
    ]

    thinking_blocks: list[ThinkingBlock] = []
    if memory_flags["resident_memory_included"]:
        thinking_blocks.append(
            ThinkingBlock(
                id="resident-memory-context",
                title="Resident Memory",
                content="Loaded stable long-term preferences and standing user context.",
                timestamp=timestamp,
                is_expanded=False,
            )
        )
    if memory_flags["working_memory_included"]:
        thinking_blocks.append(
            ThinkingBlock(
                id="working-memory-context",
                title="Working Memory",
                content="Loaded temporary notes and task context for the current conversation.",
                timestamp=timestamp,
                is_expanded=False,
            )
        )
    if memory_flags["memory_context_included"]:
        thinking_blocks.append(
            ThinkingBlock(
                id="memory-context",
                title="Memory",
                content="Loaded related profile facts and conversation history.",
                timestamp=timestamp,
                is_expanded=False,
            )
        )

    return thinking_blocks, tool_calls, memory_flags


async def prepare_serana_runtime(
    *,
    db: AsyncSession,
    user: User,
    user_input: str,
    llm_config: dict[str, Any],
    scope: MemoryScope,
    session_id: str | None = None,
    goal_id: str | None = None,
    gateway_factory: Callable[[], Any] = get_llm_gateway,
) -> SeranaRuntimeContext:
    timestamp = datetime.now(timezone.utc).isoformat()
    memory_service = MemoryService(db, user.id)

    if scope == "goal":
        memory_sections = await memory_service.build_goal_sections(
            goal=user_input,
            goal_id=goal_id,
        )
        include_history = False
    else:
        memory_sections = await memory_service.build_conversation_sections(
            user_input=user_input,
            session_id=session_id or "",
            include_facts=True,
            include_history=True,
        )
        include_history = True

    thinking_blocks, tool_calls, memory_flags = _build_memory_trace(
        session_id=session_id,
        goal_id=goal_id,
        include_history=include_history,
        memory_sections=memory_sections,
        timestamp=timestamp,
    )

    gateway = gateway_factory()
    llm = gateway.get_llm(
        user_config=llm_config["user_config"],
        use_backend_default=llm_config["use_backend_default"],
    )
    tool_calls.append(
        ToolCall(
            id="llm-gateway",
            name="llm_gateway",
            input={
                "use_backend_default": llm_config["use_backend_default"],
                "has_user_config": bool(llm_config["user_config"]),
            },
            output={"status": "resolved"},
            status="completed",
            timestamp=timestamp,
        )
    )

    agent_manager = AgentManager()
    if agent_manager.llm is None:
        agent_manager.initialize(llm)
    else:
        agent_manager.llm = llm

    return SeranaRuntimeContext(
        serana_agent=await agent_manager.get_agent("serana"),
        memory_service=memory_service,
        memory_context=memory_sections["dynamic_memory_context"]
        if memory_flags["memory_context_included"]
        else "",
        recent_history_context=memory_sections["history_memory_context"],
        resident_memory_context=memory_sections["resident_memory_context"]
        if memory_flags["resident_memory_included"]
        else "",
        working_memory_context=memory_sections["working_memory_context"]
        if memory_flags["working_memory_included"]
        else "",
        memory_context_included=memory_flags["memory_context_included"],
        resident_memory_included=memory_flags["resident_memory_included"],
        working_memory_included=memory_flags["working_memory_included"],
        thinking_blocks=thinking_blocks,
        tool_calls=tool_calls,
        timestamp=timestamp,
    )
