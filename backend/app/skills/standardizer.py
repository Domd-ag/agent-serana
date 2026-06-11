import json
from pathlib import Path
import re
from typing import Any

from app.skills.invocation import infer_parameters_from_instruction
from app.skills.script_runtime import ShellScriptAdapter
from app.skills.validator import SkillValidator


class SkillStandardizationError(RuntimeError):
    pass


class SkillStandardizer:
    """Convert downloaded marketplace packages into Serana's unified Skill contract."""

    @classmethod
    def standardize_marketplace_package(
        cls,
        skill_dir: Path,
        *,
        local_name: str,
        version: str,
        description: str,
        author: str,
        registry_slug: str,
        source_url: str,
        capabilities: list[str],
        intents: list[str],
    ) -> dict[str, Any]:
        instruction_path = skill_dir / "SKILL.md"
        if not instruction_path.is_file():
            raise SkillStandardizationError("下载的技能包缺少 SKILL.md。")
        instruction = instruction_path.read_text(encoding="utf-8", errors="replace")

        existing_manifest = cls._read_existing_manifest(skill_dir)
        if existing_manifest and cls._is_declared_executable_manifest(existing_manifest):
            cls._validate_declared_runtime(skill_dir, existing_manifest)
            manifest = {
                **existing_manifest,
                "name": local_name,
                "version": version,
                "description": description,
                "author": author,
                "registry_slug": registry_slug,
                "source_url": source_url,
                "capabilities": capabilities or existing_manifest.get("capabilities", []),
                "intents": intents or existing_manifest.get("intents", []),
            }
            cls._write_manifest(skill_dir, manifest)
            return manifest

        shell_entrypoint = cls._find_shell_entrypoint(skill_dir, instruction)
        if shell_entrypoint is not None:
            manifest = cls._build_shell_manifest(
                skill_dir,
                instruction=instruction,
                shell_entrypoint=shell_entrypoint,
                local_name=local_name,
                version=version,
                description=description,
                author=author,
                registry_slug=registry_slug,
                source_url=source_url,
                capabilities=capabilities,
                intents=intents,
            )
        else:
            manifest = cls._build_instruction_manifest(
                local_name=local_name,
                version=version,
                description=description,
                author=author,
                registry_slug=registry_slug,
                source_url=source_url,
                capabilities=capabilities,
                intents=intents,
            )
        cls._write_manifest(skill_dir, manifest)
        return manifest

    @staticmethod
    def _read_existing_manifest(skill_dir: Path) -> dict[str, Any] | None:
        manifest_path = skill_dir / "skill.json"
        if not manifest_path.is_file():
            return None
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _is_declared_executable_manifest(payload: dict[str, Any]) -> bool:
        runtime = str(payload.get("runtime") or "").lower()
        if runtime not in {"python", "script"}:
            return False
        is_valid, _ = SkillValidator.validate_manifest(payload)
        return is_valid

    @staticmethod
    def _find_shell_entrypoint(skill_dir: Path, instruction: str) -> Path | None:
        referenced_paths = []
        for match in re.finditer(r"(?:^|[\s`'\"])(?:\./)?([a-zA-Z0-9_./-]+\.sh)\b", instruction):
            candidate = (skill_dir / match.group(1)).resolve()
            if candidate.is_file() and candidate.suffix.lower() == ".sh":
                try:
                    candidate.relative_to(skill_dir.resolve())
                except ValueError:
                    continue
                referenced_paths.append(candidate)
        unique_references = list(dict.fromkeys(referenced_paths))
        if len(unique_references) > 1:
            # Multiple shell references are often optional hooks or helpers.
            # Without an explicit executable manifest, keep the package as an
            # instruction skill instead of guessing which script to register.
            return None
        if unique_references:
            return unique_references[0]

        shell_files = sorted(path.resolve() for path in skill_dir.rglob("*.sh") if path.is_file())
        if len(shell_files) > 1:
            return None
        return shell_files[0] if shell_files else None

    @staticmethod
    def _validate_declared_runtime(skill_dir: Path, manifest: dict[str, Any]) -> None:
        script = manifest.get("script") if isinstance(manifest.get("script"), dict) else {}
        if str(script.get("adapter") or "").lower() != "shell":
            return
        entrypoint = (skill_dir / str(manifest.get("entrypoint") or "")).resolve()
        if not entrypoint.is_file():
            raise SkillStandardizationError("Shell Skill 声明的入口文件不存在。")
        if ShellScriptAdapter.find_bash() is None:
            raise SkillStandardizationError(
                "检测到 Shell Skill，但当前后端没有 Bash。请安装 Git Bash，"
                "或通过 SERANA_BASH_PATH 指定 bash.exe 后重新安装。"
            )

    @classmethod
    def _build_shell_manifest(
        cls,
        skill_dir: Path,
        *,
        instruction: str,
        shell_entrypoint: Path,
        local_name: str,
        version: str,
        description: str,
        author: str,
        registry_slug: str,
        source_url: str,
        capabilities: list[str],
        intents: list[str],
    ) -> dict[str, Any]:
        if ShellScriptAdapter.find_bash() is None:
            raise SkillStandardizationError(
                "检测到 Shell Skill，但当前后端没有 Bash。请安装 Git Bash，"
                "或通过 SERANA_BASH_PATH 指定 bash.exe 后重新安装。"
            )

        source = shell_entrypoint.read_text(encoding="utf-8")
        permissions = []
        if re.search(r"\b(?:curl|wget)\b", source):
            permissions.append("network")
        if re.search(r"\b(?:mktemp|touch|mkdir)\b|(?:>|>>)", source):
            permissions.append("filesystem_write")
        relative_entrypoint = shell_entrypoint.relative_to(skill_dir.resolve()).as_posix()
        tool_name = cls._sanitize_tool_name(shell_entrypoint.stem)
        inferred_parameters = infer_parameters_from_instruction(
            instruction,
            entrypoint_names=[
                shell_entrypoint.name,
                shell_entrypoint.stem,
                local_name,
                registry_slug,
            ],
        )
        argument_order = [str(parameter["name"]) for parameter in inferred_parameters]
        properties = {
            str(parameter["name"]): {
                "type": str(parameter.get("type") or "string"),
                "description": str(parameter.get("description") or ""),
            }
            for parameter in inferred_parameters
        }
        required = [
            str(parameter["name"])
            for parameter in inferred_parameters
            if bool(parameter.get("required", True))
        ]
        return {
            "name": local_name,
            "version": version,
            "description": description,
            "author": author,
            "format": "serana_standardized",
            "runtime": "script",
            "instruction_file": "SKILL.md",
            "entrypoint": relative_entrypoint,
            "registry_slug": registry_slug,
            "source_url": source_url,
            "agent_type": "all",
            "max_instances": 1,
            "capabilities": capabilities,
            "intents": intents,
            "permissions": permissions,
            "script": {
                "adapter": "shell",
                "timeout_seconds": 20,
                "max_input_chars": 8192,
                "max_output_chars": 32768,
                "argument_order": argument_order,
                "output_format": "text",
            },
            "tools": [
                {
                    "name": tool_name,
                    "description": description,
                    "input_schema": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                }
            ],
        }

    @staticmethod
    def _build_instruction_manifest(
        *,
        local_name: str,
        version: str,
        description: str,
        author: str,
        registry_slug: str,
        source_url: str,
        capabilities: list[str],
        intents: list[str],
    ) -> dict[str, Any]:
        return {
            "name": local_name,
            "version": version,
            "description": description,
            "author": author,
            "format": "serana_standardized",
            "runtime": "instruction",
            "instruction_file": "SKILL.md",
            "entrypoint": None,
            "registry_slug": registry_slug,
            "source_url": source_url,
            "agent_type": "all",
            "max_instances": 1,
            "capabilities": capabilities,
            "intents": intents,
            "tools": [],
        }

    @staticmethod
    def _sanitize_tool_name(value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
        return normalized or "run"

    @staticmethod
    def _write_manifest(skill_dir: Path, manifest: dict[str, Any]) -> None:
        (skill_dir / "skill.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
