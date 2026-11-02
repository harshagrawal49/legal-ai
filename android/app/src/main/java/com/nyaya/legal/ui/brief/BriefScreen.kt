package com.nyaya.legal.ui.brief

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.nyaya.legal.data.Api
import com.nyaya.legal.data.Brief
import com.nyaya.legal.ui.ErrorText
import com.nyaya.legal.ui.Loading
import com.nyaya.legal.ui.documents.FlagCard
import com.nyaya.legal.ui.documents.SectionTitle
import com.nyaya.legal.ui.documents.SourceLink
import com.nyaya.legal.ui.documents.TimelineRow
import com.nyaya.legal.ui.documents.humanise
import kotlinx.coroutines.launch
import com.nyaya.legal.ui.markdown.BulletText
import com.nyaya.legal.ui.markdown.MarkdownText
import com.nyaya.legal.ui.markdown.markdownInline
import androidx.compose.ui.text.font.FontWeight

class BriefViewModel(private val caseId: String) : ViewModel() {
    var brief by mutableStateOf<Brief?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    init {
        generate()
    }

    fun generate() {
        loading = true
        error = null
        viewModelScope.launch {
            runCatching { Api.service.brief(caseId) }
                .onSuccess { brief = it }
                .onFailure { error = Api.errorMessage(it) }
            loading = false
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BriefScreen(
    caseId: String,
    onBack: () -> Unit,
    onOpenDocument: (String, Int?) -> Unit,
    onOpenJudgment: (String) -> Unit,
) {
    val vm: BriefViewModel = viewModel { BriefViewModel(caseId) }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Case-preparation brief") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
                actions = {
                    IconButton(onClick = vm::generate, enabled = !vm.loading) { Icon(Icons.Default.Refresh, "Regenerate") }
                },
            )
        },
    ) { padding ->
        val brief = vm.brief
        Column(Modifier.fillMaxSize().padding(padding)) {
            vm.error?.let { ErrorText(it) }
            when {
                vm.loading && brief == null -> Loading("Preparing your brief…")
                brief != null -> BriefContent(brief, onOpenDocument, onOpenJudgment)
            }
        }
    }
}

@Composable
private fun BriefContent(brief: Brief, onOpenDocument: (String, Int?) -> Unit, onOpenJudgment: (String) -> Unit) {
    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item {
            // The disclaimer text comes from the backend code, not from the model.
            Surface(color = MaterialTheme.colorScheme.secondaryContainer, modifier = Modifier.fillMaxWidth()) {
                Text("DRAFT. ${brief.disclaimer}", style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(10.dp))
            }
        }

        item { SectionTitle("1. Your summary") }
        item { MarkdownText(brief.userSummary ?: "No summary given yet.") }

        item { SectionTitle("2. Documents processed") }
        items(brief.documents) { d ->
            Text(
                "${d.filename}: ${d.documentType?.let(::humanise) ?: "unknown type"}, ${d.pageCount} pages, ${d.status}" +
                    (if (d.ocrPages > 0) ", ${d.ocrPages} scanned page(s) read by OCR" + (d.ocrConfidence?.let { " (avg ${it.toInt()}%)" } ?: "") else "") +
                    (d.error?.let { " ($it)" } ?: ""),
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.clickable(enabled = d.pageCount > 0) { onOpenDocument(d.documentId, null) },
            )
        }

        item { SectionTitle("3. Chronology from the documents") }
        if (brief.chronology.isEmpty()) item { Text("No dated events found in the uploaded documents.") }
        items(brief.chronology) { TimelineRow(it, onOpenDocument) }

        item { SectionTitle("4. Facts supported by your documents") }
        if (brief.supportedFacts.isEmpty()) item { Text("None yet. Upload documents to build this section.") }
        items(brief.supportedFacts) { f ->
            Column {
                Text(markdownInline("**${humanise(f.category)}:** ${f.text}"), style = MaterialTheme.typography.bodyMedium)
                SourceLink(f.source, onOpenDocument)
            }
        }

        section(
            "5. Your account, not independently supported by the uploaded documents",
            brief.userAccount.ifEmpty { listOf("Nothing recorded.") },
        )

        item { SectionTitle("6. Gaps, inconsistencies and missing information") }
        if (brief.gaps.isEmpty()) item { Text("None found in the uploaded documents.") }
        items(brief.gaps) { FlagCard(it, onOpenDocument) }

        item { SectionTitle("7. Potentially relevant judgments") }
        if (brief.legalSources.isEmpty()) item { Text("No similar-case search has been run for this case yet.") }
        items(brief.legalSources) { s ->
            Card(Modifier.fillMaxWidth().clickable { onOpenJudgment(s.judgmentId) }) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(s.title, style = MaterialTheme.typography.titleSmall)
                    Text(listOfNotNull(s.court, s.decisionDate, s.citation).joinToString(" · "), style = MaterialTheme.typography.bodySmall)
                    Text("Why it may matter", style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold)
                    MarkdownText(s.whyItMayMatter)
                    if (s.keyParagraphs.isNotEmpty()) {
                        Text("Key paragraphs: " + s.keyParagraphs.joinToString { "¶$it" }, style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
        }

        val note = if (brief.suggestionsAiGenerated) " (AI-suggested, review them)" else " (generated from the flags above)"
        section("8. Questions to discuss with an advocate$note", brief.advocateQuestions, marker = "•")
        section("9. Preparation checklist$note", brief.checklist, marker = "☐")
    }
}

/** A titled list. With a [marker], each line is a bullet with a hanging indent. */
private fun LazyListScope.section(title: String, lines: List<String>, marker: String? = null) {
    item { SectionTitle(title) }
    items(lines) { if (marker != null) BulletText(it, marker) else MarkdownText(it) }
}
