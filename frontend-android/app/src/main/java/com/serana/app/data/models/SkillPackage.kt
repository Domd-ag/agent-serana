package com.serana.app.data.models

data class SkillPackage(
    val id: String,
    val name: String,
    val version: String,
    val description: String?,
    val author: String?,
    val agentType: String,
    val maxInstances: Int,
    val isEnabled: Boolean,
    val isInstalled: Boolean,
    val installedAt: String?,
    val origin: String,
    val canUninstall: Boolean,
    val registrySlug: String?,
    val sourceUrl: String?,
    val sourceLabel: String,
    val trustState: String,
    val effectiveScope: String,
    val canUpdate: Boolean,
    val latestVersion: String?,
    val updateAvailable: Boolean,
)

data class SkillTool(
    val name: String,
    val description: String?,
    val requiredFields: List<String> = emptyList(),
)

data class MarketplaceSkill(
    val slug: String,
    val displayName: String,
    val summary: String?,
    val version: String?,
    val ownerHandle: String?,
    val canonicalUrl: String?,
    val installed: Boolean,
    val localSkillName: String?,
)

data class SkillLifecycleStatus(
    val skillName: String,
    val installedVersion: String,
    val latestVersion: String?,
    val updateAvailable: Boolean,
    val canUpdate: Boolean,
    val canUninstall: Boolean,
    val sourceLabel: String,
    val sourceUrl: String?,
    val trustState: String,
    val effectiveScope: String,
    val registrySlug: String?,
)
