@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.vedalibrary.app.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.vedalibrary.app.ui.theme.ReadSerif
import com.vedalibrary.app.ui.vm.DictViewModel
import kotlinx.coroutines.launch

/** Экран слова: вхождения с переводами. Слово жирным, перевод курсивом; сначала
 *  строки пословника своих произведений, потом остальные и предложения из переводов. */
@Composable
fun DictScreen(onVerse: (String) -> Unit, vm: DictViewModel = hiltViewModel()) {
    val rows by vm.rows.collectAsState(emptyList())
    val showAll by vm.showAllLangs.collectAsState(false)
    val volScope = rememberCoroutineScope()
    val volOwner = remember { Any() }
    DisposableEffect(Unit) {
        com.vedalibrary.app.ui.util.VolumeFont.set(volOwner) { d -> volScope.launch { vm.settings.bumpListFont(d) } }
        onDispose { com.vedalibrary.app.ui.util.VolumeFont.clear(volOwner) }
    }
    Scaffold(topBar = {
        TopAppBar(
            title = { Text("«${vm.titleWord}» — ${rows.size}", maxLines = 1, overflow = TextOverflow.Ellipsis) }
        )
    }) { pad ->
        Column(Modifier.padding(pad)) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp)) {
                FilterChip(showAll, { vm.toggleShowAll() }, { Text(if (vm.lang == "rus") "Все языки" else "All languages") })
            }
            LazyColumn(Modifier.weight(1f)) {
            items(rows, key = { it.verseId }) { r ->
                val annotated = remember(r.verseId, r.head, r.tail) {
                    buildAnnotatedString {
                        if (r.head.isNotEmpty()) {
                            withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(r.head) }
                            append(" ")
                        }
                        withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { append(r.tail) }
                        append(" (${r.ref})")
                    }
                }
                ListItem(
                    headlineContent = {
                        Text(annotated, maxLines = 3, overflow = TextOverflow.Ellipsis, fontFamily = ReadSerif)
                    },
                    modifier = Modifier.clickable { onVerse(r.verseId) }
                )
                HorizontalDivider()
            }
            }
        }
    }
}
