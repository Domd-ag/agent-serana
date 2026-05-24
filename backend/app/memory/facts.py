from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import logger
from app.core.models import ProfileFact as DBProfileFact
from app.memory.resident import ResidentMemoryManager


class ProfileFactsManager:
    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id
        self.resident_manager = ResidentMemoryManager(db, user_id)

    async def add_fact(
        self,
        key: str,
        value: str,
        source: str = "user_explicit",
        category: Optional[str] = None,
        confidence: float = 1.0,
    ) -> DBProfileFact:
        existing = await self._get_fact_by_key(key)

        if existing:
            existing.value = value
            existing.source = source
            existing.category = category
            existing.confidence = confidence
            existing.updated_at = datetime.now(timezone.utc)
            await self.db.commit()
            await self.db.refresh(existing)
            await self.resident_manager.sync_from_fact(
                key,
                value,
                category=category,
                source=source,
                priority=confidence,
            )
            logger.info("Updated profile fact: %s", key)
            return existing

        fact = DBProfileFact(
            user_id=self.user_id,
            key=key,
            value=value,
            source=source,
            category=category,
            confidence=confidence,
            is_active=True,
        )
        self.db.add(fact)
        await self.db.commit()
        await self.db.refresh(fact)
        await self.resident_manager.sync_from_fact(
            key,
            value,
            category=category,
            source=source,
            priority=confidence,
        )
        logger.info("Added profile fact: %s", key)
        return fact

    async def get_fact(self, key: str) -> Optional[DBProfileFact]:
        return await self._get_fact_by_key(key)

    async def get_all_facts(self, category: Optional[str] = None) -> List[DBProfileFact]:
        query = select(DBProfileFact).where(
            DBProfileFact.user_id == self.user_id,
            DBProfileFact.is_active.is_(True),
        )

        if category:
            query = query.where(DBProfileFact.category == category)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def update_fact(
        self,
        key: str,
        value: str,
        source: Optional[str] = None,
        category: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> Optional[DBProfileFact]:
        fact = await self._get_fact_by_key(key)
        if not fact:
            return None

        fact.value = value
        fact.source = source
        fact.category = category
        if confidence is not None:
            fact.confidence = confidence
        fact.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(fact)
        await self.resident_manager.sync_from_fact(
            key,
            value,
            category=category,
            source=source or "profile_fact",
            priority=fact.confidence,
        )
        logger.info("Edited profile fact: %s", key)
        return fact

    async def delete_fact(self, key: str) -> bool:
        fact = await self._get_fact_by_key(key)
        if not fact:
            return False

        fact.is_active = False
        fact.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.resident_manager.delete_entry(key)
        logger.info("Deleted profile fact: %s", key)
        return True

    async def _get_fact_by_key(self, key: str) -> Optional[DBProfileFact]:
        result = await self.db.execute(
            select(DBProfileFact).where(
                DBProfileFact.user_id == self.user_id,
                DBProfileFact.key == key,
                DBProfileFact.is_active.is_(True),
            ).order_by(DBProfileFact.updated_at.desc(), DBProfileFact.created_at.desc())
        )
        return result.scalars().first()

    async def to_context_string(self) -> str:
        facts = await self.get_all_facts()
        if not facts:
            return ""

        lines = ["[User Profile]"]
        for fact in facts:
            category_part = f"({fact.category}) " if fact.category else ""
            lines.append(f"- {category_part}{fact.key}: {fact.value}")

        return "\n".join(lines)
