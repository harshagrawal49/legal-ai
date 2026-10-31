package com.nyaya.legal.ui.intake

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.nyaya.legal.data.Api
import com.nyaya.legal.data.CaseDetail
import com.nyaya.legal.data.FactSheet
import com.nyaya.legal.data.IntakeAnswerRequest
import com.nyaya.legal.data.NewCaseRequest
import com.nyaya.legal.ui.Loading
import androidx.compose.foundation.layout.Row
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Description
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.LocalContext
import com.nyaya.legal.data.UPLOAD_MIMES
import com.nyaya.legal.data.uploadDocument
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class IntakeViewModel(private val existingCaseId: String?) : ViewModel() {
    var case by mutableStateOf<CaseDetail?>(null)
        private set
    var busy by mutableStateOf<String?>(null)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    init {
        existingCaseId?.let { id -> run("Loading…") { case = Api.service.getCase(id) } }
    }

    /** PDFs picked on the first step, before the case exists: (uri, file name). Uploaded after creation. */
    val pendingFiles = mutableStateListOf<Pair<Uri, String>>()

    fun submitDescription(text: String, resolver: ContentResolver) = run("Understanding your case…") {
        val created = Api.service.createCase(NewCaseRequest(text))
        case = created
        val failed = mutableListOf<String>()
        pendingFiles.forEachIndexed { i, (uri, name) ->
            busy = "Uploading documents (${i + 1}/${pendingFiles.size})…"
            runCatching { uploadDocument(resolver, created.id, uri) }.onFailure { failed += "$name: ${Api.errorMessage(it)}" }
        }
        val uploaded = pendingFiles.size - failed.size
        pendingFiles.clear()
        if (failed.isNotEmpty()) error = "Some documents were not uploaded:\n" + failed.joinToString("\n")
        if (uploaded > 0) waitForDocuments(created.id)
    }

    /** True while uploaded documents are still being read; the summary updates when they're done. */
    var readingDocuments by mutableStateOf(false)
        private set

    /** The server folds each processed document into the fact sheet; refresh until all are done. */
    private fun waitForDocuments(caseId: String) {
        readingDocuments = true
        viewModelScope.launch {
            repeat(60) { // up to ~3 minutes
                delay(3000)
                val docs = runCatching { Api.service.documents(caseId) }.getOrNull() ?: return@repeat
                if (docs.none { it.status == "processing" }) {
                    delay(1500) // the fact-sheet rebuild runs right after the last document
                    runCatching { case = Api.service.getCase(caseId) }
                    readingDocuments = false
                    return@launch
                }
            }
            readingDocuments = false
        }
    }

    fun submitAnswer(text: String) = run("Updating the summary…") {
        case = Api.service.answer(case!!.id, IntakeAnswerRequest(text))
    }

    fun search(onDone: (String) -> Unit) = run("Searching court judgments…") {
        Api.service.search(case!!.id)
        onDone(case!!.id)
    }

    private fun run(message: String, block: suspend () -> Unit) = viewModelScope.launch {
        busy = message
        error = null
        runCatching { block() }.onFailure { error = Api.errorMessage(it) }
        busy = null
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IntakeScreen(caseId: String?, onBack: () -> Unit, onResults: (String) -> Unit, onDocuments: (String) -> Unit) {
    val vm: IntakeViewModel = viewModel { IntakeViewModel(caseId) }
    val resolver = LocalContext.current.contentResolver
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(vm.case?.title ?: "New case") },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") }
                },
                actions = {
                    vm.case?.let { c -> TextButton(onClick = { onDocuments(c.id) }) { Text("My documents") } }
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            val busy = vm.busy
            val case = vm.case
            // At the top: the steps below scroll and fill the screen, so anything after them is hidden.
            vm.error?.let { message ->
                Card(
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                ) {
                    Text(message, color = MaterialTheme.colorScheme.onErrorContainer, modifier = Modifier.padding(12.dp))
                }
            }
            when {
                busy != null -> Loading(busy)
                case == null -> DescribeStep(vm.pendingFiles, onSubmit = { vm.submitDescription(it, resolver) })
                vm.readingDocuments && case.factSheet.summary.isBlank() -> Loading("Reading your documents and building the case summary…")
                else -> ReviewStep(case, onAnswer = vm::submitAnswer, onConfirm = { vm.search(onResults) }, onAttach = { onDocuments(case.id) })
            }
        }
    }
}

