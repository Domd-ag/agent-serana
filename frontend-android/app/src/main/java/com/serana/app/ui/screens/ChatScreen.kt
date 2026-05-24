package com.serana.app.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.sp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.viewmodel.compose.viewModel
import com.serana.app.data.models.ChatSession
import com.serana.app.data.models.LlmMode
import com.serana.app.data.models.Message
import com.serana.app.data.models.MarketplaceSkill
import com.serana.app.data.models.Role
import com.serana.app.data.models.SkillPackage
import com.serana.app.data.models.StreamStatus
import com.serana.app.viewmodel.ChatViewModel
import com.serana.app.viewmodel.SettingsViewModel
import com.serana.app.viewmodel.SkillsViewModel
import java.time.LocalDate
import java.time.OffsetDateTime
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import androidx.compose.runtime.rememberCoroutineScope

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    viewModel: ChatViewModel = viewModel(),
) {
    val messages by viewModel.messages.collectAsState()
    val isLoading by viewModel.isLoading.collectAsState()
    val error by viewModel.error.collectAsState()
    val sessions by viewModel.sessions.collectAsState()
    val currentSessionId by viewModel.activeSessionId.collectAsState()
    val deletingSessionIds by viewModel.deletingSessionIds.collectAsState()
    val isClearingSessions by viewModel.isClearingSessions.collectAsState()
    var inputText by remember { mutableStateOf("") }
    var showSkillsDialog by rememberSaveable { mutableStateOf(false) }
    var showSettingsDialog by rememberSaveable { mutableStateOf(false) }
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()

    if (showSkillsDialog) {
        SkillsOverlayDialog(onDismiss = { showSkillsDialog = false })
    }

    if (showSettingsDialog) {
        SettingsOverlayDialog(onDismiss = { showSettingsDialog = false })
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            ModalDrawerSheet(
                modifier = Modifier.width(276.dp),
                drawerContainerColor = MaterialTheme.colorScheme.surface,
            ) {
                ButlerDrawerContent(
                    onClose = { scope.launch { drawerState.close() } },
                    sessions = sessions,
                    currentSessionId = currentSessionId,
                    deletingSessionIds = deletingSessionIds,
                    isClearingSessions = isClearingSessions,
                    onSelectSession = {
                        viewModel.loadSession(it)
                        scope.launch { drawerState.close() }
                    },
                    onDeleteSession = viewModel::deleteSession,
                    onClearAllSessions = viewModel::clearAllSessions,
                    onOpenSkills = {
                        showSkillsDialog = true
                        scope.launch { drawerState.close() }
                    },
                    onOpenSettings = {
                        showSettingsDialog = true
                        scope.launch { drawerState.close() }
                    },
                )
            }
        },
    ) {
        Scaffold(
            containerColor = MaterialTheme.colorScheme.background,
        ) { paddingValues ->
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues),
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxSize(),
                ) {
                    LazyColumn(
                        modifier = Modifier
                            .fillMaxWidth()
                            .weight(1f)
                            .padding(horizontal = 14.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        item {
                            Spacer(modifier = Modifier.height(76.dp))
                        }

                        error?.let { errorMessage ->
                            item {
                                ErrorBanner(
                                    message = errorMessage,
                                    onDismiss = viewModel::clearError,
                                )
                            }
                        }

                        itemsIndexed(messages, key = { _, message -> message.id }) { index, message ->
                            val previousUserContent = messages
                                .subList(0, index)
                                .lastOrNull { it.role == Role.USER }
                                ?.content
                            MessageBubble(
                                message = message,
                                retrySourceContent = previousUserContent,
                                onRetry = { content, assistantId ->
                                    viewModel.retryAssistantMessage(content, assistantId)
                                },
                            )
                        }
                        if (isLoading) {
                            item {
                                Surface(
                                    color = MaterialTheme.colorScheme.surface.copy(alpha = 0.52f),
                                    shape = RoundedCornerShape(999.dp),
                                    border = BorderStroke(
                                        1.dp,
                                        MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.12f),
                                    ),
                                ) {
                                    Row(
                                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                                    ) {
                                        CircularProgressIndicator(
                                            modifier = Modifier.size(11.dp),
                                            strokeWidth = 1.6.dp,
                                            color = MaterialTheme.colorScheme.primary.copy(alpha = 0.82f),
                                        )
                                        Text(
                                            text = "Serana 正在整理回复…",
                                            style = MaterialTheme.typography.labelSmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                }
                            }
                        }
                    }
                    MessageInput(
                        inputText = inputText,
                        onTextChange = { inputText = it },
                        onSend = {
                            viewModel.sendMessage(inputText)
                            inputText = ""
                        },
                        isLoading = isLoading,
                    )
                }

                FloatingHeader(
                    modifier = Modifier.align(Alignment.TopCenter),
                    onOpenMenu = { scope.launch { drawerState.open() } },
                    onNewChat = { viewModel.startNewChat() },
                )
            }
        }
    }
}

