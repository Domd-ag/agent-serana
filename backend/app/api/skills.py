import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals import get_approval_manager, get_approval_reviewer, get_policy_gate
from app.core import get_db, logger
from app.core.audit import append_audit_record
from app.core.config import get_settings
from app.skills import (
    MarketplaceCatalogResponse,
    MarketplaceInstallRequest,
    MarketplaceInstallResponse,
    MarketplaceSearchResponse,
    MarketplaceSkillDetail,
    SkillLifecycleStatus,
    SkillManager,
    SkillMutationResponse,
    SkillPackage,
    SkillScopeUpdateRequest,
    SkillUpdateRequest,
)
from app.skills.skillhub import SkillHubClient, SkillHubError

router = APIRouter(prefix="/skills", tags=["skills"])

MARKETPLACE_ENTITY_TYPE = "skill_marketplace"
LOCAL_SKILL_ENTITY_TYPE = "skill_local"
LOCAL_UPLOAD_ENTITY_TYPE = "skill_local_package"
SKILL_UPDATE_ENTITY_TYPE = "skill_update"


def get_skill_manager() -> SkillManager:
    manager = SkillManager()
    manager.ensure_initialized()
    return manager


def get_marketplace_client() -> SkillHubClient:
    settings = get_settings()
    return SkillHubClient(
        base_url=settings.SKILLHUB_BASE_URL,
        public_base_url=settings.SKILLHUB_PUBLIC_BASE_URL,
    )


@router.get("", response_model=List[SkillPackage])
async def list_skills(manager: SkillManager = Depends(get_skill_manager)):
    return manager.list_skills()


@router.get("/marketplace", response_model=MarketplaceCatalogResponse)
async def list_marketplace_skills(
    limit: int = 20,
    cursor: Optional[str] = None,
    sort: str = "updated",
    manager: SkillManager = Depends(get_skill_manager),
    marketplace: SkillHubClient = Depends(get_marketplace_client),
):
    try:
        return marketplace.list_skills(manager=manager, limit=limit, cursor=cursor, sort=sort)
    except SkillHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/marketplace/search", response_model=MarketplaceSearchResponse)
async def search_marketplace_skills(
    q: str,
    limit: int = 20,
    manager: SkillManager = Depends(get_skill_manager),
    marketplace: SkillHubClient = Depends(get_marketplace_client),
):
    try:
        return marketplace.search_skills(query=q, manager=manager, limit=limit)
    except SkillHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/marketplace/{slug}", response_model=MarketplaceSkillDetail)
async def get_marketplace_skill_detail(
    slug: str,
    version: Optional[str] = None,
    tag: Optional[str] = None,
    manager: SkillManager = Depends(get_skill_manager),
    marketplace: SkillHubClient = Depends(get_marketplace_client),
):
    try:
        return marketplace.get_skill_detail(slug=slug, manager=manager, version=version, tag=tag)
    except SkillHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/marketplace/install", response_model=MarketplaceInstallResponse)
