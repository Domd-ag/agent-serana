from datetime import datetime, timezone
import json
import inspect
from pathlib import Path
import shutil
from typing import Callable, Dict, List, Optional
import uuid

from app.core.logger import get_logger
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
        self.skills_store_path = backend_root / "skills_store"
        self.skills_store_path.mkdir(exist_ok=True)
        self.managed_skills_path = self.skills_store_path / "installed"
        self.managed_skills_path.mkdir(exist_ok=True)
        self.staged_uploads_path = self.skills_store_path / ".staging"
        self.staged_uploads_path.mkdir(exist_ok=True)

        self.loader = SkillLoader(str(self.skills_store_path))
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
        if not self.skills_store_path.exists():
            return

        for skill_dir in self.skills_store_path.iterdir():
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

        origin = self._get_skill_origin(skill_path)
        can_uninstall = origin == "managed"
        source_label = self._get_source_label(origin, manifest)
        trust_state = self._get_trust_state(origin, manifest)

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
            manifest=manifest,
            instruction_content=self.loader.load_instruction_content(skill_path, manifest),
            path=str(skill_path),
        )

        self.skills[skill_package.name] = skill_package
        self.enabled_skills.append(skill_package.name)
        startup_logger.debug("Loaded skill: %s v%s", skill_package.name, skill_package.version)
        return skill_package

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
        if agent_type not in {"all", "serana", "aide", "forge"}:
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

        fallback_path = self.skills_store_path / skill_name
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
        if target_path.exists():
            tool_logger.warning("Skill %s already exists, overwriting...", manifest.name)
            self.unload_skill(manifest.name)
            self.skills.pop(manifest.name, None)
            if manifest.name in self.enabled_skills:
                self.enabled_skills.remove(manifest.name)
            shutil.rmtree(target_path)

        shutil.copytree(source_path, target_path)
        return self._try_load_skill(target_path)

    def update_remote_skill_from_directory(self, skill_name: str, source_path: Path) -> Optional[SkillPackage]:
        current = self.skills.get(skill_name)
        if current is None or not current.can_update:
            return None
        manifest = self.inspect_skill_directory(source_path)
        if not manifest:
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

        self.unload_skill(skill_name)
        if target_path.exists():
            shutil.rmtree(target_path)
        shutil.copytree(source_path, target_path)
        self.skills.pop(skill_name, None)
        if skill_name in self.enabled_skills:
            self.enabled_skills.remove(skill_name)
        return self._try_load_skill(target_path)

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
