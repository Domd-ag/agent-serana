import json
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from app.skills.loader import SkillLoader
from app.skills.models import SkillPackageManifest
from app.skills.script_runtime import PythonScriptAdapter, ScriptSkillError, ShellScriptAdapter
from app.skills.standardizer import SkillStandardizationError, SkillStandardizer
from app.skills.validator import SkillValidator


def _manifest_payload(
    *,
    timeout_seconds: float = 5.0,
    max_output_chars: int = 4096,
    permissions: list[str] | None = None,
) -> dict:
    return {
        "name": "script_test",
        "version": "1.0.0",
        "description": "受控 Script Skill 测试",
        "runtime": "script",
        "instruction_file": "SKILL.md",
        "entrypoint": "main.py",
        "agent_type": "all",
        "max_instances": 1,
        "permissions": permissions or [],
        "script": {
            "adapter": "python",
            "timeout_seconds": timeout_seconds,
            "max_input_chars": 4096,
            "max_output_chars": max_output_chars,
        },
        "tools": [
            {
                "name": "run",
                "description": "执行测试脚本",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                    },
                    "required": ["value"],
                },
            }
        ],
    }


class ScriptRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def _create_skill(
        self,
        root: Path,
        script: str,
        *,
        timeout_seconds: float = 5.0,
        max_output_chars: int = 4096,
        permissions: list[str] | None = None,
    ) -> tuple[Path, SkillPackageManifest]:
        skill_path = root / "script_test"
        skill_path.mkdir()
        payload = _manifest_payload(
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
            permissions=permissions,
        )
        (skill_path / "skill.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        (skill_path / "SKILL.md").write_text("# Script Test", encoding="utf-8")
        (skill_path / "main.py").write_text(textwrap.dedent(script), encoding="utf-8")
        return skill_path, SkillPackageManifest(**payload)

    async def test_python_script_adapter_executes_json_protocol(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path, manifest = self._create_skill(
                Path(temp_dir),
                """
                import json
                import sys

                request = json.load(sys.stdin)
                print(json.dumps({
                    "summary": f"received {request['arguments']['value']}",
                    "selected_tool": request["tool"],
                }, ensure_ascii=False))
                """,
            )
            adapter = PythonScriptAdapter(skill_path, manifest)

            result = await adapter.run(manifest.tools[0], {"value": "上海"})

            self.assertEqual(result["summary"], "received 上海")
            self.assertEqual(result["selected_tool"], "run")
            self.assertEqual(result["runtime"], "script")

    async def test_loader_registers_script_skill_tools(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_path, manifest = self._create_skill(
                root,
                """
                import json
                import sys
                request = json.load(sys.stdin)
                print(json.dumps({"summary": request["arguments"]["value"]}))
                """,
            )
            loader = SkillLoader(str(root))

            tools = loader.load_script_tools(skill_path, manifest)
            result = await loader.get_tool("script_test", "run")(value="registered")

            self.assertIn("run", tools)
            self.assertEqual(result["summary"], "registered")

    async def test_script_runtime_rejects_unknown_arguments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path, manifest = self._create_skill(Path(temp_dir), "print('{}')")
            adapter = PythonScriptAdapter(skill_path, manifest)

            with self.assertRaisesRegex(ScriptSkillError, "未在 schema 中声明"):
                await adapter.run(manifest.tools[0], {"value": "ok", "command": "whoami"})

    async def test_script_runtime_rejects_boolean_for_integer_argument(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path, manifest = self._create_skill(Path(temp_dir), "print('{}')")
            manifest.tools[0].input_schema.properties["value"]["type"] = "integer"
            adapter = PythonScriptAdapter(skill_path, manifest)

            with self.assertRaisesRegex(ScriptSkillError, "应为 integer"):
                await adapter.run(manifest.tools[0], {"value": True})

    async def test_script_runtime_blocks_network_without_permission(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path, manifest = self._create_skill(
                Path(temp_dir),
                """
                import json
                import socket
                import sys
                json.load(sys.stdin)
                socket.getaddrinfo("example.com", 443)
                print("{}")
                """,
            )
            adapter = PythonScriptAdapter(skill_path, manifest)

            with self.assertRaisesRegex(ScriptSkillError, "未声明 network 权限"):
                await adapter.run(manifest.tools[0], {"value": "ok"})

    async def test_script_runtime_blocks_writes_outside_skill_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_path, manifest = self._create_skill(
                root,
                """
                import json
                import pathlib
                import sys
                json.load(sys.stdin)
                pathlib.Path("../outside.txt").write_text("blocked", encoding="utf-8")
                print("{}")
                """,
                permissions=["filesystem_write"],
            )
            adapter = PythonScriptAdapter(skill_path, manifest)

            with self.assertRaisesRegex(ScriptSkillError, "文件写入权限"):
                await adapter.run(manifest.tools[0], {"value": "ok"})
            self.assertFalse((root / "outside.txt").exists())

    async def test_script_runtime_allows_declared_write_inside_skill_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_path, manifest = self._create_skill(
                root,
                """
                import json
                import pathlib
                import sys
                json.load(sys.stdin)
                pathlib.Path("result.txt").write_text("allowed", encoding="utf-8")
                print(json.dumps({"summary": "written"}))
                """,
                permissions=["filesystem_write"],
            )
            adapter = PythonScriptAdapter(skill_path, manifest)

            result = await adapter.run(manifest.tools[0], {"value": "ok"})

            self.assertEqual(result["summary"], "written")
            self.assertEqual((skill_path / "result.txt").read_text(encoding="utf-8"), "allowed")

    async def test_script_runtime_does_not_inherit_sensitive_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path, manifest = self._create_skill(
                Path(temp_dir),
                """
                import json
                import os
                import sys
                json.load(sys.stdin)
                print(json.dumps({"secret": os.environ.get("SERANA_TEST_SECRET")}))
                """,
            )
            adapter = PythonScriptAdapter(skill_path, manifest)

            with patch.dict("os.environ", {"SERANA_TEST_SECRET": "must-not-leak"}):
                result = await adapter.run(manifest.tools[0], {"value": "ok"})

            self.assertIsNone(result["secret"])

    async def test_script_runtime_enforces_output_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path, manifest = self._create_skill(
                Path(temp_dir),
                """
                import json
                import sys
                json.load(sys.stdin)
                print(json.dumps({"summary": "x" * 5000}))
                """,
                max_output_chars=1024,
            )
            adapter = PythonScriptAdapter(skill_path, manifest)

            with self.assertRaisesRegex(ScriptSkillError, "输出超过限制"):
                await adapter.run(manifest.tools[0], {"value": "ok"})

    async def test_script_runtime_enforces_timeout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path, manifest = self._create_skill(
                Path(temp_dir),
                """
                import json
                import sys
                import time
                json.load(sys.stdin)
                time.sleep(2)
                print("{}")
                """,
                timeout_seconds=1.0,
            )
            adapter = PythonScriptAdapter(skill_path, manifest)

            with self.assertRaisesRegex(ScriptSkillError, "执行超时"):
                await adapter.run(manifest.tools[0], {"value": "ok"})

    def test_validator_accepts_declared_python_script_runtime(self):
        is_valid, error = SkillValidator.validate_manifest(_manifest_payload())

        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_validator_rejects_shell_script_runtime(self):
        payload = _manifest_payload()
        payload["entrypoint"] = "run.sh"

        is_valid, error = SkillValidator.validate_manifest(payload)

        self.assertFalse(is_valid)
        self.assertIn(".py", error or "")

    def test_validator_rejects_unsupported_script_permission(self):
        payload = _manifest_payload(permissions=["subprocess"])

        is_valid, error = SkillValidator.validate_manifest(payload)

        self.assertFalse(is_valid)
        self.assertIn("不支持的权限", error or "")

    def test_validator_rejects_script_entrypoint_outside_skill_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_path = root / "script_test"
            skill_path.mkdir()
            payload = _manifest_payload()
            payload["entrypoint"] = "../outside.py"
            (skill_path / "skill.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            (skill_path / "SKILL.md").write_text("# Script Test", encoding="utf-8")
            (root / "outside.py").write_text("print('{}')", encoding="utf-8")

            is_valid, errors = SkillValidator.validate_skill_directory(skill_path)

            self.assertFalse(is_valid)
            self.assertTrue(any("入口必须位于技能目录内" in error for error in errors))

    def test_validator_rejects_python_entrypoint_and_instruction_outside_skill_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_path = root / "script_test"
            skill_path.mkdir()
            payload = _manifest_payload()
            payload["runtime"] = "python"
            payload["entrypoint"] = "../outside.py"
            payload["instruction_file"] = "../OUTSIDE.md"
            (skill_path / "skill.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            (root / "outside.py").write_text("def run(value): return value", encoding="utf-8")
            (root / "OUTSIDE.md").write_text("# outside", encoding="utf-8")

            is_valid, errors = SkillValidator.validate_skill_directory(skill_path)

            self.assertFalse(is_valid)
            self.assertTrue(any("Python 技能入口必须位于技能目录内" in error for error in errors))
            self.assertTrue(any("instruction_file 必须位于技能目录内" in error for error in errors))

    def test_loader_accepts_utf8_bom_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_path = root / "script_test"
            skill_path.mkdir()
            payload = _manifest_payload()
            (skill_path / "skill.json").write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8-sig",
            )
            (skill_path / "SKILL.md").write_text("# Script Test", encoding="utf-8")
            (skill_path / "main.py").write_text("print('{}')", encoding="utf-8")

            manifest = SkillLoader(str(root)).load_manifest(skill_path)

            self.assertIsNotNone(manifest)
            self.assertEqual(manifest.name, "script_test")

    def test_validator_accepts_declared_shell_script_runtime(self):
        payload = _manifest_payload(permissions=["network"])
        payload["entrypoint"] = "run.sh"
        payload["script"]["adapter"] = "shell"
        payload["script"]["argument_order"] = ["value"]
        payload["script"]["output_format"] = "text"

        is_valid, error = SkillValidator.validate_manifest(payload)

        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_standardizer_promotes_safe_single_shell_skill(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path = Path(temp_dir)
            (skill_path / "SKILL.md").write_text(
                "# 天气查询\n\n使用方法：`./weather.sh 上海`\n",
                encoding="utf-8",
            )
            (skill_path / "weather.sh").write_text(
                "#!/bin/bash\ncurl -s \"https://example.com/$1\"\n",
                encoding="utf-8",
            )

            with patch.object(ShellScriptAdapter, "find_bash", return_value=Path("C:/fake/bash.exe")):
                manifest = SkillStandardizer.standardize_marketplace_package(
                    skill_path,
                    local_name="weather_test",
                    version="1.0.0",
                    description="查询天气",
                    author="tester",
                    registry_slug="weather-test",
                    source_url="https://skillhub.cn/skills/weather-test",
                    capabilities=["weather", "天气"],
                    intents=["天气查询"],
                )
                loader = SkillLoader(str(skill_path.parent))
                loaded_manifest = loader.load_manifest(skill_path)
                tools = loader.load_script_tools(skill_path, loaded_manifest)

            self.assertEqual(manifest["runtime"], "script")
            self.assertEqual(manifest["script"]["adapter"], "shell")
            self.assertEqual(manifest["script"]["argument_order"], ["query"])
            self.assertEqual(manifest["tools"][0]["name"], "weather")
            self.assertIn("network", manifest["permissions"])
            self.assertIn("weather", tools)
            self.assertIsNotNone(loader.get_tool("weather_test", "weather"))

    def test_standardizer_rejects_dangerous_shell_skill(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path = Path(temp_dir)
            (skill_path / "SKILL.md").write_text("# Dangerous\n\n`./run.sh value`\n", encoding="utf-8")
            (skill_path / "run.sh").write_text("#!/bin/bash\nsudo rm -rf /\n", encoding="utf-8")

            with self.assertRaisesRegex(SkillStandardizationError, "安全检查"):
                SkillStandardizer.standardize_marketplace_package(
                    skill_path,
                    local_name="dangerous",
                    version="1.0.0",
                    description="危险测试",
                    author="tester",
                    registry_slug="dangerous",
                    source_url="https://skillhub.cn/skills/dangerous",
                    capabilities=[],
                    intents=[],
                )

    def test_standardizer_keeps_document_only_skill_as_instruction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path = Path(temp_dir)
            (skill_path / "SKILL.md").write_text("# Writing Guide", encoding="utf-8")

            manifest = SkillStandardizer.standardize_marketplace_package(
                skill_path,
                local_name="writing_guide",
                version="1.0.0",
                description="写作指导",
                author="tester",
                registry_slug="writing-guide",
                source_url="https://skillhub.cn/skills/writing-guide",
                capabilities=["writing"],
                intents=["写作建议"],
            )

            self.assertEqual(manifest["runtime"], "instruction")
            self.assertEqual(manifest["tools"], [])

    def test_standardizer_reports_missing_bash_for_shell_skill(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path = Path(temp_dir)
            (skill_path / "SKILL.md").write_text("# Query\n\n`./query.sh value`\n", encoding="utf-8")
            (skill_path / "query.sh").write_text("#!/bin/bash\necho \"$1\"\n", encoding="utf-8")

            with patch.object(ShellScriptAdapter, "find_bash", return_value=None):
                with self.assertRaisesRegex(SkillStandardizationError, "没有 Bash"):
                    SkillStandardizer.standardize_marketplace_package(
                        skill_path,
                        local_name="query",
                        version="1.0.0",
                        description="查询工具",
                        author="tester",
                        registry_slug="query",
                        source_url="https://skillhub.cn/skills/query",
                        capabilities=["query"],
                        intents=["查询"],
                    )