async def install_marketplace_skill(
    request: MarketplaceInstallRequest,
    manager: SkillManager = Depends(get_skill_manager),
    marketplace: SkillHubClient = Depends(get_marketplace_client),
    db: AsyncSession = Depends(get_db),
):
    policy_gate = get_policy_gate()
    reviewer = get_approval_reviewer()
    approval_manager = get_approval_manager()
    install_args = {
        "slug": request.slug,
        "version": request.version,
        "tag": request.tag,
    }
    policy_decision = policy_gate.evaluate(
        tool_name="skills.marketplace.install",
        arguments=install_args,
    )

    if request.approval_request_id is None and policy_decision.requires_approval:
        approval_request = reviewer.build_request(
            session_id="",
            tool_name="skills.marketplace.install",
            arguments=install_args,
            policy_decision=policy_decision,
            source="skills_marketplace",
            entity_type=MARKETPLACE_ENTITY_TYPE,
            entity_id=request.slug,
        )
        await approval_manager.register(approval_request)
        append_audit_record(
            db,
            entity_type=MARKETPLACE_ENTITY_TYPE,
            entity_id=request.slug,
            event_type="approval_requested",
            summary="等待确认安装远程技能",
            payload={
                "source": approval_request.source,
                "tool_name": approval_request.tool_name,
                "operation": approval_request.operation,
                "risk_level": approval_request.risk_level,
                "request_id": approval_request.request_id,
                "slug": request.slug,
                "version": request.version,
                "tag": request.tag,
            },
        )
        await db.commit()
        return MarketplaceInstallResponse(
            status="approval_required",
            approval_request=approval_request,
            message="安装远程技能前需要先确认来源和用途。",
        )

    if request.approval_request_id is not None:
        approval_request = await approval_manager.get_request(request.approval_request_id)
        if approval_request is None:
            raise HTTPException(status_code=400, detail="Approval request not found or already expired")
        if (
            approval_request.tool_name != "skills.marketplace.install"
            or approval_request.entity_type != MARKETPLACE_ENTITY_TYPE
            or approval_request.entity_id != request.slug
        ):
            raise HTTPException(status_code=400, detail="Approval request does not match this install operation")

        approval_result = await approval_manager.consume_resolution(request.approval_request_id)
        if approval_result is None:
            return MarketplaceInstallResponse(
                status="approval_pending",
                message="审批结果还没有返回，请确认后重试。",
            )
        if not approval_result.approved:
            return MarketplaceInstallResponse(
                status="approval_denied",
                message=approval_result.note or "这次安装没有通过审批。",
            )

    try:
        skill = marketplace.install_skill(
            slug=request.slug,
            manager=manager,
            version=request.version,
            tag=request.tag,
        )
        append_audit_record(
            db,
            entity_type=MARKETPLACE_ENTITY_TYPE,
            entity_id=request.slug,
            event_type="skills_install",
            summary="已安装远程技能",
            payload={
                "slug": request.slug,
                "version": request.version,
                "tag": request.tag,
                "approval_request_id": request.approval_request_id,
                "local_skill_name": skill.name,
                "installed_version": skill.version,
            },
        )
        await db.commit()
        return MarketplaceInstallResponse(
            status="installed",
            skill=skill,
            message="远程技能已安装。",
        )
    except SkillHubError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{skill_name}", response_model=Optional[SkillPackage])
async def get_skill(skill_name: str, manager: SkillManager = Depends(get_skill_manager)):
    skill = manager.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="未找到技能")
    return skill


@router.get("/{skill_name}/lifecycle", response_model=SkillLifecycleStatus)
async def get_skill_lifecycle(
    skill_name: str,
    manager: SkillManager = Depends(get_skill_manager),
    marketplace: SkillHubClient = Depends(get_marketplace_client),
):
    skill = manager.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="未找到技能")

    latest_version = skill.latest_version
    update_available = skill.update_available
    if skill.registry_slug:
        try:
            detail = marketplace.get_skill_detail(
                slug=skill.registry_slug,
                manager=manager,
                include_preview=False,
            )
            latest_version = detail.latest_version
            update_available = bool(
                skill.can_update
                and latest_version
                and _is_newer_version(latest_version, skill.version)
            )
        except SkillHubError as exc:
            logger.warning("Unable to refresh lifecycle for %s: %s", skill_name, exc)

    return SkillLifecycleStatus(
        skill_name=skill.name,
        installed_version=skill.version,
        latest_version=latest_version,
        update_available=update_available,
        can_update=skill.can_update,
        can_uninstall=skill.can_uninstall,
        source_label=skill.source_label,
        source_url=skill.source_url,
        trust_state=skill.trust_state,
        effective_scope=skill.effective_scope,
        registry_slug=skill.registry_slug,
    )


