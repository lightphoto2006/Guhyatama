@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.vedalibrary.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import coil.compose.AsyncImage
import com.vedalibrary.app.ui.components.GbHtml
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import com.vedalibrary.app.data.local.AppDatabase
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.stateIn

@HiltViewModel
class IllustrationsViewModel @Inject constructor(private val db: AppDatabase, saved: SavedStateHandle) : ViewModel() {
    private val bookId: String = saved.get<String>("bookId") ?: ""
    val title = flow { emit(try { db.library().book(bookId)?.title } catch (_: Exception) { null }) }
        .stateIn(viewModelScope, SharingStarted.Lazily, null)
    val items = flow { emit(try { db.library().illustrations(bookId) } catch (_: Exception) { emptyList() }) }
        .stateIn(viewModelScope, SharingStarted.Lazily, emptyList())
}

/** Все иллюстрации книги: тап по картинке — полный экран, кнопка — переход к месту в тексте */
@Composable
fun IllustrationsScreen(onVerse: (String) -> Unit, vm: IllustrationsViewModel = hiltViewModel()) {
    val title by vm.title.collectAsState(null)
    val items by vm.items.collectAsState(emptyList())
    var fullPath by remember { mutableStateOf<String?>(null) }
    Scaffold(topBar = {
        TopAppBar(
            title = { Text("Иллюстрации", maxLines = 1) }
        )
    }) { pad ->
        LazyColumn(Modifier.padding(pad).padding(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (!title.isNullOrBlank()) item { Text(title!!, style = MaterialTheme.typography.titleMedium) }
            items(items, key = { it.id }) { ill ->
                Card(Modifier.fillMaxWidth()) {
                    Column {
                        // Превью уменьшенное; полный экран — по тапу
                        AsyncImage(
                            model = java.io.File(ill.imagePath),
                            contentDescription = ill.caption,
                            contentScale = androidx.compose.ui.layout.ContentScale.Crop,
                            modifier = Modifier.fillMaxWidth().height(140.dp)
                                .clickable { fullPath = ill.imagePath }
                        )
                        if (!ill.caption.isNullOrBlank()) Text(ill.caption!!, Modifier.padding(8.dp), style = MaterialTheme.typography.bodySmall)
                        if (ill.verseId != null) {
                            TextButton(onClick = { onVerse(ill.verseId!!) }) { Text("→ Читать место") }
                        }
                    }
                }
            }
        }
    }
    // Полный экран: тап или «назад» — закрыть
    val fp = fullPath
    if (fp != null) {
        androidx.compose.ui.window.Dialog(
            onDismissRequest = { fullPath = null },
            properties = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false)
        ) {
            Box(
                Modifier.fillMaxSize().background(androidx.compose.ui.graphics.Color.Black)
                    .clickable { fullPath = null },
                contentAlignment = androidx.compose.ui.Alignment.Center
            ) {
                AsyncImage(
                    model = java.io.File(fp),
                    contentDescription = null,
                    contentScale = androidx.compose.ui.layout.ContentScale.Fit,
                    modifier = Modifier.fillMaxSize()
                )
            }
        }
    }
}
