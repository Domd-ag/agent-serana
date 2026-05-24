package com.serana.app.navigation

import androidx.compose.runtime.Composable
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.serana.app.ui.screens.ChatScreen
import com.serana.app.ui.screens.SettingsScreen
import com.serana.app.ui.screens.SkillsScreen

sealed class Screen(val route: String) {
    data object Chat : Screen("chat")
    data object Skills : Screen("skills")
    data object Settings : Screen("settings")
}

@Composable
fun NavGraph(
    navController: NavHostController = rememberNavController(),
) {
    NavHost(
        navController = navController,
        startDestination = Screen.Chat.route,
    ) {
        composable(Screen.Chat.route) {
            ChatScreen()
        }
        composable(Screen.Skills.route) {
            SkillsScreen()
        }
        composable(Screen.Settings.route) {
            SettingsScreen()
        }
    }
}
