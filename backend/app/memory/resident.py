from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.core.models import ResidentMemory as DBResidentMemory


logger = get_logger(__name__)

SNAPSHOT_KEY = "__resident_snapshot__"


class ResidentMemoryManager:
    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id

    async def upsert_entry(
        self,
        key: str,
        content: str,
        *,
        source: str = "profile_fact",
        priority: float = 1.0,
    ) -> DBResidentMemory:
        existing = await self._get_entry_by_key(key, include_snapshot=True)
        if existing:
            existing.content = content
            existing.source = source
            existing.priority = priority
            existing.is_active = True
            existing.updated_at = datetime.now(timezone.utc)
            await self.db.commit()
            await self.db.refresh(existing)
            if key != SNAPSHOT_KEY:
                await self.refresh_snapshot()
            logger.info("Updated resident memory: %s", key)
            return existing

        entry = DBResidentMemory(
            user_id=self.user_id,
            key=key,
            content=content,
            source=source,
            priority=priority,
            is_active=True,
        )
        self.db.add(entry)
        await self.db.commit()
        await self.db.refresh(entry)
        if key != SNAPSHOT_KEY:
            await self.refresh_snapshot()
        logger.info("Added resident memory: %s", key)
        return entry

    async def sync_from_fact(
        self,
        key: str,
        value: str,
        *,
        category: Optional[str] = None,
        source: str = "profile_fact",
        priority: float = 1.0,
    ) -> DBResidentMemory:
        content = self._format_fact_as_resident_content(key, value, category)
        return await self.upsert_entry(
            key,
            content,
            source=source,
            priority=priority,
        )

    async def delete_entry(self, key: str) -> bool:
        entry = await self._get_entry_by_key(key)
        if not entry:
            return False

        entry.is_active = False
        entry.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.refresh_snapshot()
        logger.info("Deleted resident memory: %s", key)
        return True

    async def get_all_entries(
        self,
        limit: int = 12,
        *,
        include_snapshot: bool = False,
    ) -> List[DBResidentMemory]:
        stmt = select(DBResidentMemory).where(
            DBResidentMemory.user_id == self.user_id,
            DBResidentMemory.is_active.is_(True),
        )
        if not include_snapshot:
            stmt = stmt.where(DBResidentMemory.key != SNAPSHOT_KEY)

        result = await self.db.execute(
            stmt.order_by(DBResidentMemory.priority.desc(), DBResidentMemory.updated_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def get_snapshot_context(
        self,
        *,
        refresh_if_missing: bool = True,
        limit: int = 12,
    ) -> str:
        snapshot = await self._get_entry_by_key(SNAPSHOT_KEY, include_snapshot=True)
        if snapshot and snapshot.is_active and snapshot.content.strip():
            return snapshot.content

        if not refresh_if_missing:
            return ""
        return await self.refresh_snapshot(limit=limit)

    async def refresh_snapshot(self, limit: int = 12) -> str:
        entries = await self.get_all_entries(limit=limit, include_snapshot=False)
        if not entries:
            await self._deactivate_snapshot()
            return ""

        snapshot_content = self._build_snapshot_context(entries)
        await self._upsert_snapshot(snapshot_content)
        logger.info("Refreshed resident memory snapshot with %s entries", len(entries))
        return snapshot_content

    async def to_context_string(self, limit: int = 12) -> str:
        snapshot_context = await self.get_snapshot_context(limit=limit)
        if snapshot_context:
            return snapshot_context

        entries = await self.get_all_entries(limit=limit)
        if not entries:
            return ""

        return self._build_snapshot_context(entries)

    async def _get_entry_by_key(
        self,
        key: str,
        *,
        include_snapshot: bool = False,
    ) -> Optional[DBResidentMemory]:
        stmt = select(DBResidentMemory).where(
            DBResidentMemory.user_id == self.user_id,
            DBResidentMemory.key == key,
            DBResidentMemory.is_active.is_(True),
        )
        if not include_snapshot and key != SNAPSHOT_KEY:
            stmt = stmt.where(DBResidentMemory.key != SNAPSHOT_KEY)
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def _upsert_snapshot(self, content: str) -> DBResidentMemory:
        snapshot = await self._get_entry_by_key(SNAPSHOT_KEY, include_snapshot=True)
        if snapshot:
            if snapshot.content == content and snapshot.is_active:
                return snapshot
            snapshot.content = content
            snapshot.source = "resident_snapshot_v2"
            snapshot.priority = 100.0
            snapshot.is_active = True
            snapshot.updated_at = datetime.now(timezone.utc)
            await self.db.commit()
            await self.db.refresh(snapshot)
            return snapshot

        snapshot = DBResidentMemory(
            user_id=self.user_id,
            key=SNAPSHOT_KEY,
            content=content,
            source="resident_snapshot_v2",
            priority=100.0,
            is_active=True,
        )
        self.db.add(snapshot)
        await self.db.commit()
        await self.db.refresh(snapshot)
        return snapshot

    async def _deactivate_snapshot(self) -> None:
        snapshot = await self._get_entry_by_key(SNAPSHOT_KEY, include_snapshot=True)
        if not snapshot:
            return
        snapshot.is_active = False
        snapshot.updated_at = datetime.now(timezone.utc)
        await self.db.commit()

    @staticmethod
    def _build_snapshot_context(entries: List[DBResidentMemory]) -> str:
        lines = ["[Resident Memory]"]
        category_counts: dict[str, int] = {}
        for entry in entries:
            category = ResidentMemoryManager._extract_category_label(entry.content)
            category_counts[category] = category_counts.get(category, 0) + 1

        if category_counts:
            ordered_categories = sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))
            summary = "；".join(
                f"{ResidentMemoryManager._format_category_name(name)} {count} 项"
                for name, count in ordered_categories
            )
            lines.append(f"稳定用户信息：{summary}")

        for entry in entries:
            lines.append(f"- {entry.content}")
        return "\n".join(lines)

    @staticmethod
    def _extract_category_label(content: str) -> str:
        if ": " in content:
            prefix, _ = content.split(": ", 1)
            normalized = prefix.strip().lower()
            if normalized:
                return normalized
        return "general"

    @staticmethod
    def _format_category_name(category: str) -> str:
        mapping = {
            "preference": "偏好",
            "profile": "个人信息",
            "general": "常驻信息",
        }
        return mapping.get(category, category)

    @staticmethod
    def _format_fact_as_resident_content(key: str, value: str, category: Optional[str]) -> str:
        category_label = f"{category}: " if category else ""
        return f"{category_label}{key} = {value}"
