package com.serana.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.serana.app.data.api.ApprovalDecisionRequest
import com.serana.app.data.api.ApprovalRequestDto
import com.serana.app.data.api.ApprovalResponseDto
import com.serana.app.data.api.AuditInsightsDto
import com.serana.app.data.api.ChatStreamEvent
import com.serana.app.data.api.ChatCompletionResponseDto
import com.serana.app.data.api.ChatDebugResponseDto
import com.serana.app.data.api.ChatMessageDto
import com.serana.app.data.api.RetrofitClient
import com.serana.app.data.api.SendMessageRequest
import com.serana.app.data.api.ThinkingBlockDto
import com.serana.app.data.api.ToolCallDto
import com.serana.app.data.models.Message
import com.serana.app.data.models.ApprovalRequest
import com.serana.app.data.models.Role
import com.serana.app.data.models.StreamStatus
import com.serana.app.data.models.ThinkingBlock
import com.serana.app.data.models.ToolTrace
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.Call
import java.util.UUID

data class ChatDebugTimelineEntry(
    val id: String,
    val eventType: String,
    val summary: String,
    val createdAt: String,
    val highlights: List<String> = emptyList(),
    val isFailure: Boolean = false,
)

data class ChatDebugSummary(
    val executionMode: String = "direct",
    val taskTypes: List<String> = emptyList(),
    val strategies: List<String> = emptyList(),
    val toolNames: List<String> = emptyList(),
    val parallelForges: List<Int> = emptyList(),
    val eventCounts: Map<String, Int> = emptyMap(),
    val agentIds: List<String> = emptyList(),
    val failedEventTypes: List<String> = emptyList(),
    val latestEventAt: String? = null,
    val totalRecords: Int = 0,
    val recentTimeline: List<ChatDebugTimelineEntry> = emptyList(),
)

class ChatViewModel : ViewModel() {
    private val _messages = MutableStateFlow(
        listOf(
            Message(
                id = "welcome",
                content = "新的对话已准备好，随时告诉 Serana 你想做什么。",
                role = Role.ASSISTANT,
            ),
        ),
    )
    val messages: StateFlow<List<Message>> = _messages.asStateFlow()

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    private val _sessions = MutableStateFlow<List<com.serana.app.data.models.ChatSession>>(emptyList())
    val sessions: StateFlow<List<com.serana.app.data.models.ChatSession>> = _sessions.asStateFlow()

    private val _executionMode = MutableStateFlow("direct")
    val executionMode: StateFlow<String> = _executionMode.asStateFlow()

    private val _debugSummary = MutableStateFlow(ChatDebugSummary())
    val debugSummary: StateFlow<ChatDebugSummary> = _debugSummary.asStateFlow()

    private val _deletingSessionIds = MutableStateFlow<Set<String>>(emptySet())
    val deletingSessionIds: StateFlow<Set<String>> = _deletingSessionIds.asStateFlow()

    private val _isClearingSessions = MutableStateFlow(false)
    val isClearingSessions: StateFlow<Boolean> = _isClearingSessions.asStateFlow()

    private val _pendingApproval = MutableStateFlow<ApprovalRequest?>(null)
    val pendingApproval: StateFlow<ApprovalRequest?> = _pendingApproval.asStateFlow()

    private val _isSubmittingApproval = MutableStateFlow(false)
    val isSubmittingApproval: StateFlow<Boolean> = _isSubmittingApproval.asStateFlow()

    private var currentSessionId: String? = null
    private val messageUpdateMutex = Mutex()
    private var activeStreamJob: Job? = null
    private var activeStreamCall: Call? = null
    private var activeAssistantMessageId: String? = null
    private val interruptedMessageIds = mutableSetOf<String>()

    private val _currentSessionId = MutableStateFlow<String?>(null)
    val activeSessionId: StateFlow<String?> = _currentSessionId.asStateFlow()

    init {
        refreshSessions()
    }