@Composable
private fun FloatingHeader(
    modifier: Modifier = Modifier,
    onOpenMenu: () -> Unit,
    onNewChat: () -> Unit,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .statusBarsPadding()
            .padding(horizontal = 10.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Row(
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            FloatingCircleButton(
                icon = Icons.Default.Menu,
                contentDescription = "打开菜单",
                onClick = onOpenMenu,
            )
            Surface(
                shape = RoundedCornerShape(999.dp),
                color = MaterialTheme.colorScheme.surface.copy(alpha = 0.92f),
                border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f)),
                tonalElevation = 1.dp,
            ) {
                Text(
                    text = "Serana",
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 7.dp),
                    style = MaterialTheme.typography.bodySmall,
                    fontWeight = FontWeight.SemiBold,
                )
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            FloatingCircleButton(
                icon = Icons.Default.Add,
                contentDescription = "新建对话",
                onClick = onNewChat,
            )
        }
    }
}

@Composable
private fun FloatingCircleButton(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    contentDescription: String,
    onClick: () -> Unit,
) {
    Surface(
        shape = CircleShape,
        color = MaterialTheme.colorScheme.surface.copy(alpha = 0.92f),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f)),
        tonalElevation = 1.dp,
        onClick = onClick,
    ) {
        Box(
            modifier = Modifier.size(32.dp),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = contentDescription,
                tint = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.size(16.dp),
            )
        }
    }
}

