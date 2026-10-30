package com.nyaya.legal.ui.chat

import android.content.ContentResolver
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withLink
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.nyaya.legal.data.Api
import com.nyaya.legal.data.ChatEvent
import com.nyaya.legal.data.PDF_MIME
import com.nyaya.legal.data.uploadPdf
import com.nyaya.legal.ui.Disclaimer
import com.nyaya.legal.ui.ErrorText
import kotlinx.coroutines.launch

/** `notice` messages are app status lines (e.g. an attached document), not part of the conversation. */
data class UiMessage(val fromUser: Boolean, val text: String, val notice: Boolean = false)

class ChatViewModel(private val caseId: String) : ViewModel() {
    val messages = mutableStateListOf<UiMessage>()
    var streaming by mutableStateOf(false)
        private set
    var status by mutableStateOf<String?>(null)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    /** judgment id -> short title, used to label citation links. */
    var titles by mutableStateOf<Map<String, String>>(emptyMap())
        private set

    /** document id -> filename, used to label document citation links. */
    var filenames by mutableStateOf<Map<String, String>>(emptyMap())
        private set

    /** Citations the backend could not verify; shown as plain text rather than links. */
    var unverified by mutableStateOf<Set<String>>(emptySet())
        private set

    var uploading by mutableStateOf(false)
        private set

    /** Shown in the title so it's clear which case this conversation is about. */
    var caseTitle by mutableStateOf<String?>(null)
        private set

    fun attach(resolver: ContentResolver, uri: Uri) {
        uploading = true
        error = null
        viewModelScope.launch {
            runCatching { uploadPdf(resolver, caseId, uri) }
                .onSuccess { doc ->
                    filenames = filenames + (doc.id to doc.filename)
                    val result = when (doc.status) {
                        "processed" -> "${doc.pageCount} pages read. You can now ask about it."
                        "processing" -> "${doc.pageCount} pages read. Facts are being extracted; you can already ask about it."
                        else -> doc.error ?: "It could not be processed."
                    }
                    messages.add(UiMessage(fromUser = false, text = "Attached ${doc.filename}: $result", notice = true))
                }
                .onFailure { error = Api.errorMessage(it) }
            uploading = false
        }
    }

    init {
        viewModelScope.launch {
            runCatching {
                caseTitle = Api.service.getCase(caseId).title
                val history = Api.service.chatHistory(caseId)
                messages.addAll(history.map { UiMessage(it.role == "user", it.displayText) })
                titles = Api.service.results(caseId).associate { it.judgment.id to it.judgment.title }
                filenames = Api.service.documents(caseId).associate { it.id to it.filename }
            }.onFailure { error = "Could not load the conversation: ${it.message}" }
        }
    }

