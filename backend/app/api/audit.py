from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import AuditInsightsResponse, AuditRecordResponse, AuditTimelineResponse, User, get_db, get_default_user
from app.core.audit import build_audit_insights, load_filtered_audit_records, serialize_audit_record


router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=List[AuditRecordResponse])
async def list_audit_records(
    entity_type: Optional[str] = Query(default=None),
    entity_id: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    del user
    records = await load_filtered_audit_records(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        limit=limit,
    )
    return [serialize_audit_record(record) for record in records]


@router.get("/timeline", response_model=AuditTimelineResponse)
async def get_audit_timeline(
    entity_type: str = Query(...),
    entity_id: str = Query(...),
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    del user
    records = await load_filtered_audit_records(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
    )
    serialized = [serialize_audit_record(record) for record in records]
    return AuditTimelineResponse(
        entity_type=entity_type,
        entity_id=entity_id,
        total_records=len(serialized),
        insights=build_audit_insights(records),
        records=serialized,
    )


@router.get("/debug-summary", response_model=AuditInsightsResponse)
async def get_audit_debug_summary(
    entity_type: str = Query(...),
    entity_id: str = Query(...),
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    del user
    records = await load_filtered_audit_records(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
    )
    return build_audit_insights(records)
