package com.vedalibrary.app.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import com.vedalibrary.app.ui.components.GbHtml
import com.vedalibrary.app.ui.theme.ReadSerif
import com.vedalibrary.app.ui.vm.SearchViewModel
import kotlinx.coroutines.launch

/** Поиск по всем книгам со scope (везде/санскрит/стих/комментарий), подсветкой совпадений и историей.
 *  Тап по выдаче открывает стих ровно на месте совпадения (запрос едет в ?hl=). */
@Composable
fun SearchScreen(vm: SearchViewModel, onVerse: (String, String) -> Unit) {
    val q by vm.query.collectAsState()
    val scope by vm.scope.collectAsState()
    val langF by vm.langFilter.collectAsState()
    val volScope = rememberCoroutineScope()
    val volOwner = remember { Any() }
    DisposableEffect(Unit) {
        com.vedalibrary.app.ui.util.VolumeFont.set(volOwner) { d -> volScope.launch { vm.settings.bumpListFont(d) } }
        onDispose { com.vedalibrary.app.ui.util.VolumeFont.clear(volOwner) }
    }
    val res by vm.results.collectAsState(emptyList())
    val history by vm.history.collectAsState(emptyList())
    val shown = remember(res, langF) {
        if (langF == "all") res else res.filter { it.item.row.bookLang == langF }
    }
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        OutlinedTextField(q, { vm.query.value = it; vm.search() }, label = { Text("Поиск по всем книгам") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        Row(Modifier.padding(vertical = 8.dp)) {
            listOf("all" to "Везде", "sanskrit" to "Санскрит", "verse" to "Стих", "purport" to "Коммент.").forEach { (v, l) ->
                FilterChip(v == scope, { vm.scope.value = v; vm.search() }, { Text(l, maxLines = 1) })
                Spacer(Modifier.width(6.dp))
            }
        }
        Row(Modifier.padding(bottom = 8.dp)) {
            listOf("all" to "Все языки", "rus" to "RU", "eng" to "EN").forEach { (v, l) ->
                FilterChip(v == langF, { vm.langFilter.value = v }, { Text(l, maxLines = 1) })
                Spacer(Modifier.width(6.dp))
            }
        }
        if (q.isBlank() && history.isNotEmpty()) {
            Row(Modifier.fillMaxWidth().padding(bottom = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("История", style = MaterialTheme.typography.titleSmall)
                TextButton(onClick = { vm.clearHistory() }) { Text("Очистить") }
            }
        }
        LazyColumn(Modifier.weight(1f)) {
            if (q.isBlank()) {
                items(history, key = { "h-$it" }) { h ->
                    ListItem(headlineContent = { Text(h, maxLines = 1, overflow = TextOverflow.Ellipsis) }, modifier = Modifier.clickable { vm.query.value = h; vm.search() })
                    HorizontalDivider()
                }
            } else {
                items(shown, key = { it.item.row.id }) { h ->
                    val snip = remember(h.item.row.id, q) {
                        val t = GbHtml.plain(h.item.row.translation ?: h.item.row.text).take(220)
                        highlightMatch(t, q)
                    }
                    ListItem(
                        headlineContent = { Text("${h.item.row.bookTitle ?: "?"} · ${h.item.ref}", maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        supportingContent = { Text(snip, maxLines = 3, overflow = TextOverflow.Ellipsis, fontFamily = ReadSerif) },
                        modifier = Modifier.clickable { onVerse(h.item.row.id, q) }
                    )
                    HorizontalDivider()
                }
            }
        }
    }
}

/** Совпадения — зелёным, как в оригинале (диакритика не важна: praptam найдёт prāptam) */
private fun highlightMatch(text: String, q: String) = buildAnnotatedString {
    append(text)
    if (q.length >= 2) {
        for (r in GbHtml.highlightRanges(text, q)) {
            addStyle(
                SpanStyle(background = Color(0xFF2E7D32), color = Color.White),
                r.first, r.last + 1
            )
        }
    }
}
