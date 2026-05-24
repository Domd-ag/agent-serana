from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from .database import get_db
from .models import User, UserLLMConfig, UserLLMMode
from .llm_gateway import create_user_llm_config_from_db
from fastapi import Depends, HTTPException, status
import logging

logger = logging.getLogger(__name__)


async def get_default_user(db: AsyncSession = Depends(get_db)) -> User:
    result = await db.execute(select(User).where(User.name == "default"))
    user = result.scalar_one_or_none()
    
    if not user:
        user = User(name="default")
        db.add(user)
        await db.commit()
        await db.refresh(user)
    
    return user


async def get_user_llm_config(
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[UserLLMConfig]:
    result = await db.execute(
        select(UserLLMConfig).where(UserLLMConfig.user_id == user.id)
    )
    return result.scalar_one_or_none()


async def get_user_llm_mode(
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> UserLLMMode:
    result = await db.execute(
        select(UserLLMMode).where(UserLLMMode.user_id == user.id)
    )
    mode = result.scalar_one_or_none()
    
    if not mode:
        mode = UserLLMMode(user_id=user.id, mode="BACKEND_DEFAULT")
        db.add(mode)
        await db.commit()
        await db.refresh(mode)
    
    return mode


async def get_current_llm_config(
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
):
    mode_result = await db.execute(
        select(UserLLMMode).where(UserLLMMode.user_id == user.id)
    )
    mode = mode_result.scalar_one_or_none()
    
    use_backend_default = True
    user_config = None
    
    if mode and mode.mode == "USER_CONFIG":
        config_result = await db.execute(
            select(UserLLMConfig).where(UserLLMConfig.user_id == user.id)
        )
        db_config = config_result.scalar_one_or_none()
        if db_config:
            user_config = create_user_llm_config_from_db(db_config)
            use_backend_default = False
    
    return {
        "user_config": user_config,
        "use_backend_default": use_backend_default,
    }