    fun refreshSessions() {
        viewModelScope.launch {
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.getChatSessions()
                }
                val payload = response.body().orEmpty()
                if (response.isSuccessful) {
                    _sessions.value = payload
                    if (currentSessionId == null && payload.isNotEmpty()) {
                        loadSession(payload.first().id)
                    }
                }
            } catch (_: Exception) {
                // Keep the shell resilient on first launch.
            }
        }
    }

    fun loadSession(sessionId: String) {
        _isLoading.value = true
        _error.value = null
        _pendingApproval.value = null
        viewModelScope.launch {
            try {
                val messagesResponse = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.getMessages(sessionId)
                }
                val debugResponse = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.getChatDebug(sessionId)
                }
                if (!messagesResponse.isSuccessful || messagesResponse.body() == null) {
                    throw IllegalStateException("加载聊天记录失败")
                }
                currentSessionId = sessionId
                _currentSessionId.value = sessionId
                _messages.value = messagesResponse.body().orEmpty().map(::mapChatMessage)
                if (debugResponse.isSuccessful && debugResponse.body() != null) {
                    applyDebugResponse(debugResponse.body()!!, keepMessages = true)
                }
            } catch (e: Exception) {
                _error.value = e.message ?: "加载会话失败"
            } finally {
                _isLoading.value = false
            }
        }
    }

    fun startNewChat() {
        currentSessionId = null
        _currentSessionId.value = null
        _executionMode.value = "direct"
        _debugSummary.value = ChatDebugSummary()
        _error.value = null
        _pendingApproval.value = null
        _messages.value = newChatMessages()
    }

    fun sendMessage(content: String) {
        val trimmed = content.trim()
        if (trimmed.isEmpty()) return

        _error.value = null
        val assistantMessageId = "streaming-${UUID.randomUUID()}"
        _messages.value = _messages.value + Message(
            id = UUID.randomUUID().toString(),
            content = trimmed,
            role = Role.USER,
        ) + Message(
            id = assistantMessageId,
            content = "",
            role = Role.ASSISTANT,
            streamStatus = StreamStatus.THINKING,
        )
        performAssistantRequest(
            content = trimmed,
            assistantMessageId = assistantMessageId,
        )
    }

    fun retryAssistantMessage(content: String, assistantMessageId: String) {
        val trimmed = content.trim()
        if (trimmed.isEmpty()) return

        _error.value = null
        _messages.value = _messages.value.map { message ->
            if (message.id == assistantMessageId) {
                message.copy(
                    content = "",
                    thinkingBlocks = emptyList(),
                    toolCalls = emptyList(),
                    streamStatus = StreamStatus.RETRYING,
                )
            } else {
                message
            }
        }
        performAssistantRequest(
            content = trimmed,
            assistantMessageId = assistantMessageId,
        )
    }

    private fun performAssistantRequest(
        content: String,
        assistantMessageId: String,
    ) {
        activeStreamJob?.cancel()
        activeStreamCall?.cancel()
        activeAssistantMessageId = assistantMessageId
        _isLoading.value = true
        activeStreamJob = viewModelScope.launch {
            var completedSessionId: String? = null
            try {
                withContext(Dispatchers.IO) {
                    RetrofitClient.streamChatMessage(
                        SendMessageRequest(
                            content = content,
                            sessionId = currentSessionId,
                            stream = true,
                        ),
                        onCallReady = { call ->
                            activeStreamCall = call
                        },
                    ) { event ->
                        when (event) {
                            is ChatStreamEvent.ThinkingBlock -> appendThinkingBlock(assistantMessageId, event.block)
                            is ChatStreamEvent.Thinking -> handleThinkingHeartbeat(assistantMessageId)
                            is ChatStreamEvent.Content -> appendAssistantContent(assistantMessageId, event.chunk)
                            is ChatStreamEvent.ApprovalRequested -> showApprovalRequest(assistantMessageId, event.request)
                            is ChatStreamEvent.ApprovalResolved -> handleApprovalResolved(assistantMessageId, event.response)
                            is ChatStreamEvent.ToolCall -> appendToolCall(assistantMessageId, event.toolCall)
                            is ChatStreamEvent.Error -> handleStreamError(assistantMessageId, event.message)
                            is ChatStreamEvent.Done -> {
                                currentSessionId = event.sessionId.ifBlank { currentSessionId }
                                _currentSessionId.value = currentSessionId
                                _isLoading.value = false
                                _pendingApproval.value = null
                                applyStreamDone(assistantMessageId, event)
                            }
                        }
                    }
                }
                completedSessionId = currentSessionId
            } catch (e: Exception) {
                if (assistantMessageId in interruptedMessageIds || e is CancellationException) {
                    return@launch
                }
                fallbackToNonStreaming(
                    content = content,
                    assistantMessageId = assistantMessageId,
                    error = e,
                )
            } finally {
                if (activeAssistantMessageId == assistantMessageId) {
                    activeAssistantMessageId = null
                    activeStreamCall = null
                    activeStreamJob = null
                }
                interruptedMessageIds.remove(assistantMessageId)
                _isLoading.value = false
            }

            completedSessionId?.let { sessionId ->
                val expectedAssistantContent = _messages.value
                    .firstOrNull { it.id == assistantMessageId }
                    ?.content
                    .orEmpty()
                viewModelScope.launch {
                    try {
                        delay(500)
                        hydrateAssistantFromDebug(sessionId, assistantMessageId, expectedAssistantContent)
                    } finally {
                        refreshSessions()
                    }
                }
            }
        }
    }

    fun interruptStreaming() {
        val messageId = activeAssistantMessageId ?: _messages.value.lastOrNull {
            it.role == Role.ASSISTANT && it.streamStatus in setOf(
                StreamStatus.THINKING,
                StreamStatus.STREAMING,
                StreamStatus.RETRYING,
                StreamStatus.WAITING_APPROVAL,
            )
        }?.id ?: return

        interruptedMessageIds += messageId
        _pendingApproval.value = null
        _isLoading.value = false
        activeStreamCall?.cancel()
        activeStreamJob?.cancel(CancellationException("User interrupted streaming response"))
        markAssistantInterrupted(messageId)
    }

    fun clearError() {
        _error.value = null
    }

    fun respondToApproval(
        requestId: String,
        approved: Boolean,
        approvalScope: String = "once",
    ) {
        if (_isSubmittingApproval.value) return

        viewModelScope.launch {
            _isSubmittingApproval.value = true
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.submitApprovalDecision(
                        requestId = requestId,
                        request = ApprovalDecisionRequest(
                            requestId = requestId,
                            approved = approved,
                            approvalScope = approvalScope,
                        ),
                    )
                }
                if (!response.isSuccessful || response.body() == null) {
                    throw IllegalStateException("审批提交失败")
                }
                _pendingApproval.value = null
            } catch (e: Exception) {
                _error.value = e.message ?: "审批提交失败"
            } finally {
                _isSubmittingApproval.value = false
            }
        }
    }

    fun deleteSession(sessionId: String) {
        if (_deletingSessionIds.value.contains(sessionId)) return

        viewModelScope.launch {
            _deletingSessionIds.value = _deletingSessionIds.value + sessionId
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.deleteChatSession(sessionId)
                }
                if (!response.isSuccessful || response.body()?.success != true) {
                    throw IllegalStateException("删除会话失败")
                }

                val wasCurrent = currentSessionId == sessionId
                val remainingSessions = _sessions.value.filterNot { it.id == sessionId }
                _sessions.value = remainingSessions

                if (wasCurrent) {
                    if (remainingSessions.isNotEmpty()) {
                        loadSession(remainingSessions.first().id)
                    } else {
                        startNewChat()
                    }
                }
            } catch (e: Exception) {
                _error.value = e.message ?: "删除会话失败"
            } finally {
                _deletingSessionIds.value = _deletingSessionIds.value - sessionId
            }
        }
    }

    fun clearAllSessions() {
        if (_isClearingSessions.value) return

        viewModelScope.launch {
            _isClearingSessions.value = true
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.clearChatSessions()
                }
                if (!response.isSuccessful || response.body()?.success != true) {
                    throw IllegalStateException("清空会话失败")
                }
                _sessions.value = emptyList()
                startNewChat()
            } catch (e: Exception) {
                _error.value = e.message ?: "清空会话失败"
            } finally {
                _isClearingSessions.value = false
            }
        }
    }

    private suspend fun fallbackToNonStreaming(
        content: String,
        assistantMessageId: String,
        error: Exception,
    ) {
        try {
            val response = withContext(Dispatchers.IO) {
                RetrofitClient.apiService.sendMessage(
                    SendMessageRequest(
                        content = content,
                        sessionId = currentSessionId,
                        stream = false,
                    ),
                )
            }
            val payload = response.body()
            if (!response.isSuccessful || payload == null) {
                throw IllegalStateException("聊天请求失败：${response.code()}")
            }
            currentSessionId = payload.sessionId
            _currentSessionId.value = payload.sessionId
            replaceAssistantMessage(assistantMessageId, mapChatMessage(payload.assistantMessage))
            _executionMode.value = payload.executionMode
            _debugSummary.value = buildDebugSummary(
                executionMode = payload.executionMode,
                insights = null,
                completion = payload,
            )
            refreshSessions()
        } catch (fallbackError: Exception) {
            _error.value = fallbackError.message ?: error.message ?: "未知错误"
            replaceAssistantMessage(
                assistantMessageId,
                Message(
                    id = assistantMessageId,
                    content = "流式响应中断，备用请求也失败了。请稍后再试。",
                    role = Role.ASSISTANT,
                    streamStatus = StreamStatus.FAILED,
                ),
            )
        }
    }

    private fun applyDebugResponse(debug: ChatDebugResponseDto, keepMessages: Boolean) {
        if (!keepMessages) {
            _messages.value = debug.messages.map(::mapChatMessage)
        }
        _executionMode.value = debug.auditSummary.executionModes.firstOrNull() ?: "direct"
        _debugSummary.value = buildDebugSummary(
            executionMode = _executionMode.value,
            insights = debug.auditSummary,
            completion = null,
            totalRecords = debug.auditTimeline.totalRecords,
            timelineEntries = debug.auditTimeline.records.map(::mapAuditRecord).takeLast(6).reversed(),
        )
    }

    private fun buildDebugSummary(
        executionMode: String,
        insights: AuditInsightsDto?,
        completion: ChatCompletionResponseDto?,
        totalRecords: Int = 0,
        timelineEntries: List<ChatDebugTimelineEntry> = emptyList(),
    ): ChatDebugSummary {
        val toolNames = insights?.toolNames ?: completion?.auditRecords?.map { it.eventType }.orEmpty()
        val recentTimeline = if (timelineEntries.isNotEmpty()) {
            timelineEntries
        } else {
            completion?.auditRecords
                ?.map(::mapAuditRecord)
                ?.takeLast(5)
                ?.reversed()
                .orEmpty()
        }
        return ChatDebugSummary(
            executionMode = executionMode,
            taskTypes = insights?.taskTypes.orEmpty(),
            strategies = insights?.strategies.orEmpty(),
            toolNames = toolNames,
            parallelForges = insights?.parallelForges.orEmpty(),
            eventCounts = insights?.eventCounts.orEmpty(),
            agentIds = insights?.agentIds.orEmpty(),
            failedEventTypes = insights?.failedEventTypes.orEmpty(),
            latestEventAt = insights?.latestEventAt,
            totalRecords = totalRecords.takeIf { it > 0 } ?: recentTimeline.size,
            recentTimeline = recentTimeline,
        )
    }

    private fun appendAssistantContent(messageId: String, chunk: String) {
        if (chunk.isEmpty()) return
        viewModelScope.launch {
            messageUpdateMutex.withLock {
                _messages.value = _messages.value.map { message ->
                    if (message.id == messageId) {
                        message.copy(content = message.content + chunk)
                            .withStreamStatus(StreamStatus.STREAMING)
                    } else {
                        message
                    }
                }
            }
        }
    }

    private fun handleThinkingHeartbeat(messageId: String) {
        updateStreamStatus(messageId, StreamStatus.THINKING)
    }

    private fun appendThinkingBlock(messageId: String, block: ThinkingBlockDto) {
        viewModelScope.launch {
            messageUpdateMutex.withLock {
                _messages.value = _messages.value.map { message ->
                    if (message.id == messageId) {
                        message.copy(
                            thinkingBlocks = message.thinkingBlocks + mapThinkingBlock(block),
                        ).withStreamStatus(StreamStatus.THINKING)
                    } else {
                        message
                    }
                }
            }
        }
    }

    private fun appendToolCall(messageId: String, toolCall: ToolCallDto) {
        viewModelScope.launch {
            messageUpdateMutex.withLock {
                val trace = mapToolCall(toolCall)
                _messages.value = _messages.value.map { message ->
                    if (message.id == messageId && message.toolCalls.none { it.id == trace.id }) {
                        message.copy(
                            toolCalls = message.toolCalls + trace,
                        ).withStreamStatus(StreamStatus.THINKING)
                    } else {
                        message
                    }
                }
            }
        }
    }

    private fun showApprovalRequest(messageId: String, request: ApprovalRequestDto) {
        _pendingApproval.value = mapApprovalRequest(request)
        updateStreamStatus(messageId, StreamStatus.WAITING_APPROVAL)
    }

    private fun handleApprovalResolved(messageId: String, response: ApprovalResponseDto) {
        val current = _pendingApproval.value
        if (current?.requestId == response.requestId) {
            _pendingApproval.value = null
        }
        updateStreamStatus(messageId, StreamStatus.THINKING)
    }

    private fun handleStreamError(messageId: String, message: String) {
        val displayMessage = message.ifBlank { "后端流式响应中断，请稍后重试。" }
        _error.value = displayMessage
        _isLoading.value = false
        replaceAssistantMessage(
            messageId,
            Message(
                id = messageId,
                content = displayMessage,
                role = Role.ASSISTANT,
                streamStatus = StreamStatus.FAILED,
            ),
        )
    }

    private fun applyStreamDone(messageId: String, event: ChatStreamEvent.Done) {
        val streamedThinkingBlocks = event.thinkingBlocks.map(::mapThinkingBlock)
        val streamedToolCalls = event.toolCalls.map(::mapToolCall)
        _messages.value = _messages.value.map { message ->
            if (message.id != messageId) {
                message
            } else {
                val knownThinkingBlockIds = message.thinkingBlocks.map { it.id }.toSet()
                val knownToolCallIds = message.toolCalls.map { it.id }.toSet()
                message.copy(
                    thinkingBlocks = message.thinkingBlocks +
                        streamedThinkingBlocks.filterNot { it.id in knownThinkingBlockIds },
                    toolCalls = message.toolCalls +
                        streamedToolCalls.filterNot { it.id in knownToolCallIds },
                    streamStatus = StreamStatus.FINALIZED,
                )
            }
        }
    }

    private suspend fun hydrateAssistantFromDebug(
        sessionId: String,
        messageId: String,
        expectedContent: String,
    ) {
        val debugResponse = withContext(Dispatchers.IO) {
            RetrofitClient.apiService.getChatDebug(sessionId)
        }
        val debug = debugResponse.body()
        if (!debugResponse.isSuccessful || debug == null) {
            return
        }
        val latestAssistant = debug.messages.lastOrNull { it.role.equals("assistant", ignoreCase = true) }
        if (latestAssistant != null && latestAssistant.content == expectedContent) {
            replaceAssistantMessage(messageId, mapChatMessage(latestAssistant))
            updateStreamStatus(messageId, StreamStatus.FINALIZED)
        }
        applyDebugResponse(debug, keepMessages = true)
    }

    private fun replaceAssistantMessage(messageId: String, replacement: Message) {
        _messages.value = _messages.value.map { message ->
            if (message.id == messageId) replacement else message
        }
    }

    private fun markAssistantInterrupted(messageId: String) {
        _messages.value = _messages.value.map { message ->
            if (message.id == messageId) {
                val content = message.content.ifBlank { "已打断。" }
                message.copy(
                    content = content,
                    streamStatus = StreamStatus.INTERRUPTED,
                )
            } else {
                message
            }
        }
    }

    private fun updateStreamStatus(messageId: String, status: StreamStatus) {
        _messages.value = _messages.value.map { message ->
            if (message.id == messageId) {
                message.copy(streamStatus = status)
            } else {
                message
            }
        }
    }
}

