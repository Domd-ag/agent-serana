import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core import logger
from app.skills.models import SkillPackageManifest


class SkillValidator:
    """Validate Sebastian-style skill packages."""

    PACKAGE_METADATA_FILE = "skill.json"
    SUPPORTED_RUNTIMES = {"python", "instruction", "script"}
    SUPPORTED_SCRIPT_ADAPTERS = {"python", "python_cli", "shell"}
    SUPPORTED_SCRIPT_PERMISSIONS = {"network", "filesystem_write"}

    @classmethod
    def validate_manifest(cls, manifest_data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        try:
            manifest = SkillPackageManifest(**manifest_data)

            if not manifest.name:
                return False, "技能名称不能为空"
            if not manifest.version:
                return False, "技能版本不能为空"
            if not manifest.description:
                return False, "技能描述不能为空"
            if manifest.max_instances < 1:
                return False, "max_instances 不能小于 1"
            if manifest.runtime not in cls.SUPPORTED_RUNTIMES:
                return False, f"不支持的 runtime：{manifest.runtime}"
            if manifest.runtime == "python" and not manifest.entrypoint:
                return False, "Python 技能必须声明入口文件"
            if manifest.runtime == "script":
                if not manifest.entrypoint:
                    return False, "Script Skill 必须声明入口文件"
                if not manifest.tools:
                    return False, "Script Skill 必须至少声明一个工具"
                script = manifest.script
                if script is None:
                    return False, "Script Skill 必须声明 script 配置"
                if script.adapter not in cls.SUPPORTED_SCRIPT_ADAPTERS:
                    return False, f"不支持的 Script Skill adapter：{script.adapter}"
                if script.adapter in {"python", "python_cli"} and not manifest.entrypoint.lower().endswith(".py"):
                    return False, "PythonScriptAdapter 入口必须是 .py 文件"
                if script.adapter == "shell" and not manifest.entrypoint.lower().endswith(".sh"):
                    return False, "ShellScriptAdapter 入口必须是 .sh 文件"
                if script.output_format not in {"json", "text"}:
                    return False, "Script Skill output_format 只支持 json 或 text"
                declared_properties = {
                    property_name
                    for tool in manifest.tools
                    for property_name in tool.input_schema.properties
                }
                unknown_ordered_arguments = set(script.argument_order) - declared_properties
                if unknown_ordered_arguments:
                    return False, (
                        "Script Skill argument_order 包含未声明参数："
                        + ", ".join(sorted(unknown_ordered_arguments))
                    )
                unsupported_permissions = set(manifest.permissions or []) - cls.SUPPORTED_SCRIPT_PERMISSIONS
                if unsupported_permissions:
                    return False, f"Script Skill 包含不支持的权限：{', '.join(sorted(unsupported_permissions))}"
            if not all(isinstance(item, str) and item.strip() for item in manifest.capabilities):
                return False, "capabilities 必须是非空字符串列表"
            if not all(isinstance(item, str) and item.strip() for item in manifest.intents):
                return False, "intents 必须是非空字符串列表"

            for index, tool in enumerate(manifest.tools):
                if not tool.name:
                    return False, f"工具 {index} 缺少名称"
                if not tool.description:
                    return False, f"工具 {tool.name} 缺少描述"

            return True, None
        except Exception as exc:
            logger.error("Skill manifest validation error: %s", exc)
            return False, str(exc)

    @classmethod
    def _load_metadata(cls, skill_path: Path) -> tuple[Optional[Path], Optional[Dict[str, Any]], List[str]]:
        errors: List[str] = []
        metadata_path = skill_path / cls.PACKAGE_METADATA_FILE

        if not metadata_path.exists():
            return None, None, ["缺少必需文件：skill.json"]

        try:
            with open(metadata_path, "r", encoding="utf-8-sig") as file:
                return metadata_path, json.load(file), errors
        except json.JSONDecodeError as exc:
            return metadata_path, None, [f"{metadata_path.name} 中的 JSON 格式无效：{exc}"]
        except Exception as exc:
            return metadata_path, None, [f"读取 {metadata_path.name} 失败：{exc}"]

    @classmethod
    def validate_skill_directory(cls, skill_path: Path) -> tuple[bool, List[str]]:
        errors: List[str] = []

        if not skill_path.exists():
            return False, ["技能目录不存在"]
        if not skill_path.is_dir():
            return False, ["技能路径不是目录"]

        metadata_path, manifest_data, metadata_errors = cls._load_metadata(skill_path)
        errors.extend(metadata_errors)
        if not metadata_path or manifest_data is None:
            return False, errors

        is_valid, error_msg = cls.validate_manifest(manifest_data)
        if not is_valid and error_msg:
            errors.append(f"技能元数据校验失败：{error_msg}")
            return False, errors

        manifest = SkillPackageManifest(**manifest_data)

        skill_root = skill_path.resolve()
        instruction_path = Path(manifest.instruction_file)
        if instruction_path.is_absolute() or ".." in instruction_path.parts:
            errors.append("Skill instruction_file 必须位于技能目录内")
        else:
            resolved_instruction_path = (skill_root / instruction_path).resolve()
            if skill_root not in resolved_instruction_path.parents:
                errors.append("Skill instruction_file 必须位于技能目录内")
            elif not resolved_instruction_path.is_file():
                errors.append(f"缺少必需文件：{manifest.instruction_file}")

        if manifest.runtime == "python":
            entrypoint = Path(manifest.entrypoint or "__init__.py")
            if entrypoint.is_absolute() or ".." in entrypoint.parts:
                errors.append("Python 技能入口必须位于技能目录内")
            else:
                entrypoint_path = (skill_root / entrypoint).resolve()
                if skill_root not in entrypoint_path.parents:
                    errors.append("Python 技能入口必须位于技能目录内")
                elif not entrypoint_path.is_file():
                    errors.append(f"缺少 Python 入口文件：{entrypoint.name}")
        elif manifest.runtime == "script":
            entrypoint = Path(manifest.entrypoint or "")
            if entrypoint.is_absolute() or ".." in entrypoint.parts:
                errors.append("Script Skill 入口必须位于技能目录内")
            else:
                entrypoint_path = (skill_root / entrypoint).resolve()
                if skill_root not in entrypoint_path.parents:
                    errors.append("Script Skill 入口必须位于技能目录内")
                elif not entrypoint_path.is_file():
                    errors.append(f"缺少 Script Skill 入口文件：{entrypoint.name}")

        return len(errors) == 0, errors
