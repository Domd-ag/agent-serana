from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.core.models import WorkingMemory as DBWorkingMemory


logger = get_logger(__name__)


class WorkingMemoryManager:
    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id

    async def upsert_entry(
        self,
        key: str,
        content: str,
        *,
        scope: str,
        session_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        source: str = "runtime",
        priority: float = 1.0,
    ) -> DBWorkingMemory:
        existing = await self._get_entry_by_key(
            key=key,
            scope=scope,
            session_id=session_id,
            goal_id=goal_id,
        )
        if existing:
            existing.content = content
            existing.source = source
            existing.priority = priority
            existing.is_active = True
            existing.updated_at = datetime.now(timezone.utc)
            await self.db.commit()
            await self.db.refresh(existing)
            logger.info("Updated working memory: %s", key)
            return existing

        entry = DBWorkingMemory(
            user_id=self.user_id,
            scope=scope,
            session_id=session_id,
            goal_id=goal_id,
            key=key,
            content=content,
            source=source,
            priority=priority,
            is_active=True,
        )
        self.db.add(entry)
        await self.db.commit()
        await self.db.refresh(entry)
        logger.info("Added working memory: %s", key)
        return entry

    async def delete_entry(
        self,
        key: str,
        *,
        scope: str,
        session_id: Optional[str] = None,
        goal_id: Optional[str] = None,
    ) -> bool:
        entry = await self._get_entry_by_key(
            key=key,
            scope=scope,
            session_id=session_id,
            goal_id=goal_id,
        )
        if not entry:
            return False

        entry.is_active = False
        entry.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        logger.info("Deleted working memory: %s", key)
        return True

    async def clear_scope(
        self,
        *,
        scope: str,
        session_id: Optional[str] = None,
        goal_id: Optional[str] = None,
    ) -> int:
        entries = await self.get_entries(
            scope=scope,
            session_id=session_id,
            goal_id=goal_id,
            limit=500,
        )
        for entry in entries:
            entry.is_active = False
            entry.updated_at = datetime.now(timezone.utc)
        if entries:
            await self.db.commit()
        logger.info("Cleared %s working memory entries for scope=%s", len(entries), scope)
        return len(entries)

    async def get_entries(
        self,
        *,
        scope: str,
        session_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[DBWorkingMemory]:
        stmt = (
            select(DBWorkingMemory)
            .where(
                DBWorkingMemory.user_id == self.user_id,
                DBWorkingMemory.scope == scope,
                DBWorkingMemory.is_active.is_(True),
            )
            .order_by(DBWorkingMemory.priority.desc(), DBWorkingMemory.updated_at.desc())
            .limit(limit)
        )
        if session_id:
            stmt = stmt.where(DBWorkingMemory.session_id == session_id)
        else:
            stmt = stmt.where(DBWorkingMemory.session_id.is_(None))
        if goal_id:
            stmt = stmt.where(DBWorkingMemory.goal_id == goal_id)
        else:
            stmt = stmt.where(DBWorkingMemory.goal_id.is_(None))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def to_context_string(
        self,
        *,
        scope: str,
        session_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        limit: int = 10,
    ) -> str:
        entries = await self.get_entries(
            scope=scope,
            session_id=session_id,
            goal_id=goal_id,
            limit=limit,
        )
        if not entries:
            return ""

        lines = ["[Working Memory]"]
        for entry in entries:
            lines.append(f"- {entry.content}")
        return "\n".join(lines)

    async def _get_entry_by_key(
        self,
        *,
        key: str,
        scope: str,
        session_id: Optional[str] = None,
        goal_id: Optional[str] = None,
    ) -> Optional[DBWorkingMemory]:
        stmt = select(DBWorkingMemory).where(
            DBWorkingMemory.user_id == self.user_id,
            DBWorkingMemory.scope == scope,
            DBWorkingMemory.key == key,
            DBWorkingMemory.is_active.is_(True),
        )
        if session_id:
            stmt = stmt.where(DBWorkingMemory.session_id == session_id)
        else:
            stmt = stmt.where(DBWorkingMemory.session_id.is_(None))
        if goal_id:
            stmt = stmt.where(DBWorkingMemory.goal_id == goal_id)
        else:
            stmt = stmt.where(DBWorkingMemory.goal_id.is_(None))
        result = await self.db.execute(stmt)
        return result.scalars().first()
