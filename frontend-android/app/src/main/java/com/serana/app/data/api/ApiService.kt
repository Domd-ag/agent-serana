package com.serana.app.data.api

import com.google.gson.annotations.SerializedName
import com.serana.app.data.models.ChatSession
import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Part
import retrofit2.http.Query

interface ApiService {
    @GET("chat/sessions")
    suspend fun getChatSessions(): Response<List<ChatSession>>

    @GET("chat/sessions/{sessionId}/messages")
    suspend fun getMessages(@Path("sessionId") sessionId: String): Response<List<ChatMessageDto>>

    @DELETE("chat/sessions/{sessionId}")
    suspend fun deleteChatSession(@Path("sessionId") sessionId: String): Response<SimpleSuccessResponse>

    @DELETE("chat/sessions")
    suspend fun clearChatSessions(): Response<ClearSessionsResponse>

    @GET("chat/sessions/{sessionId}/debug")
    suspend fun getChatDebug(@Path("sessionId") sessionId: String): Response<ChatDebugResponseDto>

    @POST("chat/message")
    suspend fun sendMessage(@Body request: SendMessageRequest): Response<ChatCompletionResponseDto>

    @POST("approvals/{requestId}")
    suspend fun submitApprovalDecision(
        @Path("requestId") requestId: String,
        @Body request: ApprovalDecisionRequest,
    ): Response<ApprovalResponseDto>

    @GET("llm/config")
    suspend fun getLlmConfig(): Response<LlmConfigDto?>

    @POST("llm/config")
    suspend fun saveLlmConfig(@Body request: LlmConfigCreateRequest): Response<LlmConfigDto>

    @DELETE("llm/config")
    suspend fun deleteLlmConfig(): Response<SimpleStatusResponse>

    @GET("llm/mode")
    suspend fun getLlmMode(): Response<LlmModeResponseDto>

    @POST("llm/mode")
    suspend fun updateLlmMode(@Body request: LlmModeUpdateRequest): Response<LlmModeResponseDto>

    @GET("skills")
    suspend fun getSkills(): Response<List<SkillPackageDto>>

    @GET("skills/{skillName}/tools")
    suspend fun getSkillTools(@Path("skillName") skillName: String): Response<List<SkillToolDto>>

    @GET("skills/{skillName}/lifecycle")
    suspend fun getSkillLifecycle(@Path("skillName") skillName: String): Response<SkillLifecycleStatusDto>

    @POST("skills/{skillName}/scope")
    suspend fun updateSkillScope(
        @Path("skillName") skillName: String,
        @Body request: SkillScopeUpdateRequest,
    ): Response<SkillMutationResponseDto>

    @POST("skills/{skillName}/update")
    suspend fun updateSkill(
        @Path("skillName") skillName: String,
        @Body request: SkillUpdateRequest,
    ): Response<SkillMutationResponseDto>

    @GET("skills/marketplace")
    suspend fun getMarketplaceSkills(
        @Query("limit") limit: Int = 20,
        @Query("cursor") cursor: String? = null,
        @Query("sort") sort: String = "updated_at",
    ): Response<MarketplaceCatalogResponseDto>

    @GET("skills/marketplace/search")
    suspend fun searchMarketplaceSkills(
        @Query("q") query: String,
        @Query("limit") limit: Int = 20,
    ): Response<MarketplaceSearchResponseDto>

    @POST("skills/marketplace/install")
    suspend fun installMarketplaceSkill(
        @Body request: MarketplaceInstallRequest,
    ): Response<MarketplaceInstallResponseDto>

    @Multipart
    @POST("skills/upload")
    suspend fun uploadSkill(
        @Part file: MultipartBody.Part? = null,
        @Part("approval_request_id") approvalRequestId: RequestBody? = null,
    ): Response<SkillMutationResponseDto>

    @POST("skills/{skillName}/enable")
    suspend fun enableSkill(@Path("skillName") skillName: String): Response<SimpleStatusResponse>

    @POST("skills/{skillName}/disable")
    suspend fun disableSkill(@Path("skillName") skillName: String): Response<SimpleStatusResponse>

    @DELETE("skills/{skillName}")
    suspend fun deleteSkill(
        @Path("skillName") skillName: String,
        @Query("approval_request_id") approvalRequestId: String? = null,
    ): Response<SkillMutationResponseDto>
}

data class SendMessageRequest(
    val content: String,
    @SerializedName("session_id")
    val sessionId: String? = null,
    val stream: Boolean = false,
)

data class ChatCompletionResponseDto(
    @SerializedName("session_id")
    val sessionId: String,
    @SerializedName("user_message")
    val userMessage: ChatMessageDto,
    @SerializedName("assistant_message")
    val assistantMessage: ChatMessageDto,
    @SerializedName("thinking_blocks")
    val thinkingBlocks: List<ThinkingBlockDto> = emptyList(),
    @SerializedName("memory_context_included")
    val memoryContextIncluded: Boolean,
    @SerializedName("execution_mode")
    val executionMode: String = "direct",
    @SerializedName("delegation_plan")
    val delegationPlan: Map<String, Any?> = emptyMap(),
    @SerializedName("audit_records")
    val auditRecords: List<AuditRecordDto> = emptyList(),
)

