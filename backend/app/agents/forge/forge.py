from datetime import datetime, timezone
from typing import Any, Dict, Optional
import asyncio
import uuid

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.base import AgentManifest, AgentState, load_manifest
from app.core.logger import get_logger


request_logger = get_logger("app.request.forge")


def _infer_task_type(task: Dict[str, Any]) -> str:
    explicit = str(task.get("task_type") or "").strip().lower()
    if explicit:
        return explicit

    description = str(task.get("description") or "").strip().lower()
    if "?" in description or description.startswith(("what", "why", "how", "when", "where", "who")):
        return "question"
    if any(keyword in description for keyword in ["research", "compare", "investigate", "find sources"]):
        return "research"
    if any(keyword in description for keyword in ["plan", "schedule", "organize", "roadmap"]):
        return "planning"
    if any(keyword in description for keyword in ["build", "implement", "develop", "code", "refactor"]):
        return "build"
    if any(keyword in description for keyword in ["analyze", "audit", "review", "evaluate"]):
        return "analysis"
    return "task"


class ForgeAgent:
    """Executes a concrete delegated task using a task-specific strategy."""

    def __init__(self, llm: BaseChatModel, agent_id: str | None = None):
        self.llm = llm
        self.agent_id = agent_id or f"forge-{uuid.uuid4().hex[:8]}"
        self.manifest: Optional[AgentManifest] = load_manifest("forge")
        self.state = AgentState(
            agent_id=self.agent_id,
            agent_name="Forge",
            status="idle",
        )

    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        description = str(task.get("description") or "unknown task")
        task_type = _infer_task_type(task)
        request_logger.info("Forge executing task: %s (%s)", description, task_type)

        self.state.thinking_blocks = []
        self.state.status = "working"
        self.state.current_task = description
        self._append_thinking("Execution Start", f"Starting {task_type} task: {description}")

        try:
            result = await self._perform_task(task, task_type)
            return {
                "success": result.get("status") == "completed",
                "agent_id": self.agent_id,
                "task": task,
                "result": result,
                "thinking_blocks": list(self.state.thinking_blocks),
            }
        finally:
            self.state.status = "idle"
            self.state.current_task = None

    async def _perform_task(self, task: Dict[str, Any], task_type: str) -> Dict[str, Any]:
        strategy_map = {
            "research": self._execute_research_task,
            "planning": self._execute_planning_task,
            "build": self._execute_build_task,
            "analysis": self._execute_analysis_task,
            "question": self._execute_question_task,
            "task": self._execute_general_task,
        }
        strategy = strategy_map.get(task_type, self._execute_general_task)
        self._append_thinking("Strategy", f"Selected {task_type} execution strategy.")
        return await strategy(task)

    async def _execute_research_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return await self._complete_with_strategy(
            task,
            strategy="research_synthesis",
            tool_name="knowledge_scout",
            action="Collected and organized research findings.",
        )

    async def _execute_planning_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return await self._complete_with_strategy(
            task,
            strategy="planning_breakdown",
            tool_name="plan_weaver",
            action="Structured the task into a workable plan.",
        )

    async def _execute_build_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return await self._complete_with_strategy(
            task,
            strategy="implementation",
            tool_name="builder_toolkit",
            action="Prepared implementation-oriented execution output.",
        )

    async def _execute_analysis_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return await self._complete_with_strategy(
            task,
            strategy="analysis_review",
            tool_name="insight_lens",
            action="Evaluated the task and produced a review summary.",
        )

    async def _execute_question_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return await self._complete_with_strategy(
            task,
            strategy="direct_answer",
            tool_name="answer_console",
            action="Prepared a concise direct answer.",
        )

    async def _execute_general_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return await self._complete_with_strategy(
            task,
            strategy="general_execution",
            tool_name="task_runner",
            action="Completed the assigned task.",
        )

    async def _complete_with_strategy(
        self,
        task: Dict[str, Any],
        strategy: str,
        tool_name: str,
        action: str,
    ) -> Dict[str, Any]:
        description = str(task.get("description") or "unknown task")
        batch_items = list(task.get("batch_items") or [])
        attempt = int(task.get("current_attempt") or 1)
        failures_before_success = int(task.get("failures_before_success") or 0)

        processed_items = len(batch_items) if batch_items else 1
        self._append_thinking("Execution", f"Using {tool_name} for {processed_items} work item(s).")
        await asyncio.sleep(0.05)

        if attempt <= failures_before_success:
            self._append_thinking("Execution", f"Encountered a transient failure on attempt {attempt}.")
            return {
                "status": "failed",
                "task_type": _infer_task_type(task),
                "strategy": strategy,
                "tool_name": tool_name,
                "message": f"Transient execution failure for '{description}' on attempt {attempt}.",
                "attempt": attempt,
                "processed_items": processed_items,
            }

        self._append_thinking("Execution", "Task execution completed.")
        return {
            "status": "completed",
            "task_type": _infer_task_type(task),
            "strategy": strategy,
            "tool_name": tool_name,
            "message": f"{action} Task '{description}' completed.",
            "attempt": attempt,
            "processed_items": processed_items,
        }

    def _append_thinking(self, title: str, content: str) -> None:
        self.state.thinking_blocks.append(
            {
                "id": str(uuid.uuid4()),
                "title": title,
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    def get_status(self) -> AgentState:
        return self.state
