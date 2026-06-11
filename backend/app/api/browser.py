import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import get_settings


router = APIRouter(prefix="/browser", tags=["browser"])


def _browser_data_dir() -> Path:
    configured = str(get_settings().SERANA_BROWSER_DATA_DIR or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "skills_store" / "browser"


def _screenshots_dir() -> Path:
    return _browser_data_dir() / "screenshots"


def _previews_dir() -> Path:
    return _browser_data_dir() / "previews"


def _downloads_dir() -> Path:
    return _browser_data_dir() / "downloads"


def _resolve_plain_file(root: Path, filename: str, expected_suffix: str | None = None) -> Path:
    if "/" in filename or "\\" in filename or filename in {"", ".", ".."}:
        raise HTTPException(status_code=404, detail="Browser artifact not found")
    if expected_suffix and not filename.lower().endswith(expected_suffix):
        raise HTTPException(status_code=404, detail="Browser artifact not found")

    resolved_root = root.resolve()
    resolved_path = (resolved_root / filename).resolve()
    if resolved_root not in resolved_path.parents or not resolved_path.exists():
        raise HTTPException(status_code=404, detail="Browser artifact not found")
    return resolved_path


@router.get("/screenshots/{filename}")
async def get_browser_screenshot(filename: str):
    screenshot_path = _resolve_plain_file(_screenshots_dir(), filename, ".png")

    return FileResponse(
        path=screenshot_path,
        media_type="image/png",
        filename=filename,
    )


@router.get("/previews/{filename}")
async def get_browser_preview(filename: str):
    preview_path = _resolve_plain_file(_previews_dir(), filename, ".html")

    return FileResponse(
        path=preview_path,
        media_type="text/html; charset=utf-8",
        filename=filename,
        content_disposition_type="inline",
        headers={
            "Content-Security-Policy": (
                "default-src 'none'; "
                "script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; "
                "img-src data:; "
                "base-uri 'none'; "
                "form-action 'none'; "
                "frame-ancestors 'none'"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/downloads/{filename}")
async def get_browser_download(filename: str):
    download_path = _resolve_plain_file(_downloads_dir(), filename)
    media_type = mimetypes.guess_type(download_path.name)[0] or "application/octet-stream"
    return FileResponse(
        path=download_path,
        media_type=media_type,
        filename=filename,
        headers={"X-Content-Type-Options": "nosniff"},
    )
