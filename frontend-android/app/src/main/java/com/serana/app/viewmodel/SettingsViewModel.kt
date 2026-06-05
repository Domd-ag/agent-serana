package com.serana.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.serana.app.data.api.LlmConfigCreateRequest
import com.serana.app.data.api.RetrofitClient
import com.serana.app.data.models.LlmMode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class SettingsUiState(
    val serverUrl: String = "",
    val savedServerUrl: String = "",
    val provider: String = "openai",
    val apiKey: String = "",
    val baseUrl: String = "",
    val model: String = "",
    val savedProvider: String = "openai",
    val savedBaseUrl: String = "",
    val savedModel: String = "",
    val mode: LlmMode = LlmMode.SERVER_CONNECTION,
    val isLoading: Boolean = false,
    val isSaving: Boolean = false,
    val error: String? = null,
    val serverUrlError: String? = null,
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
                val serverUrl = RetrofitClient.configuredServerUrl
                if (serverUrl.isBlank()) {
                    _uiState.value = _uiState.value.copy(
                        serverUrl = "",
                        savedServerUrl = "",
                        mode = LlmMode.SERVER_CONNECTION,
                        isLoading = false,
                        configExists = false,
                        statusMessage = "请先配置手机 App 要连接的 Serana 后端地址。",
                    )
                    return@launch
                }

                val configResponse = withContext(Dispatchers.IO) { RetrofitClient.apiService.getLlmConfig() }
                if (!configResponse.isSuccessful) {
                    throw IllegalStateException("无法读取服务器上的 LLM 配置，请检查服务器地址。")
                }
                val config = configResponse.body()
                val provider = config?.provider ?: "openai"
                val baseUrl = config?.baseUrl.orEmpty()
                val model = config?.model.orEmpty()
                _uiState.value = _uiState.value.copy(
                    serverUrl = serverUrl,
                    savedServerUrl = serverUrl,
                    provider = provider,
                    apiKey = "",
                    baseUrl = baseUrl,
                    model = model,
                    savedProvider = provider,
                    savedBaseUrl = baseUrl,
                    savedModel = model,
                    mode = if (config == null) LlmMode.SERVER_CONNECTION else _uiState.value.mode,
                    isLoading = false,
                    configExists = config != null,
                    modelSuggestions = defaultModelsFor(provider),
                )
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    isLoading = false,
                    error = e.message ?: "加载设置失败。",
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
    fun updateServerUrl(value: String) = updateState { copy(serverUrl = value, serverUrlError = null) }
    fun updateBaseUrl(value: String) = updateState { copy(baseUrl = value, baseUrlError = null) }
    fun updateModel(value: String) = updateState { copy(model = value, modelError = null) }
    fun updateMode(value: LlmMode) = updateState { copy(mode = value, error = null) }

    fun saveSettings() {
        val snapshot = _uiState.value
        if (snapshot.mode == LlmMode.SERVER_CONNECTION) {
            saveServerConnection(snapshot)
            return
        }

        val serverUrlError = validateServerUrl(snapshot.serverUrl)
        val providerError = validateProvider(snapshot.provider)
        val modelError = validateModel(snapshot.model)
        val baseUrlError = validateBaseUrl(snapshot.baseUrl)
        val apiKeyError = validateApiKey(snapshot)

        if (serverUrlError != null || providerError != null || modelError != null || baseUrlError != null || apiKeyError != null) {
            _uiState.value = snapshot.copy(
                serverUrlError = serverUrlError,
                providerError = providerError,
                modelError = modelError,
                baseUrlError = baseUrlError,
                apiKeyError = apiKeyError,
                error = "请先修正标红的配置项。",
            )
            return
        }

        if (snapshot.model.isBlank()) {
            _uiState.value = snapshot.copy(error = "请填写模型。", modelError = "请填写模型。")
            return
        }
        _uiState.value = snapshot.copy(
            isSaving = true,
            error = null,
            statusMessage = null,
            serverUrlError = null,
            providerError = null,
            modelError = null,
            baseUrlError = null,
            apiKeyError = null,
        )
        viewModelScope.launch {
            try {
                RetrofitClient.setServerRootUrl(snapshot.serverUrl)
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
                        throw IllegalStateException("保存 LLM 配置失败。")
                    }
                }

                _uiState.value = _uiState.value.copy(
                    isSaving = false,
                    statusMessage = "LLM 配置已保存。",
                    error = null,
                    apiKey = "",
                    savedServerUrl = RetrofitClient.configuredServerUrl,
                    savedProvider = snapshot.provider,
                    savedBaseUrl = snapshot.baseUrl,
                    savedModel = snapshot.model,
                    configExists = true,
                )
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    isSaving = false,
                    error = e.message ?: "保存设置失败。",
                )
            }
        }
    }

    fun deleteConfig() {
        _uiState.value = _uiState.value.copy(isSaving = true, error = null, statusMessage = null)
        viewModelScope.launch {
            try {
                if (!RetrofitClient.isConfigured) {
                    throw IllegalStateException("请先配置服务器地址。")
                }
                val response = withContext(Dispatchers.IO) { RetrofitClient.apiService.deleteLlmConfig() }
                if (!response.isSuccessful) {
                    throw IllegalStateException("删除 LLM 配置失败。")
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
                    statusMessage = "LLM 配置已删除。",
                )
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    isSaving = false,
                    error = e.message ?: "删除配置失败。",
                )
            }
        }
    }

    fun clearMessage() {
        _uiState.value = _uiState.value.copy(
            error = null,
            statusMessage = null,
            serverUrlError = null,
            providerError = null,
            modelError = null,
            baseUrlError = null,
            apiKeyError = null,
        )
    }

    private fun saveServerConnection(snapshot: SettingsUiState) {
        val serverUrlError = validateServerUrl(snapshot.serverUrl)
        if (serverUrlError != null) {
            _uiState.value = snapshot.copy(
                serverUrlError = serverUrlError,
                error = "请先填写可访问的服务器地址。",
            )
            return
        }

        _uiState.value = snapshot.copy(
            isSaving = true,
            error = null,
            statusMessage = null,
            serverUrlError = null,
        )
        viewModelScope.launch {
            try {
                RetrofitClient.setServerRootUrl(snapshot.serverUrl)
                _uiState.value = _uiState.value.copy(
                    isSaving = false,
                    serverUrl = RetrofitClient.configuredServerUrl,
                    savedServerUrl = RetrofitClient.configuredServerUrl,
                    statusMessage = "服务器地址已保存。接下来请配置 LLM。",
                    mode = LlmMode.LLM_CONFIG,
                )
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    isSaving = false,
                    error = e.message ?: "保存服务器地址失败。",
                )
            }
        }
    }

    private fun updateState(transform: SettingsUiState.() -> SettingsUiState) {
        val next = _uiState.value.transform()
        _uiState.value = next.copy(
            modelSuggestions = defaultModelsFor(next.provider),
        )
    }
}

