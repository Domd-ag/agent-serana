from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from datetime import datetime, timezone

from app.core import (
    get_db,
    get_default_user,
    get_user_llm_config,
    get_user_llm_mode,
    encrypt_data,
    UserLLMConfig,
    UserLLMMode,
    User,
    LLMConfigCreate,
    LLMConfigResponse,
    LLMModeUpdate,
    LLMModeResponse,
    LLMMode,
)

router = APIRouter(prefix="/llm", tags=["llm"])


@router.post("/config", response_model=LLMConfigResponse)
async def save_llm_config(
    config: LLMConfigCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    existing_config_result = await db.execute(
        select(UserLLMConfig).where(UserLLMConfig.user_id == user.id)
    )
    existing_config = existing_config_result.scalar_one_or_none()
    
    encrypted_api_key = encrypt_data(config.api_key)
    
    if existing_config:
        existing_config.provider = config.provider
        existing_config.encrypted_api_key = encrypted_api_key
        existing_config.base_url = config.base_url
        existing_config.model = config.model
        existing_config.updated_at = datetime.now(timezone.utc)
        db_config = existing_config
    else:
        db_config = UserLLMConfig(
            user_id=user.id,
            provider=config.provider,
            encrypted_api_key=encrypted_api_key,
            base_url=config.base_url,
            model=config.model,
        )
        db.add(db_config)
    
    await db.commit()
    await db.refresh(db_config)
    
    return LLMConfigResponse(
        id=db_config.id,
        provider=db_config.provider,
        base_url=db_config.base_url,
        model=db_config.model,
        created_at=db_config.created_at,
        updated_at=db_config.updated_at,
    )


@router.get("/config", response_model=Optional[LLMConfigResponse])
async def get_llm_config(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    config_result = await db.execute(
        select(UserLLMConfig).where(UserLLMConfig.user_id == user.id)
    )
    config = config_result.scalar_one_or_none()
    
    if not config:
        return None
    
    return LLMConfigResponse(
        id=config.id,
        provider=config.provider,
        base_url=config.base_url,
        model=config.model,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.delete("/config")
async def delete_llm_config(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    config_result = await db.execute(
        select(UserLLMConfig).where(UserLLMConfig.user_id == user.id)
    )
    config = config_result.scalar_one_or_none()
    
    if config:
        await db.delete(config)
        await db.commit()
    
    return {"status": "success", "message": "LLM config deleted"}


@router.post("/mode", response_model=LLMModeResponse)
async def update_llm_mode(
    mode_update: LLMModeUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    if mode_update.mode == LLMMode.BACKEND_DEFAULT:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="旧配置路径已移除，请使用前端保存的 LLM 配置。",
        )

    mode_result = await db.execute(
        select(UserLLMMode).where(UserLLMMode.user_id == user.id)
    )
    mode = mode_result.scalar_one_or_none()
    
    if mode:
        mode.mode = mode_update.mode
        mode.updated_at = datetime.now(timezone.utc)
    else:
        mode = UserLLMMode(user_id=user.id, mode=mode_update.mode)
        db.add(mode)
    
    await db.commit()
    await db.refresh(mode)
    
    return LLMModeResponse(
        mode=LLMMode(mode.mode),
        updated_at=mode.updated_at,
    )


@router.get("/mode", response_model=LLMModeResponse)
async def get_llm_mode(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    mode_result = await db.execute(
        select(UserLLMMode).where(UserLLMMode.user_id == user.id)
    )
    mode = mode_result.scalar_one_or_none()
    
    if not mode:
        mode = UserLLMMode(user_id=user.id, mode="USER_CONFIG")
        db.add(mode)
        await db.commit()
        await db.refresh(mode)
    elif mode.mode == "BACKEND_DEFAULT":
        mode.mode = "USER_CONFIG"
        mode.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(mode)
    
    return LLMModeResponse(
        mode=LLMMode(mode.mode),
        updated_at=mode.updated_at,
    )
