package com.serana.app.data.models

data class LlmConfig(
    val provider: String,
    val apiKey: String = "",
    val baseUrl: String = "",
    val model: String,
    val updatedAt: String? = null,
)

enum class LlmMode(val wireValue: String) {
    SERVER_CONNECTION("SERVER_CONNECTION"),
    LLM_CONFIG("LLM_CONFIG");

    companion object {
        fun fromWireValue(value: String): LlmMode {
            return entries.firstOrNull { it.wireValue == value } ?: SERVER_CONNECTION
        }
    }
}
