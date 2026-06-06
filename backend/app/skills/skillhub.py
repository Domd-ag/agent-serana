import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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
from app.skills.standardizer import SkillStandardizationError, SkillStandardizer


class SkillHubError(Exception):
    """Raised when a SkillHub request fails."""


class SkillHubClient:
    API_BASE_URL = "https://api.skillhub.cn"
    PUBLIC_BASE_URL = "https://skillhub.cn"

    def __init__(self, base_url: Optional[str] = None, public_base_url: Optional[str] = None):
        self.base_url = (base_url or self.API_BASE_URL).rstrip("/")
        self.public_base_url = (public_base_url or self.PUBLIC_BASE_URL).rstrip("/")

    def _build_url(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        query = ""
        if params:
            filtered = {key: value for key, value in params.items() if value is not None and value != ""}
            if filtered:
                query = "?" + urlencode(filtered)
        return f"{self.base_url}{path}{query}"

    def _http_get_bytes(self, path: str, params: Optional[Dict[str, Any]] = None) -> bytes:
        url = self._build_url(path, params)
        request = Request(url, headers={"Accept": "application/json, text/plain, application/zip, */*"})
        try:
            with urlopen(request, timeout=20) as response:
                return response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore").strip()
            raise SkillHubError(detail or f"SkillHub 请求失败：HTTP {exc.code}") from exc
        except URLError as exc:
            raise SkillHubError(f"SkillHub 连接失败：{exc.reason}") from exc

    def _http_get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raw = self._http_get_bytes(path, params)
        return json.loads(raw.decode("utf-8"))

    def _canonical_url(self, slug: str) -> str:
        return f"{self.public_base_url}/skills/{slug}"

    def _download_url(self, slug: str, version: Optional[str] = None) -> str:
        return self._build_url("/api/v1/download", {"slug": slug, "version": version})

    def _normalize_sort(self, sort: Optional[str]) -> str:
        normalized = (sort or "").strip().lower()
        alias_map = {
            "": "updated_at",
            "updated": "updated_at",
            "latest": "updated_at",
            "updated_at": "updated_at",
            "downloads": "downloads",
            "popular": "downloads",
            "stars": "stars",
            "installs": "installs",
            "score": "score",
            "recommend": "score",
            "recommended": "score",
            "trending": "score",
        }
        return alias_map.get(normalized, "updated_at")

    def _installed_info(self, manager: SkillManager, slug: str) -> tuple[bool, Optional[str]]:
        for skill in manager.list_skills():
            if skill.manifest.registry_slug == slug:
                return True, skill.name
        return False, None

    def _version_from_payload(self, item: Dict[str, Any]) -> Optional[str]:
        version = item.get("currentVersion") or item.get("latestVersion") or item.get("version")
        if isinstance(version, dict):
            return str(version.get("version") or "") or None
        if version is None:
            return None
        return str(version)

    def _owner_from_payload(self, item: Dict[str, Any]) -> tuple[Optional[str], Optional[MarketplaceOwner]]:
        creator = item.get("creator") if isinstance(item.get("creator"), dict) else {}
        owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
        handle = (
            item.get("ownerName")
            or item.get("ownerHandle")
            or owner.get("handle")
            or creator.get("agentId")
        )
        display_name = (
            item.get("author")
            or owner.get("displayName")
            or creator.get("displayName")
            or item.get("ownerName")
        )
        if not handle and not display_name:
            return None, None
        handle_value = str(handle or display_name or "skillhub")
        return handle_value, MarketplaceOwner(
            handle=handle_value,
            displayName=str(display_name) if display_name else None,
            image=owner.get("image") or creator.get("avatar"),
        )

    def _summary_from_payload(self, item: Dict[str, Any]) -> Optional[str]:
        return (
            item.get("summary_zh")
            or item.get("description_zh")
            or item.get("summary")
            or item.get("description")
            or item.get("parsedDescription")
        )

    def _display_name_from_payload(self, item: Dict[str, Any], slug: str) -> str:
        return str(item.get("displayName") or item.get("name") or item.get("parsedName") or slug)

    def _map_item(self, item: Dict[str, Any], manager: SkillManager) -> MarketplaceSkillSummary:
        slug = str(item.get("slug") or "")
        installed, local_skill_name = self._installed_info(manager, slug)
        owner_handle, owner = self._owner_from_payload(item)
        version = self._version_from_payload(item)
        raw_updated_at = item.get("updatedAt") or item.get("updated_at") or item.get("lastPublishTime")
        updated_at = raw_updated_at if isinstance(raw_updated_at, int) else None
        return MarketplaceSkillSummary(
            slug=slug,
            displayName=self._display_name_from_payload(item, slug),
            summary=self._summary_from_payload(item),
            version=version,
            updatedAt=updated_at,
            ownerHandle=owner_handle,
            owner=owner,
            canonical_url=self._canonical_url(slug),
            download_url=self._download_url(slug, version=version),
            installed=installed,
            local_skill_name=local_skill_name,
        )

    def search_skills(self, query: str, manager: SkillManager, limit: int = 20) -> MarketplaceSearchResponse:
        payload = self._http_get_json(
            "/api/skills",
            {
                "keyword": query,
                "page": 1,
                "pageSize": limit,
            },
        )
        data_payload = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        items = payload.get("items")
        if not isinstance(items, list):
            items = data_payload.get("skills", []) or data_payload.get("items", [])
        return MarketplaceSearchResponse(results=[self._map_item(item, manager) for item in items])

    def list_skills(
        self,
        manager: SkillManager,
        limit: int = 20,
        cursor: Optional[str] = None,
        sort: str = "updated",
    ) -> MarketplaceCatalogResponse:
        page = int(cursor) if cursor and str(cursor).isdigit() else 1
        normalized_sort = self._normalize_sort(sort)
        payload = self._http_get_json(
            "/api/skills",
            {
                "page": page,
                "pageSize": limit,
                "sortBy": normalized_sort,
            },
        )
        data_payload = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        items = payload.get("items")
        if not isinstance(items, list):
            items = data_payload.get("skills", []) or data_payload.get("items", [])
        total = int(payload.get("total") or data_payload.get("total") or 0)
        next_cursor = str(page + 1) if total > page * limit else None
        return MarketplaceCatalogResponse(
            items=[self._map_item(item, manager) for item in items],
            nextCursor=next_cursor,
        )

    def get_skill_detail(
        self,
        slug: str,
        manager: SkillManager,
        version: Optional[str] = None,
        tag: Optional[str] = None,
        include_preview: bool = True,
    ) -> MarketplaceSkillDetail:
        detail_payload = self._http_get_json(f"/api/v1/skills/{slug}")
        skill_payload = detail_payload.get("skill") if isinstance(detail_payload.get("skill"), dict) else detail_payload
        latest_version_payload = (
            detail_payload.get("latestVersion")
            if isinstance(detail_payload.get("latestVersion"), dict)
            else {}
        )
        latest_version = version or tag or latest_version_payload.get("version") or self._version_from_payload(skill_payload)
        owner_handle, _ = self._owner_from_payload(detail_payload)
        installed, local_skill_name = self._installed_info(manager, slug)
        preview = self._fetch_skill_markdown(slug, latest_version) if include_preview else None
        moderation = MarketplaceModeration(
            verdict=self._security_verdict(detail_payload),
            summary=self._security_summary(detail_payload),
        )

        return MarketplaceSkillDetail(
            slug=slug,
            display_name=self._display_name_from_payload(skill_payload, slug),
            summary=self._summary_from_payload(skill_payload),
            owner_handle=owner_handle,
            owner_display_name=(detail_payload.get("owner") or {}).get("displayName")
            if isinstance(detail_payload.get("owner"), dict)
            else detail_payload.get("ownerName"),
            latest_version=latest_version,
            changelog=latest_version_payload.get("changelog"),
            canonical_url=self._canonical_url(slug),
            download_url=self._download_url(slug, version=latest_version),
            skill_md_preview=preview,
            installed=installed,
            local_skill_name=local_skill_name,
            moderation=moderation,
        )

    def _security_summary(self, payload: Dict[str, Any]) -> Optional[str]:
        reports = payload.get("securityReports") if isinstance(payload.get("securityReports"), dict) else {}
        summaries = []
        for name, report in reports.items():
            if isinstance(report, dict) and report.get("statusText"):
                summaries.append(f"{name}: {report.get('statusText')}")
        if summaries:
            return "；".join(summaries)
        cert_level = payload.get("certLevel")
        recommend_level = payload.get("recommendLevel")
        if not cert_level and not recommend_level:
            return None
        return "；".join(str(value) for value in [cert_level, recommend_level] if value)

    def _security_verdict(self, payload: Dict[str, Any]) -> Optional[str]:
        reports = payload.get("securityReports") if isinstance(payload.get("securityReports"), dict) else {}
        statuses = [
            str(report.get("status"))
            for report in reports.values()
            if isinstance(report, dict) and report.get("status")
        ]
        if statuses and all(status == "benign" for status in statuses):
            return "benign"
        return statuses[0] if statuses else None

    def _fetch_skill_markdown(self, slug: str, version: Optional[str] = None) -> Optional[str]:
        params: Dict[str, Any] = {"path": "SKILL.md"}
        if version:
            params["version"] = version
        try:
            return self._http_get_bytes(f"/api/v1/skills/{slug}/file", params).decode("utf-8")
        except (SkillHubError, UnicodeDecodeError):
            return None

    def _sanitize_name(self, value: str) -> str:
        value = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
        value = value.strip("_")
        return value or "imported_skill"

    def _infer_capabilities_and_intents(
        self,
        *,
        slug: str,
        display_name: str,
        summary: str | None,
        skill_md_preview: str | None,
    ) -> tuple[list[str], list[str]]:
        source_text = " ".join(
            part for part in (slug, display_name, summary or "", skill_md_preview or "") if part
        ).lower()

        capabilities: list[str] = []
        intents: list[str] = []

        def add_capability(*values: str) -> None:
            for value in values:
                if value and value not in capabilities:
                    capabilities.append(value)

        def add_intent(*values: str) -> None:
            for value in values:
                if value and value not in intents:
                    intents.append(value)

        if any(token in source_text for token in ("weather", "天气", "forecast", "温度", "降雨", "气温")):
            add_capability("weather", "forecast", "天气", "预报")
            add_intent("天气查询", "天气预报", "今日天气", "明天天气")

        if any(token in source_text for token in ("time", "timezone", "日期", "时间", "时区", "calendar", "日历")):
            add_capability("time", "calendar", "时间", "日期")
            add_intent("时间查询", "日期查询", "时区转换")

        if any(token in source_text for token in ("calc", "calculator", "math", "数学", "算术", "计算")):
            add_capability("calculator", "math", "计算", "算术")
            add_intent("计算", "数学运算", "算一下")

        if any(token in source_text for token in ("memory", "记忆", "profile", "总结", "summary", "episode")):
            add_capability("memory", "summary", "记忆", "总结")
            add_intent("记住", "回忆", "总结对话")

        if any(
            token in source_text
            for token in (
                "self-improv",
                "self_improv",
                "continuous improvement",
                "learning",
                "learnings",
                "correction",
                "feedback",
                "error recovery",
                "lesson",
                "lessons",
                "经验",
                "教训",
                "纠正",
                "错误",
                "复盘",
                "改进",
                "反馈",
                "持续改进",
                "能力缺口",
            )
        ):
            add_capability(
                "self_improvement",
                "reflection",
                "error_recovery",
                "correction",
                "feedback",
                "learning",
                "复盘",
                "纠错",
                "持续改进",
            )
            add_intent(
                "纠正回答",
                "总结经验",
                "复盘错误",
                "记录教训",
                "吸收反馈",
                "持续改进",
                "避免下次再错",
                "刚才答错了",
            )

        if any(token in source_text for token in ("browser", "网页", "web", "搜索", "search", "crawl", "scrape")):
            add_capability("browser", "web_search", "网页", "搜索")
            add_intent("上网搜索", "打开网页", "查网页")

        if any(token in source_text for token in ("code", "coding", "program", "开发", "编程", "代码")):
            add_capability("coding", "implementation", "代码", "编程")
            add_intent("写代码", "实现方案", "代码示例")

        if any(token in source_text for token in ("travel", "trip", "旅行", "旅游", "行程")):
            add_capability("travel", "planning", "旅行", "行程")
            add_intent("旅行计划", "行程安排", "旅游建议")

        if any(token in source_text for token in ("food", "meal", "recipe", "菜谱", "美食", "饮食")):
            add_capability("food", "meal_planning", "美食", "菜谱")
            add_intent("吃什么", "菜谱建议", "饮食建议")

        return capabilities, intents

    def _build_local_skill_name(self, manager: SkillManager, slug: str) -> str:
        base_name = self._sanitize_name(slug)
        existing = manager.get_skill(base_name)
        if existing is None or existing.manifest.registry_slug == slug:
            return base_name

        fallback_name = f"skillhub_{base_name}"
        if manager.get_skill(fallback_name) is None:
            return fallback_name

        suffix = 2
        while manager.get_skill(f"{fallback_name}_{suffix}") is not None:
            suffix += 1
        return f"{fallback_name}_{suffix}"

    def _extract_downloaded_skill(self, archive_path: Path, extract_dir: Path) -> Path:
        with zipfile.ZipFile(archive_path, "r") as zip_file:
            extract_root = extract_dir.resolve()
            for item in zip_file.infolist():
                target = (extract_root / item.filename).resolve()
                try:
                    target.relative_to(extract_root)
                except ValueError as exc:
                    raise SkillHubError("下载的 SkillHub 技能包包含越界文件路径。") from exc
                unix_mode = item.external_attr >> 16
                if (unix_mode & 0o170000) == 0o120000:
                    raise SkillHubError("下载的 SkillHub 技能包包含不允许的符号链接。")
            zip_file.extractall(extract_dir)
        if (extract_dir / "SKILL.md").exists():
            return extract_dir
        for item in extract_dir.iterdir():
            if item.is_dir() and (item / "SKILL.md").exists():
                return item
        raise SkillHubError("下载的 SkillHub 技能包缺少 SKILL.md。")

    def _write_manifest(
        self,
        skill_dir: Path,
        *,
        local_name: str,
        detail: MarketplaceSkillDetail,
        version: str,
    ) -> None:
        capabilities, intents = self._infer_capabilities_and_intents(
            slug=detail.slug,
            display_name=detail.display_name,
            summary=detail.summary,
            skill_md_preview=detail.skill_md_preview,
        )
        try:
            SkillStandardizer.standardize_marketplace_package(
                skill_dir,
                local_name=local_name,
                version=version,
                description=detail.summary or f"从 SkillHub 导入的技能：{detail.display_name}",
                author=detail.owner_display_name or detail.owner_handle or "SkillHub",
                registry_slug=detail.slug,
                source_url=detail.canonical_url,
                capabilities=capabilities,
                intents=intents,
            )
        except SkillStandardizationError as exc:
            raise SkillHubError(str(exc)) from exc

    def install_skill(
        self,
        slug: str,
        manager: SkillManager,
        version: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> SkillPackage:
        detail = self.get_skill_detail(slug, manager, version=version, tag=tag, include_preview=False)
        resolved_version = detail.latest_version or version or tag or "latest"
        local_name = detail.local_skill_name or self._build_local_skill_name(manager, slug)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            archive_path = temp_root / "skillhub-skill.zip"
            archive_path.write_bytes(
                self._http_get_bytes(
                    "/api/v1/download",
                    {
                        "slug": slug,
                        "version": resolved_version if resolved_version != "latest" else None,
                    },
                )
            )
            extracted_source = self._extract_downloaded_skill(archive_path, temp_root / "extract")
            skill_dir = temp_root / local_name
            if skill_dir.exists():
                shutil.rmtree(skill_dir)
            shutil.copytree(extracted_source, skill_dir)
            self._write_manifest(
                skill_dir,
                local_name=local_name,
                detail=detail,
                version=resolved_version,
            )

            installed_skill = manager.install_skill_from_directory(skill_dir)
            if not installed_skill:
                raise SkillHubError("导入技能失败，SkillHub 技能包未通过本地校验。")

        return installed_skill