private fun newChatMessages(): List<Message> {
    return listOf(
        Message(
            id = "welcome-${UUID.randomUUID()}",
            content = "新的对话已准备好，随时告诉 Serana 你想做什么。",
            role = Role.ASSISTANT,
        ),
    )
}

private fun mapChatMessage(dto: ChatMessageDto): Message {
    return Message(
        id = dto.id,
        content = dto.content,
        role = if (dto.role.equals("user", ignoreCase = true)) Role.USER else Role.ASSISTANT,
        timestamp = dto.timestamp,
        thinkingBlocks = dto.thinkingBlocks.orEmpty().map(::mapThinkingBlock),
        toolCalls = dto.toolCalls.orEmpty().map(::mapToolCall),
        streamStatus = StreamStatus.FINALIZED,
    )
}

private fun mapThinkingBlock(dto: ThinkingBlockDto): ThinkingBlock {
    return ThinkingBlock(
        id = dto.id,
        title = dto.title,
        content = dto.content,
    )
}

private fun Message.withStreamStatus(status: StreamStatus): Message {
    return copy(streamStatus = status)
}

private fun mapApprovalRequest(dto: ApprovalRequestDto): ApprovalRequest {
    return ApprovalRequest(
        requestId = dto.requestId,
        sessionId = dto.sessionId,
        toolName = dto.toolName,
        operation = dto.operation,
        riskLevel = dto.riskLevel,
        title = dto.title,
        summary = dto.summary,
        reason = dto.reason,
        approvalOptions = dto.approvalOptions,
        details = dto.details,
        status = dto.status,
        createdAt = dto.createdAt,
        expiresAt = dto.expiresAt,
    )
}

