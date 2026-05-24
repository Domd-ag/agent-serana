package com.serana.app.data.models

data class LlmConfig(
    val provider: String,
    val apiKey: String = "",
    val baseUrl: String = "",
    val model: String,
    val updatedAt: String? = null,
)

enum class LlmMode(val wireValue: String) {
    USER_CONFIG("USER_CONFIG"),
    BACKEND_DEFAULT("BACKEND_DEFAULT");

    companion object {
        fun fromWireValue(value: String): LlmMode {
            return entries.firstOrNull { it.wireValue == value } ?: BACKEND_DEFAULT
        }
    }
}
