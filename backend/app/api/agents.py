from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List, Dict, Any
from datetime import datetime

from app.core import (
    get_db,
    get_default_user,
    get_llm_gateway,
    User,
    AgentSession,
    AgentStatusResponse,
)
from app.agents import AgentManager

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/status", response_model=List[AgentStatusResponse])
async def get_agent_statuses(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    # 获取代理管理器
    gateway = get_llm_gateway()
    llm = gateway.get_llm()
    agent_manager = AgentManager()
    
    # 确保初始化
    if agent_manager.llm is None:
        agent_manager.initialize(llm)
    
    # 获取所有代理状态
    agents_status = agent_manager.get_all_agents_status()
    
    # 转换为响应格式
    return [
        AgentStatusResponse(
            id=agent["id"],
            name=agent["name"],
            agent_type=agent["type"].upper(),
            status=agent["status"],
            current_task=agent["current_task"],
            session_id=None,
        )
        for agent in agents_status
    ]


@router.get("/manifests", response_model=List[Dict[str, Any]])
async def get_agent_manifests():
    """获取所有代理的 manifest 信息"""
    agent_types = ["serana", "forge"]
    manifests = []
    
    for agent_type in agent_types:
        manifest = AgentManager().get_manifest(agent_type)
        if manifest:
            manifests.append({
                "type": agent_type,
                "name": manifest.name,
                "display_name": manifest.display_name,
                "description": manifest.description,
                "version": manifest.version,
                "max_instances": manifest.max_instances,
                "skills": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "description": s.description,
                        "enabled": s.enabled
                    }
                    for s in manifest.skills
                ],
                "tools": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "description": t.description
                    }
                    for t in manifest.tools
                ],
            })
    
    return manifests


@router.get("/sessions", response_model=List[dict])
async def get_agent_sessions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    result = await db.execute(
        select(AgentSession)
        .order_by(desc(AgentSession.started_at))
        .limit(20)
    )
    sessions = result.scalars().all()
    
    return [
        {
            "id": s.id,
            "agent_type": s.agent_type,
            "status": s.status,
            "current_task": s.current_task,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        }
        for s in sessions
    ]
