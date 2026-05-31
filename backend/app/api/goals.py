import json
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.serana.runtime import prepare_serana_runtime
from app.core.audit import append_audit_record, build_audit_insights, load_audit_records, serialize_audit_record
from app.core import (
    Goal,
    GoalCreate,
    GoalDebugResponse,
    GoalDetailResponse,
    GoalEvent,
    GoalEventResponse,
    AuditRecordResponse,
    AuditTimelineResponse,
    GoalResponse,
    Subtask,
    SubtaskResponse,
    SubtaskStatusUpdate,
    User,
    get_current_llm_config,
    get_db,
    get_default_user,
    get_llm_gateway,
)
from app.core.schemas import ThinkingBlock
from app.memory import MemoryService

router = APIRouter(prefix="/goals", tags=["goals"])

ALLOWED_SUBTASK_STATUSES = {"pending", "in_progress", "completed", "failed"}


def _deserialize_json_object(raw_value: str | None) -> dict | None:
    if not raw_value:
        return None
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _serialize_goal_event(event: GoalEvent):
    return GoalEventResponse(
        id=event.id,
        event_type=event.event_type,
        summary=event.summary,
        details=_deserialize_json_object(event.details),
        created_at=event.created_at,
    )


def _serialize_goal(
    goal: Goal,
    subtasks: list[Subtask],
    events: list[GoalEvent],
    audit_records: list,
) -> GoalDetailResponse:
    return GoalDetailResponse(
        id=goal.id,
        description=goal.description,
        status=goal.status,
        progress=goal.progress,
        created_at=goal.created_at,
        completed_at=goal.completed_at,
        planning_summary=goal.planning_summary,
        thinking_blocks=_deserialize_thinking_blocks(goal.thinking_blocks),
        subtasks=[
            SubtaskResponse(
                id=subtask.id,
                description=subtask.description,
                status=subtask.status,
                order=subtask.order,
                created_at=subtask.created_at,
            )
            for subtask in subtasks
        ],
        events=[_serialize_goal_event(event) for event in events],
        audit_records=[serialize_audit_record(record) for record in audit_records],
    )


def _deserialize_thinking_blocks(raw_value: str | None) -> list[ThinkingBlock]:
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return []

    blocks: list[ThinkingBlock] = []
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            continue
        blocks.append(
            ThinkingBlock(
                id=str(item.get("id") or f"goal-thinking-{index}"),
                title=str(item.get("title") or "Thinking"),
                content=str(item.get("content") or ""),
                is_expanded=False,
            )
        )
    return blocks


async def _load_goal(db: AsyncSession, user_id: str, goal_id: str) -> Goal:
    result = await db.execute(
        select(Goal).where(
            Goal.id == goal_id,
            Goal.user_id == user_id,
        )
    )
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal


async def _load_subtasks(db: AsyncSession, goal_id: str) -> list[Subtask]:
    result = await db.execute(
        select(Subtask).where(Subtask.goal_id == goal_id).order_by(Subtask.order)
    )
    return list(result.scalars().all())


async def _load_goal_events(db: AsyncSession, goal_id: str) -> list[GoalEvent]:
    result = await db.execute(
        select(GoalEvent).where(GoalEvent.goal_id == goal_id).order_by(GoalEvent.created_at.asc())
    )
    return list(result.scalars().all())


def _append_goal_event(
    db: AsyncSession,
    goal_id: str,
    event_type: str,
    summary: str,
    details: dict | None = None,
) -> None:
    db.add(
        GoalEvent(
            goal_id=goal_id,
            event_type=event_type,
            summary=summary,
            details=json.dumps(details, ensure_ascii=False) if details else None,
        )
    )
    append_audit_record(
        db,
        entity_type="goal",
        entity_id=goal_id,
        event_type=event_type,
        summary=summary,
        payload=details,
        goal_id=goal_id,
    )


