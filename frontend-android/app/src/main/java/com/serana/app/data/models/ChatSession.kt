package com.serana.app.data.models

import com.google.gson.annotations.SerializedName

data class ChatSession(
    val id: String,
    val title: String?,
    @SerializedName("created_at")
    val createdAt: String,
    @SerializedName("updated_at")
    val updatedAt: String,
)
