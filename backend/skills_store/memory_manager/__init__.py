from __future__ import annotations

from typing import Any

from app.core import AsyncSessionLocal, get_default_user
from app.memory import MemoryService


async def _service() -> tuple[Any, MemoryService]:
    db = AsyncSessionLocal()
    user = await get_default_user(db)
    return db, MemoryService(db, user.id)


async def memory_save(
    key: str,
    value: str,
    category: str = "",
    confidence: float = 1.0,
) -> dict[str, Any]:
    db, service = await _service()
    try:
        return await service.save_memory(
            key=key,
            value=value,
            category=category or None,
            confidence=confidence,
        )
    finally:
        await db.close()


async def memory_search(query: str, limit: int = 5) -> dict[str, Any]:
    db, service = await _service()
    try:
        return await service.search_memory(query=query, limit=limit)
    finally:
        await db.close()


async def working_memory_save(
    key: str,
    value: str,
    scope: str = "conversation",
    session_id: str = "",
    goal_id: str = "",
    priority: float = 1.0,
) -> dict[str, Any]:
    db, service = await _service()
    try:
        return await service.save_working_memory(
            key=key,
            value=value,
            scope=scope,
            session_id=session_id or None,
            goal_id=goal_id or None,
            priority=priority,
        )
    finally:
        await db.close()


async def working_memory_clear(
    scope: str = "conversation",
    session_id: str = "",
    goal_id: str = "",
) -> dict[str, Any]:
    db, service = await _service()
    try:
        return await service.clear_working_memory(
            scope=scope,
            session_id=session_id or None,
            goal_id=goal_id or None,
        )
    finally:
        await db.close()