data class ChatDebugResponseDto(
    val session: ChatSession,
    val messages: List<ChatMessageDto> = emptyList(),
    @SerializedName("audit_timeline")
    val auditTimeline: AuditTimelineDto,
    @SerializedName("audit_summary")
    val auditSummary: AuditInsightsDto,
)

data class ChatMessageDto(
    val id: String,
    val role: String,
    val content: String,
    val timestamp: String,
    @SerializedName("thinking_blocks")
    val thinkingBlocks: List<ThinkingBlockDto>? = null,
    @SerializedName("tool_calls")
    val toolCalls: List<ToolCallDto>? = null,
)

data class ThinkingBlockDto(
    val id: String,
    val title: String,
    val content: String,
    val timestamp: String = "",
    @SerializedName("is_expanded")
    val isExpanded: Boolean = false,
)

data class ToolCallDto(
    val id: String,
    val name: String,
    val input: Map<String, Any?> = emptyMap(),
    val output: Any? = null,
    val status: String,
    val timestamp: String,
)

data class ApprovalRequestDto(
    @SerializedName("request_id")
    val requestId: String,
    @SerializedName("session_id")
    val sessionId: String? = null,
    @SerializedName("tool_name")
    val toolName: String? = null,
    val operation: String,
    @SerializedName("risk_level")
    val riskLevel: String,
    val title: String,
    val summary: String,
    val reason: String? = null,
    @SerializedName("approval_options")
    val approvalOptions: List<String> = emptyList(),
    val details: Map<String, Any?> = emptyMap(),
    val status: String,
    @SerializedName("created_at")
    val createdAt: String,
    @SerializedName("expires_at")
    val expiresAt: String? = null,
)

data class ApprovalDecisionRequest(
    @SerializedName("request_id")
    val requestId: String,
    val approved: Boolean,
    val reviewer: String = "user",
    val note: String? = null,
    @SerializedName("approval_scope")
    val approvalScope: String = "once",
)

data class ApprovalResponseDto(
    @SerializedName("request_id")
    val requestId: String,
    val approved: Boolean,
    val reviewer: String,
    val note: String? = null,
    @SerializedName("approval_scope")
    val approvalScope: String = "once",
    @SerializedName("resolved_at")
    val resolvedAt: String? = null,
)

data class AuditRecordDto(
    val id: String,
    @SerializedName("entity_type")
    val entityType: String,
    @SerializedName("entity_id")
    val entityId: String,
    @SerializedName("event_type")
    val eventType: String,
    val summary: String,
    val payload: Map<String, Any?>? = null,
    @SerializedName("created_at")
    val createdAt: String,
)

data class AuditInsightsDto(
    @SerializedName("event_counts")
    val eventCounts: Map<String, Int> = emptyMap(),
    @SerializedName("task_types")
    val taskTypes: List<String> = emptyList(),
    val strategies: List<String> = emptyList(),
    @SerializedName("tool_names")
    val toolNames: List<String> = emptyList(),
    @SerializedName("tool_result_names")
    val toolResultNames: List<String> = emptyList(),
    @SerializedName("tool_result_statuses")
    val toolResultStatuses: List<String> = emptyList(),
    @SerializedName("tool_result_schema_versions")
    val toolResultSchemaVersions: List<String> = emptyList(),
    @SerializedName("artifact_kinds")
    val artifactKinds: List<String> = emptyList(),
    @SerializedName("execution_modes")
    val executionModes: List<String> = emptyList(),
    @SerializedName("retry_limits")
    val retryLimits: List<Int> = emptyList(),
    @SerializedName("batch_sizes")
    val batchSizes: List<Int> = emptyList(),
    @SerializedName("batch_counts")
    val batchCounts: List<Int> = emptyList(),
    @SerializedName("parallel_slots")
    val parallelSlots: List<Int> = emptyList(),
    @SerializedName("parallel_forges")
    val parallelForges: List<Int> = emptyList(),
    @SerializedName("planning_stages")
    val planningStages: List<String> = emptyList(),
    @SerializedName("agent_ids")
    val agentIds: List<String> = emptyList(),
    @SerializedName("failed_event_types")
    val failedEventTypes: List<String> = emptyList(),
    @SerializedName("latest_event_at")
    val latestEventAt: String? = null,
)

data class AuditTimelineDto(
    @SerializedName("entity_type")
    val entityType: String,
    @SerializedName("entity_id")
    val entityId: String,
    @SerializedName("total_records")
    val totalRecords: Int,
    val insights: AuditInsightsDto,
    val records: List<AuditRecordDto> = emptyList(),
)

