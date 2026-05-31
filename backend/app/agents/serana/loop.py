import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.serana.nodes import (
    add_thinking_block,
    add_tool_call,
    analyze_node,
    decompose_node,
    delegate_node,
    summarize_node,
    try_lightweight_conversation,
)


LightweightAcceptor = Callable[[Optional[dict[str, Any]]], bool]
PlanningExecutor = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _mark_planning_fallback(
    state: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    next_state = add_thinking_block(
        state,
        "Routing",
        reason,
    )
    next_state = add_tool_call(
        next_state,
        "serana_loop_transition",
        {"stage": "lightweight_loop"},
        {"next_stage": "planning", "reason": reason},
    )
    return next_state


def _record_loop_stage(
    state: dict[str, Any],
    *,
    stage: str,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    output = {"stage": stage, **dict(details or {})}
    return add_tool_call(
        state,
        "serana_loop_stage",
        {"stage": stage},
        output,
    )


def _record_planning_stage(
    state: dict[str, Any],
    *,
    stage: str,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    output = {"stage": stage, **dict(details or {})}
    return add_tool_call(
        state,
        "serana_planning_stage",
        {"stage": stage},
        output,
    )


def _record_loop_action(
    state: dict[str, Any],
    *,
    action: str,
    status: str,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return add_tool_call(
        state,
        "serana_loop_action",
        {"action": action},
        {
            "action": action,
            "status": status,
            "runtime": "conversation_loop",
            **dict(details or {}),
        },
        status="completed" if status in {"completed", "started"} else status,
    )


async def execute_planning_flow(
    initial_state: dict[str, Any],
    llm: BaseChatModel,
) -> dict[str, Any]:
    """Run Serana's heavier planning stages inside the loop runtime."""
    state = await analyze_node(initial_state, llm)
    state = _record_planning_stage(
        state,
        stage="analyze",
        details={
            "execution_mode": state.get("execution_mode"),
            "goal_type": state.get("goal_type"),
            "complexity": state.get("complexity"),
            "runtime": "conversation_loop",
        },
    )

    if state.get("execution_mode") == "direct":
        state = await summarize_node(state, llm)
        return _record_planning_stage(
            state,
            stage="summarize",
            details={
                "final_response_preview": str(state.get("final_response") or "")[:200],
                "runtime": "conversation_loop",
            },
        )

    state = await decompose_node(state, llm)
    state = _record_planning_stage(
        state,
        stage="decompose",
        details={
            "subtask_count": len(state.get("subtasks", [])),
            "execution_mode": state.get("execution_mode"),
            "runtime": "conversation_loop",
        },
    )

    if state.get("execution_mode") == "delegated":
        delegation_plan = dict(state.get("delegation_plan") or {})
        state = _record_loop_action(
            state,
            action="delegate_agents",
            status="started",
            details={
                "subtask_count": len(state.get("subtasks", [])),
                "parallel_slots": delegation_plan.get("parallel_slots", 0),
                "parallel_aides": delegation_plan.get("parallel_aides", 0),
                "parallel_forges": delegation_plan.get("parallel_forges", 0),
            },
        )
        state = await delegate_node(state, llm)
        state = _record_loop_action(
            state,
            action="delegate_agents",
            status="completed",
            details={
                "aide_sessions": len(state.get("aide_sessions", [])),
                "forge_sessions": len(state.get("forge_sessions", [])),
            },
        )
        state = _record_planning_stage(
            state,
            stage="delegate",
            details={
                "aide_sessions": len(state.get("aide_sessions", [])),
                "forge_sessions": len(state.get("forge_sessions", [])),
                "runtime": "conversation_loop",
            },
        )

    state = await summarize_node(state, llm)
    return _record_planning_stage(
        state,
        stage="summarize",
        details={
            "final_response_preview": str(state.get("final_response") or "")[:200],
            "runtime": "conversation_loop",
        },
    )


def _carry_lightweight_route_decision(
    initial_state: dict[str, Any],
    lightweight_result: dict[str, Any],
) -> dict[str, Any]:
    next_state = dict(initial_state)

    route_info = lightweight_result.get("conversation_route")
    if route_info is not None:
        next_state["conversation_route"] = route_info

    route_tool_calls = [
        tool_call
        for tool_call in list(lightweight_result.get("tool_calls", []))
        if isinstance(tool_call, dict) and str(tool_call.get("name") or "") == "conversation_route"
    ]
    if route_tool_calls:
        next_state["tool_calls"] = list(initial_state.get("tool_calls", [])) + route_tool_calls

    return next_state


class ConversationLoop:
    """Owns Serana's plan-act-escalate conversation runtime.

    The public wrapper functions below stay stable for API callers, while this
    class becomes the single place that decides whether a turn finishes in the
    lightweight path or escalates into the planning flow.
    """

    def __init__(
        self,
        *,
        llm: BaseChatModel,
        planning_executor: PlanningExecutor,
        lightweight_acceptor: Optional[LightweightAcceptor] = None,
    ) -> None:
        self.llm = llm
        self.planning_executor = planning_executor
        self.lightweight_acceptor = lightweight_acceptor

    async def run(self, initial_state: dict[str, Any]) -> tuple[dict[str, Any], str]:
        loop_state = _record_loop_stage(initial_state, stage="lightweight_start")
        lightweight_result = await self._run_lightweight_turn(loop_state)

        if self._accepts_lightweight_result(lightweight_result) and lightweight_result is not None:
            return self._complete_lightweight(lightweight_result)

        planning_state = self._prepare_planning_state(loop_state, lightweight_result)
        return await self._run_planning_turn(planning_state)

    async def _run_lightweight_turn(self, loop_state: dict[str, Any]) -> Optional[dict[str, Any]]:
        return await try_lightweight_conversation(loop_state, self.llm)

    def _accepts_lightweight_result(self, lightweight_result: Optional[dict[str, Any]]) -> bool:
        if self.lightweight_acceptor is not None:
            return self.lightweight_acceptor(lightweight_result)
        return (
            lightweight_result is not None
            and str(lightweight_result.get("execution_mode") or "") == "direct"
        )

    def _complete_lightweight(self, lightweight_result: dict[str, Any]) -> tuple[dict[str, Any], str]:
        route_info = dict(lightweight_result.get("conversation_route") or {})
        direct_result = _record_loop_stage(
            lightweight_result,
            stage="lightweight_complete",
            details={
                "accepted": True,
                "route": route_info.get("route"),
                "execution_mode": lightweight_result.get("execution_mode", "direct"),
            },
        )
        return direct_result, "direct"

    def _prepare_planning_state(
        self,
        loop_state: dict[str, Any],
        lightweight_result: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        if lightweight_result is None:
            loop_state = _record_loop_stage(
                loop_state,
                stage="lightweight_complete",
                details={
                    "accepted": False,
                    "route": None,
                    "execution_mode": None,
                },
            )
            return _mark_planning_fallback(
                loop_state,
                reason="The lightweight route could not complete this request, so Serana escalated to the planning flow.",
            )

        route_info = dict(lightweight_result.get("conversation_route") or {})
        planning_base_state = _carry_lightweight_route_decision(loop_state, lightweight_result)
        planning_base_state = _record_loop_stage(
            planning_base_state,
            stage="lightweight_complete",
            details={
                "accepted": False,
                "route": route_info.get("route"),
                "execution_mode": lightweight_result.get("execution_mode", "direct"),
            },
        )
        return _mark_planning_fallback(
            planning_base_state,
            reason="This request needs fuller planning, so Serana escalated from the lightweight loop to the planning flow.",
        )

    async def _run_planning_turn(self, planning_state: dict[str, Any]) -> tuple[dict[str, Any], str]:
        planning_state = _record_loop_stage(planning_state, stage="planning_start")
        planning_result = await self.planning_executor(planning_state)
        planning_result = _record_loop_stage(
            planning_result,
            stage="planning_complete",
            details={
                "execution_mode": planning_result.get("execution_mode", "delegated"),
                "goal_type": planning_result.get("goal_type"),
                "complexity": planning_result.get("complexity"),
            },
        )
        return planning_result, "delegated"


async def execute_serana_loop(
    initial_state: dict[str, Any],
    llm: BaseChatModel,
    planning_executor: PlanningExecutor,
    *,
    lightweight_acceptor: Optional[LightweightAcceptor] = None,
) -> tuple[dict[str, Any], str]:
    loop = ConversationLoop(
        llm=llm,
        planning_executor=planning_executor,
        lightweight_acceptor=lightweight_acceptor,
    )
    return await loop.run(initial_state)


async def stream_serana_loop(
    initial_state: dict[str, Any],
    llm: BaseChatModel,
    planning_executor: PlanningExecutor,
    *,
    session_id: str,
    lightweight_acceptor: Optional[LightweightAcceptor] = None,
) -> AsyncGenerator[dict[str, Any], None]:
    heartbeat_interval_seconds = 8.0
    last_thinking_emit = asyncio.get_running_loop().time()

    yield {
        "type": "thinking",
        "content": "Analyzing your request...",
    }

    event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def emit_runtime_event(event: dict[str, Any]) -> None:
        await event_queue.put(event)

    stream_state = dict(initial_state)
    stream_state["event_emitter"] = emit_runtime_event

    execution_task = asyncio.create_task(
        execute_serana_loop(
                stream_state,
                llm,
                planning_executor,
                lightweight_acceptor=lightweight_acceptor,
            )
    )

    while True:
        if execution_task.done() and event_queue.empty():
            break
        try:
            event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            now = asyncio.get_running_loop().time()
            if not execution_task.done() and now - last_thinking_emit >= heartbeat_interval_seconds:
                last_thinking_emit = now
                yield {
                    "type": "thinking",
                    "content": "Still working on your request...",
                }
            continue
        last_thinking_emit = asyncio.get_running_loop().time()
        yield event

    result, default_execution_mode = await execution_task

    for block in result.get("thinking_blocks", []):
        yield {
            "type": "thinking_block",
            "content": block,
        }
        await asyncio.sleep(0.1)

    final_response = result.get("final_response", "")
    for char in final_response:
        yield {
            "type": "content",
            "content": char,
        }
        await asyncio.sleep(0.02)

    yield {
        "type": "done",
        "session_id": session_id,
        "execution_mode": result.get("execution_mode", default_execution_mode),
        "delegation_plan": result.get("delegation_plan", {}),
        "goal_type": result.get("goal_type"),
        "complexity": result.get("complexity"),
        "thinking_blocks": result.get("thinking_blocks", []),
        "tool_calls": result.get("tool_calls", []),
        "summary": result.get("final_response", ""),
    }
