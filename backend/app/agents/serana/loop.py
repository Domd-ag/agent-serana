from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.serana.nodes import add_thinking_block, add_tool_call, try_lightweight_conversation


LightweightAcceptor = Callable[[Optional[dict[str, Any]]], bool]
GraphExecutor = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _mark_graph_fallback(
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
        {"next_stage": "graph", "reason": reason},
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


async def execute_serana_loop(
    initial_state: dict[str, Any],
    llm: BaseChatModel,
    graph_executor: GraphExecutor,
    *,
    lightweight_acceptor: Optional[LightweightAcceptor] = None,
) -> tuple[dict[str, Any], str]:
    loop_state = _record_loop_stage(initial_state, stage="lightweight_start")
    lightweight_result = await try_lightweight_conversation(loop_state, llm)
    if lightweight_acceptor is None:
        should_use_lightweight = lightweight_result is not None
    else:
        should_use_lightweight = lightweight_acceptor(lightweight_result)

    if should_use_lightweight and lightweight_result is not None:
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
        graph_state = _mark_graph_fallback(
            loop_state,
            reason="The lightweight route could not complete this request, so Serana escalated to the planning graph.",
        )
    else:
        route_info = dict(lightweight_result.get("conversation_route") or {})
        graph_base_state = _carry_lightweight_route_decision(loop_state, lightweight_result)
        graph_base_state = _record_loop_stage(
            graph_base_state,
            stage="lightweight_complete",
            details={
                "accepted": False,
                "route": route_info.get("route"),
                "execution_mode": lightweight_result.get("execution_mode", "direct"),
            },
        )
        graph_state = _mark_graph_fallback(
            graph_base_state,
            reason="This request needs fuller planning, so Serana escalated from the lightweight loop to the planning graph.",
        )

    graph_state = _record_loop_stage(graph_state, stage="graph_start")
    graph_result = await graph_executor(graph_state)
    graph_result = _record_loop_stage(
        graph_result,
        stage="graph_complete",
        details={
            "execution_mode": graph_result.get("execution_mode", "delegated"),
            "goal_type": graph_result.get("goal_type"),
            "complexity": graph_result.get("complexity"),
        },
    )
    return graph_result, "delegated"


async def stream_serana_loop(
    initial_state: dict[str, Any],
    llm: BaseChatModel,
    graph_executor: GraphExecutor,
    *,
    session_id: str,
    lightweight_acceptor: Optional[LightweightAcceptor] = None,
) -> AsyncGenerator[dict[str, Any], None]:
    yield {
        "type": "thinking",
        "content": "Analyzing your request...",
    }

    result, default_execution_mode = await execute_serana_loop(
        initial_state,
        llm,
        graph_executor,
        lightweight_acceptor=lightweight_acceptor,
    )

    for block in result.get("thinking_blocks", []):
        yield {
            "type": "thinking_block",
            "content": block,
        }
        import asyncio

        await asyncio.sleep(0.1)

    final_response = result.get("final_response", "")
    for char in final_response:
        yield {
            "type": "content",
            "content": char,
        }
        import asyncio

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
