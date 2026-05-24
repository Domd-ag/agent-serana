import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.base import AgentManager, AgentManifest, AgentState, get_agent_limit, load_manifest
from app.core.logger import get_logger


request_logger = get_logger("app.request.aide")


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


class AideAgent:
    """Coordinates delegated work through classification, batching, and retries."""

    def __init__(self, llm: BaseChatModel, agent_id: str | None = None):
        self.llm = llm
        self.agent_id = agent_id or f"aide-{uuid.uuid4().hex[:8]}"
        self.manifest: Optional[AgentManifest] = load_manifest("aide")
        self.state = AgentState(
            agent_id=self.agent_id,
            agent_name="Aide",
            status="idle",
        )

    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        description = str(task.get("description") or "unknown task")
        request_logger.info("Aide executing task: %s", description)

        self.state.thinking_blocks = []
        self.state.status = "working"
        self.state.current_task = description
        self._append_thinking("Task Intake", f"Received delegated task: {description}")

        task_profile = self._classify_task(task)
        batch_plan = self._plan_batches(task, task_profile)
        self._append_thinking(
            "Classification",
            f"Task classified as {task_profile['task_type']} with {len(batch_plan)} batch(es).",
        )

        try:
            result = await self._dispatch_batches(task, task_profile, batch_plan)
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

    def _classify_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        task_type = _infer_task_type(task)
        retry_limit = int(task.get("max_retries") or self._default_retries_for_type(task_type))
        batch_size = int(task.get("batch_size") or self._default_batch_size_for_type(task_type))
        forge_limit = get_agent_limit("forge") or 5
        preferred_parallel_forges = min(
            forge_limit,
            int(task.get("parallel_forges") or self._default_parallelism_for_type(task_type)),
        )
        return {
            "task_type": task_type,
            "retry_limit": max(0, retry_limit),
            "batch_size": max(1, batch_size),
            "preferred_parallel_forges": max(1, preferred_parallel_forges),
        }

    def _plan_batches(self, task: Dict[str, Any], task_profile: Dict[str, Any]) -> list[Dict[str, Any]]:
        items = list(task.get("items") or task.get("batch_items") or [])
        if not items:
            return [
                {
                    "batch_index": 0,
                    "description": str(task.get("description") or "unknown task"),
                    "items": [],
                }
            ]

        batch_size = int(task_profile["batch_size"])
        batches = []
        for index in range(0, len(items), batch_size):
            chunk = items[index : index + batch_size]
            batches.append(
                {
                    "batch_index": len(batches),
                    "description": f"{task.get('description', 'task')} (batch {len(batches) + 1})",
                    "items": chunk,
                }
            )
        return batches

    async def _dispatch_batches(
        self,
        task: Dict[str, Any],
        task_profile: Dict[str, Any],
        batch_plan: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        agent_manager = AgentManager()
        if agent_manager.llm is None:
            agent_manager.initialize(self.llm)
        else:
            agent_manager.llm = self.llm

        parallel_batches = min(
            len(batch_plan),
            int(task_profile["preferred_parallel_forges"]),
        )
        self._append_thinking(
            "Scheduling",
            f"Dispatching {len(batch_plan)} batch(es) with up to {parallel_batches} Forge worker(s).",
        )
        semaphore = asyncio.Semaphore(max(1, parallel_batches))

        async def _run_batch(batch: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                return await self._execute_batch(agent_manager, task, task_profile, batch)

        batch_results = await asyncio.gather(*[_run_batch(batch) for batch in batch_plan])
        completed = all(batch["status"] == "completed" for batch in batch_results)
        worker_assigned = any(batch.get("worker_assigned", False) for batch in batch_results)
        assigned_workers = sorted(
            {
                str(batch.get("worker_result", {}).get("agent_id") or "")
                for batch in batch_results
                if batch.get("worker_result", {}).get("agent_id")
            }
        )
        total_attempts = sum(int(batch.get("attempts") or 0) for batch in batch_results)
        self._append_thinking(
            "Delegation",
            f"Completed dispatch with {len(assigned_workers)} Forge worker(s) over {total_attempts} total attempt(s).",
        )
        return {
            "status": "completed" if completed else "failed",
            "worker_assigned": worker_assigned,
            "task_type": task_profile["task_type"],
            "retry_limit": task_profile["retry_limit"],
            "parallel_forges": parallel_batches,
            "batches_planned": len(batch_plan),
            "batch_results": batch_results,
            "worker_result": {
                "agent_id": assigned_workers[0] if assigned_workers else None,
                "agent_ids": assigned_workers,
                "attempts": total_attempts,
                "batch_count": len(batch_plan),
                "task_type": task_profile["task_type"],
                "strategy": batch_results[0].get("worker_result", {}).get("result", {}).get("strategy")
                if batch_results
                else None,
                "tool_name": batch_results[0].get("worker_result", {}).get("result", {}).get("tool_name")
                if batch_results
                else None,
                "status": "completed" if completed else "failed",
            },
        }

    async def _execute_batch(
        self,
        agent_manager: AgentManager,
        task: Dict[str, Any],
        task_profile: Dict[str, Any],
        batch: Dict[str, Any],
    ) -> Dict[str, Any]:
        retry_limit = int(task_profile["retry_limit"])
        last_error: Optional[str] = None
        for attempt in range(1, retry_limit + 2):
            forge_task = {
                **task,
                "task_type": task_profile["task_type"],
                "description": batch["description"],
                "batch_items": list(batch.get("items") or []),
                "current_attempt": attempt,
            }
            self._append_thinking(
                "Delegation",
                f"Assigning batch {batch['batch_index'] + 1} attempt {attempt} to a Forge worker.",
            )

            try:
                forge = await agent_manager.get_agent("forge")
                forge_result = await forge.execute(forge_task)
                success = bool(forge_result.get("success", False))
                if success:
                    self._append_thinking(
                        "Delegation",
                        f"Batch {batch['batch_index'] + 1} completed on attempt {attempt}.",
                    )
                    return {
                        "batch_index": batch["batch_index"],
                        "status": "completed",
                        "attempts": attempt,
                        "worker_assigned": True,
                        "items": list(batch.get("items") or []),
                        "worker_result": forge_result,
                    }

                last_error = str(forge_result.get("result", {}).get("message") or "Forge execution failed.")
            except Exception as exc:
                request_logger.exception("Aide failed to assign batch %s", batch["batch_index"])
                last_error = str(exc)

            if attempt <= retry_limit:
                self._append_thinking(
                    "Retry",
                    f"Retrying batch {batch['batch_index'] + 1} after attempt {attempt} failed: {last_error}",
                )

        self._append_thinking(
            "Delegation",
            f"Batch {batch['batch_index'] + 1} failed after retries: {last_error}",
        )
        return {
            "batch_index": batch["batch_index"],
            "status": "failed",
            "attempts": retry_limit + 1,
            "worker_assigned": False,
            "items": list(batch.get("items") or []),
            "error": last_error,
            "worker_result": {},
        }

    def _default_retries_for_type(self, task_type: str) -> int:
        return {
            "research": 1,
            "planning": 1,
            "build": 2,
            "analysis": 1,
            "question": 0,
            "task": 1,
        }.get(task_type, 1)

    def _default_batch_size_for_type(self, task_type: str) -> int:
        return {
            "research": 2,
            "planning": 2,
            "build": 1,
            "analysis": 2,
            "question": 1,
            "task": 1,
        }.get(task_type, 1)

    def _default_parallelism_for_type(self, task_type: str) -> int:
        return {
            "research": 3,
            "planning": 2,
            "build": 2,
            "analysis": 2,
            "question": 1,
            "task": 1,
        }.get(task_type, 1)

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
