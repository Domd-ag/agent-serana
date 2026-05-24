from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import (
    ProfileFactCreate,
    ProfileFactUpdate,
    ProfileFactResponse,
    SearchMemoryRequest,
    User,
    get_db,
    get_default_user,
)
from app.core.models import ProfileFact
from app.memory import MemoryInjector, MemoryRetriever, ProfileFactsManager

router = APIRouter(prefix="/memory", tags=["memory"])


def response_from_db_fact(db_fact: ProfileFact) -> ProfileFactResponse:
    return ProfileFactResponse(
        id=db_fact.id,
        key=db_fact.key,
        value=db_fact.value,
        category=db_fact.category,
        confidence=db_fact.confidence,
        is_active=db_fact.is_active,
        source=db_fact.source,
        created_at=db_fact.created_at,
        updated_at=db_fact.updated_at,
    )


@router.post("/facts", response_model=ProfileFactResponse)
async def add_profile_fact(
    fact_data: ProfileFactCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    manager = ProfileFactsManager(db, user.id)
    fact = await manager.add_fact(
        key=fact_data.key,
        value=fact_data.value,
        source=fact_data.source or "user_explicit",
        category=fact_data.category,
        confidence=fact_data.confidence or 1.0,
    )
    return response_from_db_fact(fact)


@router.get("/facts", response_model=List[ProfileFactResponse])
async def get_profile_facts(
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    manager = ProfileFactsManager(db, user.id)
    facts = await manager.get_all_facts(category=category)
    return [response_from_db_fact(fact) for fact in facts]


@router.get("/facts/{key}", response_model=Optional[ProfileFactResponse])
async def get_profile_fact(
    key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    manager = ProfileFactsManager(db, user.id)
    fact = await manager.get_fact(key)
    if not fact:
        raise HTTPException(status_code=404, detail="Fact not found")
    return response_from_db_fact(fact)


@router.put("/facts/{key}", response_model=ProfileFactResponse)
async def update_profile_fact(
    key: str,
    fact_data: ProfileFactUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    manager = ProfileFactsManager(db, user.id)
    fact = await manager.update_fact(
        key=key,
        value=fact_data.value,
        source=fact_data.source,
        category=fact_data.category,
        confidence=fact_data.confidence,
    )
    if not fact:
        raise HTTPException(status_code=404, detail="Fact not found")
    return response_from_db_fact(fact)


@router.delete("/facts/{key}")
async def delete_profile_fact(
    key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    manager = ProfileFactsManager(db, user.id)
    success = await manager.delete_fact(key)
    if not success:
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"success": True}


@router.post("/search")
async def search_memories(
    request: SearchMemoryRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    retriever = MemoryRetriever(db, user.id)
    memories = await retriever.retrieve(
        query=request.query,
        limit=request.limit,
        time_range=timedelta(days=request.days) if request.days else None,
    )

    return {
        "success": True,
        "memories": [
            {
                "content": memory.content,
                "type": memory.memory_type,
                "score": memory.relevance_score,
                "timestamp": memory.timestamp,
                "metadata": memory.metadata,
            }
            for memory in memories
        ],
    }


@router.get("/context")
async def get_memory_context(
    session_id: Optional[str] = None,
    include_facts: bool = True,
    include_history: bool = True,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    injector = MemoryInjector(db, user.id)
    context = await injector.inject_for_conversation(
        user_input="",
        session_id=session_id,
        include_facts=include_facts,
        include_history=include_history,
    )

    return {
        "success": True,
        "context": context,
    }
