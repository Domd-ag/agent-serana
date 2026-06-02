from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.consolidation import MemoryConsolidationService
from app.memory.artifacts import MemoryArtifactManager
from app.memory.facts import ProfileFactsManager
from app.memory.history import HistoryManager
from app.memory.injector import MemoryInjector
from app.memory.resident import ResidentMemoryManager
from app.memory.retriever import MemoryRetriever
from app.memory.working import WorkingMemoryManager


class MemoryService:
    """Unified entrypoint for memory reads, writes, retrieval, and consolidation."""

    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id
        self.facts = ProfileFactsManager(db, user_id)
        self.history = HistoryManager(db, user_id)
        self.artifacts = MemoryArtifactManager(db, user_id)
        self.resident = ResidentMemoryManager(db, user_id)
        self.working = WorkingMemoryManager(db, user_id)
        self.retriever = MemoryRetriever(db, user_id)
        self.injector = MemoryInjector(db, user_id)
        self.consolidation = MemoryConsolidationService(db, user_id)

    async def build_conversation_sections(
        self,
        *,
        user_input: str,
        session_id: Optional[str] = None,
        include_facts: bool = True,
        include_history: bool = True,
        max_history_count: int = 10,
    ) -> dict[str, str]:
        return await self.injector.build_conversation_sections(
            user_input=user_input,
            session_id=session_id,
            include_facts=include_facts,
            include_history=include_history,
            max_history_count=max_history_count,
        )

    async def build_goal_sections(
        self,
        *,
        goal: str,
        session_id: Optional[str] = None,
        goal_id: Optional[str] = None,
    ) -> dict[str, str]:
        return await self.injector.build_goal_sections(
            goal=goal,
            session_id=session_id,
            goal_id=goal_id,
        )

    async def inject_for_conversation(
        self,
        *,
        user_input: str,
        session_id: Optional[str] = None,
        include_facts: bool = True,
        include_history: bool = True,
        max_history_count: int = 10,
    ) -> str:
        return await self.injector.inject_for_conversation(
            user_input=user_input,
            session_id=session_id,
            include_facts=include_facts,
            include_history=include_history,
            max_history_count=max_history_count,
        )

    async def inject_for_goal_execution(
        self,
        *,
        goal: str,
        session_id: Optional[str] = None,
    ) -> str:
        return await self.injector.inject_for_goal_execution(
            goal=goal,
            session_id=session_id,
        )

    async def consolidate_chat_turn(
        self,
        *,
        user_input: str,
        session_id: Optional[str] = None,
        assistant_content: str = "",
        llm: Any = None,
    ) -> dict[str, object]:
        return await self.consolidation.consolidate_chat_turn(
            user_input=user_input,
            session_id=session_id,
            assistant_content=assistant_content,
            llm=llm,
        )

    async def save_memory(
        self,
        *,
        key: str,
        value: str,
        category: Optional[str] = None,
        source: str = "memory_tool",
        confidence: float = 1.0,
    ) -> Dict[str, Any]:
        fact = await self.facts.add_fact(
            key=key.strip(),
            value=value.strip(),
            category=(category or None),
            source=source,
            confidence=confidence,
        )
        category_label = f"{fact.category} · " if fact.category else ""
        return {
            "key": fact.key,
            "value": fact.value,
            "category": fact.category,
            "summary": f"我已经记住：{category_label}{fact.key} = {fact.value}",
        }

    async def search_memory(
        self,
        *,
        query: str,
        limit: int = 5,
    ) -> Dict[str, Any]:
        safe_limit = max(1, min(int(limit or 5), 8))
        resident_entries = await self.resident.get_all_entries(limit=12)
        resident_matches: List[Dict[str, Any]] = []
        for entry in resident_entries:
            score = self._score_match(query, entry.content)
            score = max(score, self._score_resident_entry(query, entry.key))
            if score > 0.15:
                resident_matches.append(
                    {
                        "content": entry.content,
                        "memory_type": "resident",
                        "score": round(score, 3),
                    }
                )

        resident_matches.sort(key=lambda item: item["score"], reverse=True)
        retrieved = await self.retriever.retrieve(
            query=query,
            limit=safe_limit,
            memory_types=["facts", "preferences", "summaries", "episodes"],
        )

        results: List[Dict[str, Any]] = []
        seen_contents: set[str] = set()

        for item in resident_matches:
            if item["content"] in seen_contents:
                continue
            seen_contents.add(item["content"])
            results.append(item)
            if len(results) >= safe_limit:
                break

        for item in retrieved:
            if item.content in seen_contents:
                continue
            seen_contents.add(item.content)
            results.append(
                {
                    "content": item.content,
                    "memory_type": item.memory_type,
                    "score": round(item.relevance_score, 3),
                }
            )
            if len(results) >= safe_limit:
                break

        if not results:
            for entry in resident_entries[:safe_limit]:
                if entry.content in seen_contents:
                    continue
                seen_contents.add(entry.content)
                results.append(
                    {
                        "content": entry.content,
                        "memory_type": "resident",
                        "score": 0.1,
                    }
                )

        if not results:
            return {
                "query": query,
                "results": [],
                "summary": "我暂时没有找到相关记忆。",
            }

        direct_summary = self._format_memory_search_summary(query, results)
        if direct_summary:
            return {
                "query": query,
                "results": results,
                "summary": direct_summary,
            }

        summary_lines = ["我找到了这些相关记忆："]
        for index, item in enumerate(results, start=1):
            summary_lines.append(f"{index}. {item['content']}")

        return {
            "query": query,
            "results": results,
            "summary": "\n".join(summary_lines),
        }

    async def save_working_memory(
        self,
        *,
        key: str,
        value: str,
        scope: str = "conversation",
        session_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        source: str = "working_memory_tool",
        priority: float = 1.0,
    ) -> Dict[str, Any]:
        safe_scope = "goal" if str(scope).lower() == "goal" else "conversation"
        entry = await self.working.upsert_entry(
            key=key.strip(),
            content=value.strip(),
            scope=safe_scope,
            session_id=session_id if safe_scope == "conversation" else None,
            goal_id=goal_id if safe_scope == "goal" else None,
            source=source,
            priority=priority,
        )
        scope_label = "当前目标" if safe_scope == "goal" else "当前对话"
        return {
            "key": entry.key,
            "value": entry.content,
            "scope": safe_scope,
            "summary": f"我先记在{scope_label}里：{entry.key} = {entry.content}",
        }

    async def clear_working_memory(
        self,
        *,
        scope: str = "conversation",
        session_id: Optional[str] = None,
        goal_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        safe_scope = "goal" if str(scope).lower() == "goal" else "conversation"
        cleared = await self.working.clear_scope(
            scope=safe_scope,
            session_id=session_id if safe_scope == "conversation" else None,
            goal_id=goal_id if safe_scope == "goal" else None,
        )
        scope_label = "当前目标" if safe_scope == "goal" else "当前对话"
        if cleared:
            summary = f"我已经清空{scope_label}里的临时工作记忆。"
        else:
            summary = f"{scope_label}里目前没有需要清空的临时工作记忆。"
        return {
            "scope": safe_scope,
            "cleared_count": cleared,
            "summary": summary,
        }

    @staticmethod
    def _normalize_text(value: str) -> str:
        return "".join(ch.lower() for ch in value if not ch.isspace())

    @staticmethod
    def _format_memory_search_summary(query: str, results: list[dict[str, Any]]) -> str:
        if not results:
            return ""
        text = str(query or "").lower()
        top_type = str(results[0].get("memory_type") or "").lower()
        should_answer_directly = any(
            keyword in text for keyword in ("多少", "什么", "哪", "what", "which", "how much")
        ) or top_type in {"resident", "fact", "preference"}
        if not should_answer_directly:
            return ""

        top_content = str(results[0].get("content") or "").strip()
        if not top_content:
            return ""

        content = top_content
        for prefix in ("preference:", "fact:", "resident:"):
            if content.lower().startswith(prefix):
                content = content[len(prefix) :].strip()

        separator = " = " if " = " in content else (": " if ": " in content else "")
        if separator:
            key, value = content.split(separator, 1)
            key = key.strip()
            value = value.strip()
            if key and value:
                return f"你之前说过：{key} 是 {value}。"

        return f"我记得：{content}"

    @classmethod
    def _score_match(cls, query: str, content: str) -> float:
        query_normalized = cls._normalize_text(query)
        content_normalized = cls._normalize_text(content)
        if not query_normalized or not content_normalized:
            return 0.0
        if query_normalized in content_normalized:
            return 1.0

        shared = sum(1 for ch in set(query_normalized) if ch in content_normalized)
        return shared / max(len(set(query_normalized)), 1)

    @classmethod
    def _score_resident_entry(cls, query: str, key: str) -> float:
        query_normalized = cls._normalize_text(query)
        key_normalized = cls._normalize_text(key)
        compact_key = key_normalized.replace("_", "").replace("-", "")

        if not query_normalized or not key_normalized:
            return 0.0

        if compact_key == "preferreddrink" and any(
            token in query for token in ["饮料", "喝", "咖啡", "茶", "奶茶"]
        ):
            return 0.95
        if compact_key == "preferredfood" and any(
            token in query for token in ["吃", "早餐", "午餐", "晚餐", "食物", "饭"]
        ):
            return 0.95
        if compact_key == "homecity" and any(
            token in query for token in ["住", "哪里", "哪儿", "城市", "家"]
        ):
            return 0.9
        return 0.0
