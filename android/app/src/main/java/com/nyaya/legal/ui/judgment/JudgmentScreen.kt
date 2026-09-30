package com.nyaya.legal.ui.judgment

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.nyaya.legal.data.Api
import com.nyaya.legal.data.JudgmentDetail
import com.nyaya.legal.ui.ErrorText
import com.nyaya.legal.ui.Loading
import com.nyaya.legal.ui.list
import com.nyaya.legal.ui.text
import kotlinx.coroutines.launch

class JudgmentViewModel(id: String) : ViewModel() {
    var judgment by mutableStateOf<JudgmentDetail?>(null)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    init {
        viewModelScope.launch {
            runCatching { Api.service.judgment(id) }
                .onSuccess { judgment = it }
                .onFailure { error = "Could not load judgment: ${it.message}" }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun JudgmentScreen(id: String, onBack: () -> Unit) {
    val vm: JudgmentViewModel = viewModel { JudgmentViewModel(id) }
    val uriHandler = LocalUriHandler.current
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Judgment") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
                actions = {
                    vm.judgment?.let { j ->
                        IconButton(onClick = { uriHandler.openUri(j.sourceUrl) }) {
                            Icon(Icons.AutoMirrored.Filled.OpenInNew, "View original PDF")
                        }
                    }
                },
            )
        },
    ) { padding ->
        val j = vm.judgment
        when {
            vm.error != null -> ErrorText(vm.error!!, Modifier.padding(padding))
            j == null -> Column(Modifier.padding(padding)) { Loading("Loading…") }
            else -> LazyColumn(
                Modifier.fillMaxSize().padding(padding),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item {
                    Text(j.title, style = MaterialTheme.typography.titleLarge)
                    Text(
                        listOfNotNull(j.court, j.decisionDate, j.citation ?: j.neutralCitation, j.judges).joinToString(" · "),
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                item { SummaryCard(j) }
                item { Text("Full text", style = MaterialTheme.typography.titleMedium) }
                items(j.paragraphs, key = { it.paraNo }) { p ->
                    Text(if (p.paraNo > 0) "¶${p.paraNo}  ${p.text.removePrefix("${p.paraNo}.").trim()}" else p.text)
                    HorizontalDivider(Modifier.padding(top = 8.dp))
                }
            }
        }
    }
}

@Composable
private fun SummaryCard(j: JudgmentDetail) {
    val s = j.summary
    Card {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("AI summary: check it against the full text", style = MaterialTheme.typography.labelSmall)
            Labeled("Outcome", s.text("outcome"))
            Labeled("Facts", s.text("facts"))
            Labeled("Issues", s.list("issues").joinToString("\n") { "• $it" }.ifEmpty { null })
            Labeled("Decision and reasoning", s.text("holding"))
            Labeled("Laws cited", s.list("acts_cited").joinToString("\n") { "• $it" }.ifEmpty { null })
        }
    }
}

@Composable
private fun Labeled(label: String, value: String?) {
    if (value.isNullOrBlank()) return
    Text(label, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.labelLarge)
    Text(value, style = MaterialTheme.typography.bodyMedium)
}
