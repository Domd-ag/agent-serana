from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.approvals import get_approval_manager
from app.core import get_settings
from app.core.logger import configure_logging, get_logger
from app.core.init_db import main as init_db_main
from app.api import api_router
from app.agents.serana import initialize_serana_persona
from app.skills import SkillManager
from app.core.schemas import HealthResponse
from app.core.exceptions import (
    serana_exception_handler,
    sqlalchemy_exception_handler,
    general_exception_handler,
    SeranaException,
)
from sqlalchemy.exc import SQLAlchemyError

configure_logging()
startup_logger = get_logger("app.startup")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_logger.info("Starting Serana backend")
    await init_db_main()
    initialize_serana_persona()
    skill_manager = SkillManager()
    skill_manager.ensure_initialized()
    approval_manager = get_approval_manager()

    startup_logger.info("Serana backend started successfully")
    try:
        yield
    finally:
        startup_logger.info("Shutting down Serana backend")
        await approval_manager.shutdown()
        await skill_manager.shutdown()


app = FastAPI(
    title="Serana API",
    description="Serana - AI Butler API",
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(SeranaException, serana_exception_handler)
app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="healthy",
        version=settings.APP_VERSION,
    )


@app.get("/")
async def root():
    return {
        "name": "Serana API",
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }


app.include_router(api_router)