    fun send(text: String) {
        messages.add(UiMessage(fromUser = true, text = text))
        messages.add(UiMessage(fromUser = false, text = ""))
        streaming = true
        error = null
        viewModelScope.launch {
            Api.chat(caseId, text).collect { event ->
                when (event) {
                    is ChatEvent.Text -> {
                        val last = messages.last()
                        messages[messages.lastIndex] = last.copy(text = last.text + event.delta)
                        status = null
                    }
                    is ChatEvent.Tool -> status = when (event.name) {
                        "search_judgments" -> "Searching judgments…"
                        "read_judgment" -> "Reading a judgment…"
                        "read_case_documents" -> "Reading your documents…"
                        else -> "Working…"
                    }
                    is ChatEvent.Done -> {
                        status = null
                        unverified = unverified + event.unverified
                    }
                    is ChatEvent.Error -> error = event.message
                }
            }
            streaming = false
            status = null
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    caseId: String,
    onBack: () -> Unit,
    onOpenJudgment: (String) -> Unit,
    onOpenDocument: (String, Int?) -> Unit,
) {
    val vm: ChatViewModel = viewModel { ChatViewModel(caseId) }
    val listState = rememberLazyListState()
    var input by rememberSaveable { mutableStateOf("") }
    val resolver = LocalContext.current.contentResolver
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        uri?.let { vm.attach(resolver, it) }
    }

    LaunchedEffect(vm.messages.size, vm.messages.lastOrNull()?.text?.length) {
        if (vm.messages.isNotEmpty()) listState.scrollToItem(vm.messages.lastIndex)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("Ask about your case")
                        vm.caseTitle?.let { Text(it, style = MaterialTheme.typography.labelMedium, maxLines = 1) }
                    }
                },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).imePadding()) {
            Disclaimer()
            LazyColumn(
                Modifier.weight(1f),
                state = listState,
                contentPadding = PaddingValues(12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (vm.messages.isEmpty()) {
                    item {
                        Text(
                            "The assistant already knows this case: your summary, documents and any similar " +
                                "judgments found. Try: \"What do my documents show about the advance?\", " +
                                "\"Which case is most similar to mine?\" or \"What could weaken my position?\"",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
                items(vm.messages) { MessageBubble(it, vm.titles, vm.filenames, vm.unverified, onOpenJudgment, onOpenDocument) }
                vm.status?.let { item { Text(it, style = MaterialTheme.typography.labelMedium) } }
            }
            vm.error?.let { ErrorText(it) }
            if (vm.uploading) Text("Reading the document…", style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(horizontal = 12.dp))
            Row(Modifier.padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { picker.launch(PDF_MIME) }, enabled = !vm.uploading && !vm.streaming) {
                    Icon(Icons.Default.AttachFile, "Attach a PDF")
                }
                OutlinedTextField(
                    value = input,
                    onValueChange = { input = it },
                    placeholder = { Text("Ask a question") },
                    modifier = Modifier.weight(1f),
                    maxLines = 5,
                )
                IconButton(
                    onClick = { vm.send(input.trim()); input = "" },
                    enabled = input.isNotBlank() && !vm.streaming,
                ) { Icon(Icons.AutoMirrored.Filled.Send, "Send") }
            }
        }
    }
}

@Composable
private fun MessageBubble(
    msg: UiMessage,
    titles: Map<String, String>,
    filenames: Map<String, String>,
    unverified: Set<String>,
    onOpenJudgment: (String) -> Unit,
    onOpenDocument: (String, Int?) -> Unit,
) {
    if (msg.notice) {
        Text(msg.text, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.secondary)
        return
    }
    val colors = if (msg.fromUser) {
        CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
    } else {
        CardDefaults.cardColors()
    }
    Card(colors = colors, modifier = Modifier.fillMaxWidth(if (msg.fromUser) 0.85f else 1f)) {
        Text(
            if (msg.fromUser) AnnotatedString(msg.text) else withCitationLinks(msg.text, titles, filenames, unverified, onOpenJudgment, onOpenDocument),
            modifier = Modifier.padding(12.dp),
        )
    }
}

private val CITATION = Regex("""\[\[(?:J:([^\]]+)|D:([0-9a-f-]+):p(\d+))]]""")

/**
 * Turns [[J:<id>]] markers into tappable links to the judgment screen and [[D:<document id>:p<N>]]
 * markers into links to that page of the user's document. Citations the backend could not verify
 * are not linked.
 */
private fun withCitationLinks(
    text: String,
    titles: Map<String, String>,
    filenames: Map<String, String>,
    unverified: Set<String>,
    onOpenJudgment: (String) -> Unit,
    onOpenDocument: (String, Int?) -> Unit,
) = buildAnnotatedString {
    var last = 0
    for (match in CITATION.findAll(text)) {
        append(text.substring(last, match.range.first))
        val (judgmentId, docId, page) = match.destructured
        if ((if (judgmentId.isNotEmpty()) judgmentId else "$docId:p$page") in unverified) {
            append("[unverified source]")
            last = match.range.last + 1
            continue
        }
        val label = if (judgmentId.isNotEmpty()) {
            titles[judgmentId]?.let { shorten(it) } ?: "case"
        } else {
            "${filenames[docId] ?: "document"}, p.$page"
        }
        withLink(
            LinkAnnotation.Clickable(
                tag = match.value,
                styles = TextLinkStyles(SpanStyle(fontWeight = FontWeight.SemiBold)),
            ) { if (judgmentId.isNotEmpty()) onOpenJudgment(judgmentId) else onOpenDocument(docId, page.toInt()) },
        ) { append("[$label]") }
        last = match.range.last + 1
    }
    append(text.substring(last))
}

private fun shorten(title: String) = title.split(" versus ", " vs ", " v. ").first().trim().take(40)
