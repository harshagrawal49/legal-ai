package com.nyaya.legal.ui.intake

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
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
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
import com.nyaya.legal.ui.ErrorText
import com.nyaya.legal.ui.Loading
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

    fun submitDescription(text: String) = run("Understanding your case…") {
        case = Api.service.createCase(NewCaseRequest(text))
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
        runCatching { block() }.onFailure { error = "Something went wrong: ${it.message}" }
        busy = null
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IntakeScreen(caseId: String?, onBack: () -> Unit, onResults: (String) -> Unit) {
    val vm: IntakeViewModel = viewModel { IntakeViewModel(caseId) }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(vm.case?.title ?: "New case") },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") }
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            val busy = vm.busy
            val case = vm.case
            when {
                busy != null -> Loading(busy)
                case == null -> DescribeStep(onSubmit = vm::submitDescription)
                else -> ReviewStep(case, onAnswer = vm::submitAnswer, onConfirm = { vm.search(onResults) })
            }
            vm.error?.let { ErrorText(it) }
        }
    }
}

@Composable
private fun DescribeStep(onSubmit: (String) -> Unit) {
    var text by rememberSaveableText()
    Column(Modifier.padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("What happened?", style = MaterialTheme.typography.titleLarge)
        Text("Describe your situation in your own words: who is involved, what was agreed, what went wrong and what you want. No legal terms needed.")
        OutlinedTextField(
            value = text,
            onValueChange = { text = it },
            placeholder = { Text("e.g. I paid for a flat in 2019 but the builder hasn't given possession or refunded my money…") },
            modifier = Modifier.fillMaxWidth().heightIn(min = 180.dp),
        )
        Button(onClick = { onSubmit(text.trim()) }, enabled = text.trim().length >= 20, modifier = Modifier.fillMaxWidth()) {
            Text("Continue")
        }
    }
}

@Composable
private fun ReviewStep(case: CaseDetail, onAnswer: (String) -> Unit, onConfirm: () -> Unit) {
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

        Text("Our understanding of your case", style = MaterialTheme.typography.titleMedium)
        FactSheetCard(case.factSheet)
        Button(onClick = onConfirm, modifier = Modifier.fillMaxWidth()) {
            Text("This is correct: find similar cases")
        }
    }
}

@Composable
fun FactSheetCard(fs: FactSheet) {
    Card {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(fs.summary)
            Section("Parties", fs.parties.map { "${it.name} (${it.role})" })
            Section("Timeline", fs.events.map { listOfNotNull(it.date, it.description).joinToString(": ") })
            Section("Amounts", fs.amounts.map { "${it.description}: ${it.value}" })
            Section("What you want", listOfNotNull(fs.reliefSought))
            Section("Legal issues", fs.issues)
            Section("Relevant laws", fs.legalAreas)
            Section("Still unknown", fs.missingInfo)
        }
    }
}

@Composable
private fun Section(title: String, lines: List<String>) {
    if (lines.isEmpty()) return
    Text(title, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.labelLarge)
    lines.forEach { Text("• $it", style = MaterialTheme.typography.bodyMedium) }
}

@Composable
private fun rememberSaveableText() = androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf("") }