@router.post("/{skill_name}/scope", response_model=SkillMutationResponse)
async def update_skill_scope(
    skill_name: str,
    request: SkillScopeUpdateRequest,
    manager: SkillManager = Depends(get_skill_manager),
    db: AsyncSession = Depends(get_db),
):
    skill = manager.update_skill_scope(skill_name, request.agent_type)
    if not skill:
        raise HTTPException(status_code=400, detail="技能不存在，或生效范围无效")

    append_audit_record(
        db,
        entity_type=LOCAL_SKILL_ENTITY_TYPE,
        entity_id=skill.name,
        event_type="skills_scope_update",
        summary="已更新技能生效范围",
        payload={
            "skill_name": skill.name,
            "agent_type": skill.agent_type,
            "origin": skill.origin,
        },
    )
    await db.commit()
    return SkillMutationResponse(
        status="updated",
        skill=skill,
        message="技能生效范围已更新。",
    )


@router.post("/{skill_name}/update", response_model=SkillMutationResponse)
async def update_marketplace_skill(
    skill_name: str,
    request: SkillUpdateRequest,
    manager: SkillManager = Depends(get_skill_manager),
    marketplace: SkillHubClient = Depends(get_marketplace_client),
    db: AsyncSession = Depends(get_db),
):
    skill = manager.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="未找到技能")
    if not skill.can_update or not skill.registry_slug:
        raise HTTPException(status_code=400, detail="当前技能没有可用的远程更新来源")

    target_version = request.version or request.tag
    try:
        detail = marketplace.get_skill_detail(
            slug=skill.registry_slug,
            manager=manager,
            version=request.version,
            tag=request.tag,
            include_preview=False,
        )
        target_version = target_version or detail.latest_version
    except SkillHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    policy_gate = get_policy_gate()
    reviewer = get_approval_reviewer()
    approval_manager = get_approval_manager()
    update_args = {
        "skill_name": skill.name,
        "slug": skill.registry_slug,
        "current_version": skill.version,
        "target_version": target_version,
        "tag": request.tag,
    }
    policy_decision = policy_gate.evaluate(
        tool_name="skills.marketplace.update",
        arguments=update_args,
    )

    if request.approval_request_id is None and policy_decision.requires_approval:
        approval_request = reviewer.build_request(
            session_id="",
            tool_name="skills.marketplace.update",
            arguments=update_args,
            policy_decision=policy_decision,
            source="skills_marketplace",
            entity_type=SKILL_UPDATE_ENTITY_TYPE,
            entity_id=skill.name,
        )
        await approval_manager.register(approval_request)
        append_audit_record(
            db,
            entity_type=SKILL_UPDATE_ENTITY_TYPE,
            entity_id=skill.name,
            event_type="approval_requested",
            summary="等待确认更新技能",
            payload={
                "source": approval_request.source,
                "tool_name": approval_request.tool_name,
                "operation": approval_request.operation,
                "risk_level": approval_request.risk_level,
                "request_id": approval_request.request_id,
                "skill_name": skill.name,
                "slug": skill.registry_slug,
                "current_version": skill.version,
                "target_version": target_version,
            },
        )
        await db.commit()
        return SkillMutationResponse(
            status="approval_required",
            approval_request=approval_request,
            message="更新远程技能前需要先确认。",
        )

    if request.approval_request_id is not None:
        approval_request = await approval_manager.get_request(request.approval_request_id)
        if approval_request is None:
            raise HTTPException(status_code=400, detail="Approval request not found or already expired")
        if (
            approval_request.tool_name != "skills.marketplace.update"
            or approval_request.entity_type != SKILL_UPDATE_ENTITY_TYPE
            or approval_request.entity_id != skill.name
        ):
            raise HTTPException(status_code=400, detail="Approval request does not match this update operation")

        approval_result = await approval_manager.consume_resolution(request.approval_request_id)
        if approval_result is None:
            return SkillMutationResponse(
                status="approval_pending",
                message="审批结果还没有返回，请确认后重试。",
            )
        if not approval_result.approved:
            return SkillMutationResponse(
                status="approval_denied",
                message=approval_result.note or "这次更新没有通过审批。",
            )

    try:
        updated_skill = marketplace.install_skill(
            slug=skill.registry_slug,
            manager=manager,
            version=request.version,
            tag=request.tag,
        )
        append_audit_record(
            db,
            entity_type=SKILL_UPDATE_ENTITY_TYPE,
            entity_id=updated_skill.name,
            event_type="skills_update",
            summary="已更新远程技能",
            payload={
                "skill_name": updated_skill.name,
                "slug": updated_skill.registry_slug,
                "previous_version": skill.version,
                "installed_version": updated_skill.version,
                "approval_request_id": request.approval_request_id,
            },
        )
        await db.commit()
        return SkillMutationResponse(
            status="updated",
            skill=updated_skill,
            message="远程技能已更新。",
        )
    except SkillHubError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{skill_name}/tools")
