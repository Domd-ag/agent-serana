package com.serana.app.ui.state

data class LoadableState<T>(
    val data: T,
    val isLoading: Boolean = false,
    val isRefreshing: Boolean = false,
    val error: String? = null,
)