def _append_serana_audit_records(
    db: AsyncSession,
    goal_id: str,
    thinking_blocks: list[dict],
    tool_calls: list[dict],
) -> None:
    for block in thinking_blocks:
        title = str(block.get("title") or "Thinking")
        content = str(block.get("content") or "")
        append_audit_record(
            db,
            entity_type="goal",
            entity_id=goal_id,
            event_type="serana_thinking_block",
            summary=f"Serana thinking block: {title}",
            payload={
                "thinking_block_id": block.get("id"),
                "title": title,
                "content": content,
                "timestamp": block.get("timestamp"),
            },
            goal_id=goal_id,
        )

    for tool_call in tool_calls:
        name = str(tool_call.get("name") or "serana_step")
        append_audit_record(
            db,
            entity_type="goal",
            entity_id=goal_id,
            event_type=name,
            summary=f"Serana execution step: {name}",
            payload={
                "tool_call_id": tool_call.get("id"),
                "input": tool_call.get("input"),
                "output": tool_call.get("output"),
                "status": tool_call.get("status"),
                "timestamp": tool_call.get("timestamp"),
            },
            goal_id=goal_id,
        )


def _normalize_subtasks(
    raw_subtasks: list[dict],
    execution_mode: str,
    goal_description: str,
    planning_summary: str | None,
) -> list[dict]:
    if execution_mode == "direct":
        direct_description = planning_summary or goal_description
        return [
            {
                "description": f"Handle directly with Serana: {direct_description}",
                "status": "completed",
            }
        ]

    if not raw_subtasks:
        return [
            {"description": "Clarify the task requirements", "status": "pending"},
            {"description": "Prepare an execution plan", "status": "pending"},
            {"description": "Execute and review the plan", "status": "pending"},
        ]

    normalized = []
    for item in raw_subtasks:
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        normalized.append(
            {
                "description": description,
                # Goal creation is planning, not execution.
                "status": "pending",
            }
        )

    return normalized or [
        {"description": "Clarify the task requirements", "status": "pending"},
        {"description": "Prepare an execution plan", "status": "pending"},
        {"description": "Execute and review the plan", "status": "pending"},
    ]


def _recalculate_goal_fields(goal: Goal, subtasks: list[Subtask]) -> None:
    if not subtasks:
        goal.progress = 0.0
        goal.status = "pending"
        goal.completed_at = None
        return

    completed = sum(1 for subtask in subtasks if subtask.status == "completed")
    failed = any(subtask.status == "failed" for subtask in subtasks)
    in_progress = any(subtask.status == "in_progress" for subtask in subtasks)

    goal.progress = completed / len(subtasks)

    if completed == len(subtasks):
        goal.status = "completed"
        goal.completed_at = goal.completed_at or datetime.now(timezone.utc)
    elif failed:
        goal.status = "failed"
        goal.completed_at = None
    elif in_progress or completed > 0:
        goal.status = "in_progress"
        goal.completed_at = None
    else:
        goal.status = "pending"
        goal.completed_at = None


async def _sync_goal_working_memory(
    db: AsyncSession,
    user_id: str,
    goal: Goal,
    subtasks: list[Subtask],
) -> None:
    memory_service = MemoryService(db, user_id)

    if goal.status in {"completed", "failed"}:
        await memory_service.clear_working_memory(scope="goal", goal_id=goal.id)
        return

    await memory_service.save_working_memory(
        key="goal_brief",
        value=goal.description,
        scope="goal",
        goal_id=goal.id,
        source="goal_runtime",
        priority=1.0,
    )

    if goal.planning_summary:
        await memory_service.save_working_memory(
            key="goal_plan",
            value=goal.planning_summary,
            scope="goal",
            goal_id=goal.id,
            source="goal_runtime",
            priority=0.95,
        )

    await memory_service.save_working_memory(
        key="goal_progress",
        value=f"status={goal.status}; progress={goal.progress:.2f}",
        scope="goal",
        goal_id=goal.id,
        source="goal_runtime",
        priority=0.85,
    )

    current_subtask = next((subtask for subtask in subtasks if subtask.status == "in_progress"), None)
    if current_subtask:
        await memory_service.save_working_memory(
            key="current_subtask",
            value=current_subtask.description,
            scope="goal",
            goal_id=goal.id,
            source="goal_runtime",
            priority=0.9,
        )
    else:
        await memory_service.working.delete_entry(
            key="current_subtask",
            scope="goal",
            goal_id=goal.id,
        )


