from typing import Optional, Dict, Any
from enum import Enum
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from .security import decrypt_data
import logging

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    CUSTOM = "custom"


class LLMConfig:
    def __init__(
        self,
        provider: LLMProvider,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "gpt-4",
    ):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.model = model


def create_llm_from_config(config: LLMConfig) -> BaseChatModel:
    if config.provider == LLMProvider.OPENAI:
        return ChatOpenAI(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=0.7,
        )
    elif config.provider == LLMProvider.ANTHROPIC:
        return ChatAnthropic(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=0.7,
        )
    elif config.provider == LLMProvider.CUSTOM:
        return ChatOpenAI(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=0.7,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {config.provider}")


def create_user_llm_config_from_db(db_config) -> Optional[LLMConfig]:
    if not db_config:
        return None
    
    try:
        api_key = decrypt_data(db_config.encrypted_api_key)
        return LLMConfig(
            provider=LLMProvider(db_config.provider),
            api_key=api_key,
            base_url=db_config.base_url,
            model=db_config.model,
        )
    except ValueError as exc:
        logger.warning("Failed to decode user LLM config: %s", exc)
        return None
    except Exception:
        logger.exception("Unexpected failure while creating LLM config from DB")
        return None


class LLMGateway:
    def __init__(self):
        pass
    
    def get_llm(
        self,
        user_config: Optional[LLMConfig] = None,
        use_backend_default: bool = False,
    ) -> BaseChatModel:
        if user_config:
            return create_llm_from_config(user_config)
        raise ValueError("No user LLM configuration available")


_gateway: Optional[LLMGateway] = None


def get_llm_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