@Composable
private fun DescribeStep(files: MutableList<Pair<Uri, String>>, onSubmit: (String) -> Unit) {
    var text by rememberSaveableText()
    val resolver = LocalContext.current.contentResolver
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        uris.filter { u -> files.none { it.first == u } }.forEach { files += it to displayName(resolver, it) }
    }
    Column(Modifier.padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("What happened?", style = MaterialTheme.typography.titleLarge)
        Text("Describe your situation in your own words: who is involved, what was agreed, what went wrong and what you want. No legal terms needed. You can also skip this and just attach your documents.")
        OutlinedTextField(
            value = text,
            onValueChange = { text = it },
            placeholder = { Text("e.g. I paid an advance for a plot in 2023, but the seller agreed to sell it to someone else…") },
            modifier = Modifier.fillMaxWidth().heightIn(min = 180.dp),
        )

        Text("Documents (optional)", style = MaterialTheme.typography.titleMedium)
        Text(
            "Agreement to sell, receipts, notices, property records: PDF, or a photo (JPG/PNG), up to 10 MB each. Scans and photos are read with OCR.",
            style = MaterialTheme.typography.bodySmall,
        )
        files.forEach { (uri, name) ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.Description, null)
                Text(name, Modifier.weight(1f).padding(horizontal = 8.dp), maxLines = 1)
                IconButton(onClick = { files.removeAll { it.first == uri } }) { Icon(Icons.Default.Close, "Remove $name") }
            }
        }
        OutlinedButton(onClick = { picker.launch(UPLOAD_MIMES) }, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Default.AttachFile, null)
            Text(if (files.isEmpty()) "Attach documents" else "Attach more", Modifier.padding(start = 8.dp))
        }

        val trimmed = text.trim()
        Button(
            onClick = { onSubmit(trimmed) },
            // Either a description, or documents alone: the case is then built from the documents.
            enabled = trimmed.length >= 20 || (trimmed.isEmpty() && files.isNotEmpty()),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(if (trimmed.isEmpty() && files.isNotEmpty()) "Continue with documents only" else "Continue")
        }
        Text(
            "Your documents are the main record: names, dates, amounts and survey numbers are taken from them, " +
                "and anything that differs from what you wrote is shown so you can check it.",
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

private fun displayName(resolver: ContentResolver, uri: Uri): String =
    resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
        if (c.moveToFirst()) c.getString(0) else null
    } ?: "document.pdf"

@Composable
private fun ReviewStep(case: CaseDetail, onAnswer: (String) -> Unit, onConfirm: () -> Unit, onAttach: () -> Unit) {
    var answer by rememberSaveableText()
    Column(Modifier.padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (case.pendingQuestions.isNotEmpty()) {
            Card {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("A few questions", style = MaterialTheme.typography.titleMedium)
                    case.pendingQuestions.forEach { Text("• $it") }
                }
            }
        }
        OutlinedTextField(
            value = answer,
            onValueChange = { answer = it },
            label = { Text(if (case.pendingQuestions.isEmpty()) "Add or correct details" else "Your answers") },
            modifier = Modifier.fillMaxWidth().heightIn(min = 100.dp),
        )
        OutlinedButton(onClick = { onAnswer(answer.trim()); answer = "" }, enabled = answer.isNotBlank(), modifier = Modifier.fillMaxWidth()) {
            Text("Send")
        }

        Card {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Your documents", style = MaterialTheme.typography.titleMedium)
                Text(
                    "Attach agreements, receipts, notices or property records (PDF). They are used to build a " +
                        "timeline, flag gaps and prepare a brief, with every item linked to its page.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                OutlinedButton(onClick = onAttach, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Default.AttachFile, null)
                    Text("Attach documents", Modifier.padding(start = 8.dp))
                }
            }
        }

        Text("Our understanding of your case", style = MaterialTheme.typography.titleMedium)
        FactSheetCard(case.factSheet)
        Button(onClick = onConfirm, modifier = Modifier.fillMaxWidth()) {
            Text("This is correct: find similar cases")
        }
    }
}

@Composable
fun FactSheetCard(fs: FactSheet, filenames: Map<String, String> = emptyMap()) {
    Card {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(fs.summary)
            if (fs.conflicts.isNotEmpty()) {
                Text("Differences to check", fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.error)
                fs.conflicts.forEach { c ->
                    Text(
                        "• ${c.description}: " + (c.userSays?.let { "you said $it; " } ?: "") +
                            "documents say ${c.documentsSay}" + sourcesText(c.sources, filenames),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
            Section("Parties", fs.parties.map { "${it.name} (${it.role})" + sourcesText(it.sources, filenames) })
            Section("Timeline", fs.events.map { listOfNotNull(it.date, it.description).joinToString(": ") + sourcesText(it.sources, filenames) })
            Section("Amounts", fs.amounts.map { "${it.description}: ${it.value}" + sourcesText(it.sources, filenames) })
            Section("What you want", listOfNotNull(fs.reliefSought))
            Section("Legal issues", fs.issues)
            Section("Relevant laws", fs.legalAreas)
            Section("Still unknown", fs.missingInfo)
        }
    }
}

private val DOC_REF = Regex("""^D:([0-9a-f-]+):p(\d+)$""")

/** " · from receipt.pdf p.1 · you said", " · source not confirmed", or "" for older summaries. */
private fun sourcesText(sources: List<String>, filenames: Map<String, String>): String {
    if (sources.isEmpty()) return ""
    val parts = sources.mapNotNull { src ->
        when {
            src == "user" -> "you said"
            src == "unverified" -> "source not confirmed"
            else -> DOC_REF.matchEntire(src)?.let { m -> "from ${filenames[m.groupValues[1]] ?: "your document"} p.${m.groupValues[2]}" }
        }
    }
    return if (parts.isEmpty()) "" else " · " + parts.distinct().joinToString(" · ")
}

@Composable
private fun Section(title: String, lines: List<String>) {
    if (lines.isEmpty()) return
    Text(title, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.labelLarge)
    lines.forEach { Text("• $it", style = MaterialTheme.typography.bodyMedium) }
}

@Composable
private fun rememberSaveableText() = androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf("") }
