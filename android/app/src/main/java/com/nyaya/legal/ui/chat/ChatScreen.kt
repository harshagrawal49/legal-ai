package com.nyaya.legal.ui.chat

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
import com.nyaya.legal.ui.Disclaimer
import com.nyaya.legal.ui.ErrorText
import kotlinx.coroutines.launch

data class UiMessage(val fromUser: Boolean, val text: String)

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

    init {
        viewModelScope.launch {
            runCatching {
                val history = Api.service.chatHistory(caseId)
                messages.addAll(history.map { UiMessage(it.role == "user", it.displayText) })
                titles = Api.service.results(caseId).associate { it.judgment.id to it.judgment.title }
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
                        else -> "Working…"
                    }
                    is ChatEvent.Done -> status = null
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
fun ChatScreen(caseId: String, onBack: () -> Unit, onOpenJudgment: (String) -> Unit) {
    val vm: ChatViewModel = viewModel { ChatViewModel(caseId) }
    val listState = rememberLazyListState()
    var input by rememberSaveable { mutableStateOf("") }

    LaunchedEffect(vm.messages.size, vm.messages.lastOrNull()?.text?.length) {
        if (vm.messages.isNotEmpty()) listState.scrollToItem(vm.messages.lastIndex)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Ask about your case") },
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
                            "Try: \"Which case is most similar to mine?\", \"Why did the buyer win?\" or " +
                                "\"What could weaken my position?\"",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
                items(vm.messages) { MessageBubble(it, vm.titles, onOpenJudgment) }
                vm.status?.let { item { Text(it, style = MaterialTheme.typography.labelMedium) } }
            }
            vm.error?.let { ErrorText(it) }
            Row(Modifier.padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
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
private fun MessageBubble(msg: UiMessage, titles: Map<String, String>, onOpenJudgment: (String) -> Unit) {
    val colors = if (msg.fromUser) {
        CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
    } else {
        CardDefaults.cardColors()
    }
    Card(colors = colors, modifier = Modifier.fillMaxWidth(if (msg.fromUser) 0.85f else 1f)) {
        Text(
            if (msg.fromUser) AnnotatedString(msg.text) else withCitationLinks(msg.text, titles, onOpenJudgment),
            modifier = Modifier.padding(12.dp),
        )
    }
}

private val CITATION = Regex("""\[\[J:([^\]]+)]]""")

/** Turns [[J:<id>]] markers from the assistant into tappable links to the judgment screen. */
private fun withCitationLinks(text: String, titles: Map<String, String>, onOpen: (String) -> Unit) =
    buildAnnotatedString {
        var last = 0
        for (match in CITATION.findAll(text)) {
            append(text.substring(last, match.range.first))
            val id = match.groupValues[1]
            val label = titles[id]?.let { shorten(it) } ?: "case"
            withLink(
                LinkAnnotation.Clickable(
                    tag = id,
                    styles = TextLinkStyles(SpanStyle(fontWeight = FontWeight.SemiBold)),
                ) { onOpen(id) },
            ) { append("[$label]") }
            last = match.range.last + 1
        }
        append(text.substring(last))
    }

private fun shorten(title: String) = title.split(" versus ", " vs ", " v. ").first().trim().take(40)