@router.post("", response_model=GoalDetailResponse)
async def create_goal(
    goal_create: GoalCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
    llm_config: dict = Depends(get_current_llm_config),
):
    goal = Goal(
        user_id=user.id,
        description=goal_create.description,
        status="pending",
        progress=0.0,
    )
    db.add(goal)
    await db.commit()
    await db.refresh(goal)

    prepared = await prepare_serana_runtime(
        db=db,
        user=user,
        user_input=goal_create.description,
        llm_config=llm_config,
        scope="goal",
        goal_id=goal.id,
        gateway_factory=get_llm_gateway,
    )
    result = await prepared.serana_agent.execute_goal(
        goal_create.description,
        session_id=goal.id,
        memory_context=prepared.memory_context,
        resident_memory_context=prepared.resident_memory_context,
        working_memory_context=prepared.working_memory_context,
    )
    goal.planning_summary = result.get("summary")
    thinking_blocks = result.get("thinking_blocks", [])
    serana_tool_calls = result.get("tool_calls", [])
    execution_mode = str(result.get("execution_mode") or "delegated")
    goal.thinking_blocks = json.dumps(thinking_blocks, ensure_ascii=False)

    subtasks_data = _normalize_subtasks(
        result.get("subtasks", []),
        execution_mode=execution_mode,
        goal_description=goal_create.description,
        planning_summary=goal.planning_summary,
    )

    for index, subtask_data in enumerate(subtasks_data):
        db.add(
            Subtask(
                goal_id=goal.id,
                description=subtask_data["description"],
                status=subtask_data["status"],
                order=index,
            )
        )

    if execution_mode == "direct":
        goal.status = "completed"
        goal.progress = 1.0
        goal.completed_at = datetime.now(timezone.utc)

    _append_serana_audit_records(
        db=db,
        goal_id=goal.id,
        thinking_blocks=thinking_blocks,
        tool_calls=serana_tool_calls,
    )

    _append_goal_event(
        db,
        goal.id,
        "planned",
        (
            "Completed goal directly with Serana."
            if execution_mode == "direct"
            else f"Planned goal with {len(subtasks_data)} subtasks."
        ),
        {
            "goal_status": goal.status,
            "execution_mode": execution_mode,
            "subtask_count": len(subtasks_data),
            "planning_summary": goal.planning_summary,
        },
    )

    await db.commit()
    await db.refresh(goal)
    subtasks = await _load_subtasks(db, goal.id)
    events = await _load_goal_events(db, goal.id)
    audit_records = await load_audit_records(db, "goal", goal.id)
    _recalculate_goal_fields(goal, subtasks)
    await _sync_goal_working_memory(db, user.id, goal, subtasks)
    await db.commit()
    await db.refresh(goal)

    return _serialize_goal(goal, subtasks, events, audit_records)


