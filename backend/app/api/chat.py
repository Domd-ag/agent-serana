import asyncio
import inspect
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.service import resolve_approval_decision
from app.agents.serana.runtime import prepare_serana_runtime
from app.core import (
    AgentSession,
    AsyncSessionLocal,
    ApprovalResponse,
    AuditRecord,
    AuditRecordResponse,
    AuditTimelineResponse,
    ChatDebugResponse,
    ChatCompletionResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSession,
    ChatSessionCreate,
    ChatSessionResponse,
    Message,
    ThinkingBlock,
    ToolCall,
    User,
    get_current_llm_config,
    get_db,
    get_default_user,
    get_llm_gateway,
)
from app.core.audit import append_audit_record, build_audit_insights, load_audit_records, serialize_audit_record
from app.core.logger import get_logger
from app.core.models import MemoryArtifact, WorkingMemory
from app.memory import MemoryService
from app.memory.background import schedule_memory_task
from app.skills import SkillManager

router = APIRouter(prefix="/chat", tags=["chat"])
logger = get_logger(__name__)


def _is_explicit_skill_invocation(user_input: str) -> bool:
    return str(user_input or "").lstrip().startswith("@")


def _split_explicit_skill_command(user_input: str) -> tuple[str, str]:
    text = str(user_input or "").strip()
    without_marker = text[1:].strip() if text.startswith("@") else text
    if not without_marker:
        return "", ""
    parts = without_marker.split(maxsplit=1)
    command = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else ""
    return command, rest


def _invocation_examples_for_message(skill) -> str:
    examples = list(skill.invocation_examples or [])
    if examples:
        return "\n".join(f"- `{example}`" for example in examples[:3])
    return f"- `@{skill.name}`"


def _build_skill_invocation_help(user_input: str) -> tuple[str, list[ThinkingBlock], list[ToolCall], str, dict] | None:
    if not _is_explicit_skill_invocation(user_input):
        return None

    command, _ = _split_explicit_skill_command(user_input)
    manager = SkillManager()
    manager.ensure_initialized()
    if not command:
        invocable = manager.list_invocable_executable_skills()
        if not invocable:
            message = "现在没有可以用 `@` 直接调用的 python/script 技能。"
        else:
            examples = "\n".join(
                f"- `{(skill.invocation_examples or [f'@{skill.name}'])[0]}`"
                for skill in invocable[:6]
            )
            message = f"可以直接调用这些技能：\n{examples}"
        return message, [], [], "skill_invocation", {}

    skill, candidates = manager.resolve_invocation_skill(command)
    if skill is not None:
        return None

    if candidates:
        examples = "\n".join(
            f"- `{(candidate.invocation_examples or [f'@{candidate.name}'])[0]}`"
            for candidate in candidates[:6]
        )
        message = f"`@{command}` 可以匹配多个技能，请选一个完整名称：\n{examples}"
    else:
        message = (
            f"没有找到可以直接调用的 `@{command}` 技能。"
            "只有已启用的 python/script 技能支持 `@技能名 参数...`。"
        )
    return message, [], [], "skill_invocation", {}


