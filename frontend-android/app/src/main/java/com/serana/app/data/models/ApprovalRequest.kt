package com.serana.app.data.models

data class ApprovalRequest(
    val requestId: String,
    val sessionId: String? = null,
    val toolName: String? = null,
    val operation: String,
    val riskLevel: String,
    val title: String,
    val summary: String,
    val reason: String? = null,
    val approvalOptions: List<String> = emptyList(),
    val details: Map<String, Any?> = emptyMap(),
    val status: String,
    val createdAt: String,
    val expiresAt: String? = null,
)
