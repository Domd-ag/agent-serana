package com.serana.app.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.serana.app.data.models.MarketplaceSkill
import com.serana.app.data.models.SkillPackage
import com.serana.app.data.models.SkillTool
import com.serana.app.viewmodel.SkillsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SkillsScreen(
    viewModel: SkillsViewModel = viewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val selectedSkill by viewModel.selectedSkill.collectAsState()
    val selectedSkillTools by viewModel.selectedSkillTools.collectAsState()
    val isDetailLoading by viewModel.isDetailLoading.collectAsState()
    val detailError by viewModel.detailError.collectAsState()
    val updatingSkillNames by viewModel.updatingSkillNames.collectAsState()
    val marketplaceSkills by viewModel.marketplaceSkills.collectAsState()
    val marketplaceLoading by viewModel.marketplaceLoading.collectAsState()
    val marketplaceError by viewModel.marketplaceError.collectAsState()
    val installingMarketplaceSlugs by viewModel.installingMarketplaceSlugs.collectAsState()
    var query by remember { mutableStateOf("") }
    var filter by remember { mutableStateOf("全部") }
    var marketplaceQuery by remember { mutableStateOf("") }

    val filteredSkills = uiState.data.filter { skill ->
        val matchesQuery = query.isBlank() ||
            skill.name.contains(query, ignoreCase = true) ||
            (skill.description?.contains(query, ignoreCase = true) == true) ||
            skill.agentType.contains(query, ignoreCase = true)
        val matchesFilter = when (filter) {
            "已启用" -> skill.isEnabled
            "已停用" -> !skill.isEnabled
            "Forge" -> skill.agentType.equals("forge", ignoreCase = true)
            else -> true
        }
        matchesQuery && matchesFilter
    }

    selectedSkill?.let { skill ->
        SkillDetailDialog(
            skill = skill,
            tools = selectedSkillTools,
            isLoading = isDetailLoading,
            error = detailError,
            onDismiss = viewModel::dismissSkillDetail,
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text("技能")
                        Text(
                            text = "本地技能与远程市场",
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
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .padding(horizontal = 16.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (uiState.error != null) {
                ErrorBanner(
                    message = uiState.error ?: "",
                    onDismiss = viewModel::clearError,
                )
            }

            SkillsOverviewPanel(
                query = query,
                onQueryChange = { query = it },
                filter = filter,
                onFilterChange = { filter = it },
                shownCount = filteredSkills.size,
            )

            MarketplacePanel(
                query = marketplaceQuery,
                onQueryChange = { marketplaceQuery = it },
                onSearch = { viewModel.searchMarketplace(marketplaceQuery) },
                onLoadPopular = {
                    marketplaceQuery = ""
                    viewModel.loadMarketplace()
                },
                skills = marketplaceSkills.take(6),
                isLoading = marketplaceLoading,
                error = marketplaceError,
                installingSlugs = installingMarketplaceSlugs,
                onInstall = { viewModel.installMarketplaceSkill(it) },
            )

            if (uiState.isLoading) {
                CircularProgressIndicator()
            } else if (uiState.data.isEmpty()) {
                EmptySkillsCard(
                    title = "还没有安装任何技能",
                    body = "把技能包放进后端 store 后刷新，这里就会出现它们。",
                )
            } else if (filteredSkills.isEmpty()) {
                EmptySkillsCard(
                    title = "没有匹配项",
                    body = "试试更宽松的关键词，或者切回全部筛选。",
                )
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    items(filteredSkills, key = { it.id }) { skill ->
                        SkillCard(
                            skill = skill,
                            isUpdating = updatingSkillNames.contains(skill.name),
                            onDetails = { viewModel.loadSkillDetail(skill) },
                            onToggle = { viewModel.toggleSkill(skill) },
                        )
                    }
                    if (uiState.isRefreshing) {
                        item {
                            CircularProgressIndicator()
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SkillsOverviewPanel(
    query: String,
    onQueryChange: (String) -> Unit,
    filter: String,
    onFilterChange: (String) -> Unit,
    shownCount: Int,
) {
    PanelSurface {
        Text("已安装技能", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
        Text(
            text = "管理本地技能包，以及它们是否参与当前运行时。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        OutlinedTextField(
            value = query,
            onValueChange = onQueryChange,
            modifier = Modifier.fillMaxWidth(),
            label = { Text("搜索技能") },
            singleLine = true,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            listOf("全部", "已启用", "已停用", "Forge").forEach { option ->
                AssistChip(
                    onClick = { onFilterChange(option) },
                    label = { Text(option) },
                    enabled = filter != option,
                )
            }
        }
        Text(
            text = "当前显示 $shownCount 个技能",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun MarketplacePanel(
    query: String,
    onQueryChange: (String) -> Unit,
    onSearch: () -> Unit,
    onLoadPopular: () -> Unit,
    skills: List<MarketplaceSkill>,
    isLoading: Boolean,
    error: String?,
    installingSlugs: Set<String>,
    onInstall: (MarketplaceSkill) -> Unit,
) {
    PanelSurface {
        Text("ClawHub 市场", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
        Text(
            text = "导入指令型技能包，为对话和任务规划补充额外规则与知识。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        OutlinedTextField(
            value = query,
            onValueChange = onQueryChange,
            modifier = Modifier.fillMaxWidth(),
            label = { Text("搜索远程技能") },
            singleLine = true,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Button(onClick = onSearch) {
                Text("搜索")
            }
            TextButton(onClick = onLoadPopular) {
                Text("热门")
            }
        }
        if (error != null) {
            Text(
                text = error,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
        if (isLoading) {
            CircularProgressIndicator()
        } else if (skills.isEmpty()) {
            Text(
                text = "暂时没有可展示的远程技能。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                skills.forEach { skill ->
                    MarketplaceSkillCard(
                        skill = skill,
                        isInstalling = installingSlugs.contains(skill.slug),
                        onInstall = { onInstall(skill) },
                    )
                }
            }
        }
    }
}

@Composable
private fun MarketplaceSkillCard(
    skill: MarketplaceSkill,
    isInstalling: Boolean,
    onInstall: () -> Unit,
) {
    SkillSurface {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column(modifier = Modifier.fillMaxWidth(0.72f)) {
                Text(skill.displayName, style = MaterialTheme.typography.titleSmall)
                Text(
                    text = listOfNotNull(skill.ownerHandle, skill.version?.let { "v$it" }).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Button(onClick = onInstall, enabled = !isInstalling && !skill.installed) {
                Text(
                    when {
                        isInstalling -> "安装中…"
                        skill.installed -> "已安装"
                        else -> "安装"
                    },
                )
            }
        }
        skill.summary?.takeIf { it.isNotBlank() }?.let {
            Text(it, style = MaterialTheme.typography.bodySmall)
        }
        skill.localSkillName?.takeIf { skill.installed && it.isNotBlank() }?.let {
            Text(
                text = "本地技能名：$it",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun SkillCard(
    skill: SkillPackage,
    isUpdating: Boolean,
    onDetails: () -> Unit,
    onToggle: () -> Unit,
) {
    SkillSurface {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column(modifier = Modifier.fillMaxWidth(0.72f)) {
                Text(skill.name, style = MaterialTheme.typography.titleSmall)
                Text(
                    text = "v${skill.version} · ${skill.agentType}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = onDetails, enabled = !isUpdating) {
                    Text("详情")
                }
                Button(onClick = onToggle, enabled = !isUpdating) {
                    Text(
                        if (isUpdating) {
                            if (skill.isEnabled) "停用中…" else "启用中…"
                        } else if (skill.isEnabled) {
                            "停用"
                        } else {
                            "启用"
                        },
                    )
                }
            }
        }
        skill.description?.takeIf { it.isNotBlank() }?.let {
            Text(it, style = MaterialTheme.typography.bodyMedium)
        }
        Text(
            text = "最大实例数：${skill.maxInstances}",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun SkillDetailDialog(
    skill: SkillPackage,
    tools: List<SkillTool>,
    isLoading: Boolean,
    error: String?,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(onClick = onDismiss) {
                Text("关闭")
            }
        },
        title = { Text(skill.name) },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text(
                    text = "v${skill.version} · ${skill.agentType}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                skill.author?.takeIf { it.isNotBlank() }?.let {
                    Text("作者：$it", style = MaterialTheme.typography.bodySmall)
                }
                Text("最大实例数：${skill.maxInstances}", style = MaterialTheme.typography.bodySmall)
                Text(
                    text = if (skill.isEnabled) "状态：已启用" else "状态：已停用",
                    style = MaterialTheme.typography.bodySmall,
                )
                skill.description?.takeIf { it.isNotBlank() }?.let {
                    Text(it, style = MaterialTheme.typography.bodySmall)
                }
                Text(
                    text = "工具",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                when {
                    isLoading -> CircularProgressIndicator()
                    error != null -> Text(
                        text = error,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                    tools.isEmpty() -> Text(
                        text = "这个技能没有声明可执行工具。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    else -> tools.forEach { tool ->
                        Surface(
                            modifier = Modifier.fillMaxWidth(),
                            shape = MaterialTheme.shapes.medium,
                            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f),
                        ) {
                            Column(
                                modifier = Modifier.padding(12.dp),
                                verticalArrangement = Arrangement.spacedBy(4.dp),
                            ) {
                                Text(
                                    text = tool.name,
                                    style = MaterialTheme.typography.labelLarge,
                                    fontWeight = FontWeight.SemiBold,
                                )
                                tool.description?.takeIf { it.isNotBlank() }?.let {
                                    Text(it, style = MaterialTheme.typography.bodySmall)
                                }
                                if (tool.requiredFields.isNotEmpty()) {
                                    Text(
                                        text = "必填字段：${tool.requiredFields.joinToString()}",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                        }
                    }
                }
            }
        },
    )
}

@Composable
private fun EmptySkillsCard(
    title: String,
    body: String,
) {
    PanelSurface {
        Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
        Text(
            text = body,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun PanelSurface(content: @Composable () -> Unit) {
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

@Composable
private fun SkillSurface(content: @Composable () -> Unit) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            content()
        }
    }
}
