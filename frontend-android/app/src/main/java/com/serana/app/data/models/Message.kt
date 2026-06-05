package com.serana.app.data.models

data class Message(
    val id: String,
    val content: String,
    val role: Role,
    val timestamp: String = "",
    val thinkingBlocks: List<ThinkingBlock> = emptyList(),
    val toolCalls: List<ToolTrace> = emptyList(),
    val streamStatus: StreamStatus = StreamStatus.IDLE,
)

enum class Role {
    USER,
    ASSISTANT,
}

enum class StreamStatus {
    IDLE,
    THINKING,
    STREAMING,
    WAITING_APPROVAL,
    RETRYING,
    INTERRUPTED,
    FINALIZED,
    FAILED,
}

data class ThinkingBlock(
    val id: String,
    val title: String,
    val content: String,
)

data class ToolTrace(
    val id: String,
    val name: String,
    val status: String,
    val timestamp: String,
    val input: Map<String, Any?> = emptyMap(),
    val output: Any? = null,
)
