import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from app.core import logger
from app.skills.manager import SkillManager
from app.skills.models import (
    MarketplaceCatalogResponse,
    MarketplaceModeration,
    MarketplaceOwner,
    MarketplaceSearchResponse,
    MarketplaceSkillDetail,
    MarketplaceSkillSummary,
    SkillPackage,
)


class ClawHubError(Exception):
    """Raised when a ClawHub request fails."""


class ClawHubClient:
    BASE_URL = "https://clawhub.ai"

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or self.BASE_URL).rstrip("/")

    def _build_url(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        query = ""
        if params:
            filtered = {key: value for key, value in params.items() if value is not None}
            if filtered:
                query = "?" + urlencode(filtered)
        return f"{self.base_url}{path}{query}"

    def _http_get_text(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        url = self._build_url(path, params)
        try:
            with urlopen(url, timeout=15) as response:
                return response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore").strip()
            raise ClawHubError(detail or f"ClawHub 请求失败：HTTP {exc.code}") from exc
        except URLError as exc:
            raise ClawHubError(f"ClawHub 连接失败：{exc.reason}") from exc

    def _http_get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return json.loads(self._http_get_text(path, params))

    def _canonical_url(self, owner_handle: Optional[str], slug: str) -> str:
        if owner_handle:
            return f"{self.base_url}/{owner_handle}/{slug}"
        return f"{self.base_url}/skills/{slug}"

    def _download_url(self, slug: str, version: Optional[str] = None, tag: Optional[str] = None) -> str:
        return self._build_url("/api/v1/download", {"slug": slug, "version": version, "tag": tag})

    def _installed_info(self, manager: SkillManager, slug: str) -> tuple[bool, Optional[str]]:
        for skill in manager.list_skills():
            if skill.manifest.registry_slug == slug:
                return True, skill.name
        return False, None

    def _map_search_item(self, item: Dict[str, Any], manager: SkillManager) -> MarketplaceSkillSummary:
        slug = item.get("slug", "")
        installed, local_skill_name = self._installed_info(manager, slug)
        owner = item.get("owner") or {}
        owner_handle = item.get("ownerHandle") or owner.get("handle")
        return MarketplaceSkillSummary(
            slug=slug,
            displayName=item.get("displayName") or slug,
            summary=item.get("summary"),
            version=item.get("version"),
            updatedAt=item.get("updatedAt"),
            ownerHandle=owner_handle,
            owner=MarketplaceOwner(**owner) if owner else None,
            canonical_url=self._canonical_url(owner_handle, slug),
            download_url=self._download_url(slug, version=item.get("version")),
            installed=installed,
            local_skill_name=local_skill_name,
        )

    def search_skills(self, query: str, manager: SkillManager, limit: int = 20) -> MarketplaceSearchResponse:
        payload = self._http_get_json("/api/v1/search", {"q": query, "limit": limit})
        results = [self._map_search_item(item, manager) for item in payload.get("results", [])]
        return MarketplaceSearchResponse(results=results)

    def list_skills(
        self,
        manager: SkillManager,
        limit: int = 20,
        cursor: Optional[str] = None,
        sort: str = "updated",
    ) -> MarketplaceCatalogResponse:
        payload = self._http_get_json("/api/v1/skills", {"limit": limit, "cursor": cursor, "sort": sort})
        items = [self._map_search_item(item, manager) for item in payload.get("items", [])]
        return MarketplaceCatalogResponse(items=items, nextCursor=payload.get("nextCursor"))

    def get_skill_markdown(self, slug: str, version: Optional[str] = None, tag: Optional[str] = None) -> str:
        return self._http_get_text("/api/v1/skills/{slug}/file".format(slug=slug), {"path": "SKILL.md", "version": version, "tag": tag})

    def get_skill_detail(
        self,
        slug: str,
        manager: SkillManager,
        version: Optional[str] = None,
        tag: Optional[str] = None,
        include_preview: bool = True,
    ) -> MarketplaceSkillDetail:
        payload = self._http_get_json(f"/api/v1/skills/{slug}")
        skill = payload.get("skill") or {}
        owner = payload.get("owner") or {}
        latest_version = payload.get("latestVersion") or {}
        moderation_payload = payload.get("moderation")
        installed, local_skill_name = self._installed_info(manager, slug)
        preview = None
        if include_preview:
            try:
                preview = self.get_skill_markdown(slug, version=version, tag=tag)
            except ClawHubError as exc:
                logger.warning("Unable to fetch SKILL.md preview for %s: %s", slug, exc)

        return MarketplaceSkillDetail(
            slug=skill.get("slug", slug),
            display_name=skill.get("displayName") or slug,
            summary=skill.get("summary"),
            owner_handle=owner.get("handle"),
            owner_display_name=owner.get("displayName"),
            latest_version=latest_version.get("version") or version or tag,
            changelog=latest_version.get("changelog"),
            canonical_url=self._canonical_url(owner.get("handle"), skill.get("slug", slug)),
            download_url=self._download_url(skill.get("slug", slug), version=version or latest_version.get("version"), tag=tag),
            skill_md_preview=preview,
            installed=installed,
            local_skill_name=local_skill_name,
            moderation=MarketplaceModeration(**moderation_payload) if moderation_payload else None,
        )

    def _sanitize_name(self, value: str) -> str:
        value = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
        value = value.strip("_")
        return value or "imported_skill"

    def _build_local_skill_name(self, manager: SkillManager, slug: str, owner_handle: Optional[str]) -> str:
        base_name = self._sanitize_name(slug)
        existing = manager.get_skill(base_name)
        if existing is None or existing.manifest.registry_slug == slug:
            return base_name

        owner_part = self._sanitize_name(owner_handle or "clawhub")
        fallback_name = f"clawhub_{owner_part}_{base_name}"
        if manager.get_skill(fallback_name) is None:
            return fallback_name

        suffix = 2
        while manager.get_skill(f"{fallback_name}_{suffix}") is not None:
            suffix += 1
        return f"{fallback_name}_{suffix}"

    def install_skill(
        self,
        slug: str,
        manager: SkillManager,
        version: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> SkillPackage:
        detail = self.get_skill_detail(slug, manager, version=version, tag=tag, include_preview=False)
        skill_md = self.get_skill_markdown(slug, version=version, tag=tag)
        local_name = detail.local_skill_name or self._build_local_skill_name(manager, slug, detail.owner_handle)
        resolved_version = detail.latest_version or version or tag or "latest"

        manifest_payload = {
            "name": local_name,
            "version": resolved_version,
            "description": detail.summary or f"从 ClawHub 导入的技能：{detail.display_name}",
            "author": detail.owner_display_name or detail.owner_handle or "ClawHub",
            "format": "sebastian_package",
            "runtime": "instruction",
            "instruction_file": "SKILL.md",
            "entrypoint": None,
            "registry_slug": slug,
            "source_url": detail.canonical_url,
            "agent_type": "all",
            "max_instances": 1,
            "tools": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / local_name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "skill.json").write_text(
                json.dumps(manifest_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

            installed_skill = manager.install_skill_from_directory(skill_dir)
            if not installed_skill:
                raise ClawHubError("导入技能失败，生成的技能包未通过本地校验。")

        return installed_skill
