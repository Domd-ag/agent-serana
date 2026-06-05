import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

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
