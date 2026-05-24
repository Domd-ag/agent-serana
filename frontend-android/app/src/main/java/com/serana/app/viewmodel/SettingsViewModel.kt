package com.serana.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.serana.app.data.api.LlmConfigCreateRequest
import com.serana.app.data.api.LlmModeUpdateRequest
import com.serana.app.data.api.RetrofitClient
import com.serana.app.data.models.LlmConfig
import com.serana.app.data.models.LlmMode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class SettingsUiState(
    val provider: String = "openai",
    val apiKey: String = "",
    val baseUrl: String = "",
    val model: String = "",
    val savedProvider: String = "openai",
    val savedBaseUrl: String = "",
    val savedModel: String = "",
    val mode: LlmMode = LlmMode.BACKEND_DEFAULT,
    val isLoading: Boolean = false,
    val isSaving: Boolean = false,
    val error: String? = null,
    val providerError: String? = null,
    val modelError: String? = null,
    val baseUrlError: String? = null,
    val apiKeyError: String? = null,
    val statusMessage: String? = null,
    val configExists: Boolean = false,
    val providerPresets: List<String> = listOf("openai", "openrouter", "ollama"),
    val modelSuggestions: List<String> = emptyList(),
)

class SettingsViewModel : ViewModel() {
    private val _uiState = MutableStateFlow(SettingsUiState(isLoading = true))
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        _uiState.value = _uiState.value.copy(isLoading = true, error = null, statusMessage = null)
        viewModelScope.launch {
            try {
                val modeResponse = withContext(Dispatchers.IO) { RetrofitClient.apiService.getLlmMode() }
                val configResponse = withContext(Dispatchers.IO) { RetrofitClient.apiService.getLlmConfig() }
                if (!modeResponse.isSuccessful) {
                    throw IllegalStateException("Failed to load LLM mode")
                }
                val mode = LlmMode.fromWireValue(modeResponse.body()?.mode ?: LlmMode.BACKEND_DEFAULT.wireValue)
                val config = configResponse.body()
                val provider = config?.provider ?: "openai"
                val baseUrl = config?.baseUrl ?: defaultBaseUrlFor(provider)
                val model = config?.model.orEmpty().ifBlank {
                    defaultModelsFor(provider).firstOrNull().orEmpty()
                }
                _uiState.value = _uiState.value.copy(
                    provider = provider,
                    apiKey = "",
                    baseUrl = baseUrl,
                    model = model,
                    savedProvider = provider,
                    savedBaseUrl = baseUrl,
                    savedModel = model,
                    mode = mode,
                    isLoading = false,
                    configExists = config != null,
                    modelSuggestions = defaultModelsFor(provider),
                )
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    isLoading = false,
                    error = e.message ?: "Failed to load settings",
                )
            }
        }
    }

    fun updateProvider(value: String) = updateState {
        val normalized = value.trim()
        val oldDefaultBaseUrl = defaultBaseUrlFor(provider)
        val newDefaultBaseUrl = defaultBaseUrlFor(normalized)
        val shouldReplaceBaseUrl = baseUrl.isBlank() || baseUrl == oldDefaultBaseUrl
        val nextSuggestions = defaultModelsFor(normalized)
        copy(
            provider = normalized,
            baseUrl = if (shouldReplaceBaseUrl) newDefaultBaseUrl else baseUrl,
            model = if (model.isBlank()) nextSuggestions.firstOrNull().orEmpty() else model,
            providerError = null,
            baseUrlError = null,
        )
    }

    fun updateApiKey(value: String) = updateState { copy(apiKey = value, apiKeyError = null) }
    fun updateBaseUrl(value: String) = updateState { copy(baseUrl = value, baseUrlError = null) }
    fun updateModel(value: String) = updateState { copy(model = value, modelError = null) }
    fun updateMode(value: LlmMode) = updateState { copy(mode = value, error = null) }

    fun saveSettings() {
        val snapshot = _uiState.value
        val providerError = validateProvider(snapshot.provider)
        val modelError = validateModel(snapshot.model)
        val baseUrlError = validateBaseUrl(snapshot.baseUrl)
        val apiKeyError = validateApiKey(snapshot)

        if (providerError != null || modelError != null || baseUrlError != null || apiKeyError != null) {
            _uiState.value = snapshot.copy(
                providerError = providerError,
                modelError = modelError,
                baseUrlError = baseUrlError,
                apiKeyError = apiKeyError,
                error = "Please fix the highlighted fields.",
            )
            return
        }

        if (snapshot.model.isBlank()) {
            _uiState.value = snapshot.copy(error = "Model is required.", modelError = "Model is required.")
            return
        }
        _uiState.value = snapshot.copy(
            isSaving = true,
            error = null,
            statusMessage = null,
            providerError = null,
            modelError = null,
            baseUrlError = null,
            apiKeyError = null,
        )
        viewModelScope.launch {
            try {
                if (snapshot.apiKey.isNotBlank() || !snapshot.configExists) {
                    val configResponse = withContext(Dispatchers.IO) {
                        RetrofitClient.apiService.saveLlmConfig(
                            LlmConfigCreateRequest(
                                provider = snapshot.provider,
                                apiKey = snapshot.apiKey,
                                baseUrl = snapshot.baseUrl.ifBlank { null },
                                model = snapshot.model,
                            ),
                        )
                    }
                    if (!configResponse.isSuccessful) {
                        throw IllegalStateException("Failed to save LLM config")
                    }
                }

                val modeResponse = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.updateLlmMode(
                        LlmModeUpdateRequest(mode = snapshot.mode.wireValue),
                    )
                }
                if (!modeResponse.isSuccessful) {
                    throw IllegalStateException("Failed to update LLM mode")
                }
                _uiState.value = _uiState.value.copy(
                    isSaving = false,
                    statusMessage = "Settings saved.",
                    error = null,
                    apiKey = "",
                    savedProvider = snapshot.provider,
                    savedBaseUrl = snapshot.baseUrl,
                    savedModel = snapshot.model,
                    configExists = true,
                )
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    isSaving = false,
                    error = e.message ?: "Failed to save settings",
                )
            }
        }
    }

    fun deleteConfig() {
        _uiState.value = _uiState.value.copy(isSaving = true, error = null, statusMessage = null)
        viewModelScope.launch {
            try {
                val response = withContext(Dispatchers.IO) { RetrofitClient.apiService.deleteLlmConfig() }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to delete LLM config")
                }
                _uiState.value = _uiState.value.copy(
                    isSaving = false,
                    apiKey = "",
                    baseUrl = "",
                    model = "",
                    savedProvider = "openai",
                    savedBaseUrl = "",
                    savedModel = "",
                    configExists = false,
                    statusMessage = "Saved config removed.",
                )
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    isSaving = false,
                    error = e.message ?: "Failed to delete config",
                )
            }
        }
    }

    fun clearMessage() {
        _uiState.value = _uiState.value.copy(
            error = null,
            statusMessage = null,
            providerError = null,
            modelError = null,
            baseUrlError = null,
            apiKeyError = null,
        )
    }

    private fun updateState(transform: SettingsUiState.() -> SettingsUiState) {
        val next = _uiState.value.transform()
        _uiState.value = next.copy(
            modelSuggestions = defaultModelsFor(next.provider),
        )
    }
}