def _coerce_explicit_skill_arguments(skill, tool, argument_text: str) -> tuple[dict, str | None]:
    parameters = list(skill.invocation_parameters or [])
    schema = tool.input_schema
    required_names = [str(name) for name in (schema.required or [])]
    ordered_names = [str(parameter.get("name")) for parameter in parameters if parameter.get("name")]
    ordered_names = list(dict.fromkeys([*ordered_names, *required_names, *list((schema.properties or {}).keys())]))
    if not ordered_names:
        return {}, None

    required_count = len(required_names)
    raw_values: list[str]
    if len(ordered_names) == 1:
        raw_values = [argument_text.strip()] if argument_text.strip() else []
    else:
        raw_values = argument_text.split(maxsplit=max(0, len(ordered_names) - 1))

    if len(raw_values) < required_count or any(not value.strip() for value in raw_values[:required_count]):
        example = (skill.invocation_examples or [f"@{skill.name} " + " ".join(f"<{name}>" for name in ordered_names)])[0]
        parameter_names = "、".join(required_names or ordered_names)
        return {}, f"`{skill.name}` 需要 {len(required_names or ordered_names)} 个参数：{parameter_names}。\n示例：`{example}`"

    properties = dict(schema.properties or {})
    arguments = {}
    for name, raw_value in zip(ordered_names, raw_values):
        value = raw_value.strip()
        expected = str((properties.get(name) or {}).get("type") or "string").lower()
        if expected == "integer":
            try:
                arguments[name] = int(value)
            except ValueError:
                return {}, f"`{name}` 需要整数，当前收到：`{value}`。"
        elif expected == "number":
            try:
                arguments[name] = float(value)
            except ValueError:
                return {}, f"`{name}` 需要数字，当前收到：`{value}`。"
        elif expected == "boolean":
            lowered = value.lower()
            if lowered not in {"true", "false", "1", "0", "yes", "no", "是", "否"}:
                return {}, f"`{name}` 需要布尔值，当前收到：`{value}`。"
            arguments[name] = lowered in {"true", "1", "yes", "是"}
        else:
            arguments[name] = value
    return arguments, None