async def get_skill_tools(skill_name: str, manager: SkillManager = Depends(get_skill_manager)):
    skill = manager.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="未找到技能")
    return skill.manifest.tools


@router.post("/{skill_name}/enable")
async def enable_skill(skill_name: str, manager: SkillManager = Depends(get_skill_manager)):
    if not manager.enable_skill(skill_name):
        raise HTTPException(status_code=404, detail="未找到技能")
    return {"success": True, "message": f"技能 {skill_name} 已启用"}


@router.post("/{skill_name}/disable")
async def disable_skill(skill_name: str, manager: SkillManager = Depends(get_skill_manager)):
    if not manager.disable_skill(skill_name):
        raise HTTPException(status_code=404, detail="未找到技能")
    return {"success": True, "message": f"技能 {skill_name} 已停用"}


@router.delete("/{skill_name}", response_model=SkillMutationResponse)
async def unload_skill(
    skill_name: str,
    approval_request_id: Optional[str] = None,
    manager: SkillManager = Depends(get_skill_manager),
    db: AsyncSession = Depends(get_db),
):
    skill = manager.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="未找到技能")
    if not skill.can_uninstall:
        raise HTTPException(status_code=400, detail="这个技能属于项目内置能力，不能直接卸载")

    policy_gate = get_policy_gate()
    reviewer = get_approval_reviewer()
    approval_manager = get_approval_manager()
    uninstall_args = {
        "skill_name": skill.name,
        "version": skill.version,
        "origin": skill.origin,
    }
    policy_decision = policy_gate.evaluate(
        tool_name="skills.local.uninstall",
        arguments=uninstall_args,
    )

    if approval_request_id is None and policy_decision.requires_approval:
        approval_request = reviewer.build_request(
            session_id="",
            tool_name="skills.local.uninstall",
            arguments=uninstall_args,
            policy_decision=policy_decision,
            source="skills_local",
            entity_type=LOCAL_SKILL_ENTITY_TYPE,
            entity_id=skill.name,
        )
        await approval_manager.register(approval_request)
        append_audit_record(
            db,
            entity_type=LOCAL_SKILL_ENTITY_TYPE,
            entity_id=skill.name,
            event_type="approval_requested",
            summary="等待确认卸载技能",
            payload={
                "source": approval_request.source,
                "tool_name": approval_request.tool_name,
                "operation": approval_request.operation,
                "risk_level": approval_request.risk_level,
                "request_id": approval_request.request_id,
                "skill_name": skill.name,
                "version": skill.version,
                "origin": skill.origin,
            },
        )
        await db.commit()
        return SkillMutationResponse(
            status="approval_required",
            approval_request=approval_request,
            message="卸载技能前需要你先确认。",
        )

    if approval_request_id is not None:
        approval_request = await approval_manager.get_request(approval_request_id)
        if approval_request is None:
            raise HTTPException(status_code=400, detail="Approval request not found or already expired")
        if (
            approval_request.tool_name != "skills.local.uninstall"
            or approval_request.entity_type != LOCAL_SKILL_ENTITY_TYPE
            or approval_request.entity_id != skill.name
        ):
            raise HTTPException(status_code=400, detail="Approval request does not match this uninstall operation")

        approval_result = await approval_manager.consume_resolution(approval_request_id)
        if approval_result is None:
            return SkillMutationResponse(
                status="approval_pending",
                message="审批结果还没有返回，请确认后重试。",
            )
        if not approval_result.approved:
            return SkillMutationResponse(
                status="approval_denied",
                message=approval_result.note or "这次卸载没有通过审批。",
            )

    removed_skill = manager.remove_skill(skill_name)
    if removed_skill is None:
        raise HTTPException(status_code=400, detail="当前技能不能被卸载")

    append_audit_record(
        db,
        entity_type=LOCAL_SKILL_ENTITY_TYPE,
        entity_id=skill_name,
        event_type="skills_uninstall",
        summary="已卸载本地技能",
        payload={
            "skill_name": removed_skill.name,
            "version": removed_skill.version,
            "origin": removed_skill.origin,
            "approval_request_id": approval_request_id,
        },
    )
    await db.commit()
    return SkillMutationResponse(
        status="removed",
        skill=removed_skill,
        message=f"技能 {skill_name} 已卸载。",
    )


