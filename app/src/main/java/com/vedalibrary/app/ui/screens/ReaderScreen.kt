@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class, androidx.compose.foundation.ExperimentalFoundationApi::class)

package com.vedalibrary.app.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.vedalibrary.app.ui.util.VolumeFont
import com.vedalibrary.app.ui.vm.ReaderViewModel
import kotlinx.coroutines.launch

/**
 * Книга: сетка разделов 2 колонки.
 * Одноуровневая (БГ) — сразу главы; многоуровневая (ШБ) — песни, тап открывает её главы.
 * Тап по главе -> экран стихов. Долгое нажатие на книгу в библиотеке — удалить.
 */
@Composable
fun ReaderScreen(
    onVerse: (String) -> Unit, onChapter: (String) -> Unit,
    onSettings: () -> Unit, onIllustrations: (String) -> Unit, vm: ReaderViewModel
) {
    val book by vm.book.collectAsState(null)
    val chapters by vm.chapters.collectAsState(emptyList())
    val groups by vm.songGroups.collectAsState(emptyList())
    val illus by vm.illustrations.collectAsState(emptyList())
    val flatChapter by vm.flatChapter.collectAsState(null)
    val flatVerses by vm.flatVerses.collectAsState(emptyList())
    val fontL by vm.settings.fontList.collectAsState(15f)
    val align by vm.settings.paraAlign.collectAsState("justify")
    val listAlign = when (align) {
        "center" -> androidx.compose.ui.text.style.TextAlign.Center
        "justify" -> androidx.compose.ui.text.style.TextAlign.Justify
        else -> androidx.compose.ui.text.style.TextAlign.Start
    }
    var openSong by remember { mutableStateOf<String?>(null) }
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val clipScope = rememberCoroutineScope()
    val shownChapters = remember(chapters, groups, openSong) {
        if (groups.isEmpty()) chapters
        else groups.firstOrNull { it.song == openSong }?.chapters ?: emptyList()
    }
    val songTitle = remember(groups, openSong) {
        if (openSong == null) null else groups.firstOrNull { it.song == openSong }?.title
    }
    val counts by vm.verseCounts.collectAsState(emptyMap())
    // Кнопки громкости — шрифт списков (только пока открыт этот экран)
    val volOwner = remember { Any() }
    DisposableEffect(Unit) {
        VolumeFont.set(volOwner) { d -> clipScope.launch { vm.settings.bumpListFont(d) } }
        onDispose { VolumeFont.clear(volOwner) }
    }
    val eng = book?.language == "eng"
    Scaffold(topBar = {
        // Компактная шапка: название + кубик + шестерёнка, без пустого места
        Row(
            Modifier.fillMaxWidth()
                .windowInsetsPadding(WindowInsets.statusBars)
                .padding(horizontal = 12.dp, vertical = 4.dp),
            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically
        ) {
            val bookTitle = book?.title
                ?.let { com.vedalibrary.app.ui.components.VerseShare.cleanTitle(it) }
                ?.takeIf { it.isNotBlank() } ?: "Книга"
            Text(
                songTitle ?: bookTitle,
                maxLines = 2, minLines = 1, overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.weight(1f)
            )
            TextButton(onClick = { book?.let { vm.randomInBook(onVerse) } }) { Text("🎲") }
            IconButton(onClick = onSettings) { Text("⚙️", style = MaterialTheme.typography.titleLarge) }
        }
    }) { pad ->
        // Книга без глав (единственный фейковый раздел «Текст»): сразу список стихов
        if (flatChapter != null) {
            LazyColumn(Modifier.padding(pad)) {
                verseItems(
                    verses = flatVerses,
                    fontSizeSp = fontL,
                    textAlign = listAlign,
                    onVerse = onVerse,
                    onCopy = { id ->
                        clipScope.launch {
                            vm.copyVerse(id) { text ->
                                val cm = ctx.getSystemService(android.content.ClipboardManager::class.java)
                                cm.setPrimaryClip(android.content.ClipData.newPlainText("verse", text))
                            }
                        }
                    },
                    onCards = { vm.toCards(it) }
                )
            }
        } else {
        // Все плитки списка — одной высоты (по максимальной, иначе лесенка)
        var maxTileH by remember(shownChapters, groups, openSong) { mutableStateOf(0) }
        val tileMin = with(LocalDensity.current) { maxTileH.toDp() }
        fun tileMod(): Modifier = Modifier.heightIn(min = tileMin)
            .onSizeChanged { if (it.height > maxTileH) maxTileH = it.height }
        LazyVerticalGrid(
            columns = GridCells.Fixed(2),
            modifier = Modifier.padding(pad).fillMaxSize(),
            contentPadding = PaddingValues(12.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            if (illus.isNotEmpty() && book != null && openSong == null) {
                item(span = { GridItemSpan(maxLineSpan) }, key = "illus") {
                    Card(Modifier.fillMaxWidth()) {
                        ListItem(
                            headlineContent = { Text(if (eng) "Illustrations (${illus.size})" else "Иллюстрации (${illus.size})") },
                            supportingContent = { Text(if (eng) "Open all book pictures" else "Открыть все картинки книги") },
                            modifier = Modifier.clickable { onIllustrations(book!!.id) }
                        )
                    }
                }
            }
            // Песни/темы/годы (верхний уровень многоуровневых книг)
            if (groups.isNotEmpty() && openSong == null) {
                items(groups, key = { "song-${it.song}" }) { g ->
                    SectionCard(
                        title = g.title,
                        subtitle = if (g.showCount) (if (eng) "Chapters: ${g.chapters.size}" else "Глав: ${g.chapters.size}") else null,
                        onClick = { openSong = g.song },
                        modifier = tileMod()
                    )
                }
            } else {
                // Главы (для песен — с возвратом к списку песней)
                if (openSong != null) {
                    item(span = { GridItemSpan(maxLineSpan) }, key = "back-songs") {
                        val backTitle = book?.title
                            ?.let { com.vedalibrary.app.ui.components.VerseShare.cleanTitle(it) }
                            ?.takeIf { it.isNotBlank() } ?: "К разделам"
                        TextButton(onClick = { openSong = null }, modifier = Modifier.fillMaxWidth()) {
                            Text("← $backTitle")
                        }
                    }
                }
                items(shownChapters, key = { it.id }) { ch ->
                    SectionCard(
                        title = ch.title,
                        subtitle = if (eng) "Verses: ${counts[ch.id] ?: 0}" else "Стихов: ${counts[ch.id] ?: 0}",
                        onClick = { onChapter(ch.id) },
                        modifier = tileMod()
                    )
                }
            }
        }
        }
    }
}

/** Плитка раздела: только подпись */
@Composable
private fun SectionCard(title: String, subtitle: String?, onClick: () -> Unit, modifier: Modifier = Modifier) {
    Card(onClick = onClick, modifier = modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall, maxLines = 3, overflow = TextOverflow.Ellipsis)
            if (subtitle != null) {
                Spacer(Modifier.height(4.dp))
                Text(subtitle, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
