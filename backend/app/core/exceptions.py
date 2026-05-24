from fastapi import Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
import logging

logger = logging.getLogger(__name__)


class SeranaException(Exception):
    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class LLMConfigError(SeranaException):
    def __init__(self, message: str = "LLM configuration error"):
        super().__init__(message, status.HTTP_400_BAD_REQUEST)


class AgentError(SeranaException):
    def __init__(self, message: str = "Agent execution error"):
        super().__init__(message, status.HTTP_500_INTERNAL_SERVER_ERROR)


async def serana_exception_handler(request: Request, exc: SeranaException):
    logger.error(f"Serana exception: {exc.message}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.message},
    )


async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    logger.error(f"Database error: {str(exc)}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"status": "error", "message": "Database error occurred"},
    )


async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unexpected error: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"status": "error", "message": "An unexpected error occurred"},
    )
