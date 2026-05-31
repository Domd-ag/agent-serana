import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.core import ApprovalRequest, ApprovalResponse


@dataclass
class PendingApproval:
    request: ApprovalRequest
    future: asyncio.Future[ApprovalResponse]


@dataclass
class ApprovalGrant:
    key: str
    tool_name: str
    operation: str
    risk_level: str
    reviewer: str
    note: str | None
    created_at: datetime


class ApprovalManager:
    def __init__(self) -> None:
        self._pending: dict[str, PendingApproval] = {}
        self._grants: dict[str, ApprovalGrant] = {}
        self._lock = asyncio.Lock()

    def grant_key(
        self,
        *,
        tool_name: str,
        operation: str,
        risk_level: str,
        details: dict | None = None,
    ) -> str:
        stable_details = self._stable_grant_details(operation=operation, details=details or {})
        details_text = json.dumps(stable_details, sort_keys=True, ensure_ascii=False, default=str)
        return "|".join(
            [
                str(tool_name or "").strip().lower(),
                str(operation or "").strip().lower(),
                str(risk_level or "").strip().lower(),
                details_text,
            ]
        )

    def _stable_grant_details(self, *, operation: str, details: dict) -> dict:
        operation = str(operation or "").strip().lower()
        if operation == "browser_act":
            return {"action": str(details.get("action") or "").strip().lower()}
        if operation == "browser_download_send":
            return {"action": "send"}
        if operation.startswith("skills_"):
            return {"operation": operation}
        return {}

    async def register(self, request: ApprovalRequest) -> ApprovalRequest:
        future: asyncio.Future[ApprovalResponse] = asyncio.get_running_loop().create_future()
        async with self._lock:
            self._pending[request.request_id] = PendingApproval(request=request, future=future)
        return request

    async def is_granted(
        self,
        *,
        tool_name: str,
        operation: str,
        risk_level: str,
        details: dict | None = None,
    ) -> bool:
        key = self.grant_key(
            tool_name=tool_name,
            operation=operation,
            risk_level=risk_level,
            details=details,
        )
        async with self._lock:
            return key in self._grants

    async def add_grant(
        self,
        request: ApprovalRequest,
        response: ApprovalResponse,
    ) -> None:
        if not response.approved or response.approval_scope != "always":
            return
        if "always" not in request.approval_options:
            return
        if not request.tool_name:
            return
        key = self.grant_key(
            tool_name=request.tool_name,
            operation=request.operation,
            risk_level=request.risk_level,
            details=request.details,
        )
        async with self._lock:
            self._grants[key] = ApprovalGrant(
                key=key,
                tool_name=request.tool_name,
                operation=request.operation,
                risk_level=request.risk_level,
                reviewer=response.reviewer,
                note=response.note,
                created_at=response.resolved_at or datetime.now(timezone.utc),
            )

    async def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        async with self._lock:
            pending = self._pending.get(request_id)
            return pending.request if pending is not None else None

    async def resolve(
        self,
        request_id: str,
        *,
        approved: bool,
        reviewer: str = "user",
        note: str | None = None,
        approval_scope: str = "once",
    ) -> Optional[ApprovalResponse]:
        safe_scope = "always" if str(approval_scope or "").strip().lower() == "always" else "once"
        async with self._lock:
            pending = self._pending.get(request_id)
            if pending is None:
                return None
            response = ApprovalResponse(
                request_id=request_id,
                approved=approved,
                reviewer=reviewer,
                note=note,
                approval_scope=safe_scope,
                resolved_at=datetime.now(timezone.utc),
            )
            if not pending.future.done():
                pending.future.set_result(response)
            return response

    async def wait_for_resolution(
        self,
        request_id: str,
        *,
        timeout_seconds: float = 300.0,
    ) -> ApprovalResponse:
        async with self._lock:
            pending = self._pending.get(request_id)
            if pending is None:
                return ApprovalResponse(
                    request_id=request_id,
                    approved=False,
                    reviewer="system",
                    note="审批请求不存在或已失效。",
                    approval_scope="once",
                    resolved_at=datetime.now(timezone.utc),
                )
            future = pending.future

        try:
            response = await asyncio.wait_for(future, timeout=timeout_seconds)
            return response
        except asyncio.TimeoutError:
            timeout_response = ApprovalResponse(
                request_id=request_id,
                approved=False,
                reviewer="system",
                note="审批等待超时，未执行该操作。",
                approval_scope="once",
                resolved_at=datetime.now(timezone.utc),
            )
            async with self._lock:
                current = self._pending.get(request_id)
                if current is not None and not current.future.done():
                    current.future.set_result(timeout_response)
            return timeout_response
        finally:
            async with self._lock:
                self._pending.pop(request_id, None)

    async def consume_resolution(self, request_id: str) -> Optional[ApprovalResponse]:
        async with self._lock:
            pending = self._pending.get(request_id)
            if pending is None or not pending.future.done():
                return None
            response = pending.future.result()
            self._pending.pop(request_id, None)
            return response

    async def discard(self, request_id: str) -> None:
        async with self._lock:
            self._pending.pop(request_id, None)

    async def shutdown(self) -> None:
        async with self._lock:
            for request_id, pending in list(self._pending.items()):
                if pending.future.done():
                    continue
                pending.future.set_result(
                    ApprovalResponse(
                        request_id=request_id,
                        approved=False,
                        reviewer="system",
                        note="后端正在关闭，未执行待审批操作。",
                        approval_scope="once",
                        resolved_at=datetime.now(timezone.utc),
                    )
                )
            self._pending.clear()
            self._grants.clear()


_approval_manager: ApprovalManager | None = None


def get_approval_manager() -> ApprovalManager:
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ApprovalManager()
    return _approval_manager