@Composable
private fun ButlerDrawerContent(
    onClose: () -> Unit,
    sessions: List<ChatSession>,
    currentSessionId: String?,
    deletingSessionIds: Set<String>,
    isClearingSessions: Boolean,
    onSelectSession: (String) -> Unit,
    onDeleteSession: (String) -> Unit,
    onClearAllSessions: () -> Unit,
    onOpenSkills: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    var pendingDeleteSessionId by rememberSaveable { mutableStateOf<String?>(null) }
    var showClearAllConfirmation by rememberSaveable { mutableStateOf(false) }
    val groupedSessions = remember(sessions) { groupSessionsByRelativeDay(sessions) }

    pendingDeleteSessionId?.let { sessionId ->
        AlertDialog(
            onDismissRequest = { pendingDeleteSessionId = null },
            confirmButton = {
                TextButton(
                    onClick = {
                        onDeleteSession(sessionId)
                        pendingDeleteSessionId = null
                    },
                ) {
                    Text("删除")
                }
            },
            dismissButton = {
                TextButton(onClick = { pendingDeleteSessionId = null }) {
                    Text("取消")
                }
            },
            title = { Text("删除会话") },
            text = { Text("删除后将无法恢复这段对话记录。") },
        )
    }

    if (showClearAllConfirmation) {
        AlertDialog(
            onDismissRequest = { showClearAllConfirmation = false },
            confirmButton = {
                TextButton(
                    onClick = {
                        onClearAllSessions()
                        showClearAllConfirmation = false
                    },
                    enabled = !isClearingSessions,
                ) {
                    Text(if (isClearingSessions) "清空中…" else "全部清空")
                }
            },
            dismissButton = {
                TextButton(
                    onClick = { showClearAllConfirmation = false },
                    enabled = !isClearingSessions,
                ) {
                    Text("取消")
                }
            },
            title = { Text("清空全部会话") },
            text = { Text("这会删除所有历史会话记录，并且无法恢复。") },
        )
    }

    Column(
        modifier = Modifier
            .fillMaxHeight()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 12.dp, vertical = 14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text("Serana", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            }
            TextButton(onClick = onClose) {
                Text("收起")
            }
        }

        DrawerMenuPanel(
            items = listOf(
                DrawerMenuItem(
                    title = "技能",
                    icon = Icons.Default.AutoAwesome,
                    onClick = onOpenSkills,
                ),
                DrawerMenuItem(
                    title = "设置",
                    icon = Icons.Default.Settings,
                    onClick = onOpenSettings,
                ),
            ),
        )

        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 10.dp)
                .height(1.dp),
            color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.42f),
        ) {}

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 2.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("最近对话", style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Medium)
                Row(horizontalArrangement = Arrangement.spacedBy(2.dp), verticalAlignment = Alignment.CenterVertically) {
                    TextButton(
                        onClick = { showClearAllConfirmation = true },
                        enabled = sessions.isNotEmpty() && !isClearingSessions,
                    ) {
                        Text(if (isClearingSessions) "清空中…" else "清空")
                    }
                }
            }

            if (groupedSessions.isEmpty()) {
                Text(
                    "还没有历史会话。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                groupedSessions.forEach { group ->
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(3.dp),
                        ) {
                            Icon(
                                imageVector = Icons.Default.KeyboardArrowDown,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.size(14.dp),
                            )
                            Text(
                                text = group.title,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                            group.sessions.forEach { session ->
                                val isCurrent = session.id == currentSessionId
                                val isDeleting = deletingSessionIds.contains(session.id)
                                Surface(
                                    modifier = Modifier.fillMaxWidth(),
                                    shape = RoundedCornerShape(12.dp),
                                    color = if (isCurrent) {
                                        MaterialTheme.colorScheme.primary.copy(alpha = 0.08f)
                                    } else {
                                    Color.Transparent
                                },
                            ) {
                                Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(start = 3.dp, end = 2.dp, top = 1.dp, bottom = 1.dp),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                    TextButton(
                                        onClick = { onSelectSession(session.id) },
                                        modifier = Modifier.weight(1f),
                                    ) {
                                        Text(
                                            text = session.title?.ifBlank { "未命名会话" } ?: "未命名会话",
                                            maxLines = 1,
                                            style = MaterialTheme.typography.bodySmall,
                                            fontWeight = if (isCurrent) FontWeight.Medium else FontWeight.Normal,
                                            color = if (isCurrent) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
                                        )
                                    }
                                    IconButton(
                                        onClick = { pendingDeleteSessionId = session.id },
                                        enabled = !isDeleting && !isClearingSessions,
                                        modifier = Modifier.size(28.dp),
                                    ) {
                                        Icon(
                                            imageVector = Icons.Default.Delete,
                                            contentDescription = "删除会话",
                                            tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.72f),
                                            modifier = Modifier.size(14.dp),
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

private data class SessionGroup(
    val title: String,
    val sessions: List<ChatSession>,
)

private fun groupSessionsByRelativeDay(sessions: List<ChatSession>): List<SessionGroup> {
    val today = LocalDate.now()
    val yesterday = today.minusDays(1)

    fun toLocalDate(raw: String): LocalDate? {
        return runCatching { OffsetDateTime.parse(raw).toLocalDate() }.getOrNull()
    }

    val grouped = linkedMapOf<String, MutableList<ChatSession>>()
    sessions.forEach { session ->
        val date = toLocalDate(session.updatedAt)
        val key = when (date) {
            today -> "今天"
            yesterday -> "昨天"
            else -> "更早"
        }
        grouped.getOrPut(key) { mutableListOf() }.add(session)
    }

    return grouped.entries.map { SessionGroup(it.key, it.value) }
}

private data class DrawerMenuItem(
    val title: String,
    val icon: androidx.compose.ui.graphics.vector.ImageVector,
    val onClick: () -> Unit,
)

@Composable
private fun DrawerMenuPanel(
    items: List<DrawerMenuItem>,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(24.dp),
        color = MaterialTheme.colorScheme.surface.copy(alpha = 0.94f),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.68f)),
        tonalElevation = 1.dp,
    ) {
        Column {
            items.forEachIndexed { index, item ->
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    color = Color.Transparent,
                    onClick = item.onClick,
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp, vertical = 13.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Icon(
                            imageVector = item.icon,
                            contentDescription = item.title,
                            tint = MaterialTheme.colorScheme.primary.copy(alpha = 0.9f),
                            modifier = Modifier.size(15.dp),
                        )
                        Text(
                            text = item.title,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    }
                }

                if (index != items.lastIndex) {
                    Spacer(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(1.dp)
                            .padding(horizontal = 12.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun SkillsOverlayDialog(
    onDismiss: () -> Unit,
    viewModel: SkillsViewModel = viewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    val marketplaceSkills by viewModel.marketplaceSkills.collectAsState()
    val marketplaceLoading by viewModel.marketplaceLoading.collectAsState()
    val marketplaceError by viewModel.marketplaceError.collectAsState()
    val updatingSkillNames by viewModel.updatingSkillNames.collectAsState()
    val installingMarketplaceSlugs by viewModel.installingMarketplaceSlugs.collectAsState()
    var marketplaceQuery by remember { mutableStateOf("") }
    var showMarketplace by rememberSaveable { mutableStateOf(true) }

    val filteredSkills = uiState.data

    OverlayDialogScaffold(
        title = "技能",
        subtitle = "从 ClawHub 安装新技能，或管理已安装技能。",
        onDismiss = onDismiss,
    ) {
        SkillSourceSelector(
            showMarketplace = showMarketplace,
            onSelectLocal = { showMarketplace = false },
            onSelectMarketplace = { showMarketplace = true },
        )

        AnimatedVisibility(
            visible = !showMarketplace,
            enter = fadeIn() + expandVertically(),
            exit = fadeOut(),
        ) {
            OverlaySection(
                title = "本地技能",
                subtitle = "这些技能已经安装在当前设备上。",
            ) {
                if (uiState.isLoading) {
                    CircularProgressIndicator()
                } else if (filteredSkills.isEmpty()) {
                    Text(
                        "当前没有匹配的本地技能。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    filteredSkills.take(6).forEach { skill ->
                        Surface(
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(18.dp),
                            color = MaterialTheme.colorScheme.surface.copy(alpha = 0.78f),
                            border = BorderStroke(
                                1.dp,
                                MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.24f),
                            ),
                        ) {
                            Column(
                                modifier = Modifier.padding(12.dp),
                                verticalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(skill.name, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium)
                                        SkillMetaText(if (skill.isEnabled) "已启用" else "已停用")
                                    }
                                    AssistChip(
                                    onClick = { viewModel.toggleSkill(skill) },
                                    enabled = !updatingSkillNames.contains(skill.name),
                                    label = {
                                        Text(
                                            if (skill.isEnabled) {
                                                "停用"
                                            } else {
                                                "启用"
                                            },
                                        )
                                        },
                                    )
                                }
                                skill.description?.takeIf { it.isNotBlank() }?.let {
                                    Text(
                                        it,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                                skill.author?.takeIf { it.isNotBlank() }?.let {
                                    SkillMetaText(it)
                                }
                            }
                        }
                    }
                }
            }
        }

        AnimatedVisibility(
            visible = showMarketplace,
            enter = fadeIn() + expandVertically(),
            exit = fadeOut(),
        ) {
            OverlaySection(
                title = "远程技能",
                subtitle = "从 ClawHub 浏览并安装新的技能。",
            ) {
                OutlinedTextField(
                    value = marketplaceQuery,
                    onValueChange = { marketplaceQuery = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("搜索远程技能") },
                    singleLine = true,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { viewModel.searchMarketplace(marketplaceQuery) }) {
                        Text("搜索")
                    }
                    TextButton(onClick = {
                        marketplaceQuery = ""
                        viewModel.loadMarketplace()
                    }) {
                        Text("热门")
                    }
                }
                marketplaceError?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
                if (marketplaceLoading) {
                    CircularProgressIndicator()
                } else {
                    marketplaceSkills.take(4).forEach { skill ->
                        Surface(
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(18.dp),
                            color = MaterialTheme.colorScheme.surface.copy(alpha = 0.78f),
                            border = BorderStroke(
                                1.dp,
                                MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.24f),
                            ),
                        ) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(12.dp),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(skill.displayName, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium)
                                    skill.summary?.takeIf { it.isNotBlank() }?.let {
                                        Text(
                                            it,
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                }
                                AssistChip(
                                    onClick = { viewModel.installMarketplaceSkill(skill) },
                                    enabled = !skill.installed && !installingMarketplaceSlugs.contains(skill.slug),
                                    label = {
                                        Text(
                                            when {
                                                installingMarketplaceSlugs.contains(skill.slug) -> "安装中…"
                                                skill.installed -> "已安装"
                                                else -> "安装"
                                            },
                                        )
                                    },
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SettingsOverlayDialog(
    onDismiss: () -> Unit,
    viewModel: SettingsViewModel = viewModel(),
) {
    val uiState = viewModel.uiState.collectAsState().value
    var showApiKey by rememberSaveable { mutableStateOf(false) }

    OverlayDialogScaffold(
        title = "设置",
        subtitle = "模型路由与服务配置",
        onDismiss = onDismiss,
    ) {
        if (uiState.isLoading) {
            CircularProgressIndicator()
        } else {
            uiState.error?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            uiState.statusMessage?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary,
                )
            }

            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text("LLM 模式", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                OverlayModeSelector(
                    mode = uiState.mode,
                    onSelect = viewModel::updateMode,
                )
            }

            AnimatedVisibility(
                visible = uiState.mode == LlmMode.USER_CONFIG,
                enter = fadeIn() + expandVertically(),
                exit = fadeOut(),
            ) {
                OverlaySection(
                    title = "个人配置",
                    subtitle = "",
                ) {
                    OutlinedTextField(
                        value = uiState.model,
                        onValueChange = viewModel::updateModel,
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("模型") },
                        isError = uiState.modelError != null,
                        supportingText = {
                            uiState.modelError?.let { Text(it) }
                        },
                    )
                    OutlinedTextField(
                        value = uiState.baseUrl,
                        onValueChange = viewModel::updateBaseUrl,
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Base URL") },
                        isError = uiState.baseUrlError != null,
                        supportingText = {
                            uiState.baseUrlError?.let { Text(it) }
                        },
                    )
                    OutlinedTextField(
                        value = uiState.apiKey,
                        onValueChange = viewModel::updateApiKey,
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("API Key") },
                        isError = uiState.apiKeyError != null,
                        visualTransformation = if (showApiKey) VisualTransformation.None else PasswordVisualTransformation(),
                        trailingIcon = {
                            IconButton(onClick = { showApiKey = !showApiKey }) {
                                Icon(
                                    imageVector = if (showApiKey) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                                    contentDescription = if (showApiKey) "隐藏 API Key" else "显示 API Key",
                                )
                            }
                        },
                        supportingText = {
                            uiState.apiKeyError?.let { Text(it) }
                        },
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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
private fun OverlayDialogScaffold(
    title: String,
    subtitle: String,
    onDismiss: () -> Unit,
    content: @Composable ColumnScope.() -> Unit,
) {
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 24.dp),
            shape = RoundedCornerShape(30.dp),
            color = MaterialTheme.colorScheme.surface.copy(alpha = 0.98f),
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f)),
            tonalElevation = 1.dp,
            shadowElevation = 2.dp,
        ) {
            Column(
                modifier = Modifier.fillMaxWidth(),
            ) {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    color = MaterialTheme.colorScheme.surface.copy(alpha = 0.98f),
                    shadowElevation = 1.dp,
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 18.dp, vertical = 14.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                            Text(
                                subtitle,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        AssistChip(
                            onClick = onDismiss,
                            label = { Text("关闭") },
                        )
                    }
                }
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .animateContentSize()
                        .padding(horizontal = 16.dp, vertical = 12.dp)
                        .verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    content()
                }
            }
        }
    }
}

@Composable
private fun OverlaySection(
    title: String,
    subtitle: String,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(22.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.26f),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.44f)),
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(9.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                if (subtitle.isNotBlank()) {
                    Text(
                        subtitle,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            content()
        }
    }
}

@Composable
private fun OverlayModeSelector(
    mode: LlmMode,
    onSelect: (LlmMode) -> Unit,
) {
    val isUserConfig = mode == LlmMode.USER_CONFIG
    val description = if (isUserConfig) {
        "使用你自己的模型、Base URL 和 API Key。"
    } else {
        "使用后端统一维护的默认模型配置，适合直接开始对话。"
    }

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        BoxWithConstraints(
            modifier = Modifier
                .fillMaxWidth()
                .height(42.dp),
        ) {
            val segmentWidth = maxWidth / 2
            val indicatorOffset by animateDpAsState(
                targetValue = if (isUserConfig) segmentWidth else 0.dp,
                label = "mode_selector_offset",
            )

            Surface(
                modifier = Modifier.fillMaxSize(),
                shape = RoundedCornerShape(14.dp),
                color = MaterialTheme.colorScheme.surface.copy(alpha = 0.92f),
                border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.52f)),
            ) {
                Box(modifier = Modifier.fillMaxSize()) {
                    Surface(
                        modifier = Modifier
                            .padding(3.dp)
                            .width(segmentWidth - 3.dp)
                            .fillMaxHeight()
                            .offset(x = indicatorOffset),
                        shape = RoundedCornerShape(11.dp),
                        color = MaterialTheme.colorScheme.primary.copy(alpha = 0.9f),
                    ) {}

                    Row(modifier = Modifier.fillMaxSize()) {
                        Box(
                            modifier = Modifier
                                .weight(1f)
                                .fillMaxHeight()
                                .clickable { onSelect(LlmMode.BACKEND_DEFAULT) },
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                text = "默认",
                                style = MaterialTheme.typography.bodySmall,
                                color = if (isUserConfig) MaterialTheme.colorScheme.onSurface else Color.White,
                                fontWeight = FontWeight.Medium,
                            )
                        }
                        Box(
                            modifier = Modifier
                                .weight(1f)
                                .fillMaxHeight()
                                .clickable { onSelect(LlmMode.USER_CONFIG) },
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                text = "个人配置",
                                style = MaterialTheme.typography.bodySmall,
                                color = if (isUserConfig) Color.White else MaterialTheme.colorScheme.onSurface,
                                fontWeight = FontWeight.Medium,
                            )
                        }
                    }
                }
            }
        }
        Text(
            text = description,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun AssistChipRow(
    items: List<String>,
    onSelect: (String) -> Unit,
) {
    Row(
        modifier = Modifier.horizontalScroll(rememberScrollState()),
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
fun ErrorBanner(
    message: String,
    onDismiss: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        color = MaterialTheme.colorScheme.errorContainer,
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.error.copy(alpha = 0.28f)),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = message,
                modifier = Modifier.weight(1f),
                color = MaterialTheme.colorScheme.onErrorContainer,
                style = MaterialTheme.typography.bodySmall,
            )
            TextButton(onClick = onDismiss) {
                Text("关闭")
            }
        }
    }
}

@Composable
private fun SkillMetaText(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

@Composable
private fun SkillSourceSelector(
    showMarketplace: Boolean,
    onSelectLocal: () -> Unit,
    onSelectMarketplace: () -> Unit,
) {
    val description = if (showMarketplace) {
        "从 ClawHub 浏览并安装新的技能。"
    } else {
        "查看当前设备上已经安装的技能。"
    }

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        BoxWithConstraints(
            modifier = Modifier
                .fillMaxWidth()
                .height(40.dp),
        ) {
            val segmentWidth = maxWidth / 2
            val indicatorOffset by animateDpAsState(
                targetValue = if (showMarketplace) 0.dp else segmentWidth,
                label = "skill_source_selector_offset",
            )

            Surface(
                modifier = Modifier.fillMaxSize(),
                shape = RoundedCornerShape(14.dp),
                color = MaterialTheme.colorScheme.surface.copy(alpha = 0.92f),
                border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.52f)),
            ) {
                Box(modifier = Modifier.fillMaxSize()) {
                    Surface(
                        modifier = Modifier
                            .padding(3.dp)
                            .width(segmentWidth - 3.dp)
                            .fillMaxHeight()
                            .offset(x = indicatorOffset),
                        shape = RoundedCornerShape(11.dp),
                        color = MaterialTheme.colorScheme.primary.copy(alpha = 0.9f),
                    ) {}

                    Row(modifier = Modifier.fillMaxSize()) {
                        Box(
                            modifier = Modifier
                                .weight(1f)
                                .fillMaxHeight()
                                .clickable { onSelectMarketplace() },
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                text = "远程",
                                style = MaterialTheme.typography.bodySmall,
                                color = if (showMarketplace) Color.White else MaterialTheme.colorScheme.onSurface,
                                fontWeight = FontWeight.Medium,
                            )
                        }
                        Box(
                            modifier = Modifier
                                .weight(1f)
                                .fillMaxHeight()
                                .clickable { onSelectLocal() },
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                text = "本地",
                                style = MaterialTheme.typography.bodySmall,
                                color = if (showMarketplace) MaterialTheme.colorScheme.onSurface else Color.White,
                                fontWeight = FontWeight.Medium,
                            )
                        }
                    }
                }
            }
        }
        Text(
            text = description,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun MessageBubble(
    message: Message,
    retrySourceContent: String?,
    onRetry: (String, String) -> Unit,
) {
    val isUser = message.role == Role.USER
    val isDarkTheme = isSystemInDarkTheme()
    val isWelcomeNote = !isUser && (
        message.content == "New chat started. Send a message when you are ready." ||
            message.content == "新的对话已准备好，随时告诉 Serana 你想做什么。"
        )
    val backgroundColor = when {
        isUser -> MaterialTheme.colorScheme.primary.copy(alpha = 0.88f)
        isWelcomeNote -> MaterialTheme.colorScheme.surface.copy(alpha = if (isDarkTheme) 0.96f else 0.62f)
        else -> if (isDarkTheme) {
            MaterialTheme.colorScheme.surface.copy(alpha = 0.98f)
        } else {
            Color.White.copy(alpha = 0.96f)
        }
    }
    val textColor = if (isUser) Color.White else MaterialTheme.colorScheme.onSurface
    val activeStreaming = !isUser && message.streamStatus in setOf(
        StreamStatus.THINKING,
        StreamStatus.STREAMING,
        StreamStatus.RETRYING,
    )
    var showFinalizedBadge by rememberSaveable(message.id, message.streamStatus) { mutableStateOf(false) }

    LaunchedEffect(message.id, message.streamStatus) {
        showFinalizedBadge = message.streamStatus == StreamStatus.FINALIZED
        if (message.streamStatus == StreamStatus.FINALIZED) {
            delay(1800)
            showFinalizedBadge = false
        }
    }

    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
    ) {
        Surface(
            modifier = Modifier.fillMaxWidth(
                when {
                    isUser -> 0.76f
                    isWelcomeNote -> 0.84f
                    else -> 0.92f
                },
            ),
            shape = RoundedCornerShape(
                topStart = 18.dp,
                topEnd = 18.dp,
                bottomStart = if (isUser) 18.dp else if (isWelcomeNote) 18.dp else 8.dp,
                bottomEnd = if (isUser) 8.dp else 18.dp,
            ),
            color = backgroundColor,
            shadowElevation = when {
                isUser -> 0.dp
                isWelcomeNote -> 0.dp
                else -> 1.dp
            },
            border = if (isUser) {
                null
            } else if (isWelcomeNote) {
                BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.16f))
            } else {
                BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.22f))
            },
        ) {
            Column(
                modifier = Modifier.padding(
                    horizontal = if (isWelcomeNote) 13.dp else 14.dp,
                    vertical = if (isWelcomeNote) 10.dp else 11.dp,
                ),
                verticalArrangement = Arrangement.spacedBy(if (isWelcomeNote) 6.dp else 8.dp),
            ) {
                Text(
                    text = message.content.ifBlank { if (activeStreaming) " " else "" },
                    color = textColor,
                    style = (if (isWelcomeNote) MaterialTheme.typography.bodySmall else MaterialTheme.typography.bodyMedium).copy(
                        lineHeight = if (isWelcomeNote) 20.sp else 22.sp,
                        letterSpacing = 0.sp,
                    ),
                )
                if (activeStreaming) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.Start,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(12.dp),
                            strokeWidth = 1.8.dp,
                            color = if (isUser) Color.White.copy(alpha = 0.9f) else MaterialTheme.colorScheme.primary,
                        )
                    }
                }
                if (message.timestamp.isNotBlank()) {
                    Text(
                        text = message.timestamp.take(19).replace("T", " "),
                        color = textColor.copy(alpha = 0.56f),
                        style = MaterialTheme.typography.labelSmall,
                    )
                }
            }
        }

        if (!isUser && showFinalizedBadge) {
            Spacer(modifier = Modifier.height(6.dp))
            StatusPill("已完成", MaterialTheme.colorScheme.secondary)
        }

        if (!isUser && message.streamStatus == StreamStatus.FAILED) {
            Spacer(modifier = Modifier.height(6.dp))
            StatusPill("请求失败", MaterialTheme.colorScheme.error)
        }

        if (
            !isUser &&
            (message.streamStatus == StreamStatus.FAILED || message.streamStatus == StreamStatus.RETRYING) &&
            !retrySourceContent.isNullOrBlank()
        ) {
            TextButton(
                onClick = { onRetry(retrySourceContent, message.id) },
                enabled = message.streamStatus == StreamStatus.FAILED,
            ) {
                Text(if (message.streamStatus == StreamStatus.RETRYING) "重试中…" else "重试")
            }
        }
    }
}