def _format_explicit_skill_output(output) -> str:
    if isinstance(output, dict):
        for key in ("summary", "content", "result", "text", "message"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return json.dumps(output, ensure_ascii=False, indent=2)
    if output is None:
        return "技能执行完成，但没有返回可展示内容。"
    return str(output).strip()


async def _try_explicit_skill_invocation(
    user_input: str,
) -> tuple[str, list[ThinkingBlock], list[ToolCall], bool, str, dict] | None:
    help_payload = _build_skill_invocation_help(user_input)
    if help_payload is not None:
        message, thinking_blocks, tool_calls, execution_mode, delegation_plan = help_payload
        return message, thinking_blocks, tool_calls, False, execution_mode, delegation_plan

    if not _is_explicit_skill_invocation(user_input):
        return None

    command, argument_text = _split_explicit_skill_command(user_input)
    manager = SkillManager()
    manager.ensure_initialized()
    skill, _ = manager.resolve_invocation_skill(command)
    if skill is None:
        return None
    if not skill.manifest.tools:
        return (
            f"`{skill.name}` 没有声明可调用工具，不能通过 `@` 执行。",
            [],
            [],
            False,
            "skill_invocation",
            {},
        )
    tool = skill.manifest.tools[0]
    arguments, error = _coerce_explicit_skill_arguments(skill, tool, argument_text)
    if error:
        return error, [], [], False, "skill_invocation", {}

    tool_func = manager.get_tool_function(skill.name, tool.name)
    if tool_func is None:
        return (
            f"`{skill.name}` 已安装，但当前运行时没有注册 `{tool.name}`。请重新安装或重启后端。",
            [],
            [],
            False,
            "skill_invocation",
            {},
        )

    timestamp = datetime.now(timezone.utc).isoformat()
    thinking_blocks = [
        ThinkingBlock(
            id=f"skill-invocation-{skill.name}",
            title="技能调用",
            content=f"使用 @{skill.name} 调用 {tool.name}，参数：{arguments}",
            timestamp=timestamp,
            is_expanded=False,
        )
    ]
    try:
        maybe_result = tool_func(**arguments)
        result = await maybe_result if inspect.isawaitable(maybe_result) else maybe_result
        content = _format_explicit_skill_output(result)
        status = "completed"
        output = result
    except Exception as exc:
        content = f"`{skill.name}` 执行失败：{exc}"
        status = "failed"
        output = {"error": str(exc)}

    tool_calls = [
        ToolCall(
            id=f"skill-tool-{skill.name}-{tool.name}",
            name=f"{skill.name}.{tool.name}",
            input=arguments,
            output=output,
            status=status,
            timestamp=timestamp,
        )
    ]
    return content, thinking_blocks, tool_calls, False, "skill_invocation", {}


async def _run_memory_consolidation(
    *,
    chat_session_id: str,
    assistant_message_id: str,
    user_input: str,
    assistant_content: str,
    user_id: str,
    llm_config: dict | None,
) -> None:
    async with AsyncSessionLocal() as db:
        memory_service = MemoryService(db, user_id)
        consolidation_llm = None
        if llm_config:
            try:
                consolidation_llm = get_llm_gateway().get_llm(
                    user_config=llm_config["user_config"],
                    use_backend_default=llm_config["use_backend_default"],
                )
            except Exception:
                logger.exception("Memory consolidation LLM unavailable; falling back to rule extraction")

        try:
            consolidation_result = await memory_service.consolidate_chat_turn(
                user_input=user_input,
                session_id=chat_session_id,
                assistant_content=assistant_content,
                llm=consolidation_llm,
            )
            if consolidation_result["candidate_count"] or consolidation_result.get("artifact_candidate_count"):
                append_audit_record(
                    db,
                    entity_type="chat_session",
                    entity_id=chat_session_id,
                    event_type="memory_consolidation",
                    summary="Consolidated stable user context into long-term memory",
                    payload=consolidation_result,
                    message_id=assistant_message_id,
                )
                await db.commit()
        except Exception:
            logger.exception("Background memory consolidation failed for session %s", chat_session_id)


async def _delete_session_data(db: AsyncSession, session_ids: list[str]) -> int:
    if not session_ids:
        return 0

    message_result = await db.execute(
        select(Message.id).where(Message.session_id.in_(session_ids))
    )
    message_ids = [row[0] for row in message_result.all()]

    if message_ids:
        await db.execute(
            delete(AuditRecord).where(AuditRecord.message_id.in_(message_ids))
        )

    await db.execute(
        delete(AuditRecord).where(
            AuditRecord.entity_type == "chat_session",
            AuditRecord.entity_id.in_(session_ids),
        )
    )
    await db.execute(
        delete(AgentSession).where(AgentSession.chat_session_id.in_(session_ids))
    )
    await db.execute(
        delete(MemoryArtifact).where(MemoryArtifact.session_id.in_(session_ids))
    )
    await db.execute(
        delete(WorkingMemory).where(WorkingMemory.session_id.in_(session_ids))
    )
    await db.execute(
        delete(Message).where(Message.session_id.in_(session_ids))
    )
    await db.execute(
        delete(ChatSession).where(ChatSession.id.in_(session_ids))
    )
    return len(session_ids)


def _deserialize_thinking_blocks(raw_value: Optional[str]) -> list[ThinkingBlock]:
    if not raw_value:
        return []
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [ThinkingBlock.model_validate(item) for item in payload]


def _deserialize_tool_calls(raw_value: Optional[str]) -> list[ToolCall]:
    if not raw_value:
        return []
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [ToolCall.model_validate(item) for item in payload]


def _serialize_message(message: Message) -> ChatMessageResponse:
    thinking_blocks = _deserialize_thinking_blocks(message.thinking_blocks)
    tool_calls = _deserialize_tool_calls(message.tool_calls)
    return ChatMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        timestamp=_serialize_message_timestamp(message.created_at),
        thinking_blocks=thinking_blocks or None,
        tool_calls=tool_calls or None,
    )


def _serialize_message_timestamp(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


async def _get_or_create_session(
    db: AsyncSession,
    user: User,
    requested_session_id: Optional[str],
    first_message_content: str,
) -> ChatSession:
    if requested_session_id:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == requested_session_id,
                ChatSession.user_id == user.id,
            )
        )
        chat_session = result.scalar_one_or_none()
        if not chat_session:
            raise HTTPException(status_code=404, detail="Chat session not found")
        return chat_session

    chat_session = ChatSession(
        user_id=user.id,
        title=first_message_content[:50] + "..." if len(first_message_content) > 50 else first_message_content,
    )
    db.add(chat_session)
    await db.commit()
    await db.refresh(chat_session)
    return chat_session


