from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from enum import Enum


class LLMMode(str, Enum):
    USER_CONFIG = "USER_CONFIG"
    BACKEND_DEFAULT = "BACKEND_DEFAULT"


class ProfileFactCreate(BaseModel):
    key: str
    value: str
    category: Optional[str] = None
    confidence: Optional[float] = None
    source: Optional[str] = None


class ProfileFactUpdate(BaseModel):
    value: str
    category: Optional[str] = None
    confidence: Optional[float] = None
    source: Optional[str] = None


class ProfileFactResponse(BaseModel):
    id: str
    key: str
    value: str
    category: Optional[str] = None
    confidence: float
    is_active: bool
    source: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class GoalCreate(BaseModel):
    description: str


class GoalResponse(BaseModel):
    id: str
    description: str
    status: str
    progress: float
    created_at: datetime
    completed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class GoalEventResponse(BaseModel):
    id: str
    event_type: str
    summary: str
    details: Optional[Dict[str, Any]] = None
    created_at: datetime


class AuditRecordResponse(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    event_type: str
    summary: str
    payload: Optional[Dict[str, Any]] = None
    created_at: datetime


class AuditInsightsResponse(BaseModel):
    event_counts: Dict[str, int] = Field(default_factory=dict)
    task_types: List[str] = Field(default_factory=list)
    strategies: List[str] = Field(default_factory=list)
    tool_names: List[str] = Field(default_factory=list)
    tool_result_names: List[str] = Field(default_factory=list)
    tool_result_statuses: List[str] = Field(default_factory=list)
    tool_result_schema_versions: List[str] = Field(default_factory=list)
    artifact_kinds: List[str] = Field(default_factory=list)
    loop_stages: List[str] = Field(default_factory=list)
    lightweight_routes: List[str] = Field(default_factory=list)
    loop_transition_targets: List[str] = Field(default_factory=list)
    planning_stages: List[str] = Field(default_factory=list)
    execution_modes: List[str] = Field(default_factory=list)
    retry_limits: List[int] = Field(default_factory=list)
    batch_sizes: List[int] = Field(default_factory=list)
    batch_counts: List[int] = Field(default_factory=list)
    parallel_slots: List[int] = Field(default_factory=list)
    parallel_forges: List[int] = Field(default_factory=list)
    agent_ids: List[str] = Field(default_factory=list)
    failed_event_types: List[str] = Field(default_factory=list)
    latest_event_at: Optional[datetime] = None


class AuditTimelineResponse(BaseModel):
    entity_type: str
    entity_id: str
    total_records: int
    insights: AuditInsightsResponse = Field(default_factory=AuditInsightsResponse)
    records: List[AuditRecordResponse] = Field(default_factory=list)


class SubtaskResponse(BaseModel):
    id: str
    description: str
    status: str
    order: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class ThinkingBlock(BaseModel):
    id: str
    title: str
    content: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_expanded: bool = False


class GoalDetailResponse(GoalResponse):
    planning_summary: Optional[str] = None
    thinking_blocks: List[ThinkingBlock] = Field(default_factory=list)
    subtasks: List[SubtaskResponse]
    events: List[GoalEventResponse] = Field(default_factory=list)
    audit_records: List[AuditRecordResponse] = Field(default_factory=list)


class GoalDebugResponse(BaseModel):
    goal: GoalDetailResponse
    audit_timeline: AuditTimelineResponse
    audit_summary: AuditInsightsResponse


class SubtaskStatusUpdate(BaseModel):
    status: str


class SkillPackageResponse(BaseModel):
    id: str
    name: str
    version: str
    description: Optional[str] = None
    author: Optional[str] = None
    is_installed: bool
    installed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class ToolDefinitionResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    input_schema: Optional[dict] = None


class SkillPackageDetailResponse(SkillPackageResponse):
    tools: List[ToolDefinitionResponse]


class LLMConfigCreate(BaseModel):
    provider: str
    api_key: str
    base_url: Optional[str] = None
    model: str


class LLMConfigResponse(BaseModel):
    id: str
    provider: str
    base_url: Optional[str] = None
    model: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class LLMModeUpdate(BaseModel):
    mode: LLMMode


class LLMModeResponse(BaseModel):
    mode: LLMMode
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ChatMessageRequest(BaseModel):
    content: str
    session_id: Optional[str] = None
    stream: bool = True


class ChatSessionCreate(BaseModel):
    title: Optional[str] = None


class ChatSessionResponse(BaseModel):
    id: str
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ToolResult(BaseModel):
    schema_version: str = "serana.tool_result.v1"
    result_type: str = "tool"
    tool_name: str
    skill: str
    tool: str
    input: Dict[str, Any]
    output: Dict[str, Any]
    status: str
    user_summary: str = ""
    artifact: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: str


class ToolCall(BaseModel):
    id: str
    name: str
    input: Dict[str, Any]
    output: Optional[Any] = None
    status: str
    timestamp: str


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    timestamp: str
    thinking_blocks: Optional[List[ThinkingBlock]] = None
    tool_calls: Optional[List[ToolCall]] = None


class ChatCompletionResponse(BaseModel):
    session_id: str
    user_message: ChatMessageResponse
    assistant_message: ChatMessageResponse
    thinking_blocks: List[ThinkingBlock] = Field(default_factory=list)
    memory_context_included: bool = False
    execution_mode: str = "direct"
    delegation_plan: Dict[str, Any] = Field(default_factory=dict)
    audit_records: List[AuditRecordResponse] = Field(default_factory=list)


class ChatDebugResponse(BaseModel):
    session: ChatSessionResponse
    messages: List[ChatMessageResponse] = Field(default_factory=list)
    audit_timeline: AuditTimelineResponse
    audit_summary: AuditInsightsResponse


class AgentStatusResponse(BaseModel):
    id: str
    name: str
    agent_type: str
    status: str
    current_task: Optional[str] = None
    session_id: Optional[str] = None


class ApprovalRequest(BaseModel):
    request_id: str
    source: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    session_id: Optional[str] = None
    tool_name: Optional[str] = None
    operation: str
    risk_level: str
    title: str
    summary: str
    reason: Optional[str] = None
    approval_options: List[str] = Field(default_factory=lambda: ["once", "deny"])
    details: Dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"
    created_at: datetime
    expires_at: Optional[datetime] = None


class ApprovalResponse(BaseModel):
    request_id: str
    approved: bool
    reviewer: str = "user"
    note: Optional[str] = None
    approval_scope: str = "once"
    resolved_at: Optional[datetime] = None


class HealthResponse(BaseModel):
    status: str
    version: str


class SearchMemoryRequest(BaseModel):
    query: str
    limit: int = 10
    days: int = 7


class UserResponse(BaseModel):
    id: str
    name: str
    created_at: datetime
    
    class Config:
        from_attributes = True
