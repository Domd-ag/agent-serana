package com.serana.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.serana.app.data.api.ApprovalDecisionRequest
import com.serana.app.data.api.ApprovalRequestDto
import com.serana.app.data.api.MarketplaceInstallRequest
import com.serana.app.data.api.RetrofitClient
import com.serana.app.data.api.SkillScopeUpdateRequest
import com.serana.app.data.api.SkillUpdateRequest
import com.serana.app.data.models.ApprovalRequest
import com.serana.app.data.models.MarketplaceSkill
import com.serana.app.data.models.SkillLifecycleStatus
import com.serana.app.data.models.SkillPackage
import com.serana.app.data.models.SkillTool
import com.serana.app.ui.state.LoadableState
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import retrofit2.Response

class SkillsViewModel : ViewModel() {
    private val _uiState = MutableStateFlow(LoadableState(data = emptyList<SkillPackage>(), isLoading = true))
    val uiState: StateFlow<LoadableState<List<SkillPackage>>> = _uiState.asStateFlow()

    private val _selectedSkill = MutableStateFlow<SkillPackage?>(null)
    val selectedSkill: StateFlow<SkillPackage?> = _selectedSkill.asStateFlow()

    private val _selectedSkillTools = MutableStateFlow<List<SkillTool>>(emptyList())
    val selectedSkillTools: StateFlow<List<SkillTool>> = _selectedSkillTools.asStateFlow()

    private val _selectedSkillLifecycle = MutableStateFlow<SkillLifecycleStatus?>(null)
    val selectedSkillLifecycle: StateFlow<SkillLifecycleStatus?> = _selectedSkillLifecycle.asStateFlow()

    private val _isDetailLoading = MutableStateFlow(false)
    val isDetailLoading: StateFlow<Boolean> = _isDetailLoading.asStateFlow()

    private val _detailError = MutableStateFlow<String?>(null)
    val detailError: StateFlow<String?> = _detailError.asStateFlow()

    private val _updatingSkillNames = MutableStateFlow<Set<String>>(emptySet())
    val updatingSkillNames: StateFlow<Set<String>> = _updatingSkillNames.asStateFlow()

    private val _removingSkillNames = MutableStateFlow<Set<String>>(emptySet())
    val removingSkillNames: StateFlow<Set<String>> = _removingSkillNames.asStateFlow()

    private val _updatingRemoteSkillNames = MutableStateFlow<Set<String>>(emptySet())
    val updatingRemoteSkillNames: StateFlow<Set<String>> = _updatingRemoteSkillNames.asStateFlow()

    private val _marketplaceSkills = MutableStateFlow<List<MarketplaceSkill>>(emptyList())
    val marketplaceSkills: StateFlow<List<MarketplaceSkill>> = _marketplaceSkills.asStateFlow()

    private val _marketplaceLoading = MutableStateFlow(false)
    val marketplaceLoading: StateFlow<Boolean> = _marketplaceLoading.asStateFlow()

    private val _marketplaceError = MutableStateFlow<String?>(null)
    val marketplaceError: StateFlow<String?> = _marketplaceError.asStateFlow()

    private val _installingMarketplaceSlugs = MutableStateFlow<Set<String>>(emptySet())
    val installingMarketplaceSlugs: StateFlow<Set<String>> = _installingMarketplaceSlugs.asStateFlow()

    private val _pendingMarketplaceApproval = MutableStateFlow<ApprovalRequest?>(null)
    val pendingMarketplaceApproval: StateFlow<ApprovalRequest?> = _pendingMarketplaceApproval.asStateFlow()

    private val _pendingMarketplaceSkill = MutableStateFlow<MarketplaceSkill?>(null)
    private val _submittingMarketplaceApproval = MutableStateFlow(false)
    val submittingMarketplaceApproval: StateFlow<Boolean> = _submittingMarketplaceApproval.asStateFlow()

    private val _pendingLocalApproval = MutableStateFlow<ApprovalRequest?>(null)
    val pendingLocalApproval: StateFlow<ApprovalRequest?> = _pendingLocalApproval.asStateFlow()

    private val _pendingLocalSkill = MutableStateFlow<SkillPackage?>(null)
    private val _submittingLocalApproval = MutableStateFlow(false)
    val submittingLocalApproval: StateFlow<Boolean> = _submittingLocalApproval.asStateFlow()
    private var lastRecommendationTopSlugs: List<String> = emptyList()