async def _generate_assistant_payload(
    db: AsyncSession,
    user: User,
    user_input: str,
    session_id: str,
    llm_config: dict,
) -> tuple[str, list[ThinkingBlock], list[ToolCall], bool, str, dict]:
    tool_calls: list[ToolCall] = []
    thinking_blocks: list[ThinkingBlock] = []
    memory_context_included = False
    timestamp = datetime.now(timezone.utc).isoformat()

    explicit_skill_result = await _try_explicit_skill_invocation(user_input)
    if explicit_skill_result is not None:
        return explicit_skill_result

    try:
        prepared = await prepare_serana_runtime(
            db=db,
            user=user,
            user_input=user_input,
            session_id=session_id,
            llm_config=llm_config,
            scope="chat",
            gateway_factory=get_llm_gateway,
        )
        tool_calls = list(prepared.tool_calls)
        thinking_blocks = list(prepared.thinking_blocks)
        memory_context_included = prepared.memory_context_included
        serana_result = await prepared.serana_agent.execute(
            user_input,
            session_id=session_id,
            memory_context=prepared.memory_context,
            recent_history_context=prepared.recent_history_context,
            resident_memory_context=prepared.resident_memory_context,
            working_memory_context=prepared.working_memory_context,
        )
        execution_mode = str(serana_result.get("execution_mode") or "direct")
        delegation_plan = dict(serana_result.get("delegation_plan") or {})

        thinking_blocks.extend(
            ThinkingBlock(
                id=str(block.get("id") or f"serana-thinking-{index}"),
                title=str(block.get("title") or "Thinking"),
                content=str(block.get("content") or ""),
                timestamp=str(block.get("timestamp") or datetime.now(timezone.utc).isoformat()),
                is_expanded=False,
            )
            for index, block in enumerate(serana_result.get("thinking_blocks", []))
            if isinstance(block, dict)
        )

        tool_calls.extend(
            ToolCall(
                id=str(tool_call.get("id") or f"serana-tool-{index}"),
                name=str(tool_call.get("name") or "serana_step"),
                input=dict(tool_call.get("input") or {}),
                output=tool_call.get("output"),
                status=str(tool_call.get("status") or "completed"),
                timestamp=str(tool_call.get("timestamp") or prepared.timestamp),
            )
            for index, tool_call in enumerate(serana_result.get("tool_calls", []))
            if isinstance(tool_call, dict)
        )

        summary = str(serana_result.get("summary") or "").strip()
        if summary:
            tool_calls.append(
                ToolCall(
                    id="assistant-generation",
                    name="assistant_generation",
                    input={
                        "execution_mode": execution_mode,
                        "used_memory_context": memory_context_included,
                    },
                    output={
                        "response_preview": summary[:200],
                        "delegation_plan": delegation_plan,
                    },
                    status="completed",
                    timestamp=prepared.timestamp,
                )
            )
            return (
                summary,
                thinking_blocks,
                tool_calls,
                memory_context_included,
                execution_mode,
                delegation_plan,
            )
    except ValueError as exc:
        logger.warning("LLM configuration unavailable for chat session %s: %s", session_id, exc)
        thinking_blocks.append(
            ThinkingBlock(
                id="assistant-fallback",
                title="Fallback",
                content="No active LLM configuration is available.",
                is_expanded=False,
            )
        )
        tool_calls.append(
            ToolCall(
                id="assistant-generation",
                name="assistant_generation",
                input={"used_memory_context": memory_context_included},
                output={"error": str(exc)},
                status="failed",
                timestamp=timestamp,
            )
        )
    except Exception as exc:
        logger.exception("Chat assistant generation failed for session %s", session_id)
        thinking_blocks.append(
            ThinkingBlock(
                id="assistant-fallback",
                title="Fallback",
                content=f"Primary agent execution failed: {exc}",
                is_expanded=False,
            )
        )
        tool_calls.append(
            ToolCall(
                id="assistant-generation",
                name="assistant_generation",
                input={"used_memory_context": memory_context_included},
                output={"error": str(exc)},
                status="failed",
                timestamp=timestamp,
            )
        )

    if memory_context_included:
        return (
            "I found related context in your saved profile and recent history, but the main model is not fully available right now. "
            "Your message has been stored and the app can continue once an LLM configuration is ready.",
            thinking_blocks,
            tool_calls,
            memory_context_included,
            "direct",
            {},
        )

    return (
        "Your message has been saved, but no active LLM configuration is available yet. "
        "Save an LLM configuration in settings to enable full responses.",
        thinking_blocks,
        tool_calls,
        memory_context_included,
        "direct",
        {},
    )


