from datetime import timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.memory.facts import ProfileFactsManager
from app.memory.history import HistoryManager
from app.memory.resident import ResidentMemoryManager
from app.memory.retriever import MemoryRetriever
from app.memory.working import WorkingMemoryManager


logger = get_logger(__name__)


class MemoryInjector:
    """Builds memory context for chat and goal execution prompts."""

    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id
        self.retriever = MemoryRetriever(db, user_id)
        self.facts_manager = ProfileFactsManager(db, user_id)
        self.resident_manager = ResidentMemoryManager(db, user_id)
        self.working_manager = WorkingMemoryManager(db, user_id)
        self.history_manager = HistoryManager(db, user_id)

    async def inject_for_conversation(
        self,
        user_input: str,
        session_id: Optional[str] = None,
        include_facts: bool = True,
        include_history: bool = True,
        max_history_count: int = 10,
    ) -> str:
        """Build prompt context for a chat turn."""
        sections = await self.build_conversation_sections(
            user_input=user_input,
            session_id=session_id,
            include_facts=include_facts,
            include_history=include_history,
            max_history_count=max_history_count,
        )
        return sections["combined_context"]

    async def build_conversation_sections(
        self,
        user_input: str,
        session_id: Optional[str] = None,
        include_facts: bool = True,
        include_history: bool = True,
        max_history_count: int = 10,
    ) -> dict[str, str]:
        resident_context = await self.resident_manager.to_context_string()
        working_context = await self.working_manager.to_context_string(
            scope="conversation",
            session_id=session_id,
        )
        profile_context = ""
        history_context = ""
        relevant_context = ""

        if include_facts:
            profile_context = await self.facts_manager.to_context_string()

        if include_history:
            history_context = await self.history_manager.to_context_string(
                session_id=session_id,
                limit=max_history_count,
            )

        if user_input and len(user_input) > 5:
            try:
                relevant_memories = await self.retriever.retrieve(
                    query=user_input,
                    limit=5,
                    time_range=timedelta(days=7),
                )
                if relevant_memories:
                    relevant_lines = ["[Relevant Memories]"]
                    for index, memory in enumerate(relevant_memories, start=1):
                        relevant_lines.append(f"{index}. {memory.content}")
                    relevant_context = "\n".join(relevant_lines)
            except RuntimeError as exc:
                logger.warning("Memory retrieval skipped for conversation context: %s", exc)
            except ValueError as exc:
                logger.warning("Memory retrieval input was invalid: %s", exc)
            except Exception:
                logger.exception("Unexpected error retrieving conversation memories")

        dynamic_parts = [
            part for part in (profile_context, history_context, relevant_context) if part
        ]
        dynamic_context = "\n\n".join(dynamic_parts)
        combined_parts = [part for part in (resident_context, working_context, dynamic_context) if part]
        combined_context = "\n\n".join(combined_parts)
        if combined_context:
            combined_context += "\n\n"

        return {
            "resident_memory_context": resident_context,
            "working_memory_context": working_context,
            "profile_memory_context": profile_context,
            "history_memory_context": history_context,
            "relevant_memory_context": relevant_context,
            "dynamic_memory_context": dynamic_context,
            "combined_context": combined_context,
        }

    async def inject_for_goal_execution(
        self,
        goal: str,
        session_id: Optional[str] = None,
    ) -> str:
        """Build prompt context for goal planning or execution."""
        sections = await self.build_goal_sections(goal=goal, session_id=session_id)
        return sections["combined_context"]

    async def build_goal_sections(
        self,
        goal: str,
        session_id: Optional[str] = None,
        goal_id: Optional[str] = None,
    ) -> dict[str, str]:
        del session_id

        resident_context = await self.resident_manager.to_context_string()
        working_context = await self.working_manager.to_context_string(
            scope="goal",
            goal_id=goal_id,
        )
        profile_context = await self.facts_manager.to_context_string()
        relevant_context = ""

        if goal:
            try:
                relevant_memories = await self.retriever.retrieve(
                    query=goal,
                    memory_types=["history"],
                    limit=10,
                    time_range=timedelta(days=30),
                )
                if relevant_memories:
                    relevant_lines = ["[Relevant History]"]
                    for memory in relevant_memories:
                        relevant_lines.append(f"- {memory.content}")
                    relevant_context = "\n".join(relevant_lines)
            except RuntimeError as exc:
                logger.warning("Memory retrieval skipped for goal context: %s", exc)
            except ValueError as exc:
                logger.warning("Goal memory retrieval input was invalid: %s", exc)
            except Exception:
                logger.exception("Unexpected error retrieving goal memories")

        dynamic_parts = [part for part in (profile_context, relevant_context) if part]
        dynamic_context = "\n\n".join(dynamic_parts)
        combined_parts = [part for part in (resident_context, working_context, dynamic_context) if part]
        combined_context = "\n\n".join(combined_parts)
        if combined_context:
            combined_context += "\n\n"

        return {
            "resident_memory_context": resident_context,
            "working_memory_context": working_context,
            "profile_memory_context": profile_context,
            "history_memory_context": "",
            "relevant_memory_context": relevant_context,
            "dynamic_memory_context": dynamic_context,
            "combined_context": combined_context,
        }
