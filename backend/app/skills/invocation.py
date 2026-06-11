from __future__ import annotations

from dataclasses import dataclass
import re
import shlex
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any


@dataclass(frozen=True)
class InvocationCommand:
    """A runnable example found in SKILL.md."""

    raw: str
    arguments: list[str]
    source: str = "document"


@dataclass(frozen=True)
class InvocationParameterHint:
    """Parameter information inferred from SKILL.md tables or examples."""

    name: str
    description: str = ""
    required: bool | None = None
    example: str = ""
    type: str = "string"


SECTION_HEADINGS = {
    "quick start",
    "quickstart",
    "usage",
    "examples",
    "example",
    "用法",
    "快速开始",
    "示例",
    "使用方式",
    "如何使用",
}

INSTALL_COMMANDS = {
    "pip",
    "pip3",
    "python",
    "python3",
    "npm",
    "pnpm",
    "yarn",
    "git",
    "curl",
    "wget",
    "docker",
    "sudo",
    "apt",
    "apt-get",
    "yum",
    "dnf",
    "brew",
}

SHELL_LAUNCHERS = {"bash", "sh", "zsh"}


def make_invocation_name(name: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_]+", "_", str(name or "").strip().lower()).strip("_")
    return value or "skill"


def parameter_placeholder(parameter: dict[str, Any]) -> str:
    name = str(parameter.get("name") or "value").strip()
    required = bool(parameter.get("required", True))
    lowered = name.lower()
    if lowered in {"city", "location", "place"}:
        value = "上海"
    elif lowered in {"url", "link"}:
        value = "https://example.com"
    elif lowered in {"file", "path", "filename"}:
        value = "<文件路径>"
    elif lowered in {"days", "count", "limit", "num", "number"}:
        value = "3"
    elif lowered in {"keyword", "query", "q", "topic", "text", "input", "prompt"}:
        value = f"<{name}>"
    else:
        value = f"<{name}>"
    return value if required else f"[{value}]"


def extract_parameter_hints(instruction: str) -> dict[str, InvocationParameterHint]:
    hints: dict[str, InvocationParameterHint] = {}
    for row in _iter_markdown_table_rows(instruction):
        cells = [cell.strip() for cell in row]
        if len(cells) < 2:
            continue
        headerish = "".join(cells).lower()
        if any(token in headerish for token in ("参数", "parameter", "name", "说明", "描述", "description")):
            continue
        name = _normalize_parameter_name(cells[0])
        if not name:
            continue
        description = cells[1] if len(cells) >= 2 else ""
        required = None
        if len(cells) >= 3:
            required = _parse_required_flag(cells[2])
        hints[name] = InvocationParameterHint(
            name=name,
            description=description.strip(),
            required=required,
            example=_extract_example_value(" ".join(cells[1:])),
            type=_infer_type_from_text(" ".join(cells)),
        )

    bullet_pattern = re.compile(
        r"^\s*[-*]\s*`?([a-zA-Z_][a-zA-Z0-9_-]*)`?\s*(?:[:：\-]\s*)(.+?)\s*$",
        flags=re.MULTILINE,
    )
    for match in bullet_pattern.finditer(instruction):
        name = _normalize_parameter_name(match.group(1))
        if not name or name in hints:
            continue
        detail = match.group(2).strip()
        hints[name] = InvocationParameterHint(
            name=name,
            description=detail,
            required=_parse_required_flag(detail),
            example=_extract_example_value(detail),
            type=_infer_type_from_text(detail),
        )
    return hints


