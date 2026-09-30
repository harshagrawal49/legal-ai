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
import kotlinx.coroutines.launch

class CaseListViewModel : ViewModel() {
    var cases by mutableStateOf<List<CaseSummary>>(emptyList())
        private set
    var error by mutableStateOf<String?>(null)
        private set

    fun load() = viewModelScope.launch {
        runCatching { Api.service.listCases() }
            .onSuccess { cases = it; error = null }
            .onFailure { error = "Could not load cases: ${it.message}" }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CaseListScreen(
    onNewCase: () -> Unit,
    onOpenCase: (CaseSummary) -> Unit,
    vm: CaseListViewModel = viewModel(),
) {
    LaunchedEffect(Unit) { vm.load() }

    Scaffold(
        topBar = { TopAppBar(title = { Text("My cases") }) },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = onNewCase,
                icon = { Icon(Icons.Default.Add, contentDescription = null) },
                text = { Text("New case") },
            )
        },
    ) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding)) {
            vm.error?.let { item { ErrorText(it) } }
            if (vm.cases.isEmpty() && vm.error == null) {
                item {
                    Text(
                        "Describe your situation in your own words and we'll find similar Indian court cases.",
                        modifier = Modifier.padding(24.dp),
                    )
                }
            }
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
