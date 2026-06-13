
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.core.schemas import ApprovalRequest


class SkillToolInputSchema(BaseModel):
    type: str = "object"
    properties: Dict[str, Any] = Field(default_factory=dict)
    required: List[str] = Field(default_factory=list)


class SkillTool(BaseModel):
    name: str
    description: str
    input_schema: SkillToolInputSchema


class ScriptRuntimeConfig(BaseModel):
    adapter: str = "python"
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    max_input_chars: int = Field(default=32768, ge=1024, le=262144)
    max_output_chars: int = Field(default=65536, ge=1024, le=262144)
    argument_order: List[str] = Field(default_factory=list)
    output_format: str = "json"


class SkillPackageManifest(BaseModel):
    name: str
    version: str
    description: str
    author: Optional[str] = None
    format: str = "sebastian_package"
    runtime: str = "python"
    instruction_file: str = "SKILL.md"
    entrypoint: Optional[str] = "__init__.py"
    registry_slug: Optional[str] = None
    source_url: Optional[str] = None
    agent_type: str = "forge"
    max_instances: int = 3
    capabilities: List[str] = Field(default_factory=list)
    intents: List[str] = Field(default_factory=list)
    tools: List[SkillTool] = Field(default_factory=list)
    dependencies: Optional[Dict[str, Any]] = None
    permissions: Optional[List[str]] = None
    script: Optional[ScriptRuntimeConfig] = None


class SkillPackage(BaseModel):
    id: str
    name: str
    version: str
    description: str
    author: Optional[str] = None
    format: str = "sebastian_package"
    runtime: str = "python"
    agent_type: str
    max_instances: int
    is_enabled: bool = True
    is_installed: bool = True
    installed_at: Optional[datetime] = None
    origin: str = "bundled"
    can_uninstall: bool = False
    registry_slug: Optional[str] = None
    source_url: Optional[str] = None
    source_label: str = "项目内置"
    trust_state: str = "trusted"
    effective_scope: str = "forge"
    can_update: bool = False
    latest_version: Optional[str] = None
    update_available: bool = False
    run_mode_description: str = ""
    invocation_name: Optional[str] = None
    invocation_parameters: List[Dict[str, Any]] = Field(default_factory=list)
    invocation_examples: List[str] = Field(default_factory=list)
    manifest: SkillPackageManifest
    instruction_content: Optional[str] = None
    path: Optional[str] = None


class MarketplaceOwner(BaseModel):
    handle: str
    display_name: Optional[str] = Field(default=None, alias="displayName")
    image: Optional[str] = None

    model_config = {"populate_by_name": True}


class MarketplaceSkillSummary(BaseModel):
    slug: str
    display_name: str = Field(alias="displayName")
    summary: Optional[str] = None
    version: Optional[str] = None
    updated_at: Optional[int] = Field(default=None, alias="updatedAt")
    owner_handle: Optional[str] = Field(default=None, alias="ownerHandle")
    owner: Optional[MarketplaceOwner] = None
    canonical_url: Optional[str] = None
    download_url: Optional[str] = None
    installed: bool = False
    local_skill_name: Optional[str] = None

    model_config = {"populate_by_name": True}


class MarketplaceSearchResponse(BaseModel):
    results: List[MarketplaceSkillSummary] = Field(default_factory=list)


class MarketplaceSkillVersion(BaseModel):
    version: str
    created_at: Optional[int] = Field(default=None, alias="createdAt")
    changelog: Optional[str] = None

    model_config = {"populate_by_name": True}


class MarketplaceModeration(BaseModel):
    is_suspicious: Optional[bool] = Field(default=None, alias="isSuspicious")
    is_malware_blocked: Optional[bool] = Field(default=None, alias="isMalwareBlocked")
    verdict: Optional[str] = None
    summary: Optional[str] = None

    model_config = {"populate_by_name": True}


class MarketplaceSkillDetail(BaseModel):
    slug: str
    display_name: str
    summary: Optional[str] = None
    owner_handle: Optional[str] = None
    owner_display_name: Optional[str] = None
    latest_version: Optional[str] = None
    changelog: Optional[str] = None
    canonical_url: str
    download_url: str
    skill_md_preview: Optional[str] = None
    installed: bool = False
    local_skill_name: Optional[str] = None
    moderation: Optional[MarketplaceModeration] = None


class MarketplaceCatalogResponse(BaseModel):
    items: List[MarketplaceSkillSummary] = Field(default_factory=list)
    next_cursor: Optional[str] = Field(default=None, alias="nextCursor")

    model_config = {"populate_by_name": True}


class MarketplaceInstallRequest(BaseModel):
    slug: str
    version: Optional[str] = None
    tag: Optional[str] = None
    approval_request_id: Optional[str] = None


class MarketplaceInstallResponse(BaseModel):
    status: str
    skill: Optional[SkillPackage] = None
    approval_request: Optional[ApprovalRequest] = None
    message: Optional[str] = None


class SkillMutationResponse(BaseModel):
    status: str
    skill: Optional[SkillPackage] = None
    approval_request: Optional[ApprovalRequest] = None
    message: Optional[str] = None


class SkillLifecycleStatus(BaseModel):
    skill_name: str
    installed_version: str
    latest_version: Optional[str] = None
    update_available: bool = False
    can_update: bool = False
    can_uninstall: bool = False
    source_label: str
    source_url: Optional[str] = None
    trust_state: str
    effective_scope: str
    registry_slug: Optional[str] = None


class SkillUpdateRequest(BaseModel):
    version: Optional[str] = None
    tag: Optional[str] = None
    approval_request_id: Optional[str] = None


class SkillScopeUpdateRequest(BaseModel):
    agent_type: str
