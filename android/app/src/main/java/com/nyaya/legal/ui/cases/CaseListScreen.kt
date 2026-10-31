package com.nyaya.legal.ui.cases

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Gavel
import androidx.compose.material.icons.filled.Timeline
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.Alignment
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.nyaya.legal.data.Api
import com.nyaya.legal.data.CaseSummary
import com.nyaya.legal.ui.ErrorText
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import com.nyaya.legal.data.LibraryDocument
import kotlinx.coroutines.launch

class CaseListViewModel : ViewModel() {
    var cases by mutableStateOf<List<CaseSummary>>(emptyList())
        private set
    var error by mutableStateOf<String?>(null)
        private set

    /** "All my documents": every document the user uploaded, across cases. */
    var documents by mutableStateOf<List<LibraryDocument>>(emptyList())
        private set

    fun load() = viewModelScope.launch {
        runCatching { Api.service.listCases() }
            .onSuccess { cases = it; error = null }
            .onFailure { error = Api.errorMessage(it) }
        runCatching { Api.service.allDocuments() }.onSuccess { documents = it }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CaseListScreen(
    onNewCase: () -> Unit,
    onOpenCase: (CaseSummary) -> Unit,
    onOpenDocument: (caseId: String, docId: String) -> Unit,
    vm: CaseListViewModel = viewModel(),
) {
    LaunchedEffect(Unit) { vm.load() }
    var tab by rememberSaveable { mutableIntStateOf(0) }

    Scaffold(
        topBar = {
            Column {
                TopAppBar(title = { Text("NyayaSathi") })
                TabRow(selectedTabIndex = tab) {
                    Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text("My cases") })
                    Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("All my documents (${vm.documents.size})") })
                }
            }
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = onNewCase,
                icon = { Icon(Icons.Default.Add, contentDescription = null) },
                text = { Text("New case") },
            )
        },
    ) { padding ->
        if (tab == 1) {
            DocumentLibrary(vm.documents, Modifier.padding(padding), onOpenDocument)
            return@Scaffold
        }
        LazyColumn(Modifier.fillMaxSize().padding(padding)) {
            vm.error?.let { item { ErrorText(it) } }
            if (vm.cases.isEmpty() && vm.error == null) item { Welcome() }
            items(vm.cases, key = { it.id }) { case ->
                ListItem(
                    headlineContent = { Text(case.title) },
                    supportingContent = { Text(statusLabel(case.status)) },
                    modifier = Modifier.clickable { onOpenCase(case) },
                )
                HorizontalDivider()
            }
        }
    }
}

private fun statusLabel(status: String) = when (status) {
    "intake" -> "Describing the case"
    "searched" -> "Similar cases found"
    else -> status
}

private val FEATURES = listOf(
    Icons.Default.Edit to ("Describe your case" to "In your own words. We build a structured summary and ask what's missing."),
    Icons.Default.AttachFile to ("Attach your documents" to "Agreements, receipts, notices. Facts are extracted with page references."),
    Icons.Default.Timeline to ("Timeline and gaps" to "A chronology, plus differing amounts, dates or survey numbers to check."),
    Icons.Default.Gavel to ("Similar court cases" to "Indian Supreme Court judgments that support or weaken your position."),
    Icons.AutoMirrored.Filled.Chat to ("Chat about your case" to "Answers that cite your document pages and real judgments."),
    Icons.Default.Description to ("Case-preparation brief" to "Facts, gaps and questions to take to your advocate."),
)

@Composable
private fun Welcome() {
    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Prepare your property dispute", style = MaterialTheme.typography.titleLarge)
        Text("Tap New case to start. Here's what you can do:", style = MaterialTheme.typography.bodyMedium)
        FEATURES.forEach { (icon, text) ->
            Card(Modifier.fillMaxWidth()) {
                Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(icon, null, tint = MaterialTheme.colorScheme.primary)
                    Column(Modifier.padding(start = 12.dp)) {
                        Text(text.first, style = MaterialTheme.typography.titleSmall)
                        Text(text.second, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
        Text(
            "A preparation aid, not legal advice. It does not predict outcomes or replace an advocate.",
            style = MaterialTheme.typography.labelSmall,
        )
    }
}

/** Every uploaded document, grouped by case; tap to open its explanation. */
@Composable
private fun DocumentLibrary(docs: List<LibraryDocument>, modifier: Modifier, onOpen: (String, String) -> Unit) {
    if (docs.isEmpty()) {
        Text("No documents yet. Attach them when you describe a case, in My documents, or with 📎 in chat.", modifier.padding(24.dp))
        return
    }
    LazyColumn(modifier.fillMaxSize()) {
        docs.groupBy { it.caseTitle }.forEach { (caseTitle, group) ->
            item { Text(caseTitle, style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(start = 16.dp, top = 16.dp, bottom = 4.dp)) }
            items(group, key = { it.id }) { d ->
                ListItem(
                    leadingContent = { Icon(Icons.Default.Description, null) },
                    headlineContent = { Text(d.filename) },
                    supportingContent = {
                        Text(
                            listOfNotNull(
                                d.documentType?.replace('_', ' ')?.replaceFirstChar { it.uppercase() },
                                "${d.pageCount} pages",
                                when {
                                    d.status == "processing" -> "Reading…"
                                    d.understood -> "Explained"
                                    d.status == "failed" -> "Not readable"
                                    else -> null
                                },
                            ).joinToString(" · "),
                        )
                    },
                    modifier = Modifier.clickable(enabled = d.pageCount > 0) { onOpen(d.caseId, d.id) },
                )
                HorizontalDivider()
            }
        }
    }
}
