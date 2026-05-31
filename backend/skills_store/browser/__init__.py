from __future__ import annotations

import asyncio
import ipaddress
import json
import mimetypes
import re
import socket
import struct
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote, quote_plus, urlparse

from app.core.artifacts import (
    make_download_artifact,
    make_html_preview_artifact,
    make_image_artifact,
    path_size_bytes,
)

_playwright: Any | None = None
_browser: Any | None = None
_context: Any | None = None
_page: Any | None = None
_page_owned_by_browser_tool = False
_download_tasks: set[asyncio.Task[Any]] = set()
_operation_lock = asyncio.Lock()

_ROOT_DIR = Path(__file__).resolve().parent
_PROFILE_DIR = _ROOT_DIR / "profile"
_SCREENSHOTS_DIR = _ROOT_DIR / "screenshots"
_PREVIEWS_DIR = _ROOT_DIR / "previews"
_DOWNLOADS_DIR = _ROOT_DIR / "downloads"
_DOWNLOADS_MANIFEST = _DOWNLOADS_DIR / "downloads.jsonl"

_ALLOWED_ACTIONS = {
    "click",
    "type",
    "press",
    "select",
    "wait_for_text",
    "wait_for_selector",
    "back",
    "forward",
    "reload",
}
_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}
_SENSITIVE_PATTERN = re.compile(
    r"(password|passwd|passcode|secret|token|api[_-]?key|credential|auth|login|signin|sign in|"
    r"pay|payment|purchase|buy|checkout|card|credit|cc-number|cvv|billing|iban|delete|remove|"
    r"destroy|transfer|submit|confirm|account|settings|profile|email|phone|address)",
    re.IGNORECASE,
)
_HTML_BLOCKED_PATTERN = re.compile(
    r"(<\s*(iframe|object|embed|form|base)\b|"
    r"<\s*meta\b[^>]*http-equiv\s*=|"
    r"<\s*script\b[^>]*\bsrc\s*=|"
    r"\b(fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(|"
    r"\bhttps?://)",
    re.IGNORECASE,
)
_HTML_PLACEHOLDER_PATTERN = re.compile(
    r"offline demo script here|"
    r"javascript code for [^<\n\r]+|"
    r"css styles for visualization|"
    r"\bplaceholder\b|"
    r"\btodo\b",
    re.IGNORECASE,
)
_HTML_CONTROL_PATTERN = re.compile(
    r"<\s*(button|input|select|textarea)\b|"
    r"\brole\s*=\s*['\"]button['\"]",
    re.IGNORECASE,
)
_HTML_EVENT_BINDING_PATTERN = re.compile(
    r"\baddEventListener\s*\(|"
    r"\bon(click|change|input|submit|keydown|keyup)\s*=|"
    r"\.on(click|change|input|submit|keydown|keyup)\s*=",
    re.IGNORECASE,
)


def _host_is_private_or_local(hostname: str) -> bool:
    host = (hostname or "").strip().strip("[]").rstrip(".").lower()
    if not host or host in _BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def _validate_resolved_public_host(hostname: str) -> None:
    if _host_is_private_or_local(hostname):
        raise ValueError("浏览器只能打开公开 http(s) 网页，不能访问本机或内网地址。")

    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError:
        return

    for info in infos:
        ip = str(info[4][0])
        if _host_is_private_or_local(ip):
            raise ValueError("浏览器目标解析到了本机或内网地址，已拦截。")


def _normalize_public_url(url: str) -> str:
    cleaned = str(url or "").strip()
    if not cleaned:
        raise ValueError("缺少要打开的网址。")
    if not re.match(r"^https?://", cleaned, flags=re.IGNORECASE):
        cleaned = f"https://{cleaned}"
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise ValueError("浏览器只支持公开 http(s) 网页。")
    if parsed.username or parsed.password:
        raise ValueError("浏览器不会打开包含账号或密码的 URL。")
    _validate_resolved_public_host(parsed.hostname)
    return cleaned


