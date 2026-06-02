package com.serana.app.data.api

import com.google.gson.Gson
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

object RetrofitClient {
    private const val BASE_URL = "http://192.168.31.30:8000/api/v1/"
    private val gson = Gson()

    private val loggingInterceptor = HttpLoggingInterceptor().apply {
        level = HttpLoggingInterceptor.Level.BASIC
    }

    private val client = OkHttpClient.Builder()
        .addInterceptor(loggingInterceptor)
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val streamingClient = client.newBuilder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    private val retrofit = Retrofit.Builder()
        .baseUrl(BASE_URL)
        .client(client)
        .addConverterFactory(GsonConverterFactory.create())
        .build()

    val apiService: ApiService = retrofit.create(ApiService::class.java)

    fun resolveApiUrl(pathOrUrl: String): String {
        if (pathOrUrl.startsWith("http://") || pathOrUrl.startsWith("https://")) {
            return pathOrUrl
        }
        val normalizedPath = pathOrUrl.removePrefix("/")
        val apiRoot = BASE_URL.removeSuffix("/")
        return if (normalizedPath.startsWith("api/v1/")) {
            val serverRoot = apiRoot.removeSuffix("api/v1")
            "$serverRoot$normalizedPath"
        } else {
            "$apiRoot/$normalizedPath"
        }
    }

    fun streamChatMessage(
        request: SendMessageRequest,
        onEvent: (ChatStreamEvent) -> Unit,
    ) {
        val payload = gson.toJson(request.copy(stream = true))
        val httpRequest = Request.Builder()
            .url("${BASE_URL}chat/message")
            .post(payload.toRequestBody("application/json; charset=utf-8".toMediaType()))
            .build()

        streamingClient.newCall(httpRequest).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("Streaming request failed: ${response.code}")
            }
            val body = response.body ?: throw IllegalStateException("Streaming response body is empty")
            val source = body.source()
            while (!source.exhausted()) {
                val line = source.readUtf8Line() ?: break
                if (!line.startsWith("data: ")) continue
                val jsonPayload = line.removePrefix("data: ").trim()
                if (jsonPayload.isEmpty()) continue
                val event = gson.fromJson(jsonPayload, StreamEnvelope::class.java)
                when (event.type) {
                    "thinking_block" -> {
                        val block = gson.fromJson(gson.toJsonTree(event.content), ThinkingBlockDto::class.java)
                        onEvent(ChatStreamEvent.ThinkingBlock(block))
                    }
                    "content" -> {
                        onEvent(ChatStreamEvent.Content((event.content as? String).orEmpty()))
                    }
                    "thinking" -> {
                        onEvent(ChatStreamEvent.Thinking((event.content as? String).orEmpty()))
                    }
                    "approval_requested" -> {
                        val approvalRequest = gson.fromJson(gson.toJsonTree(event.content), ApprovalRequestDto::class.java)
                        onEvent(ChatStreamEvent.ApprovalRequested(approvalRequest))
                    }
                    "approval_resolved" -> {
                        val decision = gson.fromJson(gson.toJsonTree(event.content), ApprovalResponseDto::class.java)
                        onEvent(ChatStreamEvent.ApprovalResolved(decision))
                    }
                    "tool_call" -> {
                        val toolCall = gson.fromJson(gson.toJsonTree(event.content), ToolCallDto::class.java)
                        onEvent(ChatStreamEvent.ToolCall(toolCall))
                    }
                    "done" -> {
                        val fallbackSessionId = if (event.content is Map<*, *>) {
                            event.content["session_id"]?.toString().orEmpty()
                        } else {
                            ""
                        }
                        onEvent(
                            ChatStreamEvent.Done(
                                sessionId = event.sessionId?.takeIf { it.isNotBlank() } ?: fallbackSessionId,
                                thinkingBlocks = event.thinkingBlocks.orEmpty(),
                                toolCalls = event.toolCalls.orEmpty(),
                            )
                        )
                    }
                    "error" -> {
                        onEvent(ChatStreamEvent.Error(event.content?.toString().orEmpty()))
                    }
                }
            }
        }
    }
}

sealed interface ChatStreamEvent {
    data class ThinkingBlock(val block: ThinkingBlockDto) : ChatStreamEvent
    data class Thinking(val summary: String) : ChatStreamEvent
    data class Content(val chunk: String) : ChatStreamEvent
    data class ApprovalRequested(val request: ApprovalRequestDto) : ChatStreamEvent
    data class ApprovalResolved(val response: ApprovalResponseDto) : ChatStreamEvent
    data class ToolCall(val toolCall: ToolCallDto) : ChatStreamEvent
    data class Error(val message: String) : ChatStreamEvent
    data class Done(
        val sessionId: String,
        val thinkingBlocks: List<ThinkingBlockDto> = emptyList(),
        val toolCalls: List<ToolCallDto> = emptyList(),
    ) : ChatStreamEvent
}

private data class StreamEnvelope(
    val type: String,
    val content: Any? = null,
    val session_id: String? = null,
    val thinking_blocks: List<ThinkingBlockDto>? = null,
    val tool_calls: List<ToolCallDto>? = null,
) {
    val sessionId: String?
        get() = session_id

    val thinkingBlocks: List<ThinkingBlockDto>?
        get() = thinking_blocks

    val toolCalls: List<ToolCallDto>?
        get() = tool_calls
}
