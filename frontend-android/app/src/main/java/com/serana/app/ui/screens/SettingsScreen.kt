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
                    ModeOption(
                        title = "连接服务器",
                        body = "配置手机 App 要连接的 Serana 后端地址。",
                        selected = uiState.mode == LlmMode.SERVER_CONNECTION,
                        onSelect = { viewModel.updateMode(LlmMode.SERVER_CONNECTION) },
                    )
                    ModeOption(
                        title = "LLM 配置",
                        body = "在当前服务器上保存 Base URL、API Key 和模型。",
                        selected = uiState.mode == LlmMode.LLM_CONFIG,
                        onSelect = { viewModel.updateMode(LlmMode.LLM_CONFIG) },
                    )
                }

                if (uiState.mode == LlmMode.SERVER_CONNECTION) {
                    SettingsPanel {
                        Text("连接服务器", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                        OutlinedTextField(
                            value = uiState.serverUrl,
                            onValueChange = viewModel::updateServerUrl,
                            modifier = Modifier.fillMaxWidth(),
                            label = { Text("服务器地址") },
                            placeholder = { Text("例如 192.168.31.30 或 http://192.168.31.30:8000") },
                            isError = uiState.serverUrlError != null,
                            supportingText = {
                                Text(uiState.serverUrlError ?: "可以直接填写服务器 IP；未填写端口时默认使用 8000，也可以填到 /api/v1。")
                            },
                        )
                        Button(
                            onClick = { viewModel.saveSettings() },
                            enabled = !uiState.isSaving,
                        ) {
                            Text(if (uiState.isSaving) "保存中…" else "保存服务器")
                        }
                    }
                }

                if (uiState.mode == LlmMode.LLM_CONFIG) {
                SettingsPanel {
                    Text("LLM 配置", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                    Text(
                        text = "配置当前服务器用于对话的模型服务。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    OutlinedTextField(
                        value = uiState.baseUrl,
                        onValueChange = viewModel::updateBaseUrl,
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Base URL") },
                        isError = uiState.baseUrlError != null,
                        supportingText = {
                            Text(uiState.baseUrlError ?: "填写 OpenAI 兼容接口地址，例如 https://openrouter.ai/api/v1")
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
                                    "首次保存 LLM 配置时必须提供 Key。"
                                },
                            )
                        },
                    )
                    OutlinedTextField(
                        value = uiState.model,
                        onValueChange = viewModel::updateModel,
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("模型") },
                        isError = uiState.modelError != null,
                        supportingText = {
                            Text(uiState.modelError ?: "填写模型 ID，例如 openai/gpt-5 或 deepseek-chat。")
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
