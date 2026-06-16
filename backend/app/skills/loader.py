import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from app.core.logger import get_logger
from app.skills.models import SkillPackageManifest
from app.skills.script_runtime import ScriptSkillError, ScriptSkillRunner


startup_logger = get_logger("app.startup.skills")
tool_logger = get_logger("app.tool.skills")


class SkillLoader:
    """Load Serana skill packages."""

    PACKAGE_METADATA_FILE = "skill.json"

    def __init__(self, skills_store_path: str):
        self.skills_store_path = Path(skills_store_path)
        self.loaded_modules: Dict[str, Any] = {}
        self.loaded_tools: Dict[str, Callable] = {}

    def get_metadata_path(self, skill_path: Path) -> Optional[Path]:
        package_metadata = skill_path / self.PACKAGE_METADATA_FILE
        if package_metadata.exists():
            return package_metadata

        return None

    def load_manifest(self, skill_path: Path) -> Optional[SkillPackageManifest]:
        metadata_path = self.get_metadata_path(skill_path)
        if not metadata_path:
            startup_logger.warning("Skill metadata not found at %s", skill_path)
            return None

        try:
            import json

            with open(metadata_path, "r", encoding="utf-8-sig") as file:
                manifest_data = json.load(file)
            return SkillPackageManifest(**manifest_data)
        except Exception as exc:
            startup_logger.error("Error loading skill metadata from %s: %s", skill_path, exc)
            return None

    def load_instruction_content(self, skill_path: Path, manifest: SkillPackageManifest) -> Optional[str]:
        instruction_path = skill_path / manifest.instruction_file
        if not instruction_path.exists():
            return None

        try:
            return instruction_path.read_text(encoding="utf-8")
        except Exception as exc:
            startup_logger.warning("Unable to read instruction file for %s: %s", manifest.name, exc)
            return None

    def load_skill_module(self, skill_path: Path, manifest: SkillPackageManifest) -> Optional[Any]:
        if manifest.runtime != "python":
            return None

        entrypoint = manifest.entrypoint or "__init__.py"
        module_path = skill_path / entrypoint
        if not module_path.exists():
            startup_logger.warning("Entrypoint %s not found for skill %s", entrypoint, manifest.name)
            return None

        try:
            spec = importlib.util.spec_from_file_location(
                f"skills.{manifest.name}",
                module_path,
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[f"skills.{manifest.name}"] = module
                spec.loader.exec_module(module)
                self.loaded_modules[manifest.name] = module
                return module
        except Exception as exc:
            startup_logger.error("Error loading module %s: %s", manifest.name, exc)
        return None

    def load_tools_from_module(self, module: Any, manifest: SkillPackageManifest) -> Dict[str, Callable]:
        tools: Dict[str, Callable] = {}

        if manifest.runtime != "python":
            return tools

        for tool_def in manifest.tools:
            tool_name = tool_def.name
            if hasattr(module, tool_name):
                tool_func = getattr(module, tool_name)
                if callable(tool_func):
                    tools[tool_name] = tool_func
                    self.loaded_tools[f"{manifest.name}.{tool_name}"] = tool_func
                    startup_logger.debug("Loaded tool: %s.%s", manifest.name, tool_name)
            else:
                startup_logger.warning("Tool %s not found in module %s", tool_name, manifest.name)

        return tools

    def load_script_tools(self, skill_path: Path, manifest: SkillPackageManifest) -> Dict[str, Callable]:
        if manifest.runtime != "script":
            return {}
        try:
            tools = ScriptSkillRunner.build_tools(skill_path, manifest)
        except ScriptSkillError as exc:
            startup_logger.error("Unable to initialize Script Skill %s: %s", manifest.name, exc)
            return {}
        for tool_name, tool_func in tools.items():
            self.loaded_tools[f"{manifest.name}.{tool_name}"] = tool_func
            startup_logger.debug("Loaded Script Skill tool: %s.%s", manifest.name, tool_name)
        return tools

    def unload_skill(self, package_name: str):
        if package_name in self.loaded_modules:
            del self.loaded_modules[package_name]

        keys_to_delete = [key for key in self.loaded_tools if key.startswith(f"{package_name}.")]
        for key in keys_to_delete:
            del self.loaded_tools[key]

        module_name = f"skills.{package_name}"
        if module_name in sys.modules:
            del sys.modules[module_name]

        tool_logger.info("Unloaded skill: %s", package_name)

    def get_tool(self, skill_name: str, tool_name: str) -> Optional[Callable]:
        return self.loaded_tools.get(f"{skill_name}.{tool_name}")