def _truncate(text: str, max_chars: int) -> str:
    limit = max(500, min(int(max_chars or 4000), 12000))
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    return cleaned[:limit]


def _current_page_missing() -> Dict[str, Any]:
    return {
        "error": "No browser page is open. Open a public page first.",
        "summary": "当前没有已打开的浏览器页面，请先打开网页。",
        "recoverable": True,
        "browser_state": {
            "status": "missing_page",
            "page_open": False,
            "next_actions": ["open_page", "search_web"],
        },
    }


async def browser_open(url: str, max_chars: int = 4000) -> Dict[str, Any]:
    return await open_page(url=url, max_chars=max_chars)


async def browser_observe(max_chars: int = 4000) -> Dict[str, Any]:
    return await observe_page(max_chars=max_chars)


async def browser_act(action: str, target: str | None = None, value: str | None = None) -> Dict[str, Any]:
    return await act_page(action=action, target=target, value=value)


async def browser_capture(full_page: bool = False) -> Dict[str, Any]:
    return await capture_page(full_page=full_page)


async def browser_look(full_page: bool = False) -> Dict[str, Any]:
    return await look_page(full_page=full_page)


def _looks_sensitive(*parts: str | None) -> bool:
    haystack = " ".join(str(part or "") for part in parts)
    return bool(_SENSITIVE_PATTERN.search(haystack))


def _safe_filename(name: str, fallback: str = "download") -> str:
    raw_name = Path(str(name or "")).name.strip()
    if not raw_name:
        raw_name = fallback
    raw_name = re.sub(r"[^\w.\-()\[\] \u4e00-\u9fff]+", "_", raw_name, flags=re.UNICODE)
    raw_name = raw_name.strip(" ._") or fallback
    return raw_name[:120]


def _unique_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(filename)
    candidate = directory / safe_name
    if not candidate.exists():
        return candidate
    stem = candidate.stem or "download"
    suffix = candidate.suffix
    for index in range(2, 1000):
        candidate = directory / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    return directory / f"{stem}-{stamp}{suffix}"


def _append_download_record(record: dict[str, Any]) -> None:
    _DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    with _DOWNLOADS_MANIFEST.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _load_download_records() -> list[dict[str, Any]]:
    if not _DOWNLOADS_MANIFEST.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in _DOWNLOADS_MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        filename = str(record.get("filename") or "")
        path = (_DOWNLOADS_DIR / filename).resolve()
        if filename and path.exists() and _DOWNLOADS_DIR.resolve() in path.parents:
            record["size"] = path.stat().st_size
            record["mtime"] = path.stat().st_mtime
            records.append(record)
    return records


def _download_artifact(path: Path) -> dict[str, Any]:
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return make_download_artifact(
        filename=path.name,
        mime_type=mime_type,
        download_url=f"/api/v1/browser/downloads/{quote(path.name)}",
        size_bytes=path_size_bytes(path),
    )


