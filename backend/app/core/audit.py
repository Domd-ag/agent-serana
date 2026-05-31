import json
from collections import Counter
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import AuditRecord
from app.core.schemas import AuditInsightsResponse, AuditRecordResponse


def append_audit_record(
    db: AsyncSession,
    entity_type: str,
    entity_id: str,
    event_type: str,
    summary: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    message_id: str | None = None,
    goal_id: str | None = None,
) -> None:
    db.add(
        AuditRecord(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            summary=summary,
            payload=json.dumps(payload, ensure_ascii=False) if payload else None,
            message_id=message_id,
            goal_id=goal_id,
        )
    )


async def load_audit_records(
    db: AsyncSession,
    entity_type: str,
    entity_id: str,
) -> list[AuditRecord]:
    result = await db.execute(
        select(AuditRecord)
        .where(
            AuditRecord.entity_type == entity_type,
            AuditRecord.entity_id == entity_id,
        )
        .order_by(AuditRecord.created_at.asc())
    )
    return list(result.scalars().all())


async def load_filtered_audit_records(
    db: AsyncSession,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
) -> list[AuditRecord]:
    query = select(AuditRecord).order_by(AuditRecord.created_at.asc()).limit(limit)

    if entity_type:
        query = query.where(AuditRecord.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditRecord.entity_id == entity_id)
    if event_type:
        query = query.where(AuditRecord.event_type == event_type)

    result = await db.execute(query)
    return list(result.scalars().all())


def serialize_audit_record(record: AuditRecord) -> AuditRecordResponse:
    payload = None
    if record.payload:
        try:
            raw = json.loads(record.payload)
            payload = raw if isinstance(raw, dict) else None
        except json.JSONDecodeError:
            payload = None

    return AuditRecordResponse(
        id=record.id,
        entity_type=record.entity_type,
        entity_id=record.entity_id,
        event_type=record.event_type,
        summary=record.summary,
        payload=payload,
        created_at=record.created_at,
    )


def build_audit_insights(records: list[AuditRecord]) -> AuditInsightsResponse:
    event_counts: Counter[str] = Counter()
    task_types: set[str] = set()
    strategies: set[str] = set()
    tool_names: set[str] = set()
    tool_result_names: set[str] = set()
    tool_result_statuses: set[str] = set()
    tool_result_schema_versions: set[str] = set()
    artifact_kinds: set[str] = set()
    loop_stages: set[str] = set()
    lightweight_routes: set[str] = set()
    loop_transition_targets: set[str] = set()
    planning_stages: set[str] = set()
    execution_modes: set[str] = set()
    retry_limits: set[int] = set()
    batch_sizes: set[int] = set()
    batch_counts: set[int] = set()
    parallel_slots: set[int] = set()
    parallel_forges: set[int] = set()
    agent_ids: set[str] = set()
    failed_event_types: set[str] = set()
    latest_event_at = None

    for record in records:
        event_counts[record.event_type] += 1
        if latest_event_at is None or (record.created_at and record.created_at > latest_event_at):
            latest_event_at = record.created_at

        payload = None
        if record.payload:
            try:
                raw_payload = json.loads(record.payload)
                payload = raw_payload if isinstance(raw_payload, dict) else None
            except json.JSONDecodeError:
                payload = None

        if not payload:
            continue

        payload_layers = [payload]
        for nested_key in ("input", "output"):
            nested_value = payload.get(nested_key)
            if isinstance(nested_value, dict):
                payload_layers.append(nested_value)
        tool_result = payload.get("tool_result")
        if not isinstance(tool_result, dict):
            output_payload = payload.get("output")
            if isinstance(output_payload, dict) and isinstance(output_payload.get("tool_result"), dict):
                tool_result = output_payload["tool_result"]
        if isinstance(tool_result, dict):
            payload_layers.append(tool_result)
            artifact = tool_result.get("artifact")
            if isinstance(artifact, dict):
                _collect_string(artifact_kinds, artifact.get("kind"))
            _collect_string(tool_result_names, tool_result.get("tool_name"))
            _collect_string(tool_result_statuses, tool_result.get("status"))
            _collect_string(tool_result_schema_versions, tool_result.get("schema_version"))

        for layer in payload_layers:
            _collect_string(task_types, layer.get("task_type"))
            _collect_string(strategies, layer.get("strategy"))
            _collect_string(tool_names, layer.get("tool_name"))
            _collect_string(execution_modes, layer.get("execution_mode"))
            _collect_int(retry_limits, layer.get("retry_limit"))
            _collect_int(batch_sizes, layer.get("batch_size"))
            _collect_int(batch_counts, layer.get("batch_count"))
            _collect_int(batch_counts, layer.get("batches_planned"))
            _collect_int(parallel_slots, layer.get("parallel_slots"))
            _collect_int(parallel_forges, layer.get("parallel_forges"))

            _collect_agent_ids(agent_ids, layer.get("agent_id"))
            _collect_agent_ids(agent_ids, layer.get("agent_ids"))

        event_type = str(record.event_type or "").strip()
        if event_type == "conversation_route":
            for layer in payload_layers:
                _collect_string(lightweight_routes, layer.get("route"))
        elif event_type == "serana_loop_stage":
            for layer in payload_layers:
                _collect_string(loop_stages, layer.get("stage"))
        elif event_type == "assistant_generation":
            for layer in payload_layers:
                _collect_string(lightweight_routes, layer.get("execution_mode"))
        elif event_type == "serana_loop_transition":
            for layer in payload_layers:
                _collect_string(loop_transition_targets, layer.get("next_stage"))
        elif event_type == "serana_planning_stage":
            for layer in payload_layers:
                _collect_string(planning_stages, layer.get("stage"))

        if _is_failed_payload(payload_layers):
            failed_event_types.add(record.event_type)

    return AuditInsightsResponse(
        event_counts=dict(event_counts),
        task_types=sorted(task_types),
        strategies=sorted(strategies),
        tool_names=sorted(tool_names),
        tool_result_names=sorted(tool_result_names),
        tool_result_statuses=sorted(tool_result_statuses),
        tool_result_schema_versions=sorted(tool_result_schema_versions),
        artifact_kinds=sorted(artifact_kinds),
        loop_stages=sorted(loop_stages),
        lightweight_routes=sorted(lightweight_routes),
        loop_transition_targets=sorted(loop_transition_targets),
        planning_stages=sorted(planning_stages),
        execution_modes=sorted(execution_modes),
        retry_limits=sorted(retry_limits),
        batch_sizes=sorted(batch_sizes),
        batch_counts=sorted(batch_counts),
        parallel_slots=sorted(parallel_slots),
        parallel_forges=sorted(parallel_forges),
        agent_ids=sorted(agent_ids),
        failed_event_types=sorted(failed_event_types),
        latest_event_at=latest_event_at,
    )


def _collect_string(target: set[str], value: Any) -> None:
    if value is None:
        return
    text = str(value).strip()
    if text:
        target.add(text)


def _collect_int(target: set[int], value: Any) -> None:
    if value is None:
        return
    try:
        target.add(int(value))
    except (TypeError, ValueError):
        return


def _collect_agent_ids(target: set[str], value: Any) -> None:
    if value is None:
        return
    if isinstance(value, list):
        for item in value:
            _collect_string(target, item)
        return
    _collect_string(target, value)


def _is_failed_payload(payload_layers: list[dict[str, Any]]) -> bool:
    for layer in payload_layers:
        if str(layer.get("success", "")).lower() == "false":
            return True
        if str(layer.get("status", "")).lower() == "failed":
            return True
    return False