private fun mapToolCall(dto: ToolCallDto): ToolTrace {
    return ToolTrace(
        id = dto.id,
        name = dto.name,
        status = dto.status,
        timestamp = dto.timestamp,
        input = dto.input,
        output = dto.output,
    )
}

private fun mapAuditRecord(dto: com.serana.app.data.api.AuditRecordDto): ChatDebugTimelineEntry {
    return ChatDebugTimelineEntry(
        id = dto.id,
        eventType = dto.eventType,
        summary = dto.summary,
        createdAt = dto.createdAt,
        highlights = extractAuditHighlights(dto.payload),
        isFailure = dto.eventType.contains("fail", ignoreCase = true) ||
            ((dto.payload?.get("status") as? String)?.contains("fail", ignoreCase = true) == true),
    )
}

private fun extractAuditHighlights(payload: Map<String, Any?>?): List<String> {
    if (payload.isNullOrEmpty()) return emptyList()

    val entries = linkedMapOf<String, Any?>()

    fun capture(source: Map<String, Any?>?) {
        if (source == null) return
        listOf(
            "task_type",
            "strategy",
            "tool_name",
            "agent_id",
            "execution_mode",
            "status",
            "retry_limit",
            "batch_size",
            "batch_count",
            "parallel_forges",
            "parallel_slots",
        ).forEach { key ->
            if (source.containsKey(key) && entries[key] == null) {
                entries[key] = source[key]
            }
        }
    }

    capture(payload)
    capture(anyToStringMap(payload["input"]))
    capture(anyToStringMap(payload["output"]))

    return entries.entries.mapNotNull { (key, value) ->
        val normalized = when (value) {
            null -> return@mapNotNull null
            is Collection<*> -> value.joinToString()
            is Array<*> -> value.joinToString()
            else -> value.toString()
        }.takeIf { it.isNotBlank() } ?: return@mapNotNull null

        "${key.replace('_', ' ')}: $normalized"
    }
}

private fun anyToStringMap(value: Any?): Map<String, Any?>? {
    val raw = value as? Map<*, *> ?: return null
    return raw.entries
        .mapNotNull { (key, entryValue) ->
            (key as? String)?.let { it to entryValue }
        }
        .toMap()
}
