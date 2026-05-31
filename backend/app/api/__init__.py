from fastapi import APIRouter
from .llm import router as llm_router
from .chat import router as chat_router
from .memory import router as memory_router
from .goals import router as goals_router
from .agents import router as agents_router
from .skills import router as skills_router
from .audit import router as audit_router
from .browser import router as browser_router
from .approvals import router as approvals_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(llm_router)
api_router.include_router(chat_router)
api_router.include_router(memory_router)
api_router.include_router(goals_router)
api_router.include_router(agents_router)
api_router.include_router(skills_router)
api_router.include_router(audit_router)
api_router.include_router(browser_router)
api_router.include_router(approvals_router)

__all__ = ["api_router"]
