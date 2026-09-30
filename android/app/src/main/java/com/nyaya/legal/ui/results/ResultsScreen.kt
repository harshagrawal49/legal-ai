package com.nyaya.legal.ui.results

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.nyaya.legal.data.Api
import com.nyaya.legal.data.CaseResult
import com.nyaya.legal.ui.Disclaimer
import com.nyaya.legal.ui.ErrorText
import com.nyaya.legal.ui.Loading
import com.nyaya.legal.ui.text
import com.nyaya.legal.ui.theme.MixedColor
import com.nyaya.legal.ui.theme.OpposesColor
import com.nyaya.legal.ui.theme.SupportsColor
import kotlinx.coroutines.launch

class ResultsViewModel(caseId: String) : ViewModel() {
    var results by mutableStateOf<List<CaseResult>?>(null)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    init {
        viewModelScope.launch {
            runCatching { Api.service.results(caseId) }
                .onSuccess { results = it }
                .onFailure { error = "Could not load results: ${it.message}" }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ResultsScreen(caseId: String, onBack: () -> Unit, onOpenJudgment: (String) -> Unit, onChat: () -> Unit) {
    val vm: ResultsViewModel = viewModel { ResultsViewModel(caseId) }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Similar cases") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            )
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = onChat,
                icon = { Icon(Icons.AutoMirrored.Filled.Chat, null) },
                text = { Text("Ask about these cases") },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            Disclaimer()
            val results = vm.results
            when {
                vm.error != null -> ErrorText(vm.error!!)
                results == null -> Loading("Loading…")
                results.isEmpty() -> Text("No closely matching judgments were found in the database yet.", Modifier.padding(16.dp))
                else -> LazyColumn(
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    items(results, key = { it.judgment.id }) { ResultCard(it, onClick = { onOpenJudgment(it.judgment.id) }) }
                }
            }
        }
    }
}

@Composable
private fun ResultCard(result: CaseResult, onClick: () -> Unit) {
    val j = result.judgment
    Card(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(j.title, style = MaterialTheme.typography.titleMedium)
            Text(
                listOfNotNull(j.court, j.decisionDate, j.citation ?: j.neutralCitation).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall,
            )
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                StanceChip(result.stance)
                Text("${result.relevance}% match", style = MaterialTheme.typography.labelLarge)
            }
            j.summary.text("outcome")?.let { Text("Outcome: $it", style = MaterialTheme.typography.bodyMedium) }
            Text(result.explanation, style = MaterialTheme.typography.bodyMedium)
        }
    }
}

@Composable
fun StanceChip(stance: String) {
    val (label, color) = when (stance) {
        "supports" -> "Supports you" to SupportsColor
        "opposes" -> "Against you" to OpposesColor
        else -> "Mixed" to MixedColor
    }
    AssistChip(
        onClick = {},
        label = { Text(label) },
        colors = AssistChipDefaults.assistChipColors(labelColor = color),
    )
}
