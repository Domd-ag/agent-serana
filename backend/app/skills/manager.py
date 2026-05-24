from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional
import uuid

from app.core.logger import get_logger
from app.skills.loader import SkillLoader
from app.skills.models import SkillPackage, SkillTool
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

    def unload_skill(self, skill_name: str) -> bool:
        if skill_name not in self.skills:
            return False
        self.loader.unload_skill(skill_name)
        if skill_name in self.enabled_skills:
            self.enabled_skills.remove(skill_name)
        del self.skills[skill_name]
        tool_logger.info("Unloaded skill: %s", skill_name)
        return True

    def install_skill_from_directory(self, source_path: Path) -> Optional[SkillPackage]:
        import shutil

        is_valid, errors = SkillValidator.validate_skill_directory(source_path)
        if not is_valid:
            tool_logger.error("Cannot install skill: %s", errors)
            return None

        manifest = self.loader.load_manifest(source_path)
        if not manifest:
            return None

        target_path = self.skills_store_path / manifest.name
        if target_path.exists():
            tool_logger.warning("Skill %s already exists, overwriting...", manifest.name)
            self.unload_skill(manifest.name)
            shutil.rmtree(target_path)

        shutil.copytree(source_path, target_path)
        return self._try_load_skill(target_path)
