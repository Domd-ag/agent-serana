package com.serana.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.serana.app.data.api.MarketplaceInstallRequest
import com.serana.app.data.api.RetrofitClient
import com.serana.app.data.models.MarketplaceSkill
import com.serana.app.data.models.SkillPackage
import com.serana.app.data.models.SkillTool
import com.serana.app.ui.state.LoadableState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class SkillsViewModel : ViewModel() {
    private val _uiState = MutableStateFlow(LoadableState(data = emptyList<SkillPackage>(), isLoading = true))
    val uiState: StateFlow<LoadableState<List<SkillPackage>>> = _uiState.asStateFlow()

    private val _selectedSkill = MutableStateFlow<SkillPackage?>(null)
    val selectedSkill: StateFlow<SkillPackage?> = _selectedSkill.asStateFlow()

    private val _selectedSkillTools = MutableStateFlow<List<SkillTool>>(emptyList())
    val selectedSkillTools: StateFlow<List<SkillTool>> = _selectedSkillTools.asStateFlow()

    private val _isDetailLoading = MutableStateFlow(false)
    val isDetailLoading: StateFlow<Boolean> = _isDetailLoading.asStateFlow()

    private val _detailError = MutableStateFlow<String?>(null)
    val detailError: StateFlow<String?> = _detailError.asStateFlow()

    private val _updatingSkillNames = MutableStateFlow<Set<String>>(emptySet())
    val updatingSkillNames: StateFlow<Set<String>> = _updatingSkillNames.asStateFlow()

    private val _marketplaceSkills = MutableStateFlow<List<MarketplaceSkill>>(emptyList())
    val marketplaceSkills: StateFlow<List<MarketplaceSkill>> = _marketplaceSkills.asStateFlow()

    private val _marketplaceLoading = MutableStateFlow(false)
    val marketplaceLoading: StateFlow<Boolean> = _marketplaceLoading.asStateFlow()

    private val _marketplaceError = MutableStateFlow<String?>(null)
    val marketplaceError: StateFlow<String?> = _marketplaceError.asStateFlow()

    private val _installingMarketplaceSlugs = MutableStateFlow<Set<String>>(emptySet())
    val installingMarketplaceSlugs: StateFlow<Set<String>> = _installingMarketplaceSlugs.asStateFlow()

    init {
        refresh()
        loadMarketplace()
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
                val skills = response.body().orEmpty().map {
                    SkillPackage(
                        id = it.id,
                        name = it.name,
                        version = it.version,
                        description = it.description,
                        author = it.author,
                        agentType = it.agentType,
                        maxInstances = it.maxInstances,
                        isEnabled = it.isEnabled,
                        isInstalled = it.isInstalled,
                        installedAt = it.installedAt,
                    )
                }
                _uiState.value = LoadableState(data = skills)
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
        _detailError.value = null
        _isDetailLoading.value = true
        viewModelScope.launch {
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.getSkillTools(skill.name)
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to load skill tools")
                }
                _selectedSkillTools.value = response.body().orEmpty().map { tool ->
                    val requiredFields = (tool.inputSchema?.get("required") as? List<*>)
                        .orEmpty()
                        .mapNotNull { it?.toString() }
                    SkillTool(
                        name = tool.name,
                        description = tool.description,
                        requiredFields = requiredFields,
                    )
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
        _detailError.value = null
        _isDetailLoading.value = false
    }

    fun clearError() {
        _uiState.value = _uiState.value.copy(error = null)
        _detailError.value = null
        _marketplaceError.value = null
    }

    fun loadMarketplace() {
        _marketplaceLoading.value = true
        _marketplaceError.value = null
        viewModelScope.launch {
            try {
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.getMarketplaceSkills()
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to load marketplace")
                }
                _marketplaceSkills.value = response.body().orEmptyItems().map(::mapMarketplaceSkill)
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
                _marketplaceSkills.value = response.body()?.results.orEmpty().map(::mapMarketplaceSkill)
            } catch (e: Exception) {
                _marketplaceError.value = e.message ?: "Failed to search marketplace"
            } finally {
                _marketplaceLoading.value = false
            }
        }
    }

    fun installMarketplaceSkill(skill: MarketplaceSkill) {
        viewModelScope.launch {
            try {
                _installingMarketplaceSlugs.value = _installingMarketplaceSlugs.value + skill.slug
                _marketplaceError.value = null
                val response = withContext(Dispatchers.IO) {
                    RetrofitClient.apiService.installMarketplaceSkill(
                        MarketplaceInstallRequest(slug = skill.slug),
                    )
                }
                if (!response.isSuccessful) {
                    throw IllegalStateException("Failed to install marketplace skill")
                }
                refresh()
                searchMarketplace(skill.slug)
            } catch (e: Exception) {
                _marketplaceError.value = e.message ?: "Failed to install marketplace skill"
            } finally {
                _installingMarketplaceSlugs.value = _installingMarketplaceSlugs.value - skill.slug
            }
        }
    }

    private fun mapMarketplaceSkill(dto: com.serana.app.data.api.MarketplaceSkillDto): MarketplaceSkill {
        return MarketplaceSkill(
            slug = dto.slug,
            displayName = dto.displayName,
            summary = dto.summary,
            version = dto.version,
            ownerHandle = dto.ownerHandle,
            canonicalUrl = dto.canonicalUrl,
            installed = dto.installed,
            localSkillName = dto.localSkillName,
        )
    }

    private fun com.serana.app.data.api.MarketplaceCatalogResponseDto?.orEmptyItems():
        List<com.serana.app.data.api.MarketplaceSkillDto> {
        return this?.items.orEmpty()
    }
}
