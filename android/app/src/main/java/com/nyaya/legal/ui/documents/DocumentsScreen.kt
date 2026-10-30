package com.nyaya.legal.ui.documents

import android.content.ContentResolver
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.UploadFile
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.nyaya.legal.data.Api
import com.nyaya.legal.data.DocumentSummary
import com.nyaya.legal.data.Evidence
import com.nyaya.legal.data.Flag
import com.nyaya.legal.data.PDF_MIME
import com.nyaya.legal.data.SourceRef
import com.nyaya.legal.data.TimelineItem
import com.nyaya.legal.data.uploadPdf
import com.nyaya.legal.ui.ErrorText
import com.nyaya.legal.ui.Loading
import kotlinx.coroutines.launch

class DocumentsViewModel(private val caseId: String) : ViewModel() {
    var documents by mutableStateOf<List<DocumentSummary>?>(null)
        private set
    var evidence by mutableStateOf<Evidence?>(null)
        private set
    var busy by mutableStateOf<String?>(null)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            runCatching {
                documents = Api.service.documents(caseId)
                evidence = Api.service.evidence(caseId)
            }.onFailure { error = Api.errorMessage(it) }
        }
    }

    private fun run(label: String, block: suspend () -> Unit) {
        busy = label
        error = null
        viewModelScope.launch {
            runCatching { block() }.onFailure { error = Api.errorMessage(it) }
            busy = null
            refresh()
        }
    }

    fun upload(resolver: ContentResolver, uri: Uri) = run("Reading the document and extracting facts…") {
        uploadPdf(resolver, caseId, uri)
    }

    fun retry(docId: String) = run("Extracting facts again…") { Api.service.retryExtraction(caseId, docId) }

    fun delete(docId: String) = run("Deleting…") { Api.service.deleteDocument(caseId, docId) }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DocumentsScreen(caseId: String, onBack: () -> Unit, onOpenDocument: (String, Int?) -> Unit, onBrief: () -> Unit) {
    val vm: DocumentsViewModel = viewModel { DocumentsViewModel(caseId) }
    val resolver = LocalContext.current.contentResolver
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        uri?.let { vm.upload(resolver, it) }
    }
    var tab by rememberSaveable { mutableIntStateOf(0) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Documents and evidence") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
                actions = { TextButton(onClick = onBrief, enabled = !vm.documents.isNullOrEmpty()) { Text("Brief") } },
            )
        },
        floatingActionButton = {
            if (vm.busy == null) {
                ExtendedFloatingActionButton(
                    onClick = { picker.launch(PDF_MIME) },
                    icon = { Icon(Icons.Default.UploadFile, null) },
                    text = { Text("Upload PDF") },
                )
            }
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            PreparationNotice()
            vm.busy?.let {
                LinearProgressIndicator(Modifier.fillMaxWidth())
                Text(it, style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
            }
            vm.error?.let { ErrorText(it) }
            TabRow(selectedTabIndex = tab) {
                Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text("Documents") })
                Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("Timeline & flags") })
            }
            val docs = vm.documents
            when {
                docs == null && vm.error == null -> Loading("Loading…")
                docs == null -> Unit
                tab == 0 -> DocumentList(docs, onOpen = { onOpenDocument(it, null) }, onRetry = vm::retry, onDelete = vm::delete)
                else -> EvidenceList(vm.evidence ?: Evidence(), onOpenSource = onOpenDocument)
            }
        }
    }
}

@Composable
private fun DocumentList(
    docs: List<DocumentSummary>,
    onOpen: (String) -> Unit,
    onRetry: (String) -> Unit,
    onDelete: (String) -> Unit,
) {
    if (docs.isEmpty()) {
        Text(
            "No documents yet. Upload a text-based PDF such as an agreement to sell, a receipt or a notice. " +
                "Scanned images are not supported yet.",
            Modifier.padding(16.dp),
        )
        return
    }
    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        items(docs, key = { it.id }) { doc ->
            Card(Modifier.fillMaxWidth().clickable(enabled = doc.pageCount > 0) { onOpen(doc.id) }) {
                Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.Description, null)
                    Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
                        Text(doc.filename, style = MaterialTheme.typography.titleSmall)
                        Text(
                            listOfNotNull(doc.documentType?.let(::humanise), "${doc.pageCount} pages", statusLabel(doc.status))
                                .joinToString(" · "),
                            style = MaterialTheme.typography.bodySmall,
                        )
                        doc.error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                        if (doc.status == "text_only") TextButton(onClick = { onRetry(doc.id) }) { Text("Try extraction again") }
                    }
                    IconButton(onClick = { onDelete(doc.id) }) { Icon(Icons.Default.Delete, "Delete document") }
                }
            }
        }
    }
}

@Composable
private fun EvidenceList(evidence: Evidence, onOpenSource: (String, Int?) -> Unit) {
    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { SectionTitle("Possible gaps and differences to check") }
        if (evidence.flags.isEmpty()) item { Text("None found in the uploaded documents.") }
        items(evidence.flags) { FlagCard(it, onOpenSource) }
        item { SectionTitle("Chronology from the documents") }
        if (evidence.timeline.isEmpty()) item { Text("No dated events were found in the uploaded documents.") }
        items(evidence.timeline) { TimelineRow(it, onOpenSource) }
    }
}

@Composable
fun FlagCard(flag: Flag, onOpenSource: (String, Int?) -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(flag.message, style = MaterialTheme.typography.bodyMedium)
            flag.sources.forEach { SourceLink(it, onOpenSource) }
        }
    }
}

@Composable
fun TimelineRow(item: TimelineItem, onOpenSource: (String, Int?) -> Unit) {
    Column {
        Text(item.date ?: item.dateAsWritten ?: "Undated", style = MaterialTheme.typography.labelLarge)
        Text(item.description, style = MaterialTheme.typography.bodyMedium)
        SourceLink(item.source, onOpenSource)
    }
}

/** "agreement.pdf, p.2" plus whether the quoted excerpt was found on that page. Tapping opens the page. */
@Composable
fun SourceLink(ref: SourceRef, onOpenSource: (String, Int?) -> Unit) {
    val where = listOfNotNull(ref.filename, ref.page?.let { "p.$it" }).joinToString(", ")
    val check = when {
        ref.page == null -> ""
        ref.verified -> " · quote found on page"
        else -> " · quote NOT found on page, check the original"
    }
    Text(
        (ref.value?.let { "$it: " } ?: "") + where + check,
        style = MaterialTheme.typography.labelSmall,
        color = if (ref.page != null && !ref.verified) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
        modifier = Modifier.clickable { onOpenSource(ref.documentId, ref.page) },
    )
}

/** Fixed in the UI, never left to the model. */
@Composable
fun PreparationNotice() {
    Text(
        "Preparation aid only. Items are extracted automatically and may be wrong: check them against your " +
            "original documents. \"Not found\" means not found in the uploaded documents, not that it did not happen.",
        style = MaterialTheme.typography.labelSmall,
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
    )
}

@Composable
fun SectionTitle(text: String) {
    Text(text, style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 8.dp))
}

fun humanise(value: String) = value.replace('_', ' ').replaceFirstChar { it.uppercase() }

private fun statusLabel(status: String) = when (status) {
    "processed" -> "Processed"
    "text_only" -> "Text only"
    else -> "Not readable"
}