async def _prepare_serana_chat_execution(
    db: AsyncSession,
    user: User,
    user_input: str,
    session_id: str,
    llm_config: dict,
) -> dict:
    prepared = await prepare_serana_runtime(
        db=db,
        user=user,
        user_input=user_input,
        session_id=session_id,
        llm_config=llm_config,
        scope="chat",
        gateway_factory=get_llm_gateway,
    )
    return {
        "serana_agent": prepared.serana_agent,
        "memory_service": prepared.memory_service,
        "memory_context": prepared.memory_context,
        "recent_history_context": prepared.recent_history_context,
        "resident_memory_context": prepared.resident_memory_context,
        "working_memory_context": prepared.working_memory_context,
        "memory_context_included": prepared.memory_context_included,
        "thinking_blocks": prepared.thinking_blocks,
        "tool_calls": prepared.tool_calls,
        "timestamp": prepared.timestamp,
    }


async def _persist_assistant_result(
    db: AsyncSession,
    *,
    chat_session: ChatSession,
    assistant_content: str,
    thinking_blocks: list[ThinkingBlock],
    tool_calls: list[ToolCall],
    user_input: str,
    user_id: str,
    memory_context_included: bool,
    execution_mode: str,
    delegation_plan: dict,
    llm_config: dict | None = None,
) -> tuple[Message, list]:
    assistant_message = Message(
        session_id=chat_session.id,
        role="assistant",
        content=assistant_content,
        thinking_blocks=json.dumps(
            [block.model_dump() for block in thinking_blocks],
            ensure_ascii=False,
        ),
        tool_calls=json.dumps(
            [tool_call.model_dump() for tool_call in tool_calls],
            ensure_ascii=False,
        ),
    )
    db.add(assistant_message)

    for tool_call in tool_calls:
        tool_result = None
        if isinstance(tool_call.output, dict):
            maybe_tool_result = tool_call.output.get("tool_result")
            if isinstance(maybe_tool_result, dict):
                tool_result = maybe_tool_result
        append_audit_record(
            db,
            entity_type="chat_session",
            entity_id=chat_session.id,
            event_type=tool_call.name,
            summary=f"Executed chat trace step: {tool_call.name}",
            payload={
                "message_id": assistant_message.id,
                "status": tool_call.status,
                "input": tool_call.input,
                "output": tool_call.output,
                "tool_result": tool_result,
                "timestamp": tool_call.timestamp,
            },
            message_id=assistant_message.id,
        )

    await db.commit()
    await db.refresh(assistant_message)
    await db.refresh(chat_session)

    schedule_memory_task(
        _run_memory_consolidation(
            chat_session_id=chat_session.id,
            assistant_message_id=assistant_message.id,
            user_input=user_input,
            assistant_content=assistant_content,
            user_id=user_id,
            llm_config=llm_config,
        )
    )

    audit_records = await load_audit_records(db, "chat_session", chat_session.id)
    return assistant_message, audit_records


async def _persist_streamed_assistant_result(
    *,
    chat_session_id: str,
    assistant_content: str,
    thinking_blocks: list[ThinkingBlock],
    tool_calls: list[ToolCall],
    user_input: str,
    user_id: str,
    memory_context_included: bool,
    execution_mode: str,
    delegation_plan: dict,
    llm_config: dict | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ChatSession).where(ChatSession.id == chat_session_id))
        chat_session = result.scalar_one_or_none()
        if not chat_session:
            logger.warning("Skipped streamed assistant persistence for missing session %s", chat_session_id)
            return

        try:
            await _persist_assistant_result(
                db,
                chat_session=chat_session,
                assistant_content=assistant_content,
                thinking_blocks=thinking_blocks,
                tool_calls=tool_calls,
                user_input=user_input,
                user_id=user_id,
                memory_context_included=memory_context_included,
                execution_mode=execution_mode,
                delegation_plan=delegation_plan,
                llm_config=llm_config,
            )
        except Exception:
            logger.exception("Background streamed assistant persistence failed for session %s", chat_session_id)