    private val _uploadingLocalSkill = MutableStateFlow(false)
    val uploadingLocalSkill: StateFlow<Boolean> = _uploadingLocalSkill.asStateFlow()

    private val _pendingUploadApproval = MutableStateFlow<ApprovalRequest?>(null)
    val pendingUploadApproval: StateFlow<ApprovalRequest?> = _pendingUploadApproval.asStateFlow()

    private val _pendingUploadFilename = MutableStateFlow<String?>(null)
    private val _submittingUploadApproval = MutableStateFlow(false)
    val submittingUploadApproval: StateFlow<Boolean> = _submittingUploadApproval.asStateFlow()

    private val _pendingUpdateApproval = MutableStateFlow<ApprovalRequest?>(null)
    val pendingUpdateApproval: StateFlow<ApprovalRequest?> = _pendingUpdateApproval.asStateFlow()

    private val _pendingUpdateSkill = MutableStateFlow<SkillPackage?>(null)
    private val _submittingUpdateApproval = MutableStateFlow(false)
    val submittingUpdateApproval: StateFlow<Boolean> = _submittingUpdateApproval.asStateFlow()

    init {
        refresh()
        loadMarketplace(sort = "score", shuffleForRecommendations = true)
    }

    fun refresh() {
        _uiState.value = _uiState.value.copy(
            isLoading = _uiState.value.data.isEmpty(),
            isRefreshing = _uiState.value.data.isNotEmpty(),
            error = null,
        )
        viewModelScope.launch {
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.getSkills()
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to load skills")
                }
                val skills = response.body().orEmpty().map(::mapSkillPackage)
                _uiState.value = LoadableState(data = skills)
                syncMarketplaceInstalledState(skills)
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    isLoading = false,
                    isRefreshing = false,
                    error = e.message ?: "Failed to load skills",
                )
            }
        }
    }

    fun toggleSkill(skill: SkillPackage) {
        viewModelScope.launch {
            try {
                _updatingSkillNames.value = _updatingSkillNames.value + skill.name
                _uiState.value = _uiState.value.copy(error = null, isRefreshing = true)
                val response = withContext(Dispatchers.IO) {
                    if (skill.isEnabled) {
                        RetrofitClient.apiService.disableSkill(skill.name)
                    } else {
                        RetrofitClient.apiService.enableSkill(skill.name)
                    }
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to update skill")
                }
                refresh()
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    isRefreshing = false,
                    error = e.message ?: "Failed to update skill",
                )
            } finally {
                _updatingSkillNames.value = _updatingSkillNames.value - skill.name
            }
        }
    }

    fun loadSkillDetail(skill: SkillPackage) {
        _selectedSkill.value = skill
        _selectedSkillTools.value = emptyList()
        _selectedSkillLifecycle.value = null
        _detailError.value = null
        _isDetailLoading.value = true
        viewModelScope.launch {
            try {
                val toolsResponse = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.getSkillTools(skill.name)
                }
                if (!toolsResponse.isSuccessful) {
                    throw IllegalStateException("Failed to load skill tools")
                }
                _selectedSkillTools.value = toolsResponse.body().orEmpty().map { tool ->
                    val requiredFields = (tool.inputSchema?.get("required") as? List<*>)
                        .orEmpty()
                        .mapNotNull { it?.toString() }
                    SkillTool(
                        name = tool.name,
                        description = tool.description,
                        requiredFields = requiredFields,
                    )
                }
                val lifecycleResponse = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.getSkillLifecycle(skill.name)
                }
                if (lifecycleResponse.isSuccessful) {
                    lifecycleResponse.body()?.let {
                        _selectedSkillLifecycle.value = SkillLifecycleStatus(
                            skillName = it.skillName,
                            installedVersion = it.installedVersion,
                            latestVersion = it.latestVersion,
                            updateAvailable = it.updateAvailable,
                            canUpdate = it.canUpdate,
                            canUninstall = it.canUninstall,
                            sourceLabel = it.sourceLabel,
                            sourceUrl = it.sourceUrl,
                            trustState = it.trustState,
                            effectiveScope = it.effectiveScope,
                            registrySlug = it.registrySlug,
                        )
                    }
                }
            } catch (e: Exception) {
                _detailError.value = e.message ?: "Failed to load skill detail"
            } finally {
                _isDetailLoading.value = false
            }
        }
    }

    fun dismissSkillDetail() {
        _selectedSkill.value = null
        _selectedSkillTools.value = emptyList()
        _selectedSkillLifecycle.value = null
        _detailError.value = null
        _isDetailLoading.value = false
    }

    fun updateSkillScope(skill: SkillPackage, agentType: String) {
        viewModelScope.launch {
            try {
                _updatingSkillNames.value = _updatingSkillNames.value + skill.name
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.updateSkillScope(
                        skillName = skill.name,
                        request = SkillScopeUpdateRequest(agentType = agentType),
                    )
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to update skill scope")
                }
                response.body()?.skill?.let {
                    val updated = mapSkillPackage(it)
                    _selectedSkill.value = updated
                }
                refresh()
            } catch (e: Exception) {
                _detailError.value = e.message ?: "Failed to update skill scope"
            } finally {
                _updatingSkillNames.value = _updatingSkillNames.value - skill.name
            }
        }
    }

    fun clearError() {
        _uiState.value = _uiState.value.copy(error = null)
        _detailError.value = null
        _marketplaceError.value = null
    }

    fun showSkillError(message: String) {
        _uiState.value = _uiState.value.copy(error = message)
    }

    fun loadMarketplace(
        sort: String = "updated_at",
        shuffleForRecommendations: Boolean = false,
    ) {
        _marketplaceLoading.value = true
        _marketplaceError.value = null
        viewModelScope.launch {
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.getMarketplaceSkills(sort = sort)
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to load marketplace")
                }
                val mappedSkills = markMarketplaceInstalled(
                    response.body().orEmptyItems().map(::mapMarketplaceSkill),
                )
                _marketplaceSkills.value = if (shuffleForRecommendations) {
                    remixedRecommendations(mappedSkills)
                } else {
                    mappedSkills
                }
            } catch (e: Exception) {
                _marketplaceError.value = e.message ?: "Failed to load marketplace"
            } finally {
                _marketplaceLoading.value = false
            }
        }
    }

    fun searchMarketplace(query: String) {
        if (query.isBlank()) {
            loadMarketplace()
            return
        }

        _marketplaceLoading.value = true
        _marketplaceError.value = null
        viewModelScope.launch {
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.searchMarketplaceSkills(query)
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to search marketplace")
                }
                _marketplaceSkills.value = markMarketplaceInstalled(
                    response.body()?.results.orEmpty().map(::mapMarketplaceSkill),
                )
            } catch (e: Exception) {
                _marketplaceError.value = e.message ?: "Failed to search marketplace"
            } finally {
                _marketplaceLoading.value = false
            }
        }
    }

    private fun remixedRecommendations(skills: List<MarketplaceSkill>): List<MarketplaceSkill> {
        if (skills.size <= 1) {
            lastRecommendationTopSlugs = skills.take(6).map { it.slug }
            return skills
        }

        val shuffled = skills.shuffled()
        val topSignature = shuffled.take(6).map { it.slug }
        if (topSignature != lastRecommendationTopSlugs) {
            lastRecommendationTopSlugs = topSignature
            return shuffled
        }

        val remixed = shuffled.drop(1) + shuffled.take(1)
        lastRecommendationTopSlugs = remixed.take(6).map { it.slug }
        return remixed
    }

    fun installMarketplaceSkill(skill: MarketplaceSkill, approvalRequestId: String? = null) {
        if (skill.installed || _installingMarketplaceSlugs.value.contains(skill.slug)) return
        _installingMarketplaceSlugs.value = _installingMarketplaceSlugs.value + skill.slug
        viewModelScope.launch {
            try {
                _marketplaceError.value = null
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.installMarketplaceSkill(
                        MarketplaceInstallRequest(
                            slug = skill.slug,
                            approvalRequestId = approvalRequestId,
                        ),
                    )
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException(response.errorMessage("Failed to install marketplace skill"))
                }
                val payload = response.body() ?: throw IllegalStateException("Missing install response")
                when (payload.status) {
                    "approval_required" -> {
                        _pendingMarketplaceSkill.value = skill
                        _pendingMarketplaceApproval.value = payload.approvalRequest?.let(::mapApprovalRequest)
                        _installingMarketplaceSlugs.value = _installingMarketplaceSlugs.value - skill.slug
                    }
                    "installed" -> {
                        _pendingMarketplaceSkill.value = null
                        _pendingMarketplaceApproval.value = null
                        markMarketplaceSkillInstalled(skill)
                        refresh()
                        searchMarketplace(skill.slug)
                    }
                    "approval_pending" -> {
                        _marketplaceError.value = payload.message ?: "Approval is still pending"
                    }
                    "approval_denied" -> {
                        _pendingMarketplaceSkill.value = null
                        _pendingMarketplaceApproval.value = null
                        _marketplaceError.value = payload.message ?: "Install approval was denied"
                    }
                    else -> {
                        throw IllegalStateException(payload.message ?: "Unexpected install status")
                    }
                }
            } catch (e: Exception) {
                if (approvalRequestId != null) {
                    clearMarketplaceApproval()
                }
                _marketplaceError.value = e.message ?: "Failed to install marketplace skill"
            } finally {
                _installingMarketplaceSlugs.value = _installingMarketplaceSlugs.value - skill.slug
            }
        }
    }

    fun approveMarketplaceInstall() {
        val approval = _pendingMarketplaceApproval.value ?: return
        val skill = _pendingMarketplaceSkill.value ?: return
        if (_submittingMarketplaceApproval.value || _installingMarketplaceSlugs.value.contains(skill.slug)) return

        viewModelScope.launch {
            _submittingMarketplaceApproval.value = true
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.submitApprovalDecision(
                        requestId = approval.requestId,
                        request = ApprovalDecisionRequest(
                            requestId = approval.requestId,
                            approved = true,
                        ),
                    )
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException(response.errorMessage("Failed to approve marketplace install"))
                }
                clearMarketplaceApproval()
                installMarketplaceSkill(skill, approval.requestId)
            } catch (e: Exception) {
                clearMarketplaceApproval()
                _marketplaceError.value = e.message ?: "Failed to approve marketplace install"
            } finally {
                _submittingMarketplaceApproval.value = false
            }
        }
    }

    fun denyMarketplaceInstall() {
        val approval = _pendingMarketplaceApproval.value ?: return
        if (_submittingMarketplaceApproval.value) return

        viewModelScope.launch {
            _submittingMarketplaceApproval.value = true
            clearMarketplaceApproval()
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.submitApprovalDecision(
                        requestId = approval.requestId,
                        request = ApprovalDecisionRequest(
                            requestId = approval.requestId,
                            approved = false,
                        ),
                    )
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to deny marketplace install")
                }
            } catch (e: Exception) {
                _marketplaceError.value = e.message ?: "Install approval was closed"
            } finally {
                _submittingMarketplaceApproval.value = false
            }
        }
    }

    private fun clearMarketplaceApproval() {
        _pendingMarketplaceSkill.value = null
        _pendingMarketplaceApproval.value = null
    }

    fun uploadSkillArchive(
        fileName: String,
        fileBytes: ByteArray,
        approvalRequestId: String? = null,
    ) {
        viewModelScope.launch {
            try {
                _uploadingLocalSkill.value = true
                _uiState.value = _uiState.value.copy(error = null, isRefreshing = true)
                val response = withContext(Dispatchers.IO) {
                    val filePart = if (approvalRequestId == null) {
                        MultipartBody.Part.createFormData(
                            "file",
                            fileName,
                            fileBytes.toRequestBody("application/zip".toMediaType()),
                        )
                    } else {
                        null
                    }
                    val approvalPart = approvalRequestId?.toRequestBody("text/plain".toMediaType())
                    RetrofitClient.apiService.uploadSkill(
                        file = filePart,
                        approvalRequestId = approvalPart,
                    )
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to upload skill archive")
                }
                val payload = response.body() ?: throw IllegalStateException("Missing upload response")
                when (payload.status) {
                    "approval_required" -> {
                        _pendingUploadFilename.value = fileName
                        _pendingUploadApproval.value = payload.approvalRequest?.let(::mapApprovalRequest)
                        _uiState.value = _uiState.value.copy(isRefreshing = false)
                    }
                    "installed" -> {
                        _pendingUploadFilename.value = null
                        _pendingUploadApproval.value = null
                        refresh()
                    }
                    "approval_pending" -> {
                        _uiState.value = _uiState.value.copy(
                            isRefreshing = false,
                            error = payload.message ?: "Approval is still pending",
                        )
                    }
                    "approval_denied" -> {
                        _pendingUploadFilename.value = null
                        _pendingUploadApproval.value = null
                        _uiState.value = _uiState.value.copy(
                            isRefreshing = false,
                            error = payload.message ?: "Upload approval was denied",
                        )
                    }
                    else -> {
                        throw IllegalStateException(payload.message ?: "Unexpected upload status")
                    }
                }
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    isRefreshing = false,
                    error = e.message ?: "Failed to upload skill archive",
                )
            } finally {
                _uploadingLocalSkill.value = false
            }
        }
    }

    fun approveSkillUpload() {
        val approval = _pendingUploadApproval.value ?: return
        val fileName = _pendingUploadFilename.value ?: return
        if (_submittingUploadApproval.value) return

        viewModelScope.launch {
            _submittingUploadApproval.value = true
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.submitApprovalDecision(
                        requestId = approval.requestId,
                        request = ApprovalDecisionRequest(
                            requestId = approval.requestId,
                            approved = true,
                        ),
                    )
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to approve skill upload")
                }
                uploadSkillArchive(fileName = fileName, fileBytes = ByteArray(0), approvalRequestId = approval.requestId)
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    error = e.message ?: "Failed to approve skill upload",
                )
            } finally {
                _submittingUploadApproval.value = false
            }
        }
    }

    fun denySkillUpload() {
        val approval = _pendingUploadApproval.value ?: return
        if (_submittingUploadApproval.value) return

        viewModelScope.launch {
            _submittingUploadApproval.value = true
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.submitApprovalDecision(
                        requestId = approval.requestId,
                        request = ApprovalDecisionRequest(
                            requestId = approval.requestId,
                            approved = false,
                        ),
                    )
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to deny skill upload")
                }
                _pendingUploadFilename.value = null
                _pendingUploadApproval.value = null
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    error = e.message ?: "Failed to deny skill upload",
                )
            } finally {
                _submittingUploadApproval.value = false
            }
        }
    }

    fun updateRemoteSkill(skill: SkillPackage, approvalRequestId: String? = null) {
        if (!skill.canUpdate) {
            _detailError.value = "当前技能没有可用的远程更新来源"
            return
        }
        viewModelScope.launch {
            try {
                _updatingRemoteSkillNames.value = _updatingRemoteSkillNames.value + skill.name
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.updateSkill(
                        skillName = skill.name,
                        request = SkillUpdateRequest(approvalRequestId = approvalRequestId),
                    )
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to update skill")
                }
                val payload = response.body() ?: throw IllegalStateException("Missing update response")
                when (payload.status) {
                    "approval_required" -> {
                        _pendingUpdateSkill.value = skill
                        _pendingUpdateApproval.value = payload.approvalRequest?.let(::mapApprovalRequest)
                    }
                    "updated" -> {
                        payload.skill?.let {
                            val updated = mapSkillPackage(it)
                            _selectedSkill.value = updated
                        }
                        _pendingUpdateSkill.value = null
                        _pendingUpdateApproval.value = null
                        refresh()
                    }
                    "approval_pending" -> {
                        _detailError.value = payload.message ?: "Approval is still pending"
                    }
                    "approval_denied" -> {
                        _pendingUpdateSkill.value = null
                        _pendingUpdateApproval.value = null
                        _detailError.value = payload.message ?: "Update approval was denied"
                    }
                    else -> throw IllegalStateException(payload.message ?: "Unexpected update status")
                }
            } catch (e: Exception) {
                _detailError.value = e.message ?: "Failed to update skill"
            } finally {
                _updatingRemoteSkillNames.value = _updatingRemoteSkillNames.value - skill.name
            }
        }
    }

    fun approveSkillUpdate() {
        val approval = _pendingUpdateApproval.value ?: return
        val skill = _pendingUpdateSkill.value ?: return
        if (_submittingUpdateApproval.value) return

        viewModelScope.launch {
            _submittingUpdateApproval.value = true
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.submitApprovalDecision(
                        requestId = approval.requestId,
                        request = ApprovalDecisionRequest(
                            requestId = approval.requestId,
                            approved = true,
                        ),
                    )
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to approve skill update")
                }
                updateRemoteSkill(skill, approval.requestId)
            } catch (e: Exception) {
                _detailError.value = e.message ?: "Failed to approve skill update"
            } finally {
                _submittingUpdateApproval.value = false
            }
        }
    }

    fun denySkillUpdate() {
        val approval = _pendingUpdateApproval.value ?: return
        if (_submittingUpdateApproval.value) return

        viewModelScope.launch {
            _submittingUpdateApproval.value = true
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.submitApprovalDecision(
                        requestId = approval.requestId,
                        request = ApprovalDecisionRequest(
                            requestId = approval.requestId,
                            approved = false,
                        ),
                    )
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to deny skill update")
                }
                _pendingUpdateSkill.value = null
                _pendingUpdateApproval.value = null
            } catch (e: Exception) {
                _detailError.value = e.message ?: "Failed to deny skill update"
            } finally {
                _submittingUpdateApproval.value = false
            }
        }
    }

    fun removeSkill(skill: SkillPackage, approvalRequestId: String? = null) {
        if (!skill.canUninstall) {
            _uiState.value = _uiState.value.copy(error = "这个技能属于项目内置能力，不能直接卸载")
            return
        }

        viewModelScope.launch {
            try {
                _removingSkillNames.value = _removingSkillNames.value + skill.name
                _uiState.value = _uiState.value.copy(error = null, isRefreshing = true)
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.deleteSkill(skill.name, approvalRequestId)
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to remove skill")
                }
                val payload = response.body() ?: throw IllegalStateException("Missing remove response")
                when (payload.status) {
                    "approval_required" -> {
                        _pendingLocalSkill.value = skill
                        _pendingLocalApproval.value = payload.approvalRequest?.let(::mapApprovalRequest)
                        _uiState.value = _uiState.value.copy(isRefreshing = false)
                    }
                    "removed" -> {
                        if (_selectedSkill.value?.name == skill.name) {
                            dismissSkillDetail()
                        }
                        _pendingLocalSkill.value = null
                        _pendingLocalApproval.value = null
                        refresh()
                    }
                    "approval_pending" -> {
                        _uiState.value = _uiState.value.copy(
                            isRefreshing = false,
                            error = payload.message ?: "Approval is still pending",
                        )
                    }
                    "approval_denied" -> {
                        _pendingLocalSkill.value = null
                        _pendingLocalApproval.value = null
                        _uiState.value = _uiState.value.copy(
                            isRefreshing = false,
                            error = payload.message ?: "Remove approval was denied",
                        )
                    }
                    else -> {
                        throw IllegalStateException(payload.message ?: "Unexpected remove status")
                    }
                }
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    isRefreshing = false,
                    error = e.message ?: "Failed to remove skill",
                )
            } finally {
                _removingSkillNames.value = _removingSkillNames.value - skill.name
            }
        }
    }

    fun approveSkillRemoval() {
        val approval = _pendingLocalApproval.value ?: return
        val skill = _pendingLocalSkill.value ?: return
        if (_submittingLocalApproval.value) return

        viewModelScope.launch {
            _submittingLocalApproval.value = true
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.submitApprovalDecision(
                        requestId = approval.requestId,
                        request = ApprovalDecisionRequest(
                            requestId = approval.requestId,
                            approved = true,
                        ),
                    )
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to approve skill removal")
                }
                removeSkill(skill, approval.requestId)
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    error = e.message ?: "Failed to approve skill removal",
                )
            } finally {
                _submittingLocalApproval.value = false
            }
        }
    }

    fun denySkillRemoval() {
        val approval = _pendingLocalApproval.value ?: return
        if (_submittingLocalApproval.value) return

        viewModelScope.launch {
            _submittingLocalApproval.value = true
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.submitApprovalDecision(
                        requestId = approval.requestId,
                        request = ApprovalDecisionRequest(
                            requestId = approval.requestId,
                            approved = false,
                        ),
                    )
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to deny skill removal")
                }
                _pendingLocalSkill.value = null
                _pendingLocalApproval.value = null
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    error = e.message ?: "Failed to deny skill removal",
                )
            } finally {
                _submittingLocalApproval.value = false
            }
        }
    }

    private fun mapMarketplaceSkill(dto: com.serana.app.data.api.MarketplaceSkillDto): MarketplaceSkill {
        return MarketplaceSkill(
            slug = dto.slug,
            displayName = dto.displayName?.takeIf { it.isNotBlank() } ?: dto.slug,
            summary = dto.summary,
            version = dto.version,
            ownerHandle = dto.ownerHandle,
            canonicalUrl = dto.canonicalUrl,
            installed = dto.installed,
            localSkillName = dto.localSkillName,
        )
    }

    private fun syncMarketplaceInstalledState(localSkills: List<SkillPackage> = _uiState.value.data) {
        _marketplaceSkills.value = markMarketplaceInstalled(_marketplaceSkills.value, localSkills)
    }

    private fun markMarketplaceInstalled(
        skills: List<MarketplaceSkill>,
        localSkills: List<SkillPackage> = _uiState.value.data,
    ): List<MarketplaceSkill> {
        if (skills.isEmpty()) return skills
        val localKeys = localSkills.flatMap { local ->
            listOfNotNull(
                local.name,
                local.registrySlug,
                local.sourceUrl?.substringAfterLast("/")?.takeIf { it.isNotBlank() },
            )
        }.map { normalizeSkillKey(it) }.toSet()

        return skills.map { skill ->
            val candidates = listOfNotNull(
                skill.slug,
                skill.displayName,
                skill.localSkillName,
                skill.canonicalUrl?.substringAfterLast("/")?.takeIf { it.isNotBlank() },
            ).map { normalizeSkillKey(it) }
            if (skill.installed || candidates.any { it in localKeys }) {
                skill.copy(installed = true)
            } else {
                skill
            }
        }
    }

    private fun markMarketplaceSkillInstalled(skill: MarketplaceSkill) {
        _marketplaceSkills.value = _marketplaceSkills.value.map { item ->
            if (isSameMarketplaceSkill(item, skill)) {
                item.copy(installed = true)
            } else {
                item
            }
        }
    }

    private fun isSameMarketplaceSkill(left: MarketplaceSkill, right: MarketplaceSkill): Boolean {
        val rightKeys = listOfNotNull(right.slug, right.displayName, right.localSkillName)
            .map { normalizeSkillKey(it) }
            .toSet()
        return listOfNotNull(left.slug, left.displayName, left.localSkillName)
            .map { normalizeSkillKey(it) }
            .any { it in rightKeys }
    }

    private fun normalizeSkillKey(value: String): String {
        return value
            .trim()
            .lowercase()
            .replace("_", "-")
            .replace(" ", "-")
    }

    private fun mapSkillPackage(dto: com.serana.app.data.api.SkillPackageDto): SkillPackage {
        return SkillPackage(
            id = dto.id,
            name = dto.name,
            version = dto.version,
            description = dto.description,
            author = dto.author,
            agentType = dto.agentType,
            maxInstances = dto.maxInstances,
            isEnabled = dto.isEnabled,
            isInstalled = dto.isInstalled,
            installedAt = dto.installedAt,
            origin = dto.origin,
            canUninstall = dto.canUninstall,
            registrySlug = dto.registrySlug,
            sourceUrl = dto.sourceUrl,
            sourceLabel = dto.sourceLabel,
            trustState = dto.trustState,
            effectiveScope = dto.effectiveScope,
            canUpdate = dto.canUpdate,
            latestVersion = dto.latestVersion,
            updateAvailable = dto.updateAvailable,
        )
    }

    private fun com.serana.app.data.api.MarketplaceCatalogResponseDto?.orEmptyItems():
        List<com.serana.app.data.api.MarketplaceSkillDto> {
        return this?.items.orEmpty()
    }

    private fun mapApprovalRequest(dto: ApprovalRequestDto): ApprovalRequest {
        return ApprovalRequest(
            requestId = dto.requestId,
            sessionId = dto.sessionId,
            toolName = dto.toolName,
            operation = dto.operation,
            riskLevel = dto.riskLevel,
            title = dto.title,
            summary = dto.summary,
            reason = dto.reason,
            approvalOptions = dto.approvalOptions,
            details = dto.details,
            status = dto.status,
            createdAt = dto.createdAt,
            expiresAt = dto.expiresAt,
        )
    }
}

private fun Response<*>.errorMessage(fallback: String): String {
    val body = errorBody()?.string().orEmpty().trim()
    if (body.isBlank()) return fallback

    val detail = Regex("\\\"detail\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"")
        .find(body)
        ?.groupValues
        ?.getOrNull(1)
        ?.replace("\\n", "\n")
        ?.replace("\\\"", "\"")
        ?.trim()

    return detail?.takeIf { it.isNotBlank() } ?: body
}
