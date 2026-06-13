import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Awaitable, Callable

from app.skills.models import ScriptRuntimeConfig, SkillPackageManifest, SkillTool


class ScriptSkillError(RuntimeError):
    pass


class _ScriptAdapterBase:
    """Shared validation and process controls for Script Skill adapters."""

    _SAFE_ENV_KEYS = {
        "LANG",
        "LC_ALL",
        "PATH",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TZ",
        "USERPROFILE",
        "WINDIR",
    }
    _ALLOWED_PERMISSIONS = {"network", "filesystem_write"}

    def __init__(self, skill_path: Path, manifest: SkillPackageManifest):
        self.skill_path = skill_path.resolve()
        self.manifest = manifest
        self.config = manifest.script or ScriptRuntimeConfig()
        self._semaphore = asyncio.Semaphore(max(1, manifest.max_instances))
        self.permissions = {
            str(permission).strip().lower()
            for permission in (manifest.permissions or [])
            if str(permission).strip()
        }

    def _resolve_declared_entrypoint(self, entrypoint: str | None, expected_suffix: str) -> Path:
        if not entrypoint:
            raise ScriptSkillError("Script Skill 必须声明入口文件。")
        path = (self.skill_path / entrypoint).resolve()
        if path.suffix.lower() != expected_suffix:
            raise ScriptSkillError(f"Script Skill 入口必须是 {expected_suffix} 文件。")
        if path != self.skill_path and self.skill_path not in path.parents:
            raise ScriptSkillError("Script Skill 入口超出技能目录。")
        if not path.is_file():
            raise ScriptSkillError("Script Skill 入口文件不存在。")
        return path

    def _validate_arguments(self, tool: SkillTool, arguments: dict[str, Any]) -> None:
        schema = tool.input_schema
        properties = dict(schema.properties or {})
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            raise ScriptSkillError(f"工具参数未在 schema 中声明：{', '.join(unknown)}")
        missing = [name for name in schema.required if name not in arguments]
        if missing:
            raise ScriptSkillError(f"工具缺少必需参数：{', '.join(missing)}")

        expected_types = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "object": dict,
            "array": list,
        }
        for name, value in arguments.items():
            expected = str((properties.get(name) or {}).get("type") or "").lower()
            python_type = expected_types.get(expected)
            if expected in {"integer", "number"} and isinstance(value, bool):
                raise ScriptSkillError(f"工具参数 {name} 应为 {expected}。")
            if python_type and not isinstance(value, python_type):
                raise ScriptSkillError(f"工具参数 {name} 应为 {expected}。")

    def _build_environment(self) -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {allowed.upper() for allowed in self._SAFE_ENV_KEYS}
        }
        return environment

    async def _read_limited(self, stream: asyncio.StreamReader, max_chars: int) -> str:
        chunks: list[bytes] = []
        size = 0
        exceeded = False
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            size += len(chunk)
            if size > max_chars * 4:
                exceeded = True
                continue
            chunks.append(chunk)
        text = b"".join(chunks).decode("utf-8", errors="replace")
        if exceeded or len(text) > max_chars:
            raise ScriptSkillError("Script Skill 输出超过限制。")
        return text

    def _validate_permissions(self) -> None:
        unsupported_permissions = self.permissions - self._ALLOWED_PERMISSIONS
        if unsupported_permissions:
            raise ScriptSkillError(f"Script Skill 声明了不支持的权限：{', '.join(sorted(unsupported_permissions))}")

    def _validate_input_size(self, tool: SkillTool, arguments: dict[str, Any]) -> None:
        self._validate_arguments(tool, arguments)
        request_text = json.dumps(
            {"tool": tool.name, "arguments": arguments},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(request_text) > self.config.max_input_chars:
            raise ScriptSkillError("Script Skill 输入超过限制。")

    async def _collect_process_output(self, process: asyncio.subprocess.Process) -> tuple[str, str]:
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_task = asyncio.create_task(self._read_limited(process.stdout, self.config.max_output_chars))
        stderr_task = asyncio.create_task(self._read_limited(process.stderr, min(self.config.max_output_chars, 16384)))
        try:
            await asyncio.wait_for(process.wait(), timeout=self.config.timeout_seconds)
            stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        except (TimeoutError, ScriptSkillError) as exc:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
            stdout_task.cancel()
            stderr_task.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            if isinstance(exc, TimeoutError):
                raise ScriptSkillError(
                    f"Script Skill 执行超时（限制 {self.config.timeout_seconds:g} 秒）。"
                ) from exc
            raise

        if process.returncode != 0:
            detail = stderr.strip().splitlines()[-1] if stderr.strip() else "未知错误"
            missing_module = self._extract_missing_module(stderr)
            if missing_module:
                detail = self._format_missing_dependency_error(missing_module)
            raise ScriptSkillError(f"Script Skill 执行失败：{detail[:300]}")
        return stdout, stderr

    @staticmethod
    def _extract_missing_module(stderr: str) -> str | None:
        match = re.search(r"ModuleNotFoundError:\s+No module named ['\"]([^'\"]+)['\"]", stderr)
        return match.group(1) if match else None

    def _format_missing_dependency_error(self, module_name: str) -> str:
        dependencies = self.manifest.dependencies or {}
        requirements_file = dependencies.get("requirements_file") if isinstance(dependencies, dict) else None
        if requirements_file:
            requirements_path = (self.skill_path / str(requirements_file)).resolve()
            try:
                requirements_path.relative_to(self.skill_path)
                return (
                    f"缺少 Python 依赖模块 {module_name}。请在后端虚拟环境中执行："
                    f"python -m pip install -r {requirements_path}"
                )
            except ValueError:
                pass
        return f"缺少 Python 依赖模块 {module_name}。请在后端虚拟环境中安装该 skill 的 requirements.txt。"

    def _decorate_result(self, result: Any, tool: SkillTool) -> dict[str, Any]:
        if not isinstance(result, dict):
            result = {"result": result}
        result.setdefault("runtime", "script")
        result.setdefault("skill_name", self.manifest.name)
        result.setdefault("tool_name", tool.name)
        return result

    async def run(self, tool: SkillTool, arguments: dict[str, Any]) -> dict[str, Any]:
        async with self._semaphore:
            return await self._run_once(tool, arguments)

    def build_tools(self) -> dict[str, Callable[..., Awaitable[dict[str, Any]]]]:
        tools: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {}
        for tool in self.manifest.tools:
            def build_execute(tool_definition: SkillTool) -> Callable[..., Awaitable[dict[str, Any]]]:
                async def execute(**kwargs: Any) -> dict[str, Any]:
                    return await self.run(tool_definition, kwargs)

                execute.__name__ = tool_definition.name
                return execute

            tools[tool.name] = build_execute(tool)
        return tools


class PythonScriptAdapter(_ScriptAdapterBase):
    """Run a declared Python Script Skill through an isolated JSON protocol."""

    def __init__(self, skill_path: Path, manifest: SkillPackageManifest):
        super().__init__(skill_path, manifest)
        self.entrypoint = self._resolve_declared_entrypoint(manifest.entrypoint, ".py")

    async def _run_once(self, tool: SkillTool, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.config.adapter.lower() != "python":
            raise ScriptSkillError(f"不支持的 Script Skill adapter：{self.config.adapter}")
        self._validate_permissions()
        self._validate_input_size(tool, arguments)
        request_text = json.dumps(
            {"tool": tool.name, "arguments": arguments},
            ensure_ascii=False,
            separators=(",", ":"),
        )

        bootstrap = Path(__file__).resolve().with_name("script_bootstrap.py")
        bootstrap_config = json.dumps(
            {
                "skill_root": str(self.skill_path),
                "permissions": sorted(self.permissions),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-X",
            "utf8",
            str(bootstrap),
            str(self.entrypoint),
            bootstrap_config,
            cwd=str(self.skill_path),
            env=self._build_environment(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stdin is not None
        process.stdin.write(request_text.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()
        stdout, _ = await self._collect_process_output(process)

        try:
            result = json.loads(stdout.strip())
        except json.JSONDecodeError as exc:
            raise ScriptSkillError("Script Skill stdout 必须只返回一个 JSON 结果。") from exc
        return self._decorate_result(result, tool)


class PythonCliScriptAdapter(_ScriptAdapterBase):
    """Run a SkillHub-style Python CLI script with positional arguments."""

    def __init__(self, skill_path: Path, manifest: SkillPackageManifest):
        super().__init__(skill_path, manifest)
        self.entrypoint = self._resolve_declared_entrypoint(manifest.entrypoint, ".py")

    def _build_positional_arguments(self, tool: SkillTool, arguments: dict[str, Any]) -> list[str]:
        order = list(self.config.argument_order) or list(tool.input_schema.properties)
        values: list[str] = []
        for name in order:
            if name not in arguments:
                continue
            value = arguments[name]
            if isinstance(value, (dict, list)):
                values.append(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
            elif isinstance(value, bool):
                values.append("true" if value else "false")
            else:
                values.append(str(value))
        return values

    async def _run_once(self, tool: SkillTool, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.config.adapter.lower() != "python_cli":
            raise ScriptSkillError(f"不支持的 Script Skill adapter：{self.config.adapter}")
        self._validate_permissions()
        self._validate_input_size(tool, arguments)
        positional_arguments = self._build_positional_arguments(tool, arguments)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-X",
            "utf8",
            str(self.entrypoint),
            *positional_arguments,
            cwd=str(self.skill_path),
            env=self._build_environment(),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await self._collect_process_output(process)
        text = stdout.strip()
        if not text:
            raise ScriptSkillError("Python CLI Script 没有返回可展示内容。")
        if self.config.output_format == "json":
            try:
                return self._decorate_result(json.loads(text), tool)
            except json.JSONDecodeError as exc:
                raise ScriptSkillError("Python CLI Script stdout 必须返回 JSON。") from exc
        return self._decorate_result({"summary": text, "content": text}, tool)


class ShellScriptAdapter(_ScriptAdapterBase):
    """Run a SkillHub-provided shell Skill through a discovered Bash runtime."""

    def __init__(self, skill_path: Path, manifest: SkillPackageManifest):
        super().__init__(skill_path, manifest)
        self.entrypoint = self._resolve_declared_entrypoint(manifest.entrypoint, ".sh")
        source = self.entrypoint.read_text(encoding="utf-8")
        if re.search(r"\b(?:curl|wget)\b", source) and "network" not in self.permissions:
            raise ScriptSkillError("Shell Script 使用网络，但没有声明 network 权限。")
        if re.search(r"\b(?:mktemp|touch|mkdir)\b|(?:>|>>)", source) and "filesystem_write" not in self.permissions:
            raise ScriptSkillError("Shell Script 会写入文件，但没有声明 filesystem_write 权限。")
        self.bash_path = self.find_bash()
        if self.bash_path is None:
            raise ScriptSkillError(
                "当前后端没有可用的 Bash。请安装 Git Bash，或通过 SERANA_BASH_PATH 指定 bash.exe。"
            )

    @classmethod
    def find_bash(cls) -> Path | None:
        configured = str(os.environ.get("SERANA_BASH_PATH") or "").strip()
        candidates = [
            configured,
            shutil.which("bash") or "",
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
            "/bin/bash",
            "/usr/bin/bash",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return Path(candidate).resolve()
        return None

    @classmethod
    def inspect_script(cls, entrypoint: Path) -> list[str]:
        try:
            entrypoint.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ["入口脚本不是 UTF-8 编码"]
        return []

    def _build_positional_arguments(self, tool: SkillTool, arguments: dict[str, Any]) -> list[str]:
        order = list(self.config.argument_order) or list(tool.input_schema.properties)
        values = []
        for name in order:
            if name not in arguments:
                continue
            value = arguments[name]
            if isinstance(value, (dict, list)):
                values.append(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
            elif isinstance(value, bool):
                values.append("true" if value else "false")
            else:
                values.append(str(value))
        return values

    async def _run_once(self, tool: SkillTool, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.config.adapter.lower() != "shell":
            raise ScriptSkillError(f"不支持的 Script Skill adapter：{self.config.adapter}")
        self._validate_permissions()
        self._validate_input_size(tool, arguments)
        positional_arguments = self._build_positional_arguments(tool, arguments)
        environment = self._build_environment()
        environment["SERANA_SKILL_ROOT"] = str(self.skill_path)
        process = await asyncio.create_subprocess_exec(
            str(self.bash_path),
            "--noprofile",
            "--norc",
            str(self.entrypoint),
            *positional_arguments,
            cwd=str(self.skill_path),
            env=environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await self._collect_process_output(process)
        text = stdout.strip()
        if not text:
            raise ScriptSkillError("Shell Script 没有返回可展示内容。")
        if self.config.output_format == "json":
            try:
                return self._decorate_result(json.loads(text), tool)
            except json.JSONDecodeError as exc:
                raise ScriptSkillError("Shell Script stdout 必须返回 JSON。") from exc
        return self._decorate_result({"summary": text, "content": text}, tool)


class ScriptSkillRunner:
    """Select and initialize the adapter declared by a Script Skill."""

    @staticmethod
    def build_tools(skill_path: Path, manifest: SkillPackageManifest) -> dict[str, Callable[..., Awaitable[dict[str, Any]]]]:
        config = manifest.script or ScriptRuntimeConfig()
        adapter = config.adapter.lower()
        if adapter == "python":
            return PythonScriptAdapter(skill_path, manifest).build_tools()
        if adapter == "python_cli":
            return PythonCliScriptAdapter(skill_path, manifest).build_tools()
        if adapter == "shell":
            return ShellScriptAdapter(skill_path, manifest).build_tools()
        raise ScriptSkillError(f"不支持的 Script Skill adapter：{config.adapter}")
