package com.nyaya.legal

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.Composable
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.nyaya.legal.ui.cases.CaseListScreen
import com.nyaya.legal.ui.chat.ChatScreen
import com.nyaya.legal.ui.intake.IntakeScreen
import com.nyaya.legal.ui.judgment.JudgmentScreen
import com.nyaya.legal.ui.results.ResultsScreen
import com.nyaya.legal.ui.theme.NyayaTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { NyayaTheme { AppNavigation() } }
    }
}

@Composable
fun AppNavigation() {
    val nav = rememberNavController()
    NavHost(nav, startDestination = "cases") {
        composable("cases") {
            CaseListScreen(
                onNewCase = { nav.navigate("intake") },
                onOpenCase = { case ->
                    nav.navigate(if (case.status == "searched") "results/${case.id}" else "intake?caseId=${case.id}")
                },
            )
        }
        composable("intake?caseId={caseId}") { entry ->
            IntakeScreen(
                caseId = entry.arguments?.getString("caseId"),
                onBack = { nav.popBackStack() },
                onResults = { caseId ->
                    nav.navigate("results/$caseId") { popUpTo("cases") }
                },
            )
        }
        composable("results/{caseId}") { entry ->
            val caseId = entry.arguments!!.getString("caseId")!!
            ResultsScreen(
                caseId = caseId,
                onBack = { nav.popBackStack() },
                onOpenJudgment = { nav.navigate("judgment/$it") },
                onChat = { nav.navigate("chat/$caseId") },
            )
        }
        composable("judgment/{id}") { entry ->
            JudgmentScreen(id = entry.arguments!!.getString("id")!!, onBack = { nav.popBackStack() })
        }
        composable("chat/{caseId}") { entry ->
            ChatScreen(
                caseId = entry.arguments!!.getString("caseId")!!,
                onBack = { nav.popBackStack() },
                onOpenJudgment = { nav.navigate("judgment/$it") },
            )
        }
    }
}
