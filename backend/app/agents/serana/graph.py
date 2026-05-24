from typing import Any, Optional, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, StateGraph

from app.agents.serana.nodes import add_tool_call, analyze_node, decompose_node, delegate_node, summarize_node


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
    instruction_skill_names: list[str]
    instruction_skill_context: str
    final_response: Optional[str]
    llm: Optional[BaseChatModel]


def _record_graph_stage(
    state: AgentState,
    *,
    stage: str,
    details: Optional[dict[str, Any]] = None,
) -> AgentState:
    details = {"stage": stage, **dict(details or {})}
    return add_tool_call(
        state,
        "serana_graph_stage",
        {"stage": stage},
        details,
    )


def create_serana_graph(llm: BaseChatModel) -> StateGraph:
    graph = StateGraph(AgentState)

    async def analyze(state: AgentState) -> AgentState:
        next_state = await analyze_node(state, llm)
        return _record_graph_stage(
            next_state,
            stage="analyze",
            details={
                "execution_mode": next_state.get("execution_mode"),
                "goal_type": next_state.get("goal_type"),
                "complexity": next_state.get("complexity"),
            },
        )

    async def decompose(state: AgentState) -> AgentState:
        next_state = await decompose_node(state, llm)
        return _record_graph_stage(
            next_state,
            stage="decompose",
            details={
                "subtask_count": len(next_state.get("subtasks", [])),
                "execution_mode": next_state.get("execution_mode"),
            },
        )

    async def delegate(state: AgentState) -> AgentState:
        next_state = await delegate_node(state, llm)
        return _record_graph_stage(
            next_state,
            stage="delegate",
            details={
                "aide_sessions": len(next_state.get("aide_sessions", [])),
                "forge_sessions": len(next_state.get("forge_sessions", [])),
            },
        )

    async def summarize(state: AgentState) -> AgentState:
        next_state = await summarize_node(state, llm)
        return _record_graph_stage(
            next_state,
            stage="summarize",
            details={
                "final_response_preview": str(next_state.get("final_response") or "")[:200],
            },
        )

    graph.add_node("analyze", analyze)
    graph.add_node("decompose", decompose)
    graph.add_node("delegate", delegate)
    graph.add_node("summarize", summarize)

    graph.set_entry_point("analyze")

    def route_after_analyze(state: AgentState) -> str:
        if state.get("execution_mode") == "direct":
            return "summarize"
        return "decompose"

    graph.add_conditional_edges(
        "analyze",
        route_after_analyze,
        {
            "summarize": "summarize",
            "decompose": "decompose",
        },
    )
    graph.add_edge("decompose", "delegate")
    graph.add_edge("delegate", "summarize")
    graph.add_edge("summarize", END)

    return graph


def create_initial_state(
    user_input: str,
    session_id: str,
    llm: BaseChatModel,
    memory_context: str = "",
    resident_memory_context: str = "",
    working_memory_context: str = "",
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
        instruction_skill_names=[],
        instruction_skill_context="",
        final_response=None,
        llm=llm,
    )