data class LlmConfigCreateRequest(
    val provider: String,
    @SerializedName("api_key")
    val apiKey: String,
    @SerializedName("base_url")
    val baseUrl: String? = null,
    val model: String,
)

data class LlmConfigDto(
    val id: String,
    val provider: String,
    @SerializedName("base_url")
    val baseUrl: String? = null,
    val model: String,
    @SerializedName("created_at")
    val createdAt: String,
    @SerializedName("updated_at")
    val updatedAt: String,
)

data class LlmModeUpdateRequest(
    val mode: String,
)

data class LlmModeResponseDto(
    val mode: String,
    @SerializedName("updated_at")
    val updatedAt: String,
)

data class SkillPackageDto(
    val id: String,
    val name: String,
    val version: String,
    val description: String? = null,
    val author: String? = null,
    @SerializedName("agent_type")
    val agentType: String,
    @SerializedName("max_instances")
    val maxInstances: Int,
    @SerializedName("is_enabled")
    val isEnabled: Boolean,
    @SerializedName("is_installed")
    val isInstalled: Boolean,
    @SerializedName("installed_at")
    val installedAt: String? = null,
    val origin: String = "bundled",
    @SerializedName("can_uninstall")
    val canUninstall: Boolean = false,
    @SerializedName("registry_slug")
    val registrySlug: String? = null,
    @SerializedName("source_url")
    val sourceUrl: String? = null,
    @SerializedName("source_label")
    val sourceLabel: String = "项目内置",
    @SerializedName("trust_state")
    val trustState: String = "trusted",
    @SerializedName("effective_scope")
    val effectiveScope: String = "forge",
    @SerializedName("can_update")
    val canUpdate: Boolean = false,
    @SerializedName("latest_version")
    val latestVersion: String? = null,
    @SerializedName("update_available")
    val updateAvailable: Boolean = false,
)

data class SkillLifecycleStatusDto(
    @SerializedName("skill_name")
    val skillName: String,
    @SerializedName("installed_version")
    val installedVersion: String,
    @SerializedName("latest_version")
    val latestVersion: String? = null,
    @SerializedName("update_available")
    val updateAvailable: Boolean = false,
    @SerializedName("can_update")
    val canUpdate: Boolean = false,
    @SerializedName("can_uninstall")
    val canUninstall: Boolean = false,
    @SerializedName("source_label")
    val sourceLabel: String,
    @SerializedName("source_url")
    val sourceUrl: String? = null,
    @SerializedName("trust_state")
    val trustState: String,
    @SerializedName("effective_scope")
    val effectiveScope: String,
    @SerializedName("registry_slug")
    val registrySlug: String? = null,
)

data class SkillScopeUpdateRequest(
    @SerializedName("agent_type")
    val agentType: String,
)

data class SkillUpdateRequest(
    val version: String? = null,
    val tag: String? = null,
    @SerializedName("approval_request_id")
    val approvalRequestId: String? = null,
)

data class SkillMutationResponseDto(
    val status: String,
    val skill: SkillPackageDto? = null,
    @SerializedName("approval_request")
    val approvalRequest: ApprovalRequestDto? = null,
    val message: String? = null,
)

data class MarketplaceInstallRequest(
    val slug: String,
    val version: String? = null,
    val tag: String? = null,
    @SerializedName("approval_request_id")
    val approvalRequestId: String? = null,
)

data class MarketplaceInstallResponseDto(
    val status: String,
    val skill: SkillPackageDto? = null,
    @SerializedName("approval_request")
    val approvalRequest: ApprovalRequestDto? = null,
    val message: String? = null,
)

data class MarketplaceSkillDto(
    val slug: String,
    @SerializedName("display_name")
    val displayName: String? = null,
    val summary: String? = null,
    val version: String? = null,
    @SerializedName("owner_handle")
    val ownerHandle: String? = null,
    @SerializedName("canonical_url")
    val canonicalUrl: String? = null,
    val installed: Boolean = false,
    @SerializedName("local_skill_name")
    val localSkillName: String? = null,
)

data class MarketplaceCatalogResponseDto(
    val items: List<MarketplaceSkillDto> = emptyList(),
    @SerializedName("next_cursor")
    val nextCursor: String? = null,
)

data class MarketplaceSearchResponseDto(
    val results: List<MarketplaceSkillDto> = emptyList(),
)

data class SkillToolDto(
    val name: String,
    val description: String? = null,
    @SerializedName("input_schema")
    val inputSchema: Map<String, Any?>? = null,
)

data class SimpleStatusResponse(
    val status: String? = null,
    val message: String? = null,
    val success: Boolean? = null,
)

data class SimpleSuccessResponse(
    val success: Boolean,
)

data class ClearSessionsResponse(
    val success: Boolean,
    @SerializedName("deleted_count")
    val deletedCount: Int = 0,
)