@router.post("/{skill_name}/tools/{tool_name}/invoke")
async def invoke_tool(
    skill_name: str,
    tool_name: str,
    params: Optional[dict] = None,
    manager: SkillManager = Depends(get_skill_manager),
):
    tool_func = manager.get_tool_function(skill_name, tool_name)
    if not tool_func:
        raise HTTPException(status_code=404, detail="未找到工具")

    try:
        result = await tool_func(**(params or {}))
        return {"success": True, "result": result}
    except Exception as exc:
        logger.error("Error invoking tool %s.%s: %s", skill_name, tool_name, exc)
        raise HTTPException(status_code=500, detail=f"工具调用失败：{exc}")


@router.post("/upload", response_model=SkillMutationResponse)
async def upload_skill(
    file: Optional[UploadFile] = File(default=None),
    approval_request_id: Optional[str] = Form(default=None),
    manager: SkillManager = Depends(get_skill_manager),
    db: AsyncSession = Depends(get_db),
):
    approval_manager = get_approval_manager()
    reviewer = get_approval_reviewer()
    policy_gate = get_policy_gate()
    temp_dir: Optional[Path] = None

    try:
        if approval_request_id is None:
            if file is None:
                raise HTTPException(status_code=400, detail="请先上传技能压缩包")
            temp_dir, skill_source = await _extract_uploaded_skill(file)
            manifest = manager.inspect_skill_directory(skill_source)
            if manifest is None:
                raise HTTPException(status_code=400, detail="无效的技能包")

            install_args = {
                "filename": file.filename or "",
                "skill_name": manifest.name,
                "version": manifest.version,
            }
            policy_decision = policy_gate.evaluate(
                tool_name="skills.local.install",
                arguments=install_args,
            )

            if policy_decision.requires_approval:
                approval_request = reviewer.build_request(
                    session_id="",
                    tool_name="skills.local.install",
                    arguments=install_args,
                    policy_decision=policy_decision,
                    source="skills_upload",
                    entity_type=LOCAL_UPLOAD_ENTITY_TYPE,
                    entity_id=manifest.name,
                )
                if manager.stage_skill_installation(approval_request.request_id, skill_source) is None:
                    raise HTTPException(status_code=400, detail="无法暂存技能包，稍后再试")
                await approval_manager.register(approval_request)
                append_audit_record(
                    db,
                    entity_type=LOCAL_UPLOAD_ENTITY_TYPE,
                    entity_id=manifest.name,
                    event_type="approval_requested",
                    summary="等待确认导入本地技能",
                    payload={
                        "source": approval_request.source,
                        "tool_name": approval_request.tool_name,
                        "operation": approval_request.operation,
                        "risk_level": approval_request.risk_level,
                        "request_id": approval_request.request_id,
                        "filename": file.filename,
                        "skill_name": manifest.name,
                        "version": manifest.version,
                    },
                )
                await db.commit()
                return SkillMutationResponse(
                    status="approval_required",
                    approval_request=approval_request,
                    message="导入本地技能前需要先确认文件来源。",
                )

            skill = manager.install_skill_from_directory(skill_source)
            if skill is None:
                raise HTTPException(status_code=400, detail="技能安装失败")
            append_audit_record(
                db,
                entity_type=LOCAL_UPLOAD_ENTITY_TYPE,
                entity_id=skill.name,
                event_type="skills_install_local",
                summary="已导入本地技能",
                payload={
                    "filename": file.filename,
                    "skill_name": skill.name,
                    "version": skill.version,
                },
            )
            await db.commit()
            return SkillMutationResponse(
                status="installed",
                skill=skill,
                message="本地技能已导入。",
            )

        approval_request = await approval_manager.get_request(approval_request_id)
        if approval_request is None:
            raise HTTPException(status_code=400, detail="Approval request not found or already expired")
        if approval_request.tool_name != "skills.local.install":
            raise HTTPException(status_code=400, detail="Approval request does not match this install operation")

        approval_result = await approval_manager.consume_resolution(approval_request_id)
        if approval_result is None:
            return SkillMutationResponse(
                status="approval_pending",
                message="审批结果还没有返回，请确认后重试。",
            )
        if not approval_result.approved:
            manager.discard_staged_skill_installation(approval_request_id)
            return SkillMutationResponse(
                status="approval_denied",
                message=approval_result.note or "这次导入没有通过审批。",
            )

        skill = manager.consume_staged_skill_installation(approval_request_id)
        if skill is None:
            raise HTTPException(status_code=400, detail="Staged skill upload not found or already expired")

        append_audit_record(
            db,
            entity_type=LOCAL_UPLOAD_ENTITY_TYPE,
            entity_id=skill.name,
            event_type="skills_install_local",
            summary="已导入本地技能",
            payload={
                "skill_name": skill.name,
                "version": skill.version,
                "approval_request_id": approval_request_id,
            },
        )
        await db.commit()
        return SkillMutationResponse(
            status="installed",
            skill=skill,
            message="本地技能已导入。",
        )
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


