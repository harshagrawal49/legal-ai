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
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.consumeWindowInsets
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
import com.nyaya.legal.data.UPLOAD_MIMES
import com.nyaya.legal.data.uploadDocument
import com.nyaya.legal.ui.Disclaimer
import com.nyaya.legal.ui.ErrorText
import com.nyaya.legal.ui.markdown.MarkdownText
import com.nyaya.legal.ui.text
import androidx.compose.foundation.clickable
import androidx.compose.material3.HorizontalDivider
import androidx.compose.ui.text.withStyle
import com.nyaya.legal.data.ChatSource
import com.nyaya.legal.data.DocumentSummary
import kotlinx.coroutines.launch

/** `notice` messages are app status lines (e.g. an attached document), not part of the conversation. */
data class UiMessage(
    val fromUser: Boolean,
    val text: String,
    val notice: Boolean = false,
    /** Assistant replies: verified sources. Null while streaming (nothing shown yet). */
    val sources: List<ChatSource>? = null,
    /** Attachment notices: the uploaded document, so the line can open it. */
    val documentId: String? = null,
)

private val MENTION_QUERY = Regex("""@([^\s@]*)$""")

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
            runCatching { uploadDocument(resolver, caseId, uri) }
                .onSuccess { doc ->
                    filenames = filenames + (doc.id to doc.filename)
                    val result = when (doc.status) {
                        "processed" -> "${doc.pageCount} pages read. You can now ask about it."
                        "processing" -> if (doc.pageInfo.any { it.text("source") == "ocr_pending" }) {
                            "Reading the scan (OCR), then extracting facts. This can take a minute."
                        } else {
                            "${doc.pageCount} pages read. Facts are being extracted; you can already ask about it."
                        }
                        else -> doc.error ?: "It could not be processed."
                    }
                    messages.add(UiMessage(fromUser = false, text = "Attached ${doc.filename}: $result (tap to open)", notice = true, documentId = doc.id))
                    documents = documents + DocumentSummary(id = doc.id, filename = doc.filename, status = doc.status)
                }
                .onFailure { error = Api.errorMessage(it) }
            uploading = false
        }
    }

    /** The case's documents, for @ suggestions. */
    var documents by mutableStateOf<List<DocumentSummary>>(emptyList())
        private set

    /** History loaded. Sending is disabled until then, so a new message can't land above the history. */
    var loaded by mutableStateOf(false)
        private set

    init {
        viewModelScope.launch {
            runCatching {
                caseTitle = Api.service.getCase(caseId).title
                val history = Api.service.chatHistory(caseId)
                messages.addAll(history.map { UiMessage(it.role == "user", it.displayText, sources = if (it.role == "user") null else it.sources) })
                titles = Api.service.results(caseId).associate { it.judgment.id to it.judgment.title }
                documents = Api.service.documents(caseId)
                filenames = documents.associate { it.id to it.filename }
            }.onFailure { error = "Could not load the conversation: ${Api.errorMessage(it)}" }
            loaded = true
        }
    }

    /** Documents offered for the "@…" the user is typing at the end of the input. */
    fun mentionSuggestions(input: String): List<DocumentSummary> {
        val query = MENTION_QUERY.find(input)?.groupValues?.get(1) ?: return emptyList()
        return documents.filter { it.filename.contains(query, ignoreCase = true) }.take(5)
    }

    /** Document ids whose "@filename" appears in the message. */
    private fun mentionsIn(text: String) = documents.filter { "@${it.filename}" in text }.map { it.id }

    fun send(text: String) {
        messages.add(UiMessage(fromUser = true, text = text))
        // The reply's own position: notices (e.g. a finished upload) may be added after it while it streams.
        val reply = messages.size
        messages.add(UiMessage(fromUser = false, text = ""))
        streaming = true
        error = null
        viewModelScope.launch {
            Api.chat(caseId, text, mentionsIn(text)).collect { event ->
                when (event) {
                    is ChatEvent.Text -> {
                        messages[reply] = messages[reply].copy(text = messages[reply].text + event.delta)
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
                        messages[reply] = messages[reply].copy(sources = event.sources)
                        if (event.uncitedMentions.isNotEmpty()) {
                            val names = event.uncitedMentions.mapNotNull { filenames[it] }.joinToString()
                            messages.add(UiMessage(fromUser = false, text = "The answer didn't cite $names. Ask again if you expected it to.", notice = true))
                        }
                    }
                    is ChatEvent.Error -> {
                        error = event.message
                        if (messages[reply].text.isBlank()) messages.removeAt(reply) // no empty bubble
                    }
                }
            }
            streaming = false
            status = null
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class) // consumeWindowInsets: opt-in is harmless if already stable
@Composable
fun ChatScreen(
    caseId: String,
    onBack: () -> Unit,
    onOpenJudgment: (String) -> Unit,
    onOpenDocument: (String, Int?) -> Unit,
    initialMention: String? = null,
) {
    val vm: ChatViewModel = viewModel { ChatViewModel(caseId) }
    val listState = rememberLazyListState()
    var input by rememberSaveable { mutableStateOf("") }
    // Opened from "Ask about this document": start the message with @<that document>.
    LaunchedEffect(vm.documents, initialMention) {
        val doc = vm.documents.firstOrNull { it.id == initialMention }
        if (doc != null && input.isEmpty()) input = "@${doc.filename} "
    }
    val resolver = LocalContext.current.contentResolver
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
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
        Column(Modifier.fillMaxSize().padding(padding).consumeWindowInsets(padding).imePadding()) {
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
            val suggestions = vm.mentionSuggestions(input)
            if (suggestions.isNotEmpty()) {
                Card(Modifier.fillMaxWidth().padding(horizontal = 8.dp)) {
                    Column {
                        suggestions.forEach { doc ->
                            Text(
                                "@${doc.filename}" + (doc.documentType?.let { " · ${it.replace('_', ' ')}" } ?: ""),
                                modifier = Modifier.fillMaxWidth().clickable { input = input.replace(MENTION_QUERY, Regex.escapeReplacement("@${doc.filename} ")) }
                                    .padding(horizontal = 12.dp, vertical = 10.dp),
                            )
                        }
                    }
                }
            } else if (input.endsWith("@") && vm.documents.isEmpty()) {
                Text("No documents in this case yet. Attach one with 📎.", style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(horizontal = 12.dp))
            }
            Row(Modifier.padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { picker.launch(UPLOAD_MIMES) }, enabled = !vm.uploading && !vm.streaming && vm.loaded) {
                    Icon(Icons.Default.AttachFile, "Attach a PDF or photo")
                }
                OutlinedTextField(
                    value = input,
                    onValueChange = { input = it },
                    placeholder = { Text("Ask a question · type @ to refer to a document") },
                    modifier = Modifier.weight(1f),
                    maxLines = 5,
                )
                IconButton(
                    onClick = { vm.send(input.trim()); input = "" },
                    enabled = input.isNotBlank() && !vm.streaming && vm.loaded,
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
        Text(
            msg.text,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.secondary,
            modifier = msg.documentId?.let { id -> Modifier.clickable { onOpenDocument(id, null) } } ?: Modifier,
        )
        return
    }
    val colors = if (msg.fromUser) {
        CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
    } else {
        CardDefaults.cardColors()
    }
    Card(colors = colors, modifier = Modifier.fillMaxWidth(if (msg.fromUser) 0.85f else 1f)) {
        Column(Modifier.padding(12.dp)) {
            if (msg.fromUser) {
                Text(withMentions(msg.text))
            } else {
                // Replies are Markdown (lists, bold, sometimes tables): render them for a phone, with
                // citation markers turned into links wherever they appear.
                MarkdownText(
                    msg.text,
                    style = MaterialTheme.typography.bodyLarge,
                    plain = { appendCitations(it, titles, filenames, unverified, onOpenJudgment, onOpenDocument) },
                )
            }
            if (!msg.fromUser && msg.sources != null && msg.text.isNotBlank()) SourcesBlock(msg.sources, onOpenJudgment, onOpenDocument)
        }
    }
}

/** "Sources" under a reply: every document page and judgment it cited (verified by the backend). */
@Composable
private fun SourcesBlock(sources: List<ChatSource>, onOpenJudgment: (String) -> Unit, onOpenDocument: (String, Int?) -> Unit) {
    HorizontalDivider(Modifier.padding(vertical = 8.dp))
    if (sources.isEmpty()) {
        Text(
            "No sources cited: general information. Verify with an advocate.",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        return
    }
    Text("Sources", style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold)
    sources.forEach { s ->
        val (label, open) = when (s.type) {
            "document" -> "📄 ${s.filename ?: "document"}" + (s.page?.let { " · p.$it" } ?: "") to { s.documentId?.let { onOpenDocument(it, s.page) } }
            else -> "⚖️ ${s.title ?: "Judgment"}" + (s.court?.let { " · $it" } ?: "") to { s.judgmentId?.let(onOpenJudgment) }
        }
        Text(
            label,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.primary,
            modifier = Modifier.clickable { open() }.padding(vertical = 3.dp),
        )
    }
}

private val MENTION_TOKEN = Regex("""@\S+""")

/** User messages: show "@receipt.pdf" references in bold. */
private fun withMentions(text: String) = buildAnnotatedString {
    var last = 0
    for (m in MENTION_TOKEN.findAll(text)) {
        append(text.substring(last, m.range.first))
        withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { append(m.value) }
        last = m.range.last + 1
    }
    append(text.substring(last))
}

private val CITATION = Regex("""\[\[(?:J:([^\]]+)|D:([0-9a-f-]+):p(\d+))]]""")

/**
 * Appends [text], turning [[J:<id>]] markers into tappable links to the judgment screen and
 * [[D:<document id>:p<N>]] markers into links to that page of the user's document. Citations the
 * backend could not verify are not linked.
 */
private fun AnnotatedString.Builder.appendCitations(
    text: String,
    titles: Map<String, String>,
    filenames: Map<String, String>,
    unverified: Set<String>,
    onOpenJudgment: (String) -> Unit,
    onOpenDocument: (String, Int?) -> Unit,
) {
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
