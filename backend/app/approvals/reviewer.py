from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from app.core import ApprovalRequest

from .policy import PolicyDecision


class ApprovalReviewer:
    def build_request(
        self,
        *,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        policy_decision: PolicyDecision,
        source: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> ApprovalRequest:
        title, summary = self._build_copy(tool_name, arguments, policy_decision)
        return ApprovalRequest(
            request_id=str(uuid4()),
            source=source,
            entity_type=entity_type,
            entity_id=entity_id,
            session_id=session_id,
            tool_name=tool_name,
            operation=policy_decision.operation,
            risk_level=policy_decision.risk_level,
            title=title,
            summary=summary,
            reason=policy_decision.reason,
            approval_options=self._approval_options(policy_decision),
            details={
                **policy_decision.details,
                "arguments": arguments,
                "reason": policy_decision.reason,
            },
            status="pending",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

    def _approval_options(self, policy_decision: PolicyDecision) -> list[str]:
        if policy_decision.risk_level == "high":
            return ["once", "deny"]
        return ["once", "always", "deny"]

    def _build_copy(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        policy_decision: PolicyDecision,
    ) -> tuple[str, str]:
        if tool_name == "browser.act_page":
            action = str(arguments.get("action") or "").strip() or "操作"
            target = str(arguments.get("target") or arguments.get("selector") or "").strip()
            if target:
                return (
                    "确认浏览器操作",
                    f"Serana 想在当前页面执行“{action}”，目标是“{target}”。",
                )
            return (
                "确认浏览器操作",
                f"Serana 想在当前页面执行“{action}”。",
            )

        if tool_name == "browser.browser_downloads":
            filename = str(arguments.get("filename") or "").strip() or "所选文件"
            return (
                "确认发送下载文件",
                f"Serana 想把浏览器下载列表中的“{filename}”发送到当前聊天。",
            )

        if tool_name == "skills.marketplace.install":
            slug = str(arguments.get("slug") or "").strip() or "远程技能"
            version = str(arguments.get("version") or arguments.get("tag") or "").strip()
            version_suffix = f"（版本 {version}）" if version else ""
            return (
                "确认安装远程技能",
                f"Serana 想从 SkillHub 安装“{slug}”{version_suffix}。",
            )

        if tool_name == "skills.local.install":
            skill_name = str(arguments.get("skill_name") or "").strip() or "本地技能"
            version = str(arguments.get("version") or "").strip()
            version_suffix = f"（版本 {version}）" if version else ""
            return (
                "确认导入本地技能",
                f"Serana 想导入本地技能包“{skill_name}”{version_suffix}，导入后会把它加入当前运行时。",
            )

        if tool_name == "skills.local.uninstall":
            skill_name = str(arguments.get("skill_name") or "").strip() or "技能"
            return (
                "确认卸载技能",
                f"Serana 想卸载本地技能“{skill_name}”，卸载后这个技能提供的工具会立即不可用。",
            )

        return (
            "确认执行操作",
            f"Serana 想执行一个 {policy_decision.risk_level} 风险操作，需要你确认。",
        )


_approval_reviewer: ApprovalReviewer | None = None


def get_approval_reviewer() -> ApprovalReviewer:
    global _approval_reviewer
    if _approval_reviewer is None:
        _approval_reviewer = ApprovalReviewer()
    return _approval_reviewer
