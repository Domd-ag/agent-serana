package com.serana.app.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.serana.app.data.models.LlmMode
import com.serana.app.viewmodel.SettingsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    viewModel: SettingsViewModel = viewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    var showApiKey by rememberSaveable { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text("设置")
                        Text(
                            text = "模型路由与服务提供商配置",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                },
                actions = {
                    TextButton(onClick = { viewModel.refresh() }) {
                        Text("刷新")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                ),
            )
        },
    ) { paddingValues ->
        if (uiState.isLoading) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues),
                verticalArrangement = Arrangement.Center,
            ) {
                CircularProgressIndicator()
            }
        } else {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues)
                    .padding(horizontal = 16.dp, vertical = 10.dp)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                uiState.error?.let {
                    ErrorBanner(
                        message = it,
                        onDismiss = viewModel::clearMessage,
                    )
                }
                uiState.statusMessage?.let {
                    SettingsPanel {
                        Text(
                            text = it,
                            color = MaterialTheme.colorScheme.primary,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }

                SettingsPanel {
                    Text("LLM 模式", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                    Text(
                        text = "决定使用后端默认模型，还是使用你自己的服务配置。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    ModeOption(
                        title = "后端默认",
                        body = "使用后端统一维护的模型选择。",
                        selected = uiState.mode == LlmMode.BACKEND_DEFAULT,
                        onSelect = { viewModel.updateMode(LlmMode.BACKEND_DEFAULT) },
                    )
                    ModeOption(
                        title = "个人配置",
                        body = "使用你在当前设备上配置的 provider 与模型。",
                        selected = uiState.mode == LlmMode.USER_CONFIG,
                        onSelect = { viewModel.updateMode(LlmMode.USER_CONFIG) },
                    )
                }

                SettingsPanel {
                    Text("模型配置", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                    Text(
                        text = "先选 provider 预设，再选择模型，或者手动输入模型标识。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    PresetRow(
                        items = uiState.providerPresets,
                        onSelect = viewModel::updateProvider,
                    )
                    OutlinedTextField(
                        value = uiState.provider,
                        onValueChange = viewModel::updateProvider,
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Provider") },
                        isError = uiState.providerError != null,
                        supportingText = {
                            Text(uiState.providerError ?: "例如：openai、openrouter、ollama")
                        },
                    )
                    OutlinedTextField(
                        value = uiState.model,
                        onValueChange = viewModel::updateModel,
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("模型") },
                        isError = uiState.modelError != null,
                        supportingText = {
                            Text(uiState.modelError ?: "可直接点建议项，也可以手动填写模型 ID。")
                        },
                    )
                    if (uiState.modelSuggestions.isNotEmpty()) {
                        PresetRow(
                            items = uiState.modelSuggestions,
                            onSelect = viewModel::updateModel,
                        )
                    }
                    OutlinedTextField(
                        value = uiState.baseUrl,
                        onValueChange = viewModel::updateBaseUrl,
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Base URL") },
                        isError = uiState.baseUrlError != null,
                        supportingText = {
                            Text(
                                uiState.baseUrlError ?: when (uiState.provider.lowercase()) {
                                    "openai" -> "留空即可使用默认 OpenAI 地址。"
                                    "openrouter" -> "通常是 https://openrouter.ai/api/v1"
                                    "ollama" -> "模拟器通常用 http://10.0.2.2:11434/v1"
                                    else -> "可选的自定义服务地址。"
                                },
                            )
                        },
                    )
                    OutlinedTextField(
                        value = uiState.apiKey,
                        onValueChange = viewModel::updateApiKey,
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("API Key") },
                        isError = uiState.apiKeyError != null,
                        visualTransformation = if (showApiKey) {
                            VisualTransformation.None
                        } else {
                            PasswordVisualTransformation()
                        },
                        trailingIcon = {
                            IconButton(onClick = { showApiKey = !showApiKey }) {
                                Icon(
                                    imageVector = if (showApiKey) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                                    contentDescription = if (showApiKey) "隐藏 API Key" else "显示 API Key",
                                )
                            }
                        },
                        supportingText = {
                            Text(
                                uiState.apiKeyError ?: if (uiState.configExists) {
                                    "留空表示继续使用当前已保存的 Key。"
                                } else {
                                    "保存新的个人配置时必须提供 Key。"
                                },
                            )
                        },
                    )
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Button(
                            onClick = { viewModel.saveSettings() },
                            enabled = !uiState.isSaving,
                        ) {
                            Text(if (uiState.isSaving) "保存中…" else "保存")
                        }
                        TextButton(
                            onClick = { viewModel.deleteConfig() },
                            enabled = !uiState.isSaving && uiState.configExists,
                        ) {
                            Text("删除配置")
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun PresetRow(
    items: List<String>,
    onSelect: (String) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items.take(3).forEach { item ->
            AssistChip(
                onClick = { onSelect(item) },
                label = { Text(item) },
            )
        }
    }
}

@Composable
private fun ModeOption(
    title: String,
    body: String,
    selected: Boolean,
    onSelect: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            RadioButton(selected = selected, onClick = onSelect)
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(text = title, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
                Text(
                    text = body,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun SettingsPanel(content: @Composable () -> Unit) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            content()
        }
    }
}
