import asyncio
import hashlib
import html
import ipaddress
import json
import mimetypes
import re
import socket
import urllib.error
import urllib.request
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse

from app.core.config import get_settings
from app.core.artifacts import make_download_artifact, make_html_preview_artifact, path_size_bytes


_CURRENT_PAGE: dict[str, Any] = {}
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_BUNDLED_BROWSER_DIR = Path(__file__).resolve().parent
_CONFIGURED_BROWSER_DATA_DIR = str(get_settings().SERANA_BROWSER_DATA_DIR or "").strip()
_BROWSER_DATA_DIR = (
    Path(_CONFIGURED_BROWSER_DATA_DIR).expanduser()
    if _CONFIGURED_BROWSER_DATA_DIR
    else _BUNDLED_BROWSER_DIR
)
_SCREENSHOTS_DIR = _BROWSER_DATA_DIR / "screenshots"
_PREVIEWS_DIR = _BROWSER_DATA_DIR / "previews"
_PREVIEW_CACHE_PATH = _PREVIEWS_DIR / "preview-cache.json"
_DOWNLOADS_DIR = _BROWSER_DATA_DIR / "downloads"
_DOWNLOADS_MANIFEST_PATH = _DOWNLOADS_DIR / "downloads.jsonl"
_HTML_PLACEHOLDER_PATTERN = re.compile(
    r"offline demo script here|"
    r"javascript code for [^<\n\r]+|"
    r"css styles for visualization|"
    r"\bplaceholder\b|"
    r"\btodo\b",
    re.IGNORECASE,
)
_HTML_NETWORK_PATTERN = re.compile(
    r"\b(fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(|"
    r"<\s*iframe\b|"
    r"\b(src|href)\s*=\s*['\"]https?://",
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


class _ReadableTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "section", "article", "header", "footer", "li", "tr", "br", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = html.unescape(data).strip()
        if not text:
            return
        if self._in_title:
            self.title = " ".join((self.title, text)).strip()
        self._parts.append(text)
        self._parts.append(" ")

    def text(self) -> str:
        return _normalize_text("".join(self._parts))


def _normalize_text(value: str) -> str:
    text = _ANSI_PATTERN.sub("", value)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _browser_state(
    *,
    status: str,
    page_open: bool,
    next_actions: list[str] | None = None,
    url: str = "",
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "status": status,
        "page_open": page_open,
        "next_actions": list(next_actions or []),
    }
    if url:
        state["url"] = url
    return state


def _public_url_error(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "仅支持公开的 http/https 网页。"
    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname:
        return "网页地址缺少有效域名。"
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        return "出于安全限制，浏览器不能访问本机或局域网地址。"

    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        }
    except OSError:
        return "暂时无法解析这个网页地址。"

    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError:
            continue
        if not parsed_address.is_global:
            return "出于安全限制，浏览器不能访问本机或局域网地址。"
    return None


class _PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        error = _public_url_error(newurl)
        if error:
            raise urllib.error.URLError(error)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _html_preview_failure(summary: str) -> dict[str, Any]:
    return {
        "error": summary,
        "summary": summary,
        "recoverable": True,
        "browser_state": {
            "status": "failed",
            "page_open": False,
            "next_actions": ["create_html_preview"],
        },
    }


def _wrap_html_preview_document(title: str, body: str) -> str:
    text = str(body or "").strip()
    if "<!doctype html" in text[:120].lower() or "<html" in text[:240].lower():
        return text
    escaped_title = html.escape(title or "Serana 演示")
    return (
        "<!doctype html>\n"
        "<html lang=\"zh-CN\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"  <title>{escaped_title}</title>\n"
        "</head>\n"
        "<body>\n"
        f"{text}\n"
        "</body>\n"
        "</html>\n"
    )


def _preview_filename(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(title or "").strip().lower()).strip("-")
    if not slug:
        slug = "serana-preview"
    return f"{slug[:48]}-{uuid.uuid4().hex[:10]}.html"


def _preview_content_key(title: str, document: str) -> str:
    payload = f"{title}\0{document}".encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def _preview_cache_key(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _load_preview_cache() -> dict[str, Any]:
    try:
        data = json.loads(_PREVIEW_CACHE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_preview_cache(cache: dict[str, Any]) -> None:
    _PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    _PREVIEW_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _html_preview_has_meaningful_body(document: str) -> bool:
    text = str(document or "")
    body_match = re.search(r"<body[^>]*>(.*?)</body>", text, flags=re.IGNORECASE | re.DOTALL)
    body = body_match.group(1) if body_match else text
    without_scripts = re.sub(r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>", "", body, flags=re.IGNORECASE | re.DOTALL)
    readable = html.unescape(re.sub(r"<[^>]+>", " ", without_scripts))
    readable = re.sub(r"\s+", " ", readable).strip()
    return len(readable) >= 8


def _cached_preview_is_usable(preview_path: Path) -> bool:
    try:
        document = preview_path.read_text(encoding="utf-8")
    except Exception:
        return False
    if not _html_preview_has_meaningful_body(document):
        return False
    if _HTML_PLACEHOLDER_PATTERN.search(document):
        return False
    if _HTML_NETWORK_PATTERN.search(document):
        return False
    if _HTML_CONTROL_PATTERN.search(document) and not _HTML_EVENT_BINDING_PATTERN.search(document):
        return False
    return True


def _preview_result(
    *,
    title: str,
    filename: str,
    preview_path: Path,
    cached: bool,
) -> dict[str, Any]:
    download_url = f"/api/v1/browser/previews/{filename}"
    artifact = make_html_preview_artifact(
        filename=filename,
        title=title,
        download_url=download_url,
        size_bytes=path_size_bytes(preview_path),
    )
    summary = (
        f"\u5df2\u590d\u7528\u4e4b\u524d\u751f\u6210\u7684\u6f14\u793a\u9875\u9762\uff1a{filename}"
        if cached
        else f"\u5df2\u751f\u6210\u53ef\u6253\u5f00\u7684\u6f14\u793a\u9875\u9762\uff1a{filename}"
    )
    return {
        "title": title,
        "path": str(preview_path),
        "artifact": artifact,
        "artifact_url": download_url,
        "mime_type": "text/html",
        "summary": summary,
        "cached": cached,
        "browser_state": {
            "status": "preview_ready",
            "page_open": False,
            "artifact_url": download_url,
            "cached": cached,
        },
    }


def _read_url(url: str) -> dict[str, Any]:
    validation_error = _public_url_error(url)
    if validation_error:
        return {
            "url": url,
            "error": validation_error,
            "summary": validation_error,
            "recoverable": False,
            "browser_state": _browser_state(status="blocked", page_open=False),
        }
    parsed = urlparse(url)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Serana/1.0 (+https://skillhub.cn)",
            "Accept": "text/html,text/plain,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        opener = urllib.request.build_opener(_PublicRedirectHandler())
        with opener.open(request, timeout=20) as response:
            content_type = response.headers.get("content-type", "")
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            final_url = str(response.geturl() or url)
            if len(raw) > _MAX_RESPONSE_BYTES:
                return {
                    "url": final_url,
                    "error": "页面内容超过浏览器单次读取限制。",
                    "summary": "这个网页内容太大，暂时无法安全读取。",
                    "recoverable": False,
                    "browser_state": _browser_state(status="too_large", page_open=False),
                }
    except urllib.error.HTTPError as exc:
        return {
            "url": url,
            "error": f"HTTP {exc.code}: {exc.reason}",
            "summary": f"这个网页暂时无法打开（HTTP {exc.code}）。",
            "recoverable": True,
            "browser_state": _browser_state(status="failed", page_open=False),
        }
    except Exception as exc:
        return {
            "url": url,
            "error": str(exc),
            "summary": "这个网页暂时无法打开，可以换一个公开来源再试。",
            "recoverable": True,
            "browser_state": _browser_state(status="failed", page_open=False),
        }

    body = raw.decode(charset, errors="replace")
    title = urlparse(final_url).netloc or parsed.netloc or "网页"
    if "html" in content_type.lower() or "<html" in body[:500].lower():
        parser = _ReadableTextParser()
        parser.feed(body)
        text = parser.text()
        title = parser.title or title
    else:
        text = _normalize_text(body)

    return {
        "url": final_url,
        "title": title,
        "content": text,
        "content_type": content_type,
        "summary": f"已打开网页：{title}",
        "browser_state": _browser_state(
            status="opened",
            page_open=True,
            next_actions=["observe_page"],
            url=final_url,
        ),
    }


async def open_page(url: str, max_chars: int = 6000) -> dict[str, Any]:
    page = await asyncio.to_thread(_read_url, url)
    if "content" in page:
        limit = min(12000, max(1, int(max_chars or 6000)))
        page["content"] = str(page.get("content") or "")[:limit]
    _CURRENT_PAGE.clear()
    _CURRENT_PAGE.update(page)
    return dict(_CURRENT_PAGE)


async def observe_page(max_chars: int = 5000) -> dict[str, Any]:
    if not _CURRENT_PAGE:
        return {
            "error": "No page is currently open.",
            "summary": "当前没有可查看的网页，请先打开一个公开页面。",
            "recoverable": True,
            "browser_state": _browser_state(
                status="missing_page",
                page_open=False,
                next_actions=["open_page"],
            ),
        }
    page = dict(_CURRENT_PAGE)
    if "error" in page:
        return page
    if "content" in page:
        limit = min(12000, max(1, int(max_chars or 5000)))
        page["content"] = str(page.get("content") or "")[:limit]
    title = str(page.get("title") or "当前网页").strip()
    page["summary"] = f"已查看网页内容：{title}"
    page["browser_state"] = _browser_state(
        status="observed",
        page_open=True,
        next_actions=[],
        url=str(page.get("url") or ""),
    )
    return page


async def search_web(query: str, max_results: int = 5) -> dict[str, Any]:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return {
            "error": "Search query is empty.",
            "summary": "请告诉我需要搜索的具体主题。",
            "recoverable": True,
            "browser_state": _browser_state(status="missing_query", page_open=False),
        }
    search_url = f"https://www.bing.com/search?q={quote_plus(normalized_query)}"
    page = await open_page(search_url, max_chars=max(2000, min(12000, int(max_results or 5) * 1600)))
    if "error" in page:
        return {
            **page,
            "query": normalized_query,
            "summary": "网页搜索暂时没有成功，可以换一个更具体的关键词再试。",
        }
    return {
        **page,
        "query": normalized_query,
        "results": [],
        "summary": f"已搜索公开网页：{normalized_query}",
        "browser_state": _browser_state(
            status="searched",
            page_open=True,
            next_actions=["observe_page"],
            url=str(page.get("url") or search_url),
        ),
    }


def _missing_page_result() -> dict[str, Any]:
    return {
        "error": "No page is currently open.",
        "summary": "当前没有可操作的网页，请先打开一个公开页面。",
        "recoverable": True,
        "browser_state": _browser_state(
            status="missing_page",
            page_open=False,
            next_actions=["open_page"],
        ),
    }


async def act_page(action: str, target: str = "", value: str = "") -> dict[str, Any]:
    if not _CURRENT_PAGE or "error" in _CURRENT_PAGE:
        return _missing_page_result()
    return {
        "error": "Interactive browser actions are unavailable in the lightweight browser runtime.",
        "summary": "当前轻量浏览器只能读取公开网页，暂时不能在页面内点击或输入。",
        "recoverable": False,
        "browser_state": _browser_state(
            status="unsupported_action",
            page_open=True,
            next_actions=["observe_page"],
            url=str(_CURRENT_PAGE.get("url") or ""),
        ),
    }


async def capture_page(full_page: bool = False) -> dict[str, Any]:
    if not _CURRENT_PAGE or "error" in _CURRENT_PAGE:
        return _missing_page_result()
    return {
        "error": "Screenshot capture is unavailable in the lightweight browser runtime.",
        "summary": "当前轻量浏览器暂时不能截取网页图片。",
        "recoverable": False,
        "browser_state": _browser_state(
            status="unsupported_capture",
            page_open=True,
            next_actions=["observe_page"],
            url=str(_CURRENT_PAGE.get("url") or ""),
        ),
    }


async def look_page(full_page: bool = False) -> dict[str, Any]:
    return await capture_page(full_page=full_page)


def _read_download_manifest() -> list[dict[str, Any]]:
    if not _DOWNLOADS_MANIFEST_PATH.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in _DOWNLOADS_MANIFEST_PATH.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        filename = str(entry.get("filename") or "").strip()
        if not filename or "/" in filename or "\\" in filename:
            continue
        path = (_DOWNLOADS_DIR / filename).resolve()
        if _DOWNLOADS_DIR.resolve() not in path.parents or not path.is_file():
            continue
        entries.append(
            {
                **entry,
                "filename": filename,
                "size": path_size_bytes(path),
            }
        )
    return entries


async def browser_downloads(action: str = "list", filename: str = "") -> dict[str, Any]:
    entries = await asyncio.to_thread(_read_download_manifest)
    normalized_action = str(action or "list").strip().lower()
    if normalized_action == "list":
        return {
            "downloads": entries,
            "count": len(entries),
            "summary": f"浏览器下载目录中有 {len(entries)} 个可用文件。",
            "browser_state": _browser_state(status="downloads_listed", page_open=bool(_CURRENT_PAGE)),
        }
    if normalized_action != "send":
        return {
            "error": "Unsupported downloads action.",
            "summary": "浏览器下载仅支持列出文件或发送指定文件。",
            "recoverable": True,
            "browser_state": _browser_state(status="invalid_action", page_open=bool(_CURRENT_PAGE)),
        }

    normalized_filename = str(filename or "").strip()
    entry = next((item for item in entries if item["filename"] == normalized_filename), None)
    if entry is None:
        return {
            "error": "Download file not found.",
            "summary": "没有找到这个浏览器下载文件。",
            "recoverable": True,
            "browser_state": _browser_state(status="missing_download", page_open=bool(_CURRENT_PAGE)),
        }
    path = (_DOWNLOADS_DIR / normalized_filename).resolve()
    mime_type = str(entry.get("mime") or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    download_url = f"/api/v1/browser/downloads/{normalized_filename}"
    artifact = make_download_artifact(
        filename=normalized_filename,
        mime_type=mime_type,
        download_url=download_url,
        size_bytes=path_size_bytes(path),
    )
    return {
        "artifact": artifact,
        "artifact_url": download_url,
        "summary": f"浏览器下载文件已经准备好：{normalized_filename}",
        "browser_state": _browser_state(status="download_ready", page_open=bool(_CURRENT_PAGE)),
    }


async def create_html_preview(title: str, html: str = "", cache_key: str = "") -> dict[str, Any]:
    preview_title = str(title or "\u0053\u0065\u0072\u0061\u006e\u0061 \u6f14\u793a").strip()[:80] or "\u0053\u0065\u0072\u0061\u006e\u0061 \u6f14\u793a"
    normalized_cache_key = _preview_cache_key(cache_key)
    _PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)

    if normalized_cache_key:
        cache = _load_preview_cache()
        cached_filename = str(cache.get(normalized_cache_key) or "").strip()
        if cached_filename:
            if Path(cached_filename).name != cached_filename:
                cache.pop(normalized_cache_key, None)
                await asyncio.to_thread(_save_preview_cache, cache)
            else:
                cached_path = _PREVIEWS_DIR / cached_filename
                if cached_path.exists() and cached_path.suffix == ".html" and _cached_preview_is_usable(cached_path):
                    return _preview_result(
                        title=preview_title,
                        filename=cached_filename,
                        preview_path=cached_path,
                        cached=True,
                    )
                cache.pop(normalized_cache_key, None)
                await asyncio.to_thread(_save_preview_cache, cache)

    raw_html = str(html or "").strip()
    if not raw_html:
        return _html_preview_failure("没有找到可复用的演示缓存，也没有收到新的 HTML 内容，已停止生成空白演示。")

    document = _wrap_html_preview_document(preview_title, raw_html)

    if not document.strip():
        return _html_preview_failure("\u0048\u0054\u004d\u004c \u9884\u89c8\u5185\u5bb9\u4e3a\u7a7a\uff0c\u5df2\u505c\u6b62\u751f\u6210\u7a7a\u767d\u6f14\u793a\u3002")
    if _HTML_PLACEHOLDER_PATTERN.search(document):
        return _html_preview_failure("\u0048\u0054\u004d\u004c \u9884\u89c8\u91cc\u4ecd\u5305\u542b\u5360\u4f4d\u4ee3\u7801\uff0c\u5df2\u505c\u6b62\u751f\u6210\u3002")
    if _HTML_NETWORK_PATTERN.search(document):
        return _html_preview_failure("\u0048\u0054\u004d\u004c \u9884\u89c8\u5305\u542b\u5916\u90e8\u8054\u7f51\u6216\u5d4c\u5165\u8d44\u6e90\uff0c\u5df2\u62e6\u622a\u3002")
    if _HTML_CONTROL_PATTERN.search(document) and not _HTML_EVENT_BINDING_PATTERN.search(document):
        return _html_preview_failure("\u0048\u0054\u004d\u004c \u9884\u89c8\u5305\u542b\u53ef\u70b9\u51fb\u63a7\u4ef6\uff0c\u4f46\u6ca1\u6709\u68c0\u6d4b\u5230\u4e8b\u4ef6\u7ed1\u5b9a\u3002")
    if not _html_preview_has_meaningful_body(document):
        return _html_preview_failure("\u0048\u0054\u004d\u004c \u9884\u89c8\u5185\u5bb9\u4e3a\u7a7a\uff0c\u5df2\u505c\u6b62\u751f\u6210\u7a7a\u767d\u6f14\u793a\u3002")

    content_key = _preview_content_key(preview_title, document)
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", preview_title.strip().lower()).strip("-") or "serana-preview"
    filename = f"{slug[:48]}-{content_key[:16]}.html"
    preview_path = _PREVIEWS_DIR / filename
    cached = preview_path.exists()
    if not cached:
        await asyncio.to_thread(preview_path.write_text, document, encoding="utf-8")

    if normalized_cache_key:
        cache = _load_preview_cache()
        cache[normalized_cache_key] = filename
        await asyncio.to_thread(_save_preview_cache, cache)

    return _preview_result(
        title=preview_title,
        filename=filename,
        preview_path=preview_path,
        cached=cached,
    )


async def close_browser() -> dict[str, Any]:
    _CURRENT_PAGE.clear()
    return {"status": "closed", "summary": "Browser state cleared."}
