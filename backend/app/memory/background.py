from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from app.core.logger import get_logger


logger = get_logger(__name__)
_BACKGROUND_MEMORY_TASKS: set[asyncio.Task[Any]] = set()


def schedule_memory_task(coroutine: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
    task = asyncio.create_task(coroutine)
    _BACKGROUND_MEMORY_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_MEMORY_TASKS.discard)
    return task


async def shutdown_memory_tasks(timeout_seconds: float = 5.0) -> None:
    tasks = [task for task in _BACKGROUND_MEMORY_TASKS if not task.done()]
    if not tasks:
        return

    done, pending = await asyncio.wait(tasks, timeout=max(0.1, timeout_seconds))
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        try:
            task.result()
        except Exception:
            logger.exception("Background memory task failed during shutdown")