@router.get("/for-agent/{agent_type}")
async def get_tools_for_agent(agent_type: str, manager: SkillManager = Depends(get_skill_manager)):
    return manager.get_tools_for_agent(agent_type)


async def _extract_uploaded_skill(file: UploadFile) -> tuple[Path, Path]:
    temp_dir = Path(tempfile.mkdtemp())
    zip_path = temp_dir / "skill.zip"
    with open(zip_path, "wb") as output:
        output.write(await file.read())

    extract_dir = temp_dir / "extract"
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(extract_dir)

    skill_source = _locate_skill_source(extract_dir)
    if skill_source is None:
        raise HTTPException(status_code=400, detail="无效的技能包，缺少 skill.json")
    return temp_dir, skill_source


def _locate_skill_source(extract_dir: Path) -> Path | None:
    if (extract_dir / "skill.json").exists():
        return extract_dir

    for item in extract_dir.iterdir():
        if item.is_dir() and (item / "skill.json").exists():
            return item
    return None


def _is_newer_version(candidate: str, current: str) -> bool:
    candidate_parts = _version_parts(candidate)
    current_parts = _version_parts(current)
    if candidate_parts and current_parts:
        return candidate_parts > current_parts
    return candidate != current


def _version_parts(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in value.replace("-", ".").split("."):
        if part.isdigit():
            parts.append(int(part))
        else:
            break
    return tuple(parts)
