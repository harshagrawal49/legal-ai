package com.nyaya.legal

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.Composable
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.nyaya.legal.ui.brief.BriefScreen
import com.nyaya.legal.ui.cases.CaseListScreen
import com.nyaya.legal.ui.cases.CaseScreen
import com.nyaya.legal.ui.chat.ChatScreen
import com.nyaya.legal.ui.documents.DocumentScreen
import com.nyaya.legal.ui.documents.DocumentsScreen
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
                onOpenCase = { case -> nav.navigate("case/${case.id}") },
            )
        }
        composable("case/{caseId}") { entry ->
            val caseId = entry.arguments!!.getString("caseId")!!
            CaseScreen(
                caseId = caseId,
                onBack = { nav.popBackStack() },
                onChat = { nav.navigate("chat/$caseId") },
                onDocuments = { nav.navigate("documents/$caseId") },
                onResults = { nav.navigate("results/$caseId") },
                onIntake = { nav.navigate("intake?caseId=$caseId") },
                onBrief = { nav.navigate("brief/$caseId") },
            )
        }
        composable("intake?caseId={caseId}") { entry ->
            IntakeScreen(
                caseId = entry.arguments?.getString("caseId"),
                onBack = { nav.popBackStack() },
                onResults = { caseId ->
                    nav.navigate("results/$caseId") { popUpTo("cases") }
                },
                onDocuments = { caseId -> nav.navigate("documents/$caseId") },
            )
        }
        composable("results/{caseId}") { entry ->
            val caseId = entry.arguments!!.getString("caseId")!!
            ResultsScreen(
                caseId = caseId,
                onBack = { nav.popBackStack() },
                onOpenJudgment = { nav.navigate("judgment/$it") },
                onChat = { nav.navigate("chat/$caseId") },
                onDocuments = { nav.navigate("documents/$caseId") },
            )
        }
        composable("judgment/{id}") { entry ->
            JudgmentScreen(id = entry.arguments!!.getString("id")!!, onBack = { nav.popBackStack() })
        }
        composable("chat/{caseId}") { entry ->
            val caseId = entry.arguments!!.getString("caseId")!!
            ChatScreen(
                caseId = caseId,
                onBack = { nav.popBackStack() },
                onOpenJudgment = { nav.navigate("judgment/$it") },
                onOpenDocument = { docId, page -> nav.navigate(documentRoute(caseId, docId, page)) },
            )
        }
        composable("documents/{caseId}") { entry ->
            val caseId = entry.arguments!!.getString("caseId")!!
            DocumentsScreen(
                caseId = caseId,
                onBack = { nav.popBackStack() },
                onOpenDocument = { docId, page -> nav.navigate(documentRoute(caseId, docId, page)) },
                onBrief = { nav.navigate("brief/$caseId") },
            )
        }
        composable("document/{caseId}/{docId}?page={page}") { entry ->
            DocumentScreen(
                caseId = entry.arguments!!.getString("caseId")!!,
                docId = entry.arguments!!.getString("docId")!!,
                page = entry.arguments?.getString("page")?.toIntOrNull(),
                onBack = { nav.popBackStack() },
            )
        }
        composable("brief/{caseId}") { entry ->
            val caseId = entry.arguments!!.getString("caseId")!!
            BriefScreen(
                caseId = caseId,
                onBack = { nav.popBackStack() },
                onOpenDocument = { docId, page -> nav.navigate(documentRoute(caseId, docId, page)) },
                onOpenJudgment = { nav.navigate("judgment/$it") },
            )
        }
    }
}

private fun documentRoute(caseId: String, docId: String, page: Int?) =
    "document/$caseId/$docId" + (page?.let { "?page=$it" } ?: "")
