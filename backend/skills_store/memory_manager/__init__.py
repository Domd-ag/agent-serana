from __future__ import annotations

from typing import Any, Dict, Optional

from app.core.database import AsyncSessionLocal
from app.core.models import User
from app.memory import MemoryService
from sqlalchemy import select


DEFAULT_USER_NAME = "default"


async def _get_default_user_id(session) -> str:
    result = await session.execute(select(User).where(User.name == DEFAULT_USER_NAME))
    user = result.scalar_one_or_none()
    if not user:
        raise RuntimeError("Default user not found")
    return str(user.id)


async def memory_save(key: str, value: str, category: str | None = None) -> Dict[str, Any]:
    async with AsyncSessionLocal() as session:
        user_id = await _get_default_user_id(session)
        memory_service = MemoryService(session, user_id)
        return await memory_service.save_memory(
            key=key,
            value=value,
            category=category,
            source="memory_tool",
            confidence=1.0,
        )


async def memory_search(query: str, limit: int = 5) -> Dict[str, Any]:
    async with AsyncSessionLocal() as session:
        user_id = await _get_default_user_id(session)
        memory_service = MemoryService(session, user_id)
        return await memory_service.search_memory(query=query, limit=limit)


async def working_memory_save(
    key: str,
    value: str,
    scope: str = "conversation",
    session_id: Optional[str] = None,
    goal_id: Optional[str] = None,
) -> Dict[str, Any]:
    async with AsyncSessionLocal() as session:
        user_id = await _get_default_user_id(session)
        memory_service = MemoryService(session, user_id)
        return await memory_service.save_working_memory(
            key=key,
            value=value,
            scope=scope,
            session_id=session_id,
            goal_id=goal_id,
            source="working_memory_tool",
            priority=1.0,
        )


async def working_memory_clear(
    scope: str = "conversation",
    session_id: Optional[str] = None,
    goal_id: Optional[str] = None,
) -> Dict[str, Any]:
    async with AsyncSessionLocal() as session:
        user_id = await _get_default_user_id(session)
        memory_service = MemoryService(session, user_id)
        return await memory_service.clear_working_memory(
            scope=scope,
            session_id=session_id,
            goal_id=goal_id,
        )
