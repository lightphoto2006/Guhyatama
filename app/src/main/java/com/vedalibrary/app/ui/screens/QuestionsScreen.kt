@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.vedalibrary.app.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.vedalibrary.app.ui.util.VolumeFont
import com.vedalibrary.app.ui.vm.QuestionsViewModel
import kotlinx.coroutines.launch

/** Вопросы по стихам: нумерованный список «N. БГ 2.11 — О чём вопрос». Тап — правка. */
@Composable
fun QuestionsScreen(
    onVerse: (String) -> Unit, onEdit: (Long) -> Unit,
    vm: QuestionsViewModel = hiltViewModel()
) {
    val items by vm.items.collectAsState(emptyList())
    val volScope = rememberCoroutineScope()
    val volOwner = remember { Any() }
    DisposableEffect(Unit) {
        VolumeFont.set(volOwner) { d -> volScope.launch { vm.settings.bumpListFont(d) } }
        onDispose { VolumeFont.clear(volOwner) }
    }
    Scaffold(topBar = { TopAppBar(title = { Text("Вопросы") }) }) { pad ->
        if (items.isEmpty()) {
            Box(Modifier.padding(pad).fillMaxSize().padding(16.dp)) {
                Text("Пока пусто. Выделите фрагмент в стихе и выберите «Вопрос».")
            }
        } else {
            LazyColumn(Modifier.padding(pad)) {
                itemsIndexed(items, key = { _, q -> q.id }) { i, q ->
                    ListItem(
                        headlineContent = {
                            Text("${i + 1}. ${q.verseLabel} — ${q.title}",
                                maxLines = 2, overflow = TextOverflow.Ellipsis)
                        },
                        trailingContent = {
                            Row {
                                TextButton(onClick = { onVerse(q.verseId) }) { Text("›") }
                                TextButton(onClick = { vm.delete(q.id) }) { Text("×") }
                            }
                        },
                        modifier = Modifier.clickable { onEdit(q.id) }
                    )
                    HorizontalDivider()
                }
            }
        }
    }
}

/** Редактор вопроса: «О чём вопрос» + выделенный кусок + текст вопроса. */
@Composable
fun QuestionEditScreen(
    qid: Long?,
    verseId: String, verseLabel: String, quote: String,
    onDone: () -> Unit, onVerse: (String) -> Unit,
    vm: QuestionsViewModel = hiltViewModel()
) {
    val scope = rememberCoroutineScope()
    val volScope = rememberCoroutineScope()
    val volOwner = remember { Any() }
    DisposableEffect(Unit) {
        VolumeFont.set(volOwner) { d -> volScope.launch { vm.settings.bumpListFont(d) } }
        onDispose { VolumeFont.clear(volOwner) }
    }
    var title by remember(qid) { mutableStateOf("") }
    var text by remember(qid) { mutableStateOf("") }
    var loadedQ by remember(qid) { mutableStateOf<com.vedalibrary.app.data.local.Question?>(null) }
    var ready by remember(qid) { mutableStateOf(qid == null) }
    LaunchedEffect(qid) {
        if (qid != null) {
            val q = vm.load(qid)
            if (q != null) {
                loadedQ = q
                title = q.title
                text = q.text
            }
            ready = true
        }
    }
    val cur = loadedQ
    val showVerseId = cur?.verseId ?: verseId
    val showLabel = cur?.verseLabel ?: verseLabel
    val showQuote = cur?.quote ?: quote
    Scaffold(topBar = {
        TopAppBar(
            title = { Text(if (qid == null) "Новый вопрос" else "Вопрос", maxLines = 1) },
            actions = {
                TextButton(onClick = { if (showVerseId.isNotBlank()) onVerse(showVerseId) }) {
                    Text(showLabel.ifBlank { "Стих" })
                }
            }
        )
    }) { pad ->
        if (!ready) {
            Box(Modifier.padding(pad).fillMaxSize()) { Text("Загрузка…", Modifier.padding(16.dp)) }
        } else Column(
            Modifier.padding(pad).padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            OutlinedTextField(
                title, { title = it }, label = { Text("О чём вопрос") },
                modifier = Modifier.fillMaxWidth(), singleLine = true
            )
            Text("Отрывок:", style = MaterialTheme.typography.labelLarge)
            Text(
                showQuote.ifBlank { "(нет)" },
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                text, { text = it }, label = { Text("Текст вопроса") },
                modifier = Modifier.fillMaxWidth().heightIn(min = 160.dp), minLines = 5
            )
            Button(
                onClick = {
                    scope.launch {
                        vm.save(title, showQuote, text, showVerseId, showLabel, qid)
                        onDone()
                    }
                },
                enabled = title.isNotBlank() && text.isNotBlank(),
                modifier = Modifier.fillMaxWidth()
            ) { Text("Сохранить") }
        }
    }
}
