import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.agents.serana.persona import load_serana_persona
from app.skills import SkillManager


USER_FACING_RESPONSE_STYLE = """\
## User-facing response style
- Answer the user's actual request first; do not expose routing, hidden reasoning, tool traces, or delegation mechanics.
- Choose structure by domain:
  - Everyday recommendations, food, travel, shopping, routines, and personal planning: use short headings and compact bullets; include one restrained Serana-style emoji per section when it improves scanning.
  - Technical explanations, code, debugging, and architecture: use clean headings, numbered steps, and code blocks; restrained emoji is allowed for structure, warnings, or decisions.
  - Calculations, time, weather, and memory lookup: give the direct result first, then the useful context; a single fitting emoji at the start is preferred.
- Emoji style must fit Serana: restrained, cool, practical, slightly gothic. Prefer 🌙 🕯️ 🧭 ⚠️ 🛡️ 🗡️ ☀️ 🌧️ ❄️. Avoid cute, noisy, celebratory, meme-like emoji such as 😂 🥰 🎉 🚀 unless the user explicitly asks for that tone.
- Keep Chinese replies natural and polished. Avoid backend wording such as "步骤已完成", "artifact", "route", "agent", or "tool" unless the user explicitly asks about internals.
- If memory is relevant, phrase it as continuity with the user, not as a record dump.
"""


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
    runtime_context: str = "",
    available_tool_context: str = "",
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

    if runtime_context.strip():
        sections.append(f"Runtime context:\n{runtime_context.strip()}")

    if available_tool_context.strip():
        sections.append(f"Available tools:\n{available_tool_context.strip()}")

    return "\n\n".join(sections)


@dataclass(frozen=True)
class SeranaContextBundle:
    user_input: str
    persona: str
    resident_memory_context: str = ""
    working_memory_context: str = ""
    memory_context: str = ""
    instruction_skill_context: str = ""
    instruction_skill_names: tuple[str, ...] = ()
    runtime_context: str = ""
    available_tool_context: str = ""

    @property
    def has_instruction_skills(self) -> bool:
        return bool(self.instruction_skill_context.strip())

    def build_request_context(
        self,
        *,
        label: str = "User message",
        user_input: str | None = None,
        include_resident_memory: bool = True,
        include_working_memory: bool = True,
        include_memory: bool = True,
        include_instruction_skills: bool = True,
        include_runtime: bool = False,
        include_available_tools: bool = False,
    ) -> str:
        return build_contextual_request(
            (user_input or self.user_input).strip(),
            resident_memory_context=self.resident_memory_context if include_resident_memory else "",
            working_memory_context=self.working_memory_context if include_working_memory else "",
            memory_context=self.memory_context if include_memory else "",
            instruction_skill_context=self.instruction_skill_context if include_instruction_skills else "",
            runtime_context=self.runtime_context if include_runtime else "",
            available_tool_context=self.available_tool_context if include_available_tools else "",
            label=label,
        )

    def build_system_prompt(
        self,
        task_instruction: str,
        *,
        include_instruction_skills: bool | None = None,
        include_available_tools: bool = False,
        include_runtime: bool = False,
    ) -> str:
        sections = [
            self.persona,
            USER_FACING_RESPONSE_STYLE,
            "## Current task\n" + task_instruction.strip(),
        ]

        should_include_skills = self.has_instruction_skills if include_instruction_skills is None else include_instruction_skills
        if should_include_skills:
            sections.append(
                "## Installed instruction skills\n"
                "Use relevant installed instruction skills as behavioral guidance. "
                "Do not mention internal skill names unless the user explicitly asks about system internals."
            )

        if include_available_tools and self.available_tool_context.strip():
            sections.append(
                "## Available tools\n"
                "These are the currently visible local tools. Prefer them when they directly match the user's intent.\n"
                f"{self.available_tool_context.strip()}"
            )

        if include_runtime and self.runtime_context.strip():
            sections.append("## Runtime context\n" + self.runtime_context.strip())

        return "\n\n".join(section for section in sections if section.strip())


def _build_runtime_context(state: dict[str, Any]) -> str:
    lines: list[str] = []
    session_id = str(state.get("session_id") or "").strip()
    if session_id:
        lines.append(f"- session_id: {session_id}")
    execution_mode = str(state.get("execution_mode") or "").strip()
    if execution_mode:
        lines.append(f"- execution_mode: {execution_mode}")
    goal_type = str(state.get("goal_type") or "").strip()
    if goal_type:
        lines.append(f"- goal_type: {goal_type}")
    complexity = str(state.get("complexity") or "").strip()
    if complexity:
        lines.append(f"- complexity: {complexity}")
    return "\n".join(lines)


def build_available_tool_context(*, max_chars: int = 4000) -> str:
    skill_manager = SkillManager()
    skill_manager.ensure_initialized()

    lines: list[str] = []
    for skill in skill_manager.list_skills():
        if not skill.is_enabled:
            continue
        if skill.agent_type not in {"all", "serana"}:
            continue
        for tool in skill.manifest.tools:
            line = f"- {skill.name}.{tool.name}: {tool.description}"
            lines.append(line)

    if not lines:
        return ""

    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    return text[: max(max_chars - 32, 0)].rstrip() + "\n- [truncated]"


def build_serana_context_bundle(
    state: dict[str, Any],
    *,
    user_input: str | None = None,
    include_available_tools: bool = True,
) -> SeranaContextBundle:
    resolved_user_input = (user_input or get_primary_user_input(state)).strip()
    raw_skill_names = state.get("instruction_skill_names") or []
    skill_names = tuple(str(name) for name in raw_skill_names if str(name).strip())
    return SeranaContextBundle(
        user_input=resolved_user_input,
        persona=load_serana_persona(),
        resident_memory_context=str(state.get("resident_memory_context") or ""),
        working_memory_context=str(state.get("working_memory_context") or ""),
        memory_context=str(state.get("memory_context") or ""),
        instruction_skill_context=str(state.get("instruction_skill_context") or ""),
        instruction_skill_names=skill_names,
        runtime_context=_build_runtime_context(state),
        available_tool_context=build_available_tool_context() if include_available_tools else "",
    )


def build_state_system_prompt(
    state: dict[str, Any],
    task_instruction: str,
    *,
    include_instruction_skills: bool | None = None,
    include_available_tools: bool = False,
    include_runtime: bool = False,
) -> str:
    return build_serana_context_bundle(
        state,
        include_available_tools=include_available_tools,
    ).build_system_prompt(
        task_instruction,
        include_instruction_skills=include_instruction_skills,
        include_available_tools=include_available_tools,
        include_runtime=include_runtime,
    )


def build_state_request_context(
    state: dict[str, Any],
    *,
    user_input: str | None = None,
    label: str = "User message",
    include_resident_memory: bool = True,
    include_working_memory: bool = True,
    include_memory: bool = True,
    include_instruction_skills: bool = True,
    include_runtime: bool = False,
    include_available_tools: bool = False,
) -> str:
    return build_serana_context_bundle(
        state,
        user_input=user_input,
        include_available_tools=include_available_tools,
    ).build_request_context(
        label=label,
        include_resident_memory=include_resident_memory,
        include_working_memory=include_working_memory,
        include_memory=include_memory,
        include_instruction_skills=include_instruction_skills,
        include_runtime=include_runtime,
        include_available_tools=include_available_tools,
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
