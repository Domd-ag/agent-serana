from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


TOOL_RESULT_SCHEMA_VERSION = "serana.tool_result.v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_tool_artifact(tool_output: dict[str, Any]) -> dict[str, Any] | None:
    artifact = tool_output.get("artifact")
    return artifact if isinstance(artifact, dict) else None


def build_tool_result(
    *,
    skill_name: str,
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: dict[str, Any],
    status: str,
    user_summary: str | None = None,
    result_type: str = "tool",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    full_tool_name = f"{skill_name}.{tool_name}"
    summary = str(
        user_summary
        or tool_output.get("summary")
        or tool_output.get("message")
        or tool_output.get("error")
        or ""
    ).strip()
    normalized_status = str(status or "completed").strip().lower()
    result: dict[str, Any] = {
        "schema_version": TOOL_RESULT_SCHEMA_VERSION,
        "result_type": result_type,
        "tool_name": full_tool_name,
        "skill": skill_name,
        "tool": tool_name,
        "input": tool_input,
        "output": tool_output,
        "status": normalized_status,
        "user_summary": summary,
        "created_at": utc_now_iso(),
    }
    artifact = extract_tool_artifact(tool_output)
    if artifact is not None:
        result["artifact"] = artifact
    if metadata:
        result["metadata"] = metadata
    return result


def attach_tool_result(tool_output: dict[str, Any], tool_result: dict[str, Any]) -> dict[str, Any]:
    return {
        **tool_output,
        "tool_result": tool_result,
    }


def append_tool_result(state: dict[str, Any], tool_result: dict[str, Any]) -> dict[str, Any]:
    tool_results = list(state.get("tool_results", []))
    tool_results.append(tool_result)
    return {**state, "tool_results": tool_results}
