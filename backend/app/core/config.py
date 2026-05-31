from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Serana Backend"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "local"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    SQL_ECHO: bool = False
    CORS_ALLOW_ORIGINS: str = "*"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./serana.db"

    # Security
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ENCRYPTION_KEY: str = "dev-encryption-key-32bytes!!"
    ALGORITHM: str = "HS256"

    # Backend Default LLM
    DEFAULT_LLM_PROVIDER: Optional[str] = None
    DEFAULT_LLM_API_KEY: Optional[str] = None
    DEFAULT_LLM_BASE_URL: Optional[str] = None
    DEFAULT_LLM_MODEL: str = "gpt-4"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Marketplace
    CLAWHUB_BASE_URL: str = "https://clawhub.ai"

    def cors_allow_origins(self) -> list[str]:
        if self.CORS_ALLOW_ORIGINS.strip() == "*":
            return ["*"]
        return [
            origin.strip()
            for origin in self.CORS_ALLOW_ORIGINS.split(",")
            if origin.strip()
        ]

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings():
    return Settings()