private fun validateProvider(provider: String): String? {
    return if (provider.isBlank()) "请填写 Provider。" else null
}

private fun validateModel(model: String): String? {
    return if (model.isBlank()) "请填写模型。" else null
}

private fun validateServerUrl(serverUrl: String): String? {
    if (serverUrl.isBlank()) return "请填写服务器地址。"
    return if (serverUrl.startsWith("http://") || serverUrl.startsWith("https://")) {
        null
    } else {
        "服务器地址必须以 http:// 或 https:// 开头。"
    }
}

private fun validateBaseUrl(baseUrl: String): String? {
    if (baseUrl.isBlank()) return null
    return if (baseUrl.startsWith("http://") || baseUrl.startsWith("https://")) {
        null
    } else {
        "Base URL 必须以 http:// 或 https:// 开头。"
    }
}

private fun validateApiKey(state: SettingsUiState): String? {
    val configFieldsChanged =
        state.provider != state.savedProvider ||
            state.baseUrl != state.savedBaseUrl ||
            state.model != state.savedModel

    return when {
        state.mode == LlmMode.LLM_CONFIG && state.apiKey.isBlank() && !state.configExists ->
            "首次保存 LLM 配置必须填写 API Key。"
        state.configExists && configFieldsChanged && state.apiKey.isBlank() ->
            "修改已保存的 LLM 配置时，请重新输入 API Key。"
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