@router.post("/session", response_model=ChatSessionResponse)
async def create_chat_session(
    session_create: Optional[ChatSessionCreate] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    title = session_create.title if session_create else "New Conversation"

    chat_session = ChatSession(
        user_id=user.id,
        title=title,
    )
    db.add(chat_session)
    await db.commit()
    await db.refresh(chat_session)

    return ChatSessionResponse(
        id=chat_session.id,
        title=chat_session.title,
        created_at=chat_session.created_at,
        updated_at=chat_session.updated_at,
    )


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_chat_sessions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user.id)
        .order_by(desc(ChatSession.updated_at))
    )
    sessions = result.scalars().all()

    return [
        ChatSessionResponse(
            id=session.id,
            title=session.title,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
        for session in sessions
    ]


@router.delete("/sessions/{session_id}")
async def delete_chat_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    session_result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
        )
    )
    chat_session = session_result.scalar_one_or_none()
    if not chat_session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    await _delete_session_data(db, [chat_session.id])
    await db.commit()
    return {"success": True}


@router.delete("/sessions")
async def clear_chat_sessions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    result = await db.execute(
        select(ChatSession.id).where(ChatSession.user_id == user.id)
    )
    session_ids = [row[0] for row in result.all()]
    deleted_count = await _delete_session_data(db, session_ids)
    await db.commit()
    return {"success": True, "deleted_count": deleted_count}


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
async def list_chat_messages(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    session_result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
        )
    )
    chat_session = session_result.scalar_one_or_none()
    if not chat_session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    message_result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
    )
    messages = message_result.scalars().all()
    return [_serialize_message(message) for message in messages]


@router.get("/sessions/{session_id}/audit", response_model=list[AuditRecordResponse])
async def list_chat_audit_records(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    session_result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
        )
    )
    chat_session = session_result.scalar_one_or_none()
    if not chat_session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    records = await load_audit_records(db, "chat_session", chat_session.id)
    return [serialize_audit_record(record) for record in records]


@router.get("/sessions/{session_id}/debug", response_model=ChatDebugResponse)
async def get_chat_debug(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
):
    session_result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
        )
    )
    chat_session = session_result.scalar_one_or_none()
    if not chat_session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    message_result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
    )
    messages = list(message_result.scalars().all())
    audit_records = await load_audit_records(db, "chat_session", chat_session.id)
    timeline = AuditTimelineResponse(
        entity_type="chat_session",
        entity_id=chat_session.id,
        total_records=len(audit_records),
        insights=build_audit_insights(audit_records),
        records=[serialize_audit_record(record) for record in audit_records],
    )
    return ChatDebugResponse(
        session=ChatSessionResponse(
            id=chat_session.id,
            title=chat_session.title,
            created_at=chat_session.created_at,
            updated_at=chat_session.updated_at,
        ),
        messages=[_serialize_message(message) for message in messages],
        audit_timeline=timeline,
        audit_summary=timeline.insights,
    )


@router.post("/approvals/{request_id}", response_model=ApprovalResponse)
async def submit_chat_approval(
    request_id: str,
    approval_response: ApprovalResponse,
    db: AsyncSession = Depends(get_db),
):
    return await resolve_approval_decision(
        request_id=request_id,
        approval_response=approval_response,
        db=db,
    )