@router.get("", response_model=List[GoalResponse])
async def list_goals(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    result = await db.execute(
        select(Goal)
        .where(Goal.user_id == user.id)
        .order_by(desc(Goal.created_at))
    )
    goals = result.scalars().all()

    return [
        GoalResponse(
            id=goal.id,
            description=goal.description,
            status=goal.status,
            progress=goal.progress,
            created_at=goal.created_at,
            completed_at=goal.completed_at,
        )
        for goal in goals
    ]


@router.get("/{goal_id}", response_model=GoalDetailResponse)
async def get_goal(
    goal_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    goal = await _load_goal(db, user.id, goal_id)
    subtasks = await _load_subtasks(db, goal.id)
    events = await _load_goal_events(db, goal.id)
    audit_records = await load_audit_records(db, "goal", goal.id)
    return _serialize_goal(goal, subtasks, events, audit_records)


@router.get("/{goal_id}/events", response_model=List[GoalEventResponse])
async def list_goal_events(
    goal_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    goal = await _load_goal(db, user.id, goal_id)
    events = await _load_goal_events(db, goal.id)
    return [_serialize_goal_event(event) for event in events]


@router.get("/{goal_id}/audit", response_model=List[AuditRecordResponse])
async def list_goal_audit_records(
    goal_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    goal = await _load_goal(db, user.id, goal_id)
    records = await load_audit_records(db, "goal", goal.id)
    return [serialize_audit_record(record) for record in records]


@router.get("/{goal_id}/debug", response_model=GoalDebugResponse)
async def get_goal_debug(
    goal_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    goal = await _load_goal(db, user.id, goal_id)
    subtasks = await _load_subtasks(db, goal.id)
    events = await _load_goal_events(db, goal.id)
    audit_records = await load_audit_records(db, "goal", goal.id)
    goal_payload = _serialize_goal(goal, subtasks, events, audit_records)
    timeline = AuditTimelineResponse(
        entity_type="goal",
        entity_id=goal.id,
        total_records=len(audit_records),
        insights=build_audit_insights(audit_records),
        records=[serialize_audit_record(record) for record in audit_records],
    )
    return GoalDebugResponse(
        goal=goal_payload,
        audit_timeline=timeline,
        audit_summary=timeline.insights,
    )


@router.delete("/{goal_id}")
async def delete_goal(
    goal_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    goal = await _load_goal(db, user.id, goal_id)
    memory_service = MemoryService(db, user.id)
    await memory_service.clear_working_memory(scope="goal", goal_id=goal.id)
    await db.delete(goal)
    await db.commit()
    return {"status": "success", "message": "Goal deleted"}


@router.post("/{goal_id}/start", response_model=GoalDetailResponse)
async def start_goal(
    goal_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    goal = await _load_goal(db, user.id, goal_id)
    subtasks = await _load_subtasks(db, goal.id)
    previous_status = goal.status

    if not subtasks:
        raise HTTPException(status_code=400, detail="Goal has no subtasks")

    first_pending = next((subtask for subtask in subtasks if subtask.status == "pending"), None)
    if first_pending:
        first_pending.status = "in_progress"
        _append_goal_event(
            db,
            goal.id,
            "started",
            f"Started goal execution with subtask: {first_pending.description}",
            {
                "goal_status_before": previous_status,
                "goal_status_after": "in_progress",
                "subtask_id": first_pending.id,
                "subtask_status": first_pending.status,
            },
        )

    _recalculate_goal_fields(goal, subtasks)
    await _sync_goal_working_memory(db, user.id, goal, subtasks)
    await db.commit()
    await db.refresh(goal)
    events = await _load_goal_events(db, goal.id)
    audit_records = await load_audit_records(db, "goal", goal.id)

    return _serialize_goal(goal, subtasks, events, audit_records)


@router.post("/{goal_id}/subtasks/{subtask_id}", response_model=GoalDetailResponse)
async def update_subtask_status(
    goal_id: str,
    subtask_id: str,
    update: SubtaskStatusUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    goal = await _load_goal(db, user.id, goal_id)
    subtasks = await _load_subtasks(db, goal.id)
    previous_goal_status = goal.status
    previous_progress = goal.progress
    target = next((subtask for subtask in subtasks if subtask.id == subtask_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Subtask not found")

    new_status = update.status.strip().lower()
    if new_status not in ALLOWED_SUBTASK_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid subtask status")

    previous_subtask_status = target.status
    target.status = new_status
    _append_goal_event(
        db,
        goal.id,
        "subtask_updated",
        f"Updated subtask '{target.description}' from {previous_subtask_status} to {new_status}.",
        {
            "subtask_id": target.id,
            "subtask_description": target.description,
            "previous_status": previous_subtask_status,
            "new_status": new_status,
        },
    )

    if new_status == "completed":
        next_pending = next(
            (subtask for subtask in subtasks if subtask.id != target.id and subtask.status == "pending"),
            None,
        )
        if next_pending:
            next_pending.status = "in_progress"
            _append_goal_event(
                db,
                goal.id,
                "subtask_auto_started",
                f"Automatically started next subtask: {next_pending.description}",
                {
                    "subtask_id": next_pending.id,
                    "subtask_description": next_pending.description,
                    "new_status": next_pending.status,
                },
            )

    _recalculate_goal_fields(goal, subtasks)
    if goal.status != previous_goal_status or goal.progress != previous_progress:
        _append_goal_event(
            db,
            goal.id,
            "goal_progress_updated",
            f"Goal status is now {goal.status} with progress {goal.progress:.2f}.",
            {
                "previous_status": previous_goal_status,
                "new_status": goal.status,
                "previous_progress": previous_progress,
                "new_progress": goal.progress,
            },
        )
    await _sync_goal_working_memory(db, user.id, goal, subtasks)
    await db.commit()
    await db.refresh(goal)
    events = await _load_goal_events(db, goal.id)
    audit_records = await load_audit_records(db, "goal", goal.id)

    return _serialize_goal(goal, subtasks, events, audit_records)
