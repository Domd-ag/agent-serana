package com.serana.app.ui.screens

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.serana.app.data.models.ApprovalRequest
import com.serana.app.data.models.MarketplaceSkill
import com.serana.app.data.models.SkillLifecycleStatus
import com.serana.app.data.models.SkillPackage
import com.serana.app.data.models.SkillTool
import com.serana.app.viewmodel.SkillsViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SkillsScreen(
    viewModel: SkillsViewModel = viewModel(),
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val uiState by viewModel.uiState.collectAsState()
    val selectedSkill by viewModel.selectedSkill.collectAsState()
    val selectedSkillTools by viewModel.selectedSkillTools.collectAsState()
    val selectedSkillLifecycle by viewModel.selectedSkillLifecycle.collectAsState()
    val isDetailLoading by viewModel.isDetailLoading.collectAsState()
    val detailError by viewModel.detailError.collectAsState()
    val updatingSkillNames by viewModel.updatingSkillNames.collectAsState()
    val removingSkillNames by viewModel.removingSkillNames.collectAsState()
    val updatingRemoteSkillNames by viewModel.updatingRemoteSkillNames.collectAsState()
    val marketplaceSkills by viewModel.marketplaceSkills.collectAsState()
    val marketplaceLoading by viewModel.marketplaceLoading.collectAsState()
    val marketplaceError by viewModel.marketplaceError.collectAsState()
    val installingMarketplaceSlugs by viewModel.installingMarketplaceSlugs.collectAsState()
    val pendingMarketplaceApproval by viewModel.pendingMarketplaceApproval.collectAsState()
    val submittingMarketplaceApproval by viewModel.submittingMarketplaceApproval.collectAsState()
    val pendingLocalApproval by viewModel.pendingLocalApproval.collectAsState()
    val submittingLocalApproval by viewModel.submittingLocalApproval.collectAsState()
    val uploadingLocalSkill by viewModel.uploadingLocalSkill.collectAsState()
    val pendingUploadApproval by viewModel.pendingUploadApproval.collectAsState()
    val submittingUploadApproval by viewModel.submittingUploadApproval.collectAsState()
    val pendingUpdateApproval by viewModel.pendingUpdateApproval.collectAsState()
    val submittingUpdateApproval by viewModel.submittingUpdateApproval.collectAsState()
    var query by remember { mutableStateOf("") }
    var filter by remember { mutableStateOf("全部") }
    var marketplaceQuery by remember { mutableStateOf("") }

    val importLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument(),
    ) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        scope.launch {
            val archive = withContext(Dispatchers.IO) {
                readSkillArchiveFromUri(context, uri)
            }
            if (archive == null) {
                viewModel.showSkillError("无法读取所选技能压缩包")
                return@launch
            }
            viewModel.uploadSkillArchive(
                fileName = archive.first,
                fileBytes = archive.second,
            )
        }
    }

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
            lifecycle = selectedSkillLifecycle,
            tools = selectedSkillTools,
            isLoading = isDetailLoading,
            error = detailError,
            isRemoving = removingSkillNames.contains(skill.name),
            isUpdating = updatingRemoteSkillNames.contains(skill.name) || updatingSkillNames.contains(skill.name),
            onRemove = { viewModel.removeSkill(skill) },
            onUpdate = { viewModel.updateRemoteSkill(skill) },
            onScopeChange = { viewModel.updateSkillScope(skill, it) },
            onDismiss = viewModel::dismissSkillDetail,
        )
    }

    pendingMarketplaceApproval?.let { approval ->
        SkillApprovalDialog(
            request = approval,
            isSubmitting = submittingMarketplaceApproval,
            onApprove = viewModel::approveMarketplaceInstall,
            onDeny = viewModel::denyMarketplaceInstall,
            confirmLabel = "允许安装",
            dismissLabel = "取消",
        )
    }

    pendingLocalApproval?.let { approval ->
        SkillApprovalDialog(
            request = approval,
            isSubmitting = submittingLocalApproval,
            onApprove = viewModel::approveSkillRemoval,
            onDeny = viewModel::denySkillRemoval,
            confirmLabel = "确认卸载",
            dismissLabel = "保留技能",
        )
    }

    pendingUploadApproval?.let { approval ->
        SkillApprovalDialog(
            request = approval,
            isSubmitting = submittingUploadApproval,
            onApprove = viewModel::approveSkillUpload,
            onDeny = viewModel::denySkillUpload,
            confirmLabel = "确认导入",
            dismissLabel = "取消导入",
        )
    }

    pendingUpdateApproval?.let { approval ->
        SkillApprovalDialog(
            request = approval,
            isSubmitting = submittingUpdateApproval,
            onApprove = viewModel::approveSkillUpdate,
            onDeny = viewModel::denySkillUpdate,
            confirmLabel = "确认更新",
            dismissLabel = "取消",
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
                isUploading = uploadingLocalSkill,
                onImportZip = {
                    importLauncher.launch(
                        arrayOf(
                            "application/zip",
                            "application/x-zip-compressed",
                            "application/octet-stream",
                            "*/*",
                        ),
                    )
                },
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
                    body = "可以从 SkillHub 市场安装，也可以导入本地 ZIP 技能包。",
                )
            } else if (filteredSkills.isEmpty()) {
                EmptySkillsCard(
                    title = "没有匹配结果",
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
                            isUpdating = updatingSkillNames.contains(skill.name) || removingSkillNames.contains(skill.name),
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
private fun SkillApprovalDialog(
    request: ApprovalRequest,
    isSubmitting: Boolean,
    onApprove: () -> Unit,
    onDeny: () -> Unit,
    confirmLabel: String,
    dismissLabel: String,
) {
    AlertDialog(
        onDismissRequest = {},
        confirmButton = {
            Button(onClick = onApprove, enabled = !isSubmitting) {
                Text(if (isSubmitting) "提交中..." else confirmLabel)
            }
        },
        dismissButton = {
            TextButton(onClick = onDeny, enabled = !isSubmitting) {
                Text(dismissLabel)
            }
        },
        title = { Text(request.title) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    text = request.summary,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = when (request.riskLevel.lowercase()) {
                        "high" -> "高风险"
                        "medium" -> "中风险"
                        else -> "低风险"
                    },
                    style = MaterialTheme.typography.labelMedium,
                    color = when (request.riskLevel.lowercase()) {
                        "high" -> MaterialTheme.colorScheme.error
                        "medium" -> MaterialTheme.colorScheme.primary
                        else -> MaterialTheme.colorScheme.secondary
                    },
                )
                skillApprovalRows(request).forEach { (label, value) ->
                    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text(
                            text = label,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Text(
                            text = value,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    }
                }
            }
        },
    )
}

private fun skillApprovalRows(request: ApprovalRequest): List<Pair<String, String>> {
    val rows = mutableListOf<Pair<String, String>>()
    request.details["slug"]?.toString()?.takeIf { it.isNotBlank() }?.let {
        rows += "技能" to it
    }
    request.details["skill_name"]?.toString()?.takeIf { it.isNotBlank() }?.let {
        rows += "技能" to it
    }
    request.details["version"]?.toString()?.takeIf { it.isNotBlank() }?.let {
        rows += "版本" to it
    }
    request.details["filename"]?.toString()?.takeIf { it.isNotBlank() }?.let {
        rows += "文件" to it
    }
    request.details["origin"]?.toString()?.takeIf { it.isNotBlank() }?.let {
        rows += "来源" to if (it.equals("managed", ignoreCase = true)) "已安装技能" else it
    }
    request.details["reason"]?.toString()?.takeIf { it.isNotBlank() }?.let {
        rows += "原因" to it
    }
    return rows
}

@Composable
private fun SkillsOverviewPanel(
    query: String,
    onQueryChange: (String) -> Unit,
    filter: String,
    onFilterChange: (String) -> Unit,
    shownCount: Int,
    isUploading: Boolean,
    onImportZip: () -> Unit,
) {
    PanelSurface {
        Text("已安装技能", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
        Text(
            text = "管理本地技能包，以及它们是否参与当前运行时。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                text = "支持导入本地 ZIP 技能包",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Button(onClick = onImportZip, enabled = !isUploading) {
                Text(if (isUploading) "导入中..." else "导入 ZIP")
            }
        }
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
        Text("SkillHub 市场", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
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
                        isInstalling -> "安装中..."
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
                    text = "v${skill.version} · ${skill.sourceLabel}",
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
                            if (skill.isEnabled) "停用中..." else "启用中..."
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
            text = "范围：${scopeLabel(skill.effectiveScope)} · 信任：${trustLabel(skill.trustState)}",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun SkillDetailDialog(
    skill: SkillPackage,
    lifecycle: SkillLifecycleStatus?,
    tools: List<SkillTool>,
    isLoading: Boolean,
    error: String?,
    isRemoving: Boolean,
    isUpdating: Boolean,
    onRemove: () -> Unit,
    onUpdate: () -> Unit,
    onScopeChange: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(onClick = onDismiss) {
                Text("关闭")
            }
        },
        dismissButton = if (skill.canUninstall) {
            {
                TextButton(onClick = onRemove, enabled = !isRemoving) {
                    Text(if (isRemoving) "卸载中..." else "卸载技能")
                }
            }
        } else {
            null
        },
        title = { Text(skill.name) },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text(
                    text = "v${skill.version} · ${skill.sourceLabel}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                skill.author?.takeIf { it.isNotBlank() }?.let {
                    Text("作者：$it", style = MaterialTheme.typography.bodySmall)
                }
                Text(
                    text = if (skill.isEnabled) "状态：已启用" else "状态：已停用",
                    style = MaterialTheme.typography.bodySmall,
                )
                Text(
                    text = "信任状态：${trustLabel(lifecycle?.trustState ?: skill.trustState)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                lifecycle?.sourceUrl?.takeIf { it.isNotBlank() }?.let {
                    Text(
                        text = "来源：$it",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                SkillScopeSelector(
                    selected = lifecycle?.effectiveScope ?: skill.effectiveScope,
                    enabled = !isUpdating,
                    onScopeChange = onScopeChange,
                )
                if ((lifecycle?.canUpdate == true || skill.canUpdate) && lifecycle?.updateAvailable == true) {
                    Button(onClick = onUpdate, enabled = !isUpdating) {
                        Text(
                            if (isUpdating) {
                                "更新中..."
                            } else {
                                "更新到 v${lifecycle.latestVersion ?: "latest"}"
                            },
                        )
                    }
                } else if (lifecycle?.canUpdate == true || skill.canUpdate) {
                    Text(
                        text = "当前已经是最新版本",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
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
private fun SkillScopeSelector(
    selected: String,
    enabled: Boolean,
    onScopeChange: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(
            text = "生效范围",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            listOf("all", "serana", "aide", "forge").forEach { scope ->
                AssistChip(
                    onClick = { onScopeChange(scope) },
                    label = { Text(scopeLabel(scope)) },
                    enabled = enabled && selected != scope,
                )
            }
        }
    }
}

private fun scopeLabel(scope: String): String {
    return when (scope.lowercase()) {
        "all" -> "全部"
        "serana" -> "Serana"
        "aide" -> "Aide"
        "forge" -> "Forge"
        else -> scope
    }
}

private fun trustLabel(trustState: String): String {
    return when (trustState.lowercase()) {
        "trusted" -> "项目可信"
        "marketplace" -> "市场来源"
        "local" -> "本地导入"
        else -> trustState
    }
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

private fun readSkillArchiveFromUri(context: Context, uri: Uri): Pair<String, ByteArray>? {
    val fileName = resolveDisplayName(context, uri) ?: "skill.zip"
    val bytes = context.contentResolver.openInputStream(uri)?.use { input ->
        input.readBytes()
    } ?: return null
    return fileName to bytes
}

private fun resolveDisplayName(context: Context, uri: Uri): String? {
    context.contentResolver.query(
        uri,
        arrayOf(OpenableColumns.DISPLAY_NAME),
        null,
        null,
        null,
    )?.use { cursor ->
        val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
        if (nameIndex >= 0 && cursor.moveToFirst()) {
            return cursor.getString(nameIndex)
        }
    }
    return null
}
