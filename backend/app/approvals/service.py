from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ApprovalResponse
from app.core.audit import append_audit_record
from app.skills import SkillManager

from .manager import get_approval_manager


async def resolve_approval_decision(
    *,
    request_id: str,
    approval_response: ApprovalResponse,
    db: AsyncSession,
) -> ApprovalResponse:
    if approval_response.request_id != request_id:
        raise HTTPException(status_code=400, detail="Approval request id mismatch")

    manager = get_approval_manager()
    approval_request = await manager.get_request(request_id)
    if approval_request is None:
        raise HTTPException(status_code=404, detail="Approval request not found")

    resolved = await manager.resolve(
        request_id,
        approved=approval_response.approved,
        reviewer=approval_response.reviewer or "user",
        note=approval_response.note,
        approval_scope=approval_response.approval_scope,
    )
    if resolved is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if resolved.approved and resolved.approval_scope == "always":
        await manager.add_grant(approval_request, resolved)

    if approval_request.entity_type and approval_request.entity_id:
        append_audit_record(
            db,
            entity_type=approval_request.entity_type,
            entity_id=approval_request.entity_id,
            event_type="approval_resolved",
            summary="Resolved approval decision",
            payload={
                "source": approval_request.source,
                "tool_name": approval_request.tool_name,
                "operation": approval_request.operation,
                "risk_level": approval_request.risk_level,
                "approved": resolved.approved,
                "reviewer": resolved.reviewer,
                "note": resolved.note,
                "approval_scope": resolved.approval_scope,
                "request_id": resolved.request_id,
            },
        )
        await db.commit()

    should_retain_for_followup = (
        approval_request.source in {"skills_marketplace", "skills_upload", "skills_local"} and resolved.approved
    )
    if approval_request.source == "skills_upload" and not should_retain_for_followup:
        SkillManager().discard_staged_skill_installation(request_id)
    if not should_retain_for_followup:
        await manager.discard(request_id)

    return resolved
