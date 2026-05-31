from dataclasses import dataclass, field
from typing import Any


@dataclass
class PolicyDecision:
    requires_approval: bool
    operation: str
    risk_level: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


class PolicyGate:
    _SENSITIVE_TARGET_KEYWORDS = (
        "delete",
        "remove",
        "logout",
        "sign out",
        "submit",
        "confirm",
        "pay",
        "purchase",
        "order",
        "transfer",
        "密码",
        "付款",
        "购买",
        "提交",
        "删除",
        "确认",
        "登录",
        "退出",
    )

    def evaluate(self, *, tool_name: str, arguments: dict[str, Any]) -> PolicyDecision:
        normalized_tool_name = str(tool_name or "").strip().lower()

        if normalized_tool_name == "browser.act_page":
            action = str(arguments.get("action") or "").strip().lower()
            target = str(arguments.get("target") or arguments.get("selector") or "").strip()
            target_lower = target.lower()
            details = {
                "action": action,
                "target": target,
                "text": str(arguments.get("text") or "").strip(),
            }
            risk_level = "medium"
            if action in {"type", "press", "select"} or any(
                keyword in target_lower for keyword in self._SENSITIVE_TARGET_KEYWORDS
            ):
                risk_level = "high"
            if action in {"click", "type", "press", "select"}:
                return PolicyDecision(
                    requires_approval=True,
                    operation="browser_act",
                    risk_level=risk_level,
                    reason="浏览器交互可能改变页面状态或提交信息，需要用户确认。",
                    details=details,
                )
            return PolicyDecision(
                requires_approval=False,
                operation="browser_act",
                risk_level=risk_level,
                reason="该浏览器动作属于只读或低风险导航操作。",
                details=details,
            )

        if normalized_tool_name == "browser.browser_downloads":
            action = str(arguments.get("action") or "").strip().lower()
            filename = str(arguments.get("filename") or "").strip()
            if action == "send":
                return PolicyDecision(
                    requires_approval=True,
                    operation="browser_download_send",
                    risk_level="medium",
                    reason="向聊天界面发送下载文件前，需要用户确认要暴露的本地文件。",
                    details={"action": action, "filename": filename},
                )
            return PolicyDecision(
                requires_approval=False,
                operation="browser_download_list",
                risk_level="low",
                reason="仅列出下载文件，不涉及发送内容。",
                details={"action": action, "filename": filename},
            )

        if normalized_tool_name == "skills.marketplace.install":
            slug = str(arguments.get("slug") or "").strip()
            version = str(arguments.get("version") or arguments.get("tag") or "").strip()
            return PolicyDecision(
                requires_approval=True,
                operation="skills_marketplace_install",
                risk_level="medium",
                reason="远程技能会把外部内容导入本地运行时，需要先确认来源和用途。",
                details={
                    "slug": slug,
                    "version": version,
                    "tag": str(arguments.get("tag") or "").strip(),
                },
            )

        if normalized_tool_name == "skills.local.install":
            skill_name = str(arguments.get("skill_name") or "").strip()
            version = str(arguments.get("version") or "").strip()
            filename = str(arguments.get("filename") or "").strip()
            return PolicyDecision(
                requires_approval=True,
                operation="skills_local_install",
                risk_level="high",
                reason="本地技能包会把外部文件导入运行时，并可能注册新的工具能力，需要先确认来源与内容。",
                details={
                    "skill_name": skill_name,
                    "version": version,
                    "filename": filename,
                },
            )

        if normalized_tool_name == "skills.local.uninstall":
            skill_name = str(arguments.get("skill_name") or "").strip()
            version = str(arguments.get("version") or "").strip()
            origin = str(arguments.get("origin") or "").strip()
            return PolicyDecision(
                requires_approval=True,
                operation="skills_local_uninstall",
                risk_level="medium",
                reason="卸载技能会移除本地能力包并让对应工具立即不可用，需要你确认。",
                details={
                    "skill_name": skill_name,
                    "version": version,
                    "origin": origin,
                },
            )

        if normalized_tool_name == "skills.marketplace.update":
            skill_name = str(arguments.get("skill_name") or "").strip()
            slug = str(arguments.get("slug") or "").strip()
            current_version = str(arguments.get("current_version") or "").strip()
            target_version = str(arguments.get("target_version") or arguments.get("tag") or "").strip()
            return PolicyDecision(
                requires_approval=True,
                operation="skills_marketplace_update",
                risk_level="medium",
                reason="更新技能会替换本地已安装内容，并改变后续对话可用的能力，需要先确认。",
                details={
                    "skill_name": skill_name,
                    "slug": slug,
                    "current_version": current_version,
                    "target_version": target_version,
                },
            )

        return PolicyDecision(
            requires_approval=False,
            operation="allow",
            risk_level="low",
            reason="当前工具不需要额外审批。",
            details={},
        )


_policy_gate: PolicyGate | None = None


def get_policy_gate() -> PolicyGate:
    global _policy_gate
    if _policy_gate is None:
        _policy_gate = PolicyGate()
    return _policy_gate
