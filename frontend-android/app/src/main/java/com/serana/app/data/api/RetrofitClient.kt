package com.serana.app.data.api

import android.content.Context
import com.google.gson.Gson
import okhttp3.Call
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

object RetrofitClient {
    private const val PREFS_NAME = "serana_network"
    private const val KEY_SERVER_ROOT_URL = "server_root_url"
    private val gson = Gson()
    @Volatile private var appContext: Context? = null
    @Volatile private var serverRootUrl: String = ""
    @Volatile private var service: ApiService? = null

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

    val configuredServerUrl: String
        get() = serverRootUrl

    val isConfigured: Boolean
        get() = serverRootUrl.isNotBlank()

    val apiService: ApiService
        get() = service ?: synchronized(this) {
            service ?: buildRetrofit().create(ApiService::class.java).also { service = it }
        }

    fun initialize(context: Context) {
        appContext = context.applicationContext
        val savedUrl = appContext
            ?.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            ?.getString(KEY_SERVER_ROOT_URL, "")
            .orEmpty()
        if (savedUrl.isNotBlank()) {
            setServerRootUrl(savedUrl, persist = false)
        }
    }

    fun setServerRootUrl(url: String, persist: Boolean = true) {
        val normalized = normalizeServerRootUrl(url)
        synchronized(this) {
            serverRootUrl = normalized
            service = null
        }
        if (persist) {
            appContext
                ?.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                ?.edit()
                ?.putString(KEY_SERVER_ROOT_URL, normalized)
                ?.apply()
        }
    }

    fun resolveApiUrl(pathOrUrl: String): String {
        if (pathOrUrl.startsWith("http://") || pathOrUrl.startsWith("https://")) {
            return pathOrUrl
        }
        val normalizedPath = pathOrUrl.removePrefix("/")
        val apiRoot = apiBaseUrl().removeSuffix("/")
        return if (normalizedPath.startsWith("api/v1/")) {
            val serverRoot = apiRoot.removeSuffix("api/v1")
            "$serverRoot$normalizedPath"
        } else {
            "$apiRoot/$normalizedPath"
        }
    }

    fun streamChatMessage(
        request: SendMessageRequest,
        onCallReady: (Call) -> Unit = {},
        onEvent: (ChatStreamEvent) -> Unit,
    ) {
        val payload = gson.toJson(request.copy(stream = true))
        val httpRequest = Request.Builder()
            .url("${apiBaseUrl()}chat/message")
            .post(payload.toRequestBody("application/json; charset=utf-8".toMediaType()))
            .build()

        val call = streamingClient.newCall(httpRequest)
        onCallReady(call)

        call.execute().use { response ->
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

    private fun buildRetrofit(): Retrofit {
        return Retrofit.Builder()
            .baseUrl(apiBaseUrl())
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
    }

    private fun apiBaseUrl(): String {
        val root = serverRootUrl.trimEnd('/')
        if (root.isBlank()) {
            throw IllegalStateException("请先在设置里配置服务器地址。")
        }
        return "$root/api/v1/"
    }

    fun normalizeServerRootUrl(url: String): String {
        val trimmed = url.trim().trimEnd('/')
        val withScheme = when {
            trimmed.startsWith("http://") || trimmed.startsWith("https://") -> trimmed
            IPV4_WITH_OPTIONAL_PORT.matches(trimmed) -> {
                val hasPort = trimmed.substringAfterLast('.').contains(':')
                "http://$trimmed${if (hasPort) "" else ":8000"}"
            }
            else -> trimmed
        }

        return when {
            withScheme.endsWith("/api/v1") -> withScheme.removeSuffix("/api/v1")
            withScheme.endsWith("/api/v1/") -> withScheme.removeSuffix("/api/v1/")
            else -> withScheme
        }
    }

    private val IPV4_WITH_OPTIONAL_PORT =
        Regex("""^((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(:\d{1,5})?$""")
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
