import io
import json
import os
from pathlib import Path
import runpy
import sys
from typing import Any


_BLOCKED_IMPORTS = {"ctypes", "multiprocessing", "subprocess"}
_WRITE_OPEN_FLAGS = os.O_APPEND | os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_RDWR


def _is_within(path: Any, roots: tuple[Path, ...]) -> bool:
    try:
        resolved = Path(path).resolve()
    except (OSError, TypeError, ValueError):
        return False
    return any(resolved == root or root in resolved.parents for root in roots)


def _install_audit_hook(skill_root: Path, permissions: set[str]) -> None:
    readable_roots = tuple(
        {
            skill_root.resolve(),
            Path(sys.base_prefix).resolve(),
            Path(sys.prefix).resolve(),
        }
    )
    allow_network = "network" in permissions
    allow_write = "filesystem_write" in permissions

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "import":
            module_name = str(args[0] or "").split(".", 1)[0]
            if module_name in _BLOCKED_IMPORTS:
                raise PermissionError(f"Script Skill 禁止导入模块：{module_name}")
            return

        if event == "open":
            path = args[0] if args else None
            mode = str(args[1] or "") if len(args) > 1 else ""
            flags = int(args[2] or 0) if len(args) > 2 and isinstance(args[2], int) else 0
            is_write = any(token in mode for token in ("w", "a", "x", "+")) or bool(flags & _WRITE_OPEN_FLAGS)
            if is_write:
                if not allow_write or not _is_within(path, (skill_root.resolve(),)):
                    raise PermissionError("Script Skill 没有该文件写入权限。")
            elif path is not None and not isinstance(path, int) and not _is_within(path, readable_roots):
                raise PermissionError("Script Skill 只能读取自身目录和 Python 标准库。")
            return

        if event.startswith("socket.") and not allow_network:
            raise PermissionError("Script Skill 未声明 network 权限。")

        if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn"}:
            raise PermissionError("Script Skill 禁止启动子进程。")

        if event in {"os.listdir", "os.scandir", "os.chdir"}:
            path = args[0] if args else skill_root
            if not _is_within(path, readable_roots):
                raise PermissionError("Script Skill 只能浏览自身目录和 Python 标准库。")

        if event in {
            "os.chmod",
            "os.chown",
            "os.link",
            "os.mkdir",
            "os.remove",
            "os.rename",
            "os.rmdir",
            "os.symlink",
            "os.truncate",
            "os.utime",
        }:
            paths = [value for value in args[:2] if isinstance(value, (str, bytes, os.PathLike))]
            if not allow_write or not paths or any(not _is_within(path, (skill_root.resolve(),)) for path in paths):
                raise PermissionError("Script Skill 没有该文件系统修改权限。")

    sys.addaudithook(audit)


def main() -> None:
    if len(sys.argv) != 3:
        raise RuntimeError("Script Skill bootstrap 参数无效。")

    entrypoint = Path(sys.argv[1]).resolve()
    config = json.loads(sys.argv[2])
    skill_root = Path(config["skill_root"]).resolve()
    permissions = {str(item).strip().lower() for item in config.get("permissions", [])}

    if entrypoint.suffix.lower() != ".py" or not _is_within(entrypoint, (skill_root,)):
        raise PermissionError("Script Skill 入口必须是技能目录内的 Python 文件。")

    request_text = sys.stdin.read()
    _install_audit_hook(skill_root, permissions)
    sys.stdin = io.StringIO(request_text)
    sys.argv = [str(entrypoint)]
    os.chdir(skill_root)
    runpy.run_path(str(entrypoint), run_name="__main__")


if __name__ == "__main__":
    main()