@router.post("/message")
async def send_chat_message(
    message_request: ChatMessageRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_default_user),
    llm_config: dict = Depends(get_current_llm_config),
):
    chat_session = await _get_or_create_session(
        db=db,
        user=user,
        requested_session_id=message_request.session_id,
        first_message_content=message_request.content,
    )

    user_message = Message(
        session_id=chat_session.id,
        role="user",
        content=message_request.content,
    )
    db.add(user_message)
    await db.commit()
    await db.refresh(user_message)

    if message_request.stream:
        async def generate_response():
            try:
                explicit_skill_result = await _try_explicit_skill_invocation(message_request.content)
                if explicit_skill_result is not None:
                    (
                        assistant_content,
                        thinking_blocks,
                        tool_calls,
                        memory_context_included,
                        execution_mode,
                        delegation_plan,
                    ) = explicit_skill_result
                    await _persist_assistant_result(
                        db,
                        chat_session=chat_session,
                        assistant_content=assistant_content,
                        thinking_blocks=thinking_blocks,
                        tool_calls=tool_calls,
                        user_input=message_request.content,
                        user_id=user.id,
                        memory_context_included=memory_context_included,
                        execution_mode=execution_mode,
                        delegation_plan=delegation_plan,
                        llm_config=llm_config,
                    )
                    for block in thinking_blocks:
                        yield f"data: {json.dumps({'type': 'thinking_block', 'content': block.model_dump()}, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0.05)
                    for tool_call in tool_calls:
                        yield f"data: {json.dumps({'type': 'tool_call', 'content': tool_call.model_dump()}, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0.05)
                    for char in assistant_content:
                        yield f"data: {json.dumps({'type': 'content', 'content': char}, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0.01)
                    yield f"data: {json.dumps({'type': 'done', 'session_id': chat_session.id, 'execution_mode': execution_mode, 'delegation_plan': delegation_plan, 'thinking_blocks': [block.model_dump() for block in thinking_blocks], 'tool_calls': [tool_call.model_dump() for tool_call in tool_calls]}, ensure_ascii=False)}\n\n"
                    return

                prepared = await _prepare_serana_chat_execution(
                    db=db,
                    user=user,
                    user_input=message_request.content,
                    session_id=chat_session.id,
                    llm_config=llm_config,
                )
                for block in prepared["thinking_blocks"]:
                    yield f"data: {json.dumps({'type': 'thinking_block', 'content': block.model_dump()}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.05)

                accumulated_content = ""
                streamed_thinking_blocks = list(prepared["thinking_blocks"])
                streamed_tool_calls = list(prepared["tool_calls"])
                done_payload: dict = {}

                async for event in prepared["serana_agent"].execute_stream(
                    message_request.content,
                    session_id=chat_session.id,
                    memory_context=prepared["memory_context"],
                    recent_history_context=prepared["recent_history_context"],
                    resident_memory_context=prepared["resident_memory_context"],
                    working_memory_context=prepared["working_memory_context"],
                ):
                    event_type = event.get("type")
                    if event_type == "thinking":
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                        continue
                    if event_type == "thinking_block":
                        block_payload = event.get("content")
                        if isinstance(block_payload, dict):
                            streamed_thinking_blocks.append(ThinkingBlock.model_validate(block_payload))
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                        continue
                    if event_type == "content":
                        accumulated_content += str(event.get("content") or "")
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                        continue
                    if event_type in {"approval_requested", "approval_resolved"}:
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                        continue
                    if event_type == "tool_call":
                        tool_call_payload = event.get("content")
                        if isinstance(tool_call_payload, dict):
                            tool_call = ToolCall.model_validate(tool_call_payload)
                            if not any(existing.id == tool_call.id for existing in streamed_tool_calls):
                                streamed_tool_calls.append(tool_call)
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                        continue
                    if event_type == "done":
                        done_payload = event
                        for raw_block in event.get("thinking_blocks", []):
                            if isinstance(raw_block, dict):
                                block = ThinkingBlock.model_validate(raw_block)
                                if not any(existing.id == block.id for existing in streamed_thinking_blocks):
                                    streamed_thinking_blocks.append(block)
                        for raw_tool_call in event.get("tool_calls", []):
                            if isinstance(raw_tool_call, dict):
                                tool_call = ToolCall.model_validate(raw_tool_call)
                                if not any(existing.id == tool_call.id for existing in streamed_tool_calls):
                                    streamed_tool_calls.append(tool_call)
                        streamed_tool_calls.append(
                            ToolCall(
                                id="assistant-generation",
                                name="assistant_generation",
                                input={
                                    "execution_mode": str(event.get("execution_mode") or "direct"),
                                    "used_memory_context": prepared["memory_context_included"],
                                },
                                output={
                                    "response_preview": accumulated_content[:200],
                                    "delegation_plan": dict(event.get("delegation_plan") or {}),
                                },
                                status="completed",
                                timestamp=prepared["timestamp"],
                            )
                        )
                        done_event = {
                            **event,
                            "thinking_blocks": [
                                block.model_dump() for block in streamed_thinking_blocks
                            ],
                            "tool_calls": [
                                tool_call.model_dump() for tool_call in streamed_tool_calls
                            ],
                        }
                        schedule_memory_task(
                            _persist_streamed_assistant_result(
                                chat_session_id=chat_session.id,
                                assistant_content=accumulated_content,
                                thinking_blocks=streamed_thinking_blocks,
                                tool_calls=streamed_tool_calls,
                                user_input=message_request.content,
                                user_id=user.id,
                                memory_context_included=prepared["memory_context_included"],
                                execution_mode=str(event.get("execution_mode") or "direct"),
                                delegation_plan=dict(event.get("delegation_plan") or {}),
                                llm_config=llm_config,
                            )
                        )
                        yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"
                        return
                    if event_type == "error":
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                        return

            except Exception:
                logger.exception("Streaming assistant generation failed for session %s", chat_session.id)
                (
                    assistant_content,
                    thinking_blocks,
                    tool_calls,
                    memory_context_included,
                    execution_mode,
                    delegation_plan,
                ) = await _generate_assistant_payload(
                    db=db,
                    user=user,
                    user_input=message_request.content,
                    session_id=chat_session.id,
                    llm_config=llm_config,
                )
                await _persist_assistant_result(
                    db,
                    chat_session=chat_session,
                    assistant_content=assistant_content,
                    thinking_blocks=thinking_blocks,
                    tool_calls=tool_calls,
                    user_input=message_request.content,
                    user_id=user.id,
                    memory_context_included=memory_context_included,
                    execution_mode=execution_mode,
                    delegation_plan=delegation_plan,
                    llm_config=llm_config,
                )
                for block in thinking_blocks:
                    yield f"data: {json.dumps({'type': 'thinking_block', 'content': block.model_dump()}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.05)

                for char in assistant_content:
                    yield f"data: {json.dumps({'type': 'content', 'content': char}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)

                yield f"data: {json.dumps({'type': 'done', 'session_id': chat_session.id, 'execution_mode': execution_mode, 'delegation_plan': delegation_plan}, ensure_ascii=False)}\n\n"

        return StreamingResponse(generate_response(), media_type="text/event-stream")

    (
        assistant_content,
        thinking_blocks,
        tool_calls,
        memory_context_included,
        execution_mode,
        delegation_plan,
    ) = await _generate_assistant_payload(
        db=db,
        user=user,
        user_input=message_request.content,
        session_id=chat_session.id,
        llm_config=llm_config,
    )
    assistant_message, audit_records = await _persist_assistant_result(
        db,
        chat_session=chat_session,
        assistant_content=assistant_content,
        thinking_blocks=thinking_blocks,
        tool_calls=tool_calls,
        user_input=message_request.content,
        user_id=user.id,
        memory_context_included=memory_context_included,
        execution_mode=execution_mode,
        delegation_plan=delegation_plan,
        llm_config=llm_config,
    )

    response_payload = ChatCompletionResponse(
        session_id=chat_session.id,
        user_message=_serialize_message(user_message),
        assistant_message=_serialize_message(assistant_message),
        thinking_blocks=thinking_blocks,
        memory_context_included=memory_context_included,
        execution_mode=execution_mode,
        delegation_plan=delegation_plan,
        audit_records=[serialize_audit_record(record) for record in audit_records],
    )
    return response_payload