async def _save_download(download: Any) -> dict[str, Any] | None:
    try:
        suggested = _safe_filename(getattr(download, "suggested_filename", "download"))
    except Exception:
        suggested = "download"

    path = _unique_path(_DOWNLOADS_DIR, suggested)
    try:
        await download.save_as(str(path))
    except Exception:
        return None

    record = {
        "filename": path.name,
        "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "size": path.stat().st_size,
        "mtime": path.stat().st_mtime,
        "original": suggested,
        "source_url": getattr(_page, "url", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _append_download_record(record)
    return record


def _attach_download_listener(page: Any) -> None:
    def _on_download(download: Any) -> None:
        task = asyncio.create_task(_save_download(download))
        _download_tasks.add(task)
        task.add_done_callback(_download_tasks.discard)

    try:
        page.on("download", _on_download)
    except Exception:
        pass


async def _collect_interactive_summary(page: Any, limit: int = 30) -> list[dict[str, Any]]:
    try:
        return await page.evaluate(
            """(limit) => Array.from(document.querySelectorAll(
                'a,button,input,textarea,select,[role="button"],[contenteditable="true"]'
            )).slice(0, limit).map((el, index) => ({
                index,
                tag: el.tagName.toLowerCase(),
                type: el.getAttribute('type') || '',
                text: (el.innerText || el.value || '').trim().slice(0, 120),
                label: (
                    el.getAttribute('aria-label') ||
                    el.getAttribute('placeholder') ||
                    el.getAttribute('name') ||
                    el.getAttribute('id') ||
                    ''
                ).slice(0, 120),
                href: el.href ? new URL(el.href, location.href).href.split('#')[0].split('?')[0] : ''
            }))""",
            max(1, min(int(limit or 30), 60)),
        )
    except Exception:
        return []


async def _target_metadata(page: Any, target: str) -> dict[str, Any]:
    try:
        return await page.locator(target).first.evaluate(
            """(el) => ({
                tag: el.tagName.toLowerCase(),
                type: el.getAttribute('type') || '',
                role: el.getAttribute('role') || '',
                text: (el.innerText || '').trim().slice(0, 200),
                label: (
                    el.getAttribute('aria-label') ||
                    el.getAttribute('placeholder') ||
                    el.getAttribute('name') ||
                    el.getAttribute('id') ||
                    el.getAttribute('title') ||
                    ''
                ).slice(0, 200),
                href: el.href || '',
                formText: el.form ? (el.form.innerText || '').slice(0, 300) : ''
            })"""
        )
    except Exception:
        return {"target": target}


def _target_metadata_sensitive(action: str, metadata: dict[str, Any]) -> bool:
    combined = " ".join(str(value or "") for value in metadata.values())
    if _looks_sensitive(combined):
        return True
    if action == "click" and str(metadata.get("type") or "").lower() in {"submit", "button"}:
        return _looks_sensitive(str(metadata.get("formText") or ""), str(metadata.get("text") or ""))
    return False


def _cleanup_old_files(directory: Path, pattern: str, *, max_files: int = 80) -> None:
    try:
        files = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old_file in files[max_files:]:
        try:
            old_file.unlink()
        except OSError:
            pass


async def _current_page_metadata() -> Dict[str, Any]:
    if _page is None:
        return {}
    return {
        "url": _page.url,
        "title": await _page.title(),
        "opened_by_browser_tool": _page_owned_by_browser_tool,
    }


def _browser_state_from_metadata(
    metadata: dict[str, Any] | None = None,
    *,
    status: str = "ready",
    next_actions: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    metadata = dict(metadata or {})
    page_open = bool(metadata.get("url"))
    state: dict[str, Any] = {
        "status": status,
        "page_open": page_open,
        "url": metadata.get("url"),
        "title": metadata.get("title"),
        "opened_by_browser_tool": bool(metadata.get("opened_by_browser_tool", False)),
        "next_actions": next_actions
        or (["observe_page", "act_page", "capture_page", "look_page"] if page_open else ["open_page", "search_web"]),
    }
    if error:
        state["error"] = error
        state["recoverable"] = status in {"missing_page", "failed", "blocked"}
    return state


async def _current_browser_state(
    *,
    status: str = "ready",
    next_actions: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    metadata = await _current_page_metadata()
    if not metadata:
        return _browser_state_from_metadata(
            {},
            status="missing_page" if status == "ready" else status,
            next_actions=next_actions,
            error=error,
        )
    return _browser_state_from_metadata(
        metadata,
        status=status,
        next_actions=next_actions,
        error=error,
    )


async def _ensure_page() -> Any:
    global _browser, _context, _page, _playwright
    if _page is not None:
        return _page
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("当前环境未安装 Playwright，浏览器技能不可用。") from exc

    try:
        _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        _DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        _playwright = await async_playwright().start()
        _browser = None
        _context = await _playwright.chromium.launch_persistent_context(
            user_data_dir=str(_PROFILE_DIR),
            headless=True,
            accept_downloads=True,
            downloads_path=str(_DOWNLOADS_DIR),
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        _page = await _context.new_page()
        _attach_download_listener(_page)
        return _page
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "浏览器运行时启动失败。请确认已执行 playwright install chromium。"
        ) from exc


async def _observe_current_page(max_chars: int = 4000) -> Dict[str, Any]:
    if _page is None:
        raise RuntimeError("当前没有由浏览器技能打开的页面。")
    page = _page
    try:
        title = await page.title()
        url = page.url
        text = await page.locator("body").inner_text(timeout=5000)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("当前网页无法读取。") from exc
    content = _truncate(text, max_chars)
    return {
        "url": url,
        "title": title,
        "content": content,
        "interactive_summary": await _collect_interactive_summary(page),
        "browser_state": _browser_state_from_metadata(
            {
                "url": url,
                "title": title,
                "opened_by_browser_tool": _page_owned_by_browser_tool,
            },
            status="ready",
        ),
        "summary": f"已读取网页：{title or url}",
    }


async def open_page(url: str, max_chars: int = 4000) -> Dict[str, Any]:
    global _page_owned_by_browser_tool
    try:
        normalized_url = _normalize_public_url(url)
        async with _operation_lock:
            page = await _ensure_page()
            response = await page.goto(normalized_url, wait_until="domcontentloaded", timeout=30000)
            _normalize_public_url(str(page.url))
            _page_owned_by_browser_tool = True
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            observed = await _observe_current_page(max_chars=max_chars)
        observed["status_code"] = response.status if response else None
        observed["summary"] = f"已打开并读取网页：{observed.get('title') or observed.get('url')}"
        return observed
    except Exception as exc:  # noqa: BLE001
        return {
            "error": str(exc),
            "summary": f"浏览器打开网页失败：{exc}",
            "recoverable": True,
            "browser_state": await _current_browser_state(status="failed", error=str(exc)),
        }


async def observe_page(max_chars: int = 4000) -> Dict[str, Any]:
    try:
        return await _observe_current_page(max_chars=max_chars)
    except Exception as exc:  # noqa: BLE001
        return {
            "error": str(exc),
            "summary": f"浏览器观察网页失败：{exc}",
            "recoverable": True,
            "browser_state": await _current_browser_state(status="failed", error=str(exc)),
        }


def _extract_search_results(page_text: str, max_results: int) -> List[Dict[str, str]]:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    results: List[Dict[str, str]] = []
    seen: set[str] = set()
    for line in lines:
        if len(line) < 8 or line in seen:
            continue
        if line.lower() in {"images", "videos", "maps", "news", "shopping"}:
            continue
        seen.add(line)
        results.append({"title": line})
        if len(results) >= max_results:
            break
    return results


async def search_web(query: str, max_results: int = 5) -> Dict[str, Any]:
    cleaned_query = str(query or "").strip()
    if not cleaned_query:
        return {
            "error": "缺少搜索关键词。",
            "summary": "缺少搜索关键词。",
            "recoverable": True,
            "browser_state": await _current_browser_state(status="failed", error="Missing search query."),
        }

    max_results = max(1, min(int(max_results or 5), 8))
    search_url = f"https://www.bing.com/search?q={quote_plus(cleaned_query)}"
    opened = await open_page(search_url, max_chars=6000)
    if "error" in opened:
        return opened

    results = _extract_search_results(str(opened.get("content") or ""), max_results=max_results)
    opened["query"] = cleaned_query
    opened["results"] = results
    opened["summary"] = f"已搜索：{cleaned_query}，找到 {len(results)} 条可见结果。"
    return opened


async def act_page(action: str, target: str | None = None, value: str | None = None) -> Dict[str, Any]:
    if _page is None:
        return _current_page_missing()

    normalized = str(action or "").strip().lower()
    if normalized not in _ALLOWED_ACTIONS:
        return {
            "error": f"Unsupported browser action: {action}",
            "summary": "不支持这个浏览器动作。",
            "recoverable": True,
            "browser_state": await _current_browser_state(status="blocked", error=f"Unsupported browser action: {action}"),
        }
    if _looks_sensitive(target, value):
        return {
            "error": "Browser action blocked because the target or value looks sensitive.",
            "summary": "这个浏览器动作看起来涉及敏感信息或高影响操作，已拦截。请你在页面里手动处理。",
            "recoverable": True,
            "browser_state": await _current_browser_state(status="blocked", error="Sensitive browser action blocked."),
        }

    try:
        if target and normalized in {"click", "type", "select", "wait_for_selector"}:
            metadata = await _target_metadata(_page, target)
            if _target_metadata_sensitive(normalized, metadata):
                return {
                    "error": "Browser action blocked because the target looks sensitive or high-impact.",
                    "summary": "这个页面动作看起来会触碰账号、凭证、付款、提交或高影响区域，已拦截。请你在页面里手动处理。",
                    "target_metadata": metadata,
                    "recoverable": True,
                    "browser_state": await _current_browser_state(status="blocked", error="Sensitive browser target blocked."),
                }

        if normalized == "click":
            if not target:
                return {
                    "error": "click requires target",
                    "summary": "点击动作需要目标。",
                    "recoverable": True,
                    "browser_state": await _current_browser_state(status="failed", error="Missing click target."),
                }
            await _page.locator(target).first.click(timeout=8000)
        elif normalized == "type":
            if not target:
                return {
                    "error": "type requires target",
                    "summary": "输入动作需要目标。",
                    "recoverable": True,
                    "browser_state": await _current_browser_state(status="failed", error="Missing type target."),
                }
            await _page.locator(target).first.fill(str(value or ""), timeout=8000)
        elif normalized == "select":
            if not target:
                return {
                    "error": "select requires target",
                    "summary": "选择动作需要目标。",
                    "recoverable": True,
                    "browser_state": await _current_browser_state(status="failed", error="Missing select target."),
                }
            await _page.locator(target).first.select_option(str(value or ""), timeout=8000)
        elif normalized == "press":
            await _page.keyboard.press(str(value or target or "Enter"))
        elif normalized == "wait_for_text":
            if not target:
                return {
                    "error": "wait_for_text requires target",
                    "summary": "等待文本需要目标文本。",
                    "recoverable": True,
                    "browser_state": await _current_browser_state(status="failed", error="Missing text target."),
                }
            await _page.get_by_text(target).first.wait_for(timeout=10000)
        elif normalized == "wait_for_selector":
            if not target:
                return {
                    "error": "wait_for_selector requires target",
                    "summary": "等待选择器需要目标。",
                    "recoverable": True,
                    "browser_state": await _current_browser_state(status="failed", error="Missing selector target."),
                }
            await _page.locator(target).first.wait_for(timeout=10000)
        elif normalized == "back":
            await _page.go_back(wait_until="domcontentloaded", timeout=10000)
        elif normalized == "forward":
            await _page.go_forward(wait_until="domcontentloaded", timeout=10000)
        elif normalized == "reload":
            await _page.reload(wait_until="domcontentloaded", timeout=10000)

        _normalize_public_url(str(_page.url))
        try:
            await _page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass
        metadata = await _current_page_metadata()
        return {
            "action": normalized,
            "target": target,
            **metadata,
            "browser_state": _browser_state_from_metadata(metadata, status="ready"),
            "summary": f"浏览器动作已完成：{normalized}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "error": str(exc),
            "summary": f"浏览器动作失败：{exc}",
            "recoverable": True,
            "browser_state": await _current_browser_state(status="failed", error=str(exc)),
        }


async def capture_page(full_page: bool = False) -> Dict[str, Any]:
    if _page is None:
        return _current_page_missing()
    try:
        _SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        _cleanup_old_files(_SCREENSHOTS_DIR, "browser-*.png", max_files=80)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        path = _SCREENSHOTS_DIR / f"browser-{stamp}.png"
        await _page.screenshot(path=str(path), full_page=bool(full_page))
        metadata = await _current_page_metadata()
        artifact = _image_artifact(path)
        return {
            **metadata,
            "path": str(path),
            "artifact": artifact,
            "artifact_url": artifact["download_url"],
            "mime_type": artifact["mime_type"],
            "full_page": bool(full_page),
            "browser_state": _browser_state_from_metadata(metadata, status="ready"),
            "summary": f"已截取当前浏览器页面：{path.name}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "error": str(exc),
            "summary": f"浏览器截图失败：{exc}",
            "recoverable": True,
            "browser_state": await _current_browser_state(status="failed", error=str(exc)),
        }


def _png_dimensions(path: Path) -> Dict[str, int] | None:
    try:
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError:
        return None
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width, height = struct.unpack(">II", header[16:24])
    return {"width": int(width), "height": int(height)}


def _image_artifact(path: Path) -> Dict[str, Any]:
    download_url = f"/api/v1/browser/screenshots/{path.name}"
    return make_image_artifact(
        filename=path.name,
        download_url=download_url,
        size_bytes=path_size_bytes(path),
        thumbnail_url=download_url,
    )


def _preview_artifact(path: Path, title: str) -> Dict[str, Any]:
    download_url = f"/api/v1/browser/previews/{path.name}"
    return make_html_preview_artifact(
        filename=path.name,
        title=title,
        download_url=download_url,
        size_bytes=path_size_bytes(path),
    )


def _safe_preview_filename(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", title).strip("-").lower()
    if not slug:
        slug = "preview"
    return slug[:40]


def _select_preview_html(title: str, html: str) -> str:
    body = str(html or "").strip()
    if _HTML_PLACEHOLDER_PATTERN.search(body):
        raise ValueError("HTML 仍包含占位代码或注释，请先生成完整可运行页面。")
    if _HTML_CONTROL_PATTERN.search(body) and not _HTML_EVENT_BINDING_PATTERN.search(body):
        raise ValueError("HTML 包含可操作控件，但没有检测到真实的事件绑定。")
    return body


def _wrap_html_preview(title: str, html: str) -> str:
    body = _select_preview_html(title, html)
    if not body:
        raise ValueError("缺少要生成的 HTML 内容。")
    if _HTML_BLOCKED_PATTERN.search(body):
        raise ValueError("HTML 预览包含外链、表单或网络访问代码，已拦截。")
    if "<html" in body.lower():
        return body
    safe_title = escape(title or "Serana Preview")
    return (
        "<!doctype html>\n"
        "<html lang=\"zh-CN\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"  <title>{safe_title}</title>\n"
        "</head>\n"
        "<body>\n"
        f"{body}\n"
        "</body>\n"
        "</html>\n"
    )


async def create_html_preview(title: str, html: str) -> Dict[str, Any]:
    cleaned_title = str(title or "Serana Preview").strip()[:80] or "Serana Preview"
    try:
        document = _wrap_html_preview(cleaned_title, html)
        _PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
        _cleanup_old_files(_PREVIEWS_DIR, "*.html", max_files=80)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        filename = f"{_safe_preview_filename(cleaned_title)}-{stamp}.html"
        path = _PREVIEWS_DIR / filename
        path.write_text(document, encoding="utf-8")
        artifact = _preview_artifact(path, cleaned_title)
        return {
            "title": cleaned_title,
            "path": str(path),
            "artifact": artifact,
            "artifact_url": artifact["download_url"],
            "mime_type": artifact["mime_type"],
            "browser_state": await _current_browser_state(status="preview_ready", next_actions=["open_preview"]),
            "summary": f"已生成可打开的演示页面：{artifact['filename']}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "error": str(exc),
            "summary": f"生成演示页面失败：{exc}",
            "recoverable": True,
            "browser_state": await _current_browser_state(status="failed", error=str(exc)),
        }


async def look_page(full_page: bool = False) -> Dict[str, Any]:
    if _page is None:
        return _current_page_missing()
    try:
        _SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        _cleanup_old_files(_SCREENSHOTS_DIR, "browser-look-*.png", max_files=20)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        path = _SCREENSHOTS_DIR / f"browser-look-{stamp}.png"
        await _page.screenshot(path=str(path), full_page=bool(full_page))
        metadata = await _current_page_metadata()
        dimensions = _png_dimensions(path) or {}
        return {
            **metadata,
            "path": str(path),
            "mime_type": "image/png",
            "full_page": bool(full_page),
            "dimensions": dimensions,
            "browser_state": _browser_state_from_metadata(metadata, status="ready"),
            "model_observation": {
                "kind": "browser_visual_snapshot",
                "image_path": str(path),
                "mime_type": "image/png",
                "dimensions": dimensions,
                "runtime_only": True,
            },
            "summary": f"已观察当前浏览器页面的视觉快照：{path.name}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "error": str(exc),
            "summary": f"浏览器视觉观察失败：{exc}",
            "recoverable": True,
            "browser_state": await _current_browser_state(status="failed", error=str(exc)),
        }


async def browser_downloads(action: str = "list", filename: str | None = None) -> Dict[str, Any]:
    normalized = str(action or "list").strip().lower()
    if normalized not in {"list", "send"}:
        return {
            "error": f"Unsupported browser downloads action: {action}",
            "summary": "下载管理只支持 list 或 send。",
        }

    if _download_tasks:
        await asyncio.gather(*list(_download_tasks), return_exceptions=True)

    records = _load_download_records()
    if normalized == "list":
        return {
            "downloads": records[-20:][::-1],
            "count": len(records),
            "browser_state": await _current_browser_state(status="downloads"),
            "summary": f"已找到 {len(records)} 个浏览器下载文件。",
        }

    raw_filename = str(filename or "").strip()
    if not raw_filename:
        return {
            "error": "browser_downloads send requires filename",
            "summary": "发送下载文件前，请先列出下载并选择文件名。",
            "recoverable": True,
            "browser_state": await _current_browser_state(status="failed", error="Missing download filename."),
        }
    safe_name = _safe_filename(raw_filename)
    path = (_DOWNLOADS_DIR / safe_name).resolve()
    downloads_root = _DOWNLOADS_DIR.resolve()
    if downloads_root not in path.parents or not path.exists():
        return {
            "error": "Download is not available in the browser downloads directory.",
            "summary": "没有找到这个浏览器下载文件。",
            "recoverable": True,
            "browser_state": await _current_browser_state(status="failed", error="Download file is unavailable."),
        }
    artifact = _download_artifact(path)
    return {
        "filename": path.name,
        "artifact": artifact,
        "artifact_url": artifact["download_url"],
        "mime_type": artifact["mime_type"],
        "browser_state": await _current_browser_state(status="download_ready", next_actions=["send_download"]),
        "summary": f"已准备好浏览器下载文件：{path.name}",
    }


async def close_browser() -> Dict[str, Any]:
    global _browser, _context, _page, _playwright, _page_owned_by_browser_tool
    closed = False
    if _download_tasks:
        await asyncio.gather(*list(_download_tasks), return_exceptions=True)
        _download_tasks.clear()
    if _context is not None:
        try:
            await _context.close()
            closed = True
        except Exception:
            pass
    if _browser is not None:
        try:
            await _browser.close()
            closed = True
        except Exception:
            pass
    if _playwright is not None:
        try:
            await _playwright.stop()
            closed = True
        except Exception:
            pass
    _page = None
    _context = None
    _browser = None
    _playwright = None
    _page_owned_by_browser_tool = False
    return {
        "closed": closed,
        "browser_state": _browser_state_from_metadata(
            {},
            status="closed",
            next_actions=["open_page", "search_web"],
        ),
        "summary": "浏览器会话已关闭。" if closed else "没有正在运行的浏览器会话。",
    }

