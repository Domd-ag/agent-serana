import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core import logger
from app.skills.models import SkillPackageManifest


class SkillValidator:
    """Validate Sebastian-style skill packages."""

    PACKAGE_METADATA_FILE = "skill.json"

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
            if manifest.runtime == "python" and not manifest.entrypoint:
                return False, "Python 技能必须声明入口文件"

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
            with open(metadata_path, "r", encoding="utf-8") as file:
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

        instruction_path = skill_path / manifest.instruction_file
        if not instruction_path.exists():
            errors.append(f"缺少必需文件：{manifest.instruction_file}")

        if manifest.runtime == "python":
            entrypoint_path = skill_path / (manifest.entrypoint or "__init__.py")
            if not entrypoint_path.exists():
                errors.append(f"缺少 Python 入口文件：{entrypoint_path.name}")

        return len(errors) == 0, errors
