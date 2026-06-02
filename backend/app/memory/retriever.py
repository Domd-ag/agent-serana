
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import logger
from app.core.models import ProfileFact, Message
from app.memory.artifacts import MemoryArtifactManager
from app.memory.facts import ProfileFactsManager
from app.memory.history import HistoryManager


class MemoryItem:
    """记忆项"""
    def __init__(
        self,
        content: str,
        memory_type: str,
        relevance_score: float = 1.0,
        timestamp: Optional[datetime] = None,
        metadata: Optional[Dict] = None
    ):
        self.content = content
        self.memory_type = memory_type
        self.relevance_score = relevance_score
        self.timestamp = timestamp or datetime.now(timezone.utc)
        self.metadata = metadata or {}


class MemoryRetriever:
    """记忆检索器"""
    
    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id
        self.facts_manager = ProfileFactsManager(db, user_id)
        self.history_manager = HistoryManager(db, user_id)
        self.artifact_manager = MemoryArtifactManager(db, user_id)
    
    async def retrieve(
        self,
        query: str,
        memory_types: Optional[List[str]] = None,
        limit: int = 10,
        time_range: Optional[timedelta] = None
    ) -> List[MemoryItem]:
        """
        检索相关记忆
        
        Args:
            query: 查询文本
            memory_types: 记忆类型列表，如 ["facts", "history"]，None 表示所有
            limit: 返回数量限制
            time_range: 时间范围限制
        """
        if memory_types is None:
            memory_types = ["facts", "preferences", "summaries", "episodes"]
        
        items: List[MemoryItem] = []
        
        # 检索 Profile Facts
        if "facts" in memory_types:
            fact_items = await self._retrieve_facts(query, time_range)
            items.extend(fact_items)

        if "preferences" in memory_types or "preference" in memory_types:
            preference_items = await self._retrieve_artifacts(query, ["preference"], limit)
            items.extend(preference_items)

        if "summaries" in memory_types or "summary" in memory_types:
            summary_items = await self._retrieve_artifacts(query, ["summary"], limit)
            items.extend(summary_items)

        summary_count = sum(1 for item in items if item.memory_type == "summary")
        should_fetch_episodes = (
            "episodes" in memory_types or "episode" in memory_types
        ) and summary_count < limit

        if should_fetch_episodes:
            remaining = max(1, limit - summary_count)
            episode_items = await self._retrieve_artifacts(query, ["episode"], remaining)
            items.extend(episode_items)
        
        # 检索历史记录
        if "history" in memory_types:
            history_items = await self._retrieve_history(query, time_range, limit // 2)
            items.extend(history_items)
        
        # Summary-first: dense summaries outrank detailed episodes and raw history.
        priority = {"fact": 3, "preference": 3, "summary": 2, "episode": 1, "history": 0}
        items.sort(key=lambda x: (priority.get(x.memory_type, 0), x.relevance_score), reverse=True)
        
        return items[:limit]

    async def _retrieve_artifacts(
        self,
        query: str,
        kinds: list[str],
        limit: int,
    ) -> List[MemoryItem]:
        artifacts = await self.artifact_manager.search(
            query=query,
            kinds=kinds,
            limit=limit,
        )
        items: List[MemoryItem] = []
        for artifact in artifacts:
            content = self.artifact_manager._sanitize_content(str(artifact.content or ""))
            if not content:
                continue
            score = self.artifact_manager.score_text(query, f"{artifact.title or ''} {content}")
            items.append(
                MemoryItem(
                    content=content,
                    memory_type=str(artifact.kind),
                    relevance_score=score * float(artifact.confidence or 0.8),
                    timestamp=artifact.updated_at or artifact.created_at,
                    metadata={
                        "artifact_id": artifact.id,
                        "title": artifact.title,
                        "session_id": artifact.session_id,
                        "source": artifact.source,
                    },
                )
            )
        return items
    
    async def _retrieve_facts(
        self,
        query: str,
        time_range: Optional[timedelta] = None
    ) -> List[MemoryItem]:
        """检索相关的 Profile Facts"""
        facts = await self.facts_manager.get_all_facts()
        items: List[MemoryItem] = []
        
        for fact in facts:
            # 简单的关键词匹配评分
            score = self._calculate_keyword_score(query, f"{fact.key} {fact.value}")
            if score > 0:
                items.append(MemoryItem(
                    content=f"{fact.key}: {fact.value}",
                    memory_type="fact",
                    relevance_score=score * fact.confidence,
                    timestamp=fact.created_at,
                    metadata={"key": fact.key, "category": fact.category}
                ))
        
        return items
    
    async def _retrieve_history(
        self,
        query: str,
        time_range: Optional[timedelta] = None,
        limit: int = 5
    ) -> List[MemoryItem]:
        """检索相关的历史记录"""
        # 先尝试搜索关键词
        if query and len(query) > 2:
            messages = await self.history_manager.search_messages(query, limit)
        else:
            messages = await self.history_manager.get_recent_messages(limit)
        
        items: List[MemoryItem] = []
        
        for msg in messages:
            # 时间衰减评分
            time_decay = 1.0
            if time_range:
                message_time = msg.created_at
                if message_time.tzinfo is None:
                    message_time = message_time.replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - message_time
                if age > time_range:
                    continue
                time_decay = max(0, 1.0 - (age.total_seconds() / time_range.total_seconds()))
            
            # 关键词匹配
            keyword_score = self._calculate_keyword_score(query, msg.content)
            
            items.append(MemoryItem(
                content=f"{msg.role}: {msg.content}",
                memory_type="history",
                relevance_score=(0.5 + keyword_score * 0.5) * time_decay,
                timestamp=msg.created_at,
                metadata={"session_id": msg.session_id, "role": msg.role}
            ))
        
        return items
    
    def _calculate_keyword_score(self, query: str, content: str) -> float:
        """简单的关键词匹配评分"""
        if not query or not content:
            return 0.5
        
        query_lower = query.lower()
        content_lower = content.lower()
        
        # 计算匹配的关键词数量
        query_words = query_lower.split()
        matches = sum(1 for word in query_words if word in content_lower)
        
        if not query_words:
            return 0.5
        
        return matches / len(query_words)
    
    async def get_all_facts(self) -> List[MemoryItem]:
        """获取所有 Profile Facts 作为记忆项"""
        facts = await self.facts_manager.get_all_facts()
        return [
            MemoryItem(
                content=f"{f.key}: {f.value}",
                memory_type="fact",
                relevance_score=1.0,
                timestamp=f.created_at,
                metadata={"key": f.key, "category": f.category}
            )
            for f in facts
        ]

