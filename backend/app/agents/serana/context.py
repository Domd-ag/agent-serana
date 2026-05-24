import uuid
from datetime import datetime, timezone
from typing import Any

from app.skills import SkillManager


def add_thinking_block(state: dict[str, Any], title: str, content: str) -> dict[str, Any]:
    thinking_blocks = list(state.get("thinking_blocks", []))
    thinking_blocks.append(
        {
            "id": str(uuid.uuid4()),
            "title": title,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {**state, "thinking_blocks": thinking_blocks}


def add_tool_call(
    state: dict[str, Any],
    name: str,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
    status: str = "completed",
) -> dict[str, Any]:
    tool_calls = list(state.get("tool_calls", []))
    tool_calls.append(
        {
            "id": str(uuid.uuid4()),
            "name": name,
            "input": input_payload,
            "output": output_payload,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {**state, "tool_calls": tool_calls}


def get_primary_user_input(state: dict[str, Any]) -> str:
    return str(state.get("original_user_input") or state.get("user_input") or "").strip()


def build_contextual_request(
    user_input: str,
    *,
    resident_memory_context: str = "",
    working_memory_context: str = "",
    memory_context: str = "",
    instruction_skill_context: str = "",
    label: str = "User message",
) -> str:
    sections = [f"{label}:\n{user_input}"]

    if resident_memory_context.strip():
        sections.append(f"Resident memory:\n{resident_memory_context.strip()}")

    if working_memory_context.strip():
        sections.append(f"Working memory:\n{working_memory_context.strip()}")

    if memory_context.strip():
        sections.append(f"Relevant memory context:\n{memory_context.strip()}")

    if instruction_skill_context.strip():
        sections.append(f"Installed instruction skills:\n{instruction_skill_context.strip()}")

    return "\n\n".join(sections)


def build_state_request_context(
    state: dict[str, Any],
    *,
    user_input: str | None = None,
    label: str = "User message",
) -> str:
    resolved_user_input = (user_input or get_primary_user_input(state)).strip()
    return build_contextual_request(
        resolved_user_input,
        resident_memory_context=str(state.get("resident_memory_context") or ""),
        working_memory_context=str(state.get("working_memory_context") or ""),
        memory_context=str(state.get("memory_context") or ""),
        instruction_skill_context=str(state.get("instruction_skill_context") or ""),
        label=label,
    )


def _parse_working_memory_context(context: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    if not context.strip():
        return entries

    for raw_line in context.splitlines():
        line = raw_line.strip()
        if not line or line == "[Working Memory]" or not line.startswith("- "):
            continue
        body = line[2:]
        if " = " in body:
            key, value = body.split(" = ", 1)
            entries[key.strip()] = value.strip()
    return entries


def build_working_memory_context(entries: dict[str, str]) -> str:
    normalized = {key.strip(): value.strip() for key, value in entries.items() if key.strip() and value.strip()}
    if not normalized:
        return ""
    lines = ["[Working Memory]"]
    for key, value in normalized.items():
        lines.append(f"- {key} = {value}")
    return "\n".join(lines)


def get_working_memory_entries(state: dict[str, Any]) -> dict[str, str]:
    existing = state.get("working_memory_entries")
    if isinstance(existing, dict):
        return {str(key): str(value) for key, value in existing.items()}
    return _parse_working_memory_context(str(state.get("working_memory_context") or ""))


def set_working_memory_entry(state: dict[str, Any], key: str, value: str) -> dict[str, Any]:
    entries = get_working_memory_entries(state)
    cleaned_key = key.strip()
    cleaned_value = value.strip()
    if cleaned_key and cleaned_value:
        entries[cleaned_key] = cleaned_value
    return {
        **state,
        "working_memory_entries": entries,
        "working_memory_context": build_working_memory_context(entries),
    }


def remove_working_memory_entry(state: dict[str, Any], key: str) -> dict[str, Any]:
    entries = get_working_memory_entries(state)
    entries.pop(key.strip(), None)
    return {
        **state,
        "working_memory_entries": entries,
        "working_memory_context": build_working_memory_context(entries),
    }


def clear_working_memory_entries(state: dict[str, Any]) -> dict[str, Any]:
    return {
        **state,
        "working_memory_entries": {},
        "working_memory_context": "",
    }


def ensure_instruction_skill_context(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("instruction_skill_context"):
        return state

    skill_manager = SkillManager()
    skill_manager.ensure_initialized()

    instruction_skills = skill_manager.get_enabled_instruction_skills()
    if not instruction_skills:
        return state

    sections: list[str] = []
    skill_names: list[str] = []
    total_budget = 5000
    used_budget = 0

    for skill in instruction_skills:
        skill_names.append(skill.name)
        snippet = (skill.instruction_content or "").strip()
        if not snippet:
            continue

        source = skill.manifest.source_url or "本地导入"
        section = (
            f"## 技能：{skill.name}\n"
            f"描述：{skill.description}\n"
            f"来源：{source}\n"
            f"{snippet}\n"
        )
        remaining = total_budget - used_budget
        if remaining <= 0:
            break
        if len(section) > remaining:
            section = section[: max(remaining - 20, 0)] + "\n[内容已截断]\n"
        used_budget += len(section)
        sections.append(section)

    if not sections:
        return state

    next_state = {
        **state,
        "instruction_skill_names": skill_names,
        "instruction_skill_context": "\n\n".join(sections),
    }
    next_state = add_thinking_block(
        next_state,
        "技能",
        f"已加载 {len(skill_names)} 个导入技能提示：{', '.join(skill_names)}",
    )
    next_state = add_tool_call(
        next_state,
        "instruction_skill_context",
        {"skill_count": len(skill_names)},
        {
            "skill_names": skill_names,
            "context_preview": next_state["instruction_skill_context"][:300],
        },
    )
    return next_state
