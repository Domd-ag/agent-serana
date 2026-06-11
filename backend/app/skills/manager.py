from datetime import datetime, timezone
import json
import inspect
from pathlib import Path
import re
import shutil
from typing import Any, Callable, Dict, List, Optional
import uuid

from app.core.config import get_settings
from app.core.logger import get_logger
from app.skills.invocation import (
    build_invocation_examples,
    make_invocation_name,
    parameter_placeholder,
    refine_parameters_with_instruction,
)
from app.skills.loader import SkillLoader
from app.skills.models import SkillPackage, SkillPackageManifest, SkillTool
from app.skills.validator import SkillValidator


startup_logger = get_logger("app.startup.skills")
tool_logger = get_logger("app.tool.skills")


class SkillManager:
    """Singleton manager for local backend skill packages."""

    _instance: Optional["SkillManager"] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if SkillManager._initialized:
            return

        backend_root = Path(__file__).resolve().parents[2]
        settings = get_settings()
        self.bundled_skills_path = backend_root / "skills_store"
        configured_skills_dir = str(settings.SERANA_SKILLS_DIR or "").strip()
        self.skills_store_path = (
            Path(configured_skills_dir).expanduser()
            if configured_skills_dir
            else self.bundled_skills_path
        )
        self.skills_store_path.mkdir(parents=True, exist_ok=True)
        self.managed_skills_path = self.skills_store_path / "installed"
        self.managed_skills_path.mkdir(parents=True, exist_ok=True)
        self.staged_uploads_path = self.skills_store_path / ".staging"
        self.staged_uploads_path.mkdir(exist_ok=True)

        self.loader = SkillLoader(str(self.bundled_skills_path))
        self.skills: Dict[str, SkillPackage] = {}
        self.enabled_skills: List[str] = []
        self._skills_loaded = False

        SkillManager._initialized = True

    def initialize(self):
        """Scan the local skill store and load all valid packages."""
        startup_logger.info("Initializing SkillManager")
        self.skills.clear()
        self.enabled_skills.clear()
        self._scan_skills_store()
        self._skills_loaded = True
        startup_logger.info("SkillManager ready with %s skills", len(self.skills))

    def ensure_initialized(self):
        if not self._skills_loaded:
            self.initialize()

    def _scan_skills_store(self):
        if self.bundled_skills_path.exists():
            for skill_dir in self.bundled_skills_path.iterdir():
                if skill_dir.is_dir() and skill_dir.name not in {"installed", ".staging", "__pycache__"}:
                    self._try_load_skill(skill_dir)

        if self.managed_skills_path.exists():
            for skill_dir in self.managed_skills_path.iterdir():
                if skill_dir.is_dir():
                    self._try_load_skill(skill_dir)

    def _try_load_skill(self, skill_path: Path) -> Optional[SkillPackage]:
        is_valid, errors = SkillValidator.validate_skill_directory(skill_path)
        if not is_valid:
            startup_logger.warning("Skill at %s invalid: %s", skill_path, errors)
            return None

        manifest = self.loader.load_manifest(skill_path)
        if not manifest:
            return None

        if manifest.name in self.skills:
            startup_logger.warning("Skill %s already loaded", manifest.name)
            return self.skills[manifest.name]

        module = self.loader.load_skill_module(skill_path, manifest)
        if manifest.runtime == "python" and not module:
            return None

        if module:
            self.loader.load_tools_from_module(module, manifest)
        if manifest.runtime == "script":
            script_tools = self.loader.load_script_tools(skill_path, manifest)
            if len(script_tools) != len(manifest.tools):
                self.loader.unload_skill(manifest.name)
                return None

        origin = self._get_skill_origin(skill_path)
        can_uninstall = origin == "managed"
        source_label = self._get_source_label(origin, manifest)
        trust_state = self._get_trust_state(origin, manifest)
        instruction_content = self.loader.load_instruction_content(skill_path, manifest)
        invocation_metadata = self._build_invocation_metadata(manifest, instruction_content)

        skill_package = SkillPackage(
            id=str(uuid.uuid4()),
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            author=manifest.author,
            format=manifest.format,
            runtime=manifest.runtime,
            agent_type=manifest.agent_type,
            max_instances=manifest.max_instances,
            is_enabled=True,
            is_installed=True,
            installed_at=datetime.now(timezone.utc),
            origin=origin,
            can_uninstall=can_uninstall,
            registry_slug=manifest.registry_slug,
            source_url=manifest.source_url,
            source_label=source_label,
            trust_state=trust_state,
            effective_scope=manifest.agent_type,
            can_update=can_uninstall and bool(manifest.registry_slug),
            run_mode_description=invocation_metadata["run_mode_description"],
            invocation_name=invocation_metadata["invocation_name"],
            invocation_parameters=invocation_metadata["invocation_parameters"],
            invocation_examples=invocation_metadata["invocation_examples"],
            manifest=manifest,
            instruction_content=instruction_content,
            path=str(skill_path),
        )

        self.skills[skill_package.name] = skill_package
        self.enabled_skills.append(skill_package.name)
        startup_logger.debug("Loaded skill: %s v%s", skill_package.name, skill_package.version)
        return skill_package

    def list_invocable_executable_skills(self) -> List[SkillPackage]:
        return [
            skill
            for skill in self.skills.values()
            if skill.is_enabled
            and skill.runtime in {"python", "script"}
            and skill.name != "browser"
            and bool(skill.manifest.tools)
        ]

    def list_skills(self) -> List[SkillPackage]:
        return list(self.skills.values())

    def get_skill(self, skill_name: str) -> Optional[SkillPackage]:
        return self.skills.get(skill_name)

    def get_tools_for_agent(self, agent_type: str) -> List[SkillTool]:
        tools: List[SkillTool] = []
        for skill in self.skills.values():
            if not skill.is_enabled:
                continue
            if skill.agent_type == agent_type or skill.agent_type == "all":
                tools.extend(skill.manifest.tools)
        return tools

    def get_tool_function(self, skill_name: str, tool_name: str) -> Optional[Callable]:
        return self.loader.get_tool(skill_name, tool_name)

    def get_enabled_instruction_skills(self) -> List[SkillPackage]:
        return [
            skill
            for skill in self.skills.values()
            if skill.is_enabled and skill.runtime == "instruction" and skill.instruction_content
        ]

    def resolve_invocation_skill(self, token: str) -> tuple[Optional[SkillPackage], List[SkillPackage]]:
        query = re.sub(r"[^a-zA-Z0-9_.-]+", "", str(token or "").strip().lower())
        if not query:
            return None, []

        candidates = self.list_invocable_executable_skills()
        exact = [
            skill for skill in candidates
            if skill.name.lower() == query or str(skill.invocation_name or "").lower() == query
        ]
        if len(exact) == 1:
            return exact[0], exact

        prefix = [
            skill for skill in candidates
            if skill.name.lower().startswith(query)
            or str(skill.invocation_name or "").lower().startswith(query)
            or str(skill.registry_slug or "").lower().startswith(query)
        ]
        if len(prefix) == 1:
            return prefix[0], prefix
        return None, prefix

    @classmethod
    def _build_invocation_metadata(
        cls,
        manifest: SkillPackageManifest,
        instruction_content: str | None,
    ) -> Dict[str, Any]:
        if manifest.runtime == "instruction":
            return {
                "run_mode_description": (
                    "这是 instruction 技能：启用后会作为 Serana 的对话提示参与回答，"
                    "不会在聊天中被当作脚本直接执行。"
                ),
                "invocation_name": None,
                "invocation_parameters": [],
                "invocation_examples": [],
            }

        if manifest.runtime not in {"python", "script"} or not manifest.tools:
            return {
                "run_mode_description": "该技能暂未声明可在聊天中直接调用的工具。",
                "invocation_name": None,
                "invocation_parameters": [],
                "invocation_examples": [],
            }

        tool = manifest.tools[0]
        parameters = refine_parameters_with_instruction(
            cls._ordered_tool_parameters(manifest, tool),
            instruction_content or "",
        )
        invocation_name = make_invocation_name(manifest.name)
        examples = build_invocation_examples(
            instruction_content or "",
            invocation_name=invocation_name,
            entrypoint_names=cls._entrypoint_names(manifest),
            parameters=parameters,
            max_examples=4,
        )
        adapter = ""
        if manifest.runtime == "script" and manifest.script:
            adapter = f" ({manifest.script.adapter})"
        return {
            "run_mode_description": (
                f"这是 {manifest.runtime}{adapter} 技能：普通自然语言不会自动触发；"
                f"请在聊天框使用 @{invocation_name} 参数... 显式调用。"
            ),
            "invocation_name": invocation_name,
            "invocation_parameters": parameters,
            "invocation_examples": examples,
        }

    @staticmethod
    def _ordered_tool_parameters(
        manifest: SkillPackageManifest,
        tool: SkillTool,
    ) -> List[Dict[str, Any]]:
        schema = tool.input_schema
        properties = dict(schema.properties or {})
        configured_order = []
        if manifest.script and manifest.script.argument_order:
            configured_order = list(manifest.script.argument_order)
        ordered_names = [
            name for name in [*configured_order, *schema.required, *properties.keys()]
            if name in properties or name in schema.required
        ]
        ordered_names = list(dict.fromkeys(ordered_names))
        parameters = []
        for name in ordered_names:
            raw_property = properties.get(name) or {}
            required = name in set(schema.required or [])
            parameters.append(
                {
                    "name": name,
                    "type": str(raw_property.get("type") or "string"),
                    "description": str(raw_property.get("description") or ""),
                    "required": required,
                }
            )
        return parameters

    @staticmethod
    def _parameter_placeholder(parameter: Dict[str, Any]) -> str:
        return parameter_placeholder(parameter)

    @staticmethod
    def _entrypoint_names(manifest: SkillPackageManifest) -> List[str]:
        names = [manifest.name]
        if manifest.registry_slug:
            names.append(manifest.registry_slug)
        if manifest.entrypoint:
            entrypoint = Path(manifest.entrypoint)
            names.extend([entrypoint.name, entrypoint.stem])
        names.extend(tool.name for tool in manifest.tools)
        return list(dict.fromkeys(name for name in names if name))

    def enable_skill(self, skill_name: str) -> bool:
        if skill_name not in self.skills:
            return False
        self.skills[skill_name].is_enabled = True
        if skill_name not in self.enabled_skills:
            self.enabled_skills.append(skill_name)
        tool_logger.info("Enabled skill: %s", skill_name)
        return True

    def disable_skill(self, skill_name: str) -> bool:
        if skill_name not in self.skills:
            return False
        self.skills[skill_name].is_enabled = False
        if skill_name in self.enabled_skills:
            self.enabled_skills.remove(skill_name)
        tool_logger.info("Disabled skill: %s", skill_name)
        return True

    def update_skill_scope(self, skill_name: str, agent_type: str) -> Optional[SkillPackage]:
        if agent_type not in {"all", "serana", "forge"}:
            return None
        skill = self.skills.get(skill_name)
        if skill is None:
            return None

        skill.agent_type = agent_type
        skill.effective_scope = agent_type
        skill.manifest.agent_type = agent_type
        self._persist_manifest(skill)
        tool_logger.info("Updated skill scope: %s -> %s", skill_name, agent_type)
        return skill

    def unload_skill(self, skill_name: str) -> bool:
        if skill_name not in self.skills:
            return False
        self.loader.unload_skill(skill_name)
        if skill_name in self.enabled_skills:
            self.enabled_skills.remove(skill_name)
        del self.skills[skill_name]
        tool_logger.info("Unloaded skill: %s", skill_name)
        return True

    def remove_skill(self, skill_name: str) -> Optional[SkillPackage]:
        skill = self.skills.get(skill_name)
        if skill is None or not skill.can_uninstall:
            return None

        skill_path = Path(skill.path).resolve() if skill.path else self.managed_skills_path / skill_name
        if not self._is_within(skill_path, self.managed_skills_path):
            return None

        removed_skill = skill.model_copy(deep=True)
        self.loader.unload_skill(skill_name)
        if skill_name in self.enabled_skills:
            self.enabled_skills.remove(skill_name)
        self.skills.pop(skill_name, None)

        if skill_path.exists():
            shutil.rmtree(skill_path)

        fallback_path = self.bundled_skills_path / skill_name
        if fallback_path.exists() and fallback_path.is_dir():
            self._try_load_skill(fallback_path)

        tool_logger.info("Removed managed skill: %s", skill_name)
        return removed_skill

    def inspect_skill_directory(self, source_path: Path) -> Optional[SkillPackageManifest]:
        is_valid, errors = SkillValidator.validate_skill_directory(source_path)
        if not is_valid:
            tool_logger.error("Cannot inspect skill: %s", errors)
            return None
        return self.loader.load_manifest(source_path)

    def install_skill_from_directory(self, source_path: Path) -> Optional[SkillPackage]:
        manifest = self.inspect_skill_directory(source_path)
        if not manifest:
            return None

        target_path = self.managed_skills_path / manifest.name
        backup_path = self.managed_skills_path / f".{manifest.name}.backup-{uuid.uuid4().hex}"
        if target_path.exists():
            tool_logger.warning("Skill %s already exists, overwriting...", manifest.name)
            self.unload_skill(manifest.name)
            self.skills.pop(manifest.name, None)
            if manifest.name in self.enabled_skills:
                self.enabled_skills.remove(manifest.name)
            target_path.rename(backup_path)

        try:
            shutil.copytree(source_path, target_path)
            installed = self._try_load_skill(target_path)
            if installed is None:
                raise RuntimeError("Skill copied successfully but failed runtime registration.")
            if backup_path.exists():
                shutil.rmtree(backup_path, ignore_errors=True)
            return installed
        except Exception as exc:
            tool_logger.error("Unable to install skill %s: %s", manifest.name, exc)
            if target_path.exists():
                shutil.rmtree(target_path, ignore_errors=True)
            if backup_path.exists():
                backup_path.rename(target_path)
                self._try_load_skill(target_path)
            return None

    def update_remote_skill_from_directory(self, skill_name: str, source_path: Path) -> Optional[SkillPackage]:
        current = self.skills.get(skill_name)
        if current is None or not current.can_update:
            return None
        manifest = self.inspect_skill_directory(source_path)
        if not manifest:
            return None
        if manifest.name != current.name:
            tool_logger.error(
                "Refusing update for %s: package name changed to %s",
                skill_name,
                manifest.name,
            )
            return None
        if manifest.registry_slug != current.registry_slug:
            tool_logger.error(
                "Refusing update for %s: registry slug changed from %s to %s",
                skill_name,
                current.registry_slug,
                manifest.registry_slug,
            )
            return None

        target_path = Path(current.path).resolve() if current.path else self.managed_skills_path / skill_name
        if not self._is_within(target_path, self.managed_skills_path):
            return None

        backup_path = self.managed_skills_path / f".{skill_name}.update-backup-{uuid.uuid4().hex}"
        self.unload_skill(skill_name)
        self.skills.pop(skill_name, None)
        if skill_name in self.enabled_skills:
            self.enabled_skills.remove(skill_name)
        if target_path.exists():
            target_path.rename(backup_path)

        try:
            shutil.copytree(source_path, target_path)
            updated = self._try_load_skill(target_path)
            if updated is None:
                raise RuntimeError("Skill update copied successfully but failed runtime registration.")
            if backup_path.exists():
                shutil.rmtree(backup_path, ignore_errors=True)
            return updated
        except Exception as exc:
            tool_logger.error("Unable to update skill %s: %s", skill_name, exc)
            self.loader.unload_skill(skill_name)
            self.skills.pop(skill_name, None)
            if skill_name in self.enabled_skills:
                self.enabled_skills.remove(skill_name)
            if target_path.exists():
                shutil.rmtree(target_path, ignore_errors=True)
            if backup_path.exists():
                backup_path.rename(target_path)
                self._try_load_skill(target_path)
            return None

    def stage_skill_installation(self, request_id: str, source_path: Path) -> Optional[SkillPackageManifest]:
        manifest = self.inspect_skill_directory(source_path)
        if not manifest:
            return None

        staging_root = self.staged_uploads_path / request_id
        if staging_root.exists():
            shutil.rmtree(staging_root)
        staging_root.mkdir(parents=True, exist_ok=True)

        target_path = staging_root / manifest.name
        shutil.copytree(source_path, target_path)
        return manifest

    def consume_staged_skill_installation(self, request_id: str) -> Optional[SkillPackage]:
        staging_root = self.staged_uploads_path / request_id
        if not staging_root.exists():
            return None

        try:
            skill_source = next(
                (
                    item
                    for item in staging_root.iterdir()
                    if item.is_dir() and (item / "skill.json").exists()
                ),
                None,
            )
            if skill_source is None:
                return None
            return self.install_skill_from_directory(skill_source)
        finally:
            self.discard_staged_skill_installation(request_id)

    def discard_staged_skill_installation(self, request_id: str) -> None:
        staging_root = self.staged_uploads_path / request_id
        if staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)

    async def shutdown(self) -> None:
        """Release resources held by long-lived skills."""
        browser_close = self.get_tool_function("browser", "close_browser")
        if browser_close is not None:
            try:
                result = browser_close()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                tool_logger.warning("Error shutting down browser skill: %s", exc)

    def _get_skill_origin(self, skill_path: Path) -> str:
        return "managed" if self._is_within(skill_path.resolve(), self.managed_skills_path.resolve()) else "bundled"

    def _get_source_label(self, origin: str, manifest: SkillPackageManifest) -> str:
        if manifest.source_url and "skillhub" in manifest.source_url:
            return "SkillHub 市场"
        if origin == "managed":
            return "本地导入"
        return "项目内置"

    def _get_trust_state(self, origin: str, manifest: SkillPackageManifest) -> str:
        if origin == "bundled":
            return "trusted"
        if manifest.source_url and "skillhub" in manifest.source_url:
            return "marketplace"
        return "local"

    def _persist_manifest(self, skill: SkillPackage) -> None:
        if not skill.path:
            return
        metadata_path = Path(skill.path) / "skill.json"
        if not metadata_path.exists():
            return
        metadata_path.write_text(
            json.dumps(skill.manifest.model_dump(exclude_none=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False
