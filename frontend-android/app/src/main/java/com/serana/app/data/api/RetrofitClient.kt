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

    private val retrofit = Retrofit.Builder()
        .baseUrl(BASE_URL)
        .client(client)
        .addConverterFactory(GsonConverterFactory.create())
        .build()

    val apiService: ApiService = retrofit.create(ApiService::class.java)

    fun streamChatMessage(
        request: SendMessageRequest,
        onEvent: (ChatStreamEvent) -> Unit,
    ) {
        val payload = gson.toJson(request.copy(stream = true))
        val httpRequest = Request.Builder()
            .url("${BASE_URL}chat/message")
            .post(payload.toRequestBody("application/json; charset=utf-8".toMediaType()))
            .build()

        client.newCall(httpRequest).execute().use { response ->
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
                    "done" -> {
                        val sessionId = if (event.content is Map<*, *>) {
                            event.content["session_id"]?.toString().orEmpty()
                        } else {
                            event.sessionId.orEmpty()
                        }
                        onEvent(ChatStreamEvent.Done(sessionId))
                    }
                }
            }
        }
    }
}

sealed interface ChatStreamEvent {
    data class ThinkingBlock(val block: ThinkingBlockDto) : ChatStreamEvent
    data class Content(val chunk: String) : ChatStreamEvent
    data class Done(val sessionId: String) : ChatStreamEvent
}

private data class StreamEnvelope(
    val type: String,
    val content: Any? = null,
    val session_id: String? = null,
) {
    val sessionId: String?
        get() = session_id
}