def infer_parameters_from_instruction(
    instruction: str,
    *,
    entrypoint_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    hints = extract_parameter_hints(instruction)
    commands = extract_invocation_commands(
        instruction,
        invocation_name="skill",
        entrypoint_names=entrypoint_names or [],
        parameter_placeholders=[],
    )
    best = max(commands, key=lambda command: len(command.arguments), default=None)
    if best is None or not best.arguments:
        return [
            {
                "name": "query",
                "type": "string",
                "description": "传给技能处理的主要查询内容。",
                "required": True,
            }
        ]

    parameters: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for index, raw_arg in enumerate(best.arguments):
        name, required, example = _parameter_from_argument(raw_arg, index)
        hint = hints.get(name)
        if hint is None and len(hints) == len(best.arguments):
            hint = list(hints.values())[index]
            name = hint.name
        name = _dedupe_name(name, used_names)
        used_names.add(name)
        parameters.append(
            {
                "name": name,
                "type": (hint.type if hint else _infer_type_from_text(raw_arg)) or "string",
                "description": (hint.description if hint else _default_parameter_description(name)),
                "required": hint.required if hint and hint.required is not None else required,
                "example": (hint.example if hint else "") or example,
            }
        )
    return parameters


def refine_parameters_with_instruction(
    parameters: list[dict[str, Any]],
    instruction: str,
) -> list[dict[str, Any]]:
    hints = extract_parameter_hints(instruction)
    refined: list[dict[str, Any]] = []
    for parameter in parameters:
        name = str(parameter.get("name") or "").strip()
        hint = hints.get(name)
        next_parameter = dict(parameter)
        if hint is not None:
            if hint.description and not str(next_parameter.get("description") or "").strip():
                next_parameter["description"] = hint.description
            if hint.required is not None:
                next_parameter["required"] = hint.required
            if hint.example:
                next_parameter["example"] = hint.example
            if hint.type:
                next_parameter["type"] = hint.type
        refined.append(next_parameter)
    return refined


def extract_invocation_commands(
    instruction: str,
    *,
    invocation_name: str,
    entrypoint_names: list[str] | None = None,
    parameter_placeholders: list[str] | None = None,
) -> list[InvocationCommand]:
    if not instruction.strip():
        return []

    entrypoint_names = [name.lower() for name in (entrypoint_names or []) if name]
    parameter_placeholders = parameter_placeholders or []
    lines = _candidate_lines(instruction)
    commands: list[InvocationCommand] = []
    for raw_line in lines:
        line = _clean_command_line(raw_line)
        if not line:
            continue
        parsed = _parse_command_line(line, invocation_name=invocation_name, entrypoint_names=entrypoint_names)
        if parsed is None:
            continue
        commands.append(parsed)

    normalized: list[InvocationCommand] = []
    for command in commands:
        normalized_args = [
            _normalize_example_argument(argument)
            for argument in command.arguments
            if _normalize_example_argument(argument)
        ]
        normalized.append(
            InvocationCommand(
                raw=_format_at_invocation(invocation_name, normalized_args, parameter_placeholders),
                arguments=normalized_args,
                source=command.source,
            )
        )

    deduped: list[InvocationCommand] = []
    seen: set[str] = set()
    for command in normalized:
        if not command.raw or command.raw in seen:
            continue
        seen.add(command.raw)
        deduped.append(command)
    return deduped


def build_invocation_examples(
    instruction: str,
    *,
    invocation_name: str,
    entrypoint_names: list[str] | None,
    parameters: list[dict[str, Any]],
    max_examples: int = 4,
) -> list[str]:
    placeholders = [parameter_placeholder(parameter) for parameter in parameters]
    commands = extract_invocation_commands(
        instruction,
        invocation_name=invocation_name,
        entrypoint_names=entrypoint_names,
        parameter_placeholders=placeholders,
    )
    examples = [command.raw for command in commands]
    generated = " ".join(part for part in [f"@{invocation_name}", *placeholders] if part)
    examples.append(generated)
    return list(dict.fromkeys(example for example in examples if example))[:max_examples]


def _iter_markdown_table_rows(instruction: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in instruction.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        if re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?", stripped):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        rows.append(cells)
    return rows


def _candidate_lines(instruction: str) -> list[str]:
    lines: list[str] = []
    in_relevant_section = False
    in_code_block = False
    for line in instruction.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        heading = stripped.lstrip("#").strip().lower()
        if heading in SECTION_HEADINGS:
            in_relevant_section = True
            continue
        if in_relevant_section and stripped.startswith("#"):
            in_relevant_section = False

        if in_code_block or in_relevant_section:
            lines.append(stripped)
            continue
        if "`" in stripped:
            lines.extend(re.findall(r"`([^`]+)`", stripped))
    return lines


def _clean_command_line(line: str) -> str:
    line = line.strip().strip("`")
    line = re.sub(r"^\s*(?:\$|>|#)\s*", "", line)
    line = re.sub(r"\s+#.*$", "", line)
    return line.strip()


def _parse_command_line(
    line: str,
    *,
    invocation_name: str,
    entrypoint_names: list[str],
) -> InvocationCommand | None:
    if not line or line.startswith(("#", "//")):
        return None
    try:
        tokens = shlex.split(line, posix=False)
    except ValueError:
        tokens = line.split()
    tokens = [token.strip().strip("'\"") for token in tokens if token.strip()]
    if not tokens:
        return None
    first = _command_basename(tokens[0]).lower()
    if first in INSTALL_COMMANDS and first not in SHELL_LAUNCHERS:
        return None

    command_index = None
    if tokens[0].startswith("@"):
        command_index = 0
    elif first in SHELL_LAUNCHERS and len(tokens) > 1 and _matches_entrypoint(tokens[1], entrypoint_names):
        command_index = 1
    elif _matches_entrypoint(tokens[0], entrypoint_names):
        command_index = 0
    elif invocation_name and first in {invocation_name.lower(), make_invocation_name(invocation_name).lower()}:
        command_index = 0

    if command_index is None:
        return None

    args = _command_arguments(tokens[command_index + 1 :])
    return InvocationCommand(raw=line, arguments=args)


def _command_arguments(tokens: list[str]) -> list[str]:
    args: list[str] = []
    skip_next_option_value = False
    for token in tokens:
        if skip_next_option_value:
            args.append(token)
            skip_next_option_value = False
            continue
        if token in {"&&", "|", ";"}:
            break
        if token.startswith("--"):
            if "=" in token:
                _, value = token.split("=", 1)
                args.append(value)
            else:
                skip_next_option_value = True
            continue
        if token.startswith("-"):
            continue
        args.append(token)
    return args


def _matches_entrypoint(token: str, entrypoint_names: list[str]) -> bool:
    basename = _command_basename(token).lower()
    stem = re.sub(r"\.(?:sh|py|js|ts|mjs|cjs)$", "", basename)
    return basename in entrypoint_names or stem in entrypoint_names


def _command_basename(token: str) -> str:
    token = token.strip().strip("'\"")
    posix_name = PurePosixPath(token).name
    return PureWindowsPath(posix_name).name


def _format_at_invocation(invocation_name: str, args: list[str], fallback_placeholders: list[str]) -> str:
    if not invocation_name:
        return ""
    usable_args = args or fallback_placeholders
    return " ".join(part for part in [f"@{invocation_name}", *usable_args] if part)


def _normalize_example_argument(argument: str) -> str:
    argument = argument.strip().strip("'\"")
    if not argument:
        return ""
    if argument.startswith("<") and argument.endswith(">"):
        return argument
    if argument.startswith("[") and argument.endswith("]"):
        return argument
    return argument


def _parameter_from_argument(argument: str, index: int) -> tuple[str, bool, str]:
    raw = argument.strip()
    required = not (raw.startswith("[") and raw.endswith("]"))
    cleaned = raw.strip("[]{}<>").strip()
    lowered = cleaned.lower()
    if re.fullmatch(r"\d+", cleaned):
        return ("days" if index == 1 else f"number_{index + 1}", required, cleaned)
    if re.match(r"https?://", cleaned):
        return "url", required, cleaned
    if re.search(r"\.(?:txt|md|pdf|docx?|xlsx?|csv|json|yaml|yml)$", cleaned, flags=re.IGNORECASE):
        return "file", required, cleaned
    if lowered in {"city", "location", "place", "城市", "地点", "位置"}:
        return "city", required, "上海"
    if lowered in {"keyword", "query", "topic", "关键词", "查询", "主题"}:
        return "query", required, f"<{cleaned}>"
    if re.search(r"[\u4e00-\u9fff]", cleaned) and len(cleaned) <= 12:
        return "city", required, cleaned
    return ("query" if index == 0 else f"arg{index + 1}", required, cleaned)


def _normalize_parameter_name(value: str) -> str:
    value = value.strip().strip("`：:[]<>")
    aliases = {
        "城市": "city",
        "地点": "city",
        "位置": "city",
        "关键词": "query",
        "查询": "query",
        "主题": "query",
        "链接": "url",
        "地址": "url",
        "文件": "file",
        "路径": "file",
        "天数": "days",
        "数量": "count",
    }
    value = aliases.get(value, value)
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
    return normalized


def _parse_required_flag(text: str) -> bool | None:
    lowered = str(text or "").lower()
    if any(token in lowered for token in ("required", "必填", "必须", "yes", "true", "是")):
        return True
    if any(token in lowered for token in ("optional", "可选", "否", "false", "no")):
        return False
    return None


def _extract_example_value(text: str) -> str:
    match = re.search(r"(?:例如|示例|example|e\.g\.)\s*[:：]?\s*`?([^`，,。；;\s]+)`?", text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _infer_type_from_text(text: str) -> str:
    lowered = str(text or "").lower()
    if any(token in lowered for token in ("integer", "int", "number", "数字", "整数", "天数", "数量")):
        return "integer"
    if any(token in lowered for token in ("boolean", "bool", "true", "false", "布尔")):
        return "boolean"
    return "string"


def _default_parameter_description(name: str) -> str:
    descriptions = {
        "city": "城市或地区名称。",
        "location": "地点名称。",
        "url": "网页地址。",
        "file": "文件路径。",
        "days": "需要查询或处理的天数。",
        "query": "传给技能处理的主要查询内容。",
    }
    return descriptions.get(name, f"{name} 参数。")


def _dedupe_name(name: str, used: set[str]) -> str:
    base = name or "arg"
    if base not in used:
        return base
    index = 2
    while f"{base}_{index}" in used:
        index += 1
    return f"{base}_{index}"
