import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core import logger
from app.skills import (
    MarketplaceCatalogResponse,
    MarketplaceInstallRequest,
    MarketplaceSearchResponse,
    MarketplaceSkillDetail,
    SkillManager,
    SkillPackage,
)
from app.skills.clawhub import ClawHubClient, ClawHubError

router = APIRouter(prefix="/skills", tags=["skills"])


def get_skill_manager() -> SkillManager:
    manager = SkillManager()
    manager.ensure_initialized()
    return manager


def get_marketplace_client() -> ClawHubClient:
    return ClawHubClient()


@router.get("", response_model=List[SkillPackage])
async def list_skills(manager: SkillManager = Depends(get_skill_manager)):
    return manager.list_skills()


@router.get("/marketplace", response_model=MarketplaceCatalogResponse)
async def list_marketplace_skills(
    limit: int = 20,
    cursor: Optional[str] = None,
    sort: str = "updated",
    manager: SkillManager = Depends(get_skill_manager),
    marketplace: ClawHubClient = Depends(get_marketplace_client),
):
    try:
        return marketplace.list_skills(manager=manager, limit=limit, cursor=cursor, sort=sort)
    except ClawHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/marketplace/search", response_model=MarketplaceSearchResponse)
async def search_marketplace_skills(
    q: str,
    limit: int = 20,
    manager: SkillManager = Depends(get_skill_manager),
    marketplace: ClawHubClient = Depends(get_marketplace_client),
):
    try:
        return marketplace.search_skills(query=q, manager=manager, limit=limit)
    except ClawHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/marketplace/{slug}", response_model=MarketplaceSkillDetail)
async def get_marketplace_skill_detail(
    slug: str,
    version: Optional[str] = None,
    tag: Optional[str] = None,
    manager: SkillManager = Depends(get_skill_manager),
    marketplace: ClawHubClient = Depends(get_marketplace_client),
):
    try:
        return marketplace.get_skill_detail(slug=slug, manager=manager, version=version, tag=tag)
    except ClawHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/marketplace/install", response_model=SkillPackage)
async def install_marketplace_skill(
    request: MarketplaceInstallRequest,
    manager: SkillManager = Depends(get_skill_manager),
    marketplace: ClawHubClient = Depends(get_marketplace_client),
):
    try:
        return marketplace.install_skill(
            slug=request.slug,
            manager=manager,
            version=request.version,
            tag=request.tag,
        )
    except ClawHubError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{skill_name}", response_model=Optional[SkillPackage])
async def get_skill(skill_name: str, manager: SkillManager = Depends(get_skill_manager)):
    skill = manager.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="未找到技能")
    return skill


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
    return {"success": True, "message": f"技能 {skill_name} 已禁用"}


@router.delete("/{skill_name}")
async def unload_skill(skill_name: str, manager: SkillManager = Depends(get_skill_manager)):
    if not manager.unload_skill(skill_name):
        raise HTTPException(status_code=404, detail="未找到技能")
    return {"success": True, "message": f"技能 {skill_name} 已卸载"}


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


@router.post("/upload")
async def upload_skill(
    file: UploadFile = File(...),
    manager: SkillManager = Depends(get_skill_manager),
):
    import zipfile

    temp_dir = tempfile.mkdtemp()
    try:
        zip_path = Path(temp_dir) / "skill.zip"
        with open(zip_path, "wb") as output:
            output.write(await file.read())

        extract_dir = Path(temp_dir) / "extract"
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

        skill_source = None
        for item in extract_dir.iterdir():
            if item.is_dir() and (item / "skill.json").exists():
                skill_source = item
                break

        if not skill_source and (extract_dir / "skill.json").exists():
            skill_source = extract_dir

        if not skill_source:
            raise HTTPException(status_code=400, detail="无效的技能包：缺少 skill.json")

        skill = manager.install_skill_from_directory(skill_source)
        if not skill:
            raise HTTPException(status_code=400, detail="技能安装失败")

        return {"success": True, "skill": skill}
    finally:
        try:
            shutil.rmtree(temp_dir)
        except OSError:
            pass


@router.get("/for-agent/{agent_type}")
async def get_tools_for_agent(agent_type: str, manager: SkillManager = Depends(get_skill_manager)):
    return manager.get_tools_for_agent(agent_type)
