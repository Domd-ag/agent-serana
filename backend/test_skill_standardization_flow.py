import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from app.core.config import get_settings
from app.skills.loader import SkillLoader
from app.skills.manager import SkillManager
from app.skills.models import MarketplaceSkillDetail
from app.skills.script_runtime import ShellScriptAdapter
from app.skills.skillhub import SkillHubClient, SkillHubError


def _build_skill_archive(script: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("sample/SKILL.md", "# Sample Query\n\n使用：`./query.sh 内容`\n")
        archive.writestr("sample/query.sh", script)
    return buffer.getvalue()


def _build_skill_archive_with_docs(skill_md: str, script: str, script_name: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("sample/SKILL.md", skill_md)
        archive.writestr(f"sample/{script_name}", script)
    return buffer.getvalue()


def _isolated_manager(root: Path) -> SkillManager:
    manager = object.__new__(SkillManager)
    manager.skills_store_path = root
    manager.managed_skills_path = root / "installed"
    manager.managed_skills_path.mkdir(parents=True)
    manager.staged_uploads_path = root / ".staging"
    manager.staged_uploads_path.mkdir()
    manager.loader = SkillLoader(str(root))
    manager.skills = {}
    manager.enabled_skills = []
    manager._skills_loaded = True
    return manager


def _detail() -> MarketplaceSkillDetail:
    return MarketplaceSkillDetail(
        slug="sample-query",
        display_name="Sample Query",
        summary="查询指定内容",
        owner_handle="tester",
        owner_display_name="Tester",
        latest_version="1.0.0",
        canonical_url="https://skillhub.cn/skills/sample-query",
        download_url="https://api.skillhub.cn/api/v1/download?slug=sample-query",
    )


class SkillStandardizationFlowTests(unittest.TestCase):
    def test_skill_manager_uses_configured_persistent_skill_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.dict("os.environ", {"SERANA_SKILLS_DIR": str(root)}):
                get_settings.cache_clear()
                SkillManager._instance = None
                SkillManager._initialized = False
                try:
                    manager = SkillManager()
                    manager.initialize()

                    self.assertEqual(manager.skills_store_path, root)
                    self.assertEqual(manager.managed_skills_path, root / "installed")
                    self.assertIn("browser", manager.skills)
                    self.assertNotIn(str(root), manager.skills["browser"].path)
                finally:
                    SkillManager._instance = None
                    SkillManager._initialized = False
                    get_settings.cache_clear()

    def test_skillhub_download_standardizes_and_registers_safe_shell_skill(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = _isolated_manager(Path(temp_dir))
            client = SkillHubClient()
            archive = _build_skill_archive("#!/bin/bash\necho \"结果：$1\"\n")

            with (
                patch.object(client, "get_skill_detail", return_value=_detail()),
                patch.object(client, "_http_get_bytes", return_value=archive),
                patch.object(ShellScriptAdapter, "find_bash", return_value=Path("C:/fake/bash.exe")),
            ):
                skill = client.install_skill("sample-query", manager)

            self.assertEqual(skill.runtime, "script")
            self.assertEqual(skill.manifest.script.adapter, "shell")
            self.assertIsNotNone(manager.get_tool_function(skill.name, "query"))
            self.assertTrue((manager.managed_skills_path / skill.name / "skill.json").is_file())

    def test_skillhub_shell_skill_infers_invocation_protocol_from_quick_start(self):
        skill_md = """# Weather CN Pro

## Quick Start

```bash
./weather-cn-pro.sh 上海
./weather-cn-pro.sh 北京 3
```

| 参数 | 说明 | 必填 |
| --- | --- | --- |
| city | 城市名称，例如 上海 | 是 |
| days | 预报天数，例如 3 | 否 |
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = _isolated_manager(Path(temp_dir))
            client = SkillHubClient()
            detail = MarketplaceSkillDetail(
                slug="weather-cn-pro",
                display_name="Weather CN Pro",
                summary="中文天气脚本",
                owner_handle="tester",
                owner_display_name="Tester",
                latest_version="1.0.0",
                canonical_url="https://skillhub.cn/skills/weather-cn-pro",
                download_url="https://api.skillhub.cn/api/v1/download?slug=weather-cn-pro",
            )
            archive = _build_skill_archive_with_docs(
                skill_md,
                "#!/bin/bash\necho \"$1 $2\"\n",
                "weather-cn-pro.sh",
            )

            with (
                patch.object(client, "get_skill_detail", return_value=detail),
                patch.object(client, "_http_get_bytes", return_value=archive),
                patch.object(ShellScriptAdapter, "find_bash", return_value=Path("C:/fake/bash.exe")),
            ):
                skill = client.install_skill("weather-cn-pro", manager)

            self.assertEqual(skill.runtime, "script")
            self.assertEqual(skill.invocation_name, "weather_cn_pro")
            self.assertEqual(skill.manifest.script.argument_order, ["city", "days"])
            tool = skill.manifest.tools[0]
            self.assertEqual(tool.input_schema.required, ["city"])
            self.assertIn("城市", tool.input_schema.properties["city"]["description"])
            self.assertIn("天数", tool.input_schema.properties["days"]["description"])
            self.assertIn("@weather_cn_pro 上海", skill.invocation_examples)
            self.assertIn("@weather_cn_pro 北京 3", skill.invocation_examples)

    def test_skillhub_download_rejects_dangerous_shell_skill_without_residue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = _isolated_manager(Path(temp_dir))
            client = SkillHubClient()
            archive = _build_skill_archive("#!/bin/bash\nsudo rm -rf /\n")

            with (
                patch.object(client, "get_skill_detail", return_value=_detail()),
                patch.object(client, "_http_get_bytes", return_value=archive),
            ):
                with self.assertRaisesRegex(SkillHubError, "安全检查"):
                    client.install_skill("sample-query", manager)

            self.assertEqual(list(manager.managed_skills_path.iterdir()), [])

    def test_failed_runtime_registration_restores_previous_skill(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = _isolated_manager(root)
            old_source = root / "old-source"
            old_source.mkdir()
            (old_source / "SKILL.md").write_text("# Stable", encoding="utf-8")
            (old_source / "skill.json").write_text(
                json.dumps(
                    {
                        "name": "stable_skill",
                        "version": "1.0.0",
                        "description": "稳定版本",
                        "runtime": "instruction",
                        "instruction_file": "SKILL.md",
                        "entrypoint": None,
                        "agent_type": "all",
                        "tools": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            previous = manager.install_skill_from_directory(old_source)

            new_source = root / "new-source"
            new_source.mkdir()
            (new_source / "SKILL.md").write_text("# Shell", encoding="utf-8")
            (new_source / "run.sh").write_text("#!/bin/bash\necho \"$1\"\n", encoding="utf-8")
            (new_source / "skill.json").write_text(
                json.dumps(
                    {
                        "name": "stable_skill",
                        "version": "2.0.0",
                        "description": "需要 Bash 的版本",
                        "runtime": "script",
                        "instruction_file": "SKILL.md",
                        "entrypoint": "run.sh",
                        "agent_type": "all",
                        "permissions": [],
                        "script": {
                            "adapter": "shell",
                            "argument_order": ["query"],
                            "output_format": "text",
                        },
                        "tools": [
                            {
                                "name": "run",
                                "description": "运行",
                                "input_schema": {
                                    "type": "object",
                                    "properties": {"query": {"type": "string"}},
                                    "required": ["query"],
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(ShellScriptAdapter, "find_bash", return_value=None):
                updated = manager.install_skill_from_directory(new_source)

            self.assertIsNotNone(previous)
            self.assertIsNone(updated)
            self.assertEqual(manager.get_skill("stable_skill").version, "1.0.0")
            self.assertTrue((manager.managed_skills_path / "stable_skill" / "SKILL.md").is_file())

    def test_failed_remote_update_restores_previous_skill(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = _isolated_manager(root)
            old_source = root / "old-source"
            old_source.mkdir()
            (old_source / "SKILL.md").write_text("# Stable", encoding="utf-8")
            (old_source / "skill.json").write_text(
                json.dumps(
                    {
                        "name": "stable_skill",
                        "version": "1.0.0",
                        "description": "稳定版本",
                        "runtime": "instruction",
                        "instruction_file": "SKILL.md",
                        "entrypoint": None,
                        "registry_slug": "stable-skill",
                        "source_url": "https://skillhub.cn/skills/stable-skill",
                        "agent_type": "all",
                        "tools": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            previous = manager.install_skill_from_directory(old_source)
            self.assertIsNotNone(previous)
            self.assertTrue(previous.can_update)

            new_source = root / "new-source"
            new_source.mkdir()
            (new_source / "SKILL.md").write_text("# Shell", encoding="utf-8")
            (new_source / "run.sh").write_text("#!/bin/bash\necho \"$1\"\n", encoding="utf-8")
            (new_source / "skill.json").write_text(
                json.dumps(
                    {
                        "name": "stable_skill",
                        "version": "2.0.0",
                        "description": "需要 Bash 的版本",
                        "runtime": "script",
                        "instruction_file": "SKILL.md",
                        "entrypoint": "run.sh",
                        "registry_slug": "stable-skill",
                        "source_url": "https://skillhub.cn/skills/stable-skill",
                        "agent_type": "all",
                        "permissions": [],
                        "script": {
                            "adapter": "shell",
                            "argument_order": ["query"],
                            "output_format": "text",
                        },
                        "tools": [
                            {
                                "name": "run",
                                "description": "运行",
                                "input_schema": {
                                    "type": "object",
                                    "properties": {"query": {"type": "string"}},
                                    "required": ["query"],
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(ShellScriptAdapter, "find_bash", return_value=None):
                updated = manager.update_remote_skill_from_directory("stable_skill", new_source)

            self.assertIsNone(updated)
            restored = manager.get_skill("stable_skill")
            self.assertIsNotNone(restored)
            self.assertEqual(restored.version, "1.0.0")
            self.assertTrue((manager.managed_skills_path / "stable_skill" / "SKILL.md").is_file())
