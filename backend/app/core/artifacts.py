from __future__ import annotations

from pathlib import Path
from typing import Any


def path_size_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def make_artifact(
    *,
    kind: str,
    filename: str,
    mime_type: str,
    download_url: str,
    size_bytes: int = 0,
    title: str | None = None,
    thumbnail_url: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact: dict[str, Any] = {
        "kind": kind,
        "filename": filename,
        "mime_type": mime_type,
        "size_bytes": max(0, int(size_bytes or 0)),
        "download_url": download_url,
    }
    if title:
        artifact["title"] = title
    if thumbnail_url:
        artifact["thumbnail_url"] = thumbnail_url
    if metadata:
        artifact["metadata"] = metadata
    return artifact


def make_image_artifact(
    *,
    filename: str,
    download_url: str,
    size_bytes: int = 0,
    thumbnail_url: str | None = None,
) -> dict[str, Any]:
    return make_artifact(
        kind="image",
        filename=filename,
        mime_type="image/png",
        size_bytes=size_bytes,
        download_url=download_url,
        thumbnail_url=thumbnail_url or download_url,
    )


def make_html_preview_artifact(
    *,
    filename: str,
    title: str,
    download_url: str,
    size_bytes: int = 0,
) -> dict[str, Any]:
    return make_artifact(
        kind="html_preview",
        filename=filename,
        title=title,
        mime_type="text/html",
        size_bytes=size_bytes,
        download_url=download_url,
    )


def make_download_artifact(
    *,
    filename: str,
    mime_type: str,
    download_url: str,
    size_bytes: int = 0,
) -> dict[str, Any]:
    return make_artifact(
        kind="download",
        filename=filename,
        mime_type=mime_type or "application/octet-stream",
        size_bytes=size_bytes,
        download_url=download_url,
    )