private fun validateProvider(provider: String): String? {
    return if (provider.isBlank()) "Provider is required." else null
}

private fun validateModel(model: String): String? {
    return if (model.isBlank()) "Model is required." else null
}

private fun validateBaseUrl(baseUrl: String): String? {
    if (baseUrl.isBlank()) return null
    return if (baseUrl.startsWith("http://") || baseUrl.startsWith("https://")) {
        null
    } else {
        "Base URL must start with http:// or https://"
    }
}

private fun validateApiKey(state: SettingsUiState): String? {
    val configFieldsChanged =
        state.provider != state.savedProvider ||
            state.baseUrl != state.savedBaseUrl ||
            state.model != state.savedModel

    return when {
        state.mode == LlmMode.USER_CONFIG && state.apiKey.isBlank() && !state.configExists ->
            "API key is required for user config mode."
        state.configExists && configFieldsChanged && state.apiKey.isBlank() ->
            "Re-enter the API key before changing the saved model config."
        else -> null
    }
}

private fun defaultBaseUrlFor(provider: String): String {
    return when (provider.lowercase()) {
        "openai" -> ""
        "openrouter" -> "https://openrouter.ai/api/v1"
        "ollama" -> "http://10.0.2.2:11434/v1"
        else -> ""
    }
}

private fun defaultModelsFor(provider: String): List<String> {
    return when (provider.lowercase()) {
        "openai" -> listOf("gpt-5", "gpt-5-mini", "gpt-4.1")
        "openrouter" -> listOf("openai/gpt-5", "anthropic/claude-3.7-sonnet", "google/gemini-2.5-pro")
        "ollama" -> listOf("llama3.1", "qwen2.5", "mistral")
        else -> emptyList()
    }
}
