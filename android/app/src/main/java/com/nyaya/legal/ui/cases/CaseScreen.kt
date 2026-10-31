package com.nyaya.legal.ui.cases

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Gavel
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.nyaya.legal.data.Api
import com.nyaya.legal.data.CaseDetail
import com.nyaya.legal.ui.Disclaimer
import com.nyaya.legal.ui.ErrorText
import com.nyaya.legal.ui.Loading
import com.nyaya.legal.ui.intake.FactSheetCard
import kotlinx.coroutines.launch

class CaseViewModel(private val caseId: String) : ViewModel() {
    var case by mutableStateOf<CaseDetail?>(null)
        private set
    var documentCount by mutableStateOf(0)
        private set
    var filenames by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    var error by mutableStateOf<String?>(null)
        private set

    fun load() {
        viewModelScope.launch {
            runCatching {
                case = Api.service.getCase(caseId)
                val docs = Api.service.documents(caseId)
                documentCount = docs.size
                filenames = docs.associate { it.id to it.filename }
            }.onSuccess { error = null }
                .onFailure { error = Api.errorMessage(it) }
        }
    }
}

/** Home of one case: its summary and everything the user can do with it. Chat is the main action. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CaseScreen(
    caseId: String,
    onBack: () -> Unit,
    onChat: () -> Unit,
    onDocuments: () -> Unit,
    onResults: () -> Unit,
    onIntake: () -> Unit,
    onBrief: () -> Unit,
) {
    val vm: CaseViewModel = viewModel { CaseViewModel(caseId) }
    // Reload when coming back from other screens (new documents, a new search, intake edits).
    LaunchedEffect(Unit) { vm.load() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(vm.case?.title ?: "Case") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
            )
        },
    ) { padding ->
        val case = vm.case
        Column(Modifier.fillMaxSize().padding(padding)) {
            Disclaimer()
            when {
                vm.error != null && case == null -> ErrorText(vm.error!!)
                case == null -> Loading("Loading…")
                else -> Column(
                    Modifier.padding(16.dp).verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Button(onClick = onChat, modifier = Modifier.fillMaxWidth()) {
                        Icon(Icons.AutoMirrored.Filled.Chat, null)
                        Text("Chat about this case", Modifier.padding(start = 8.dp))
                    }
                    Text(
                        "The assistant knows this case: your summary, your documents and the similar judgments found. " +
                            "Your conversation is saved with the case.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                    val searched = case.status == "searched"
                    Action(Icons.Default.AttachFile, "My documents (${vm.documentCount})", onDocuments)
                    if (searched) Action(Icons.Default.Gavel, "Similar cases (${case.results.size})", onResults)
                    Action(Icons.Default.Edit, if (searched) "Update case details" else "Finish describing and find similar cases", onIntake)
                    Action(Icons.Default.Description, "Case-preparation brief", onBrief)

                    Text("Case summary", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Built from your documents and what you told us. Each item shows its source.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                    FactSheetCard(case.factSheet, vm.filenames)
                }
            }
        }
    }
}

@Composable
private fun Action(icon: ImageVector, label: String, onClick: () -> Unit) {
    OutlinedButton(onClick = onClick, modifier = Modifier.fillMaxWidth()) {
        Icon(icon, null)
        Text(label, Modifier.padding(start = 8.dp).weight(1f))
    }
}