@Composable
private fun StatusPill(
    label: String,
    color: Color,
) {
    Surface(
        color = color.copy(alpha = 0.14f),
        shape = RoundedCornerShape(999.dp),
    ) {
        Text(
            text = label,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
            style = MaterialTheme.typography.labelSmall,
            color = color,
        )
    }
}

@Composable
private fun MessageInput(
    inputText: String,
    onTextChange: (String) -> Unit,
    onSend: () -> Unit,
    isLoading: Boolean,
) {
    val isDarkTheme = isSystemInDarkTheme()
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp)
            .navigationBarsPadding()
            .padding(bottom = 6.dp),
        shape = RoundedCornerShape(20.dp),
        color = if (isDarkTheme) {
            MaterialTheme.colorScheme.surface.copy(alpha = 0.98f)
        } else {
            Color.White.copy(alpha = 0.93f)
        },
        shadowElevation = 1.dp,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.12f)),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value = inputText,
                onValueChange = onTextChange,
                modifier = Modifier.weight(1f),
                placeholder = {
                    Text(
                        "告诉 Serana 你想做什么…",
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.72f),
                    )
                },
                shape = RoundedCornerShape(18.dp),
                maxLines = 4,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { onSend() }),
                enabled = !isLoading,
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = Color.Transparent,
                    unfocusedContainerColor = Color.Transparent,
                    disabledContainerColor = Color.Transparent,
                    focusedIndicatorColor = Color.Transparent,
                    unfocusedIndicatorColor = Color.Transparent,
                    disabledIndicatorColor = Color.Transparent,
                ),
            )
            Spacer(modifier = Modifier.size(8.dp))
            Surface(
                shape = CircleShape,
                color = if (inputText.isNotBlank() && !isLoading) {
                    MaterialTheme.colorScheme.primary.copy(alpha = 0.88f)
                } else {
                    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.58f)
                },
                onClick = {
                    if (inputText.isNotBlank() && !isLoading) {
                        onSend()
                    }
                },
            ) {
                Box(
                    modifier = Modifier.size(32.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.Send,
                        contentDescription = "发送",
                        tint = if (inputText.isNotBlank() && !isLoading) {
                            Color.White
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                        modifier = Modifier.size(14.dp),
                    )
                }
            }
        }
    }
}

