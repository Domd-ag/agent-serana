from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.service import resolve_approval_decision
from app.core import ApprovalResponse, get_db

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.post("/{request_id}", response_model=ApprovalResponse)
async def submit_approval(
    request_id: str,
    approval_response: ApprovalResponse,
    db: AsyncSession = Depends(get_db),
):
    return await resolve_approval_decision(
        request_id=request_id,
        approval_response=approval_response,
        db=db,
    )
