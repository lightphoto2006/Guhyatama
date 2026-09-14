@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class, androidx.compose.foundation.ExperimentalFoundationApi::class)

package com.vedalibrary.app.ui.screens

import android.content.ClipData
import android.content.ClipboardManager
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.vedalibrary.app.ui.components.GbHtml
import com.vedalibrary.app.ui.theme.ReadSerif
import com.vedalibrary.app.ui.util.VolumeFont
import com.vedalibrary.app.ui.vm.ChapterViewModel
import kotlinx.coroutines.launch

/** Глава -> список стихов. Тап -> детали, долгое нажатие -> копировать с номером / в карточки. */
@Composable
fun ChapterScreen(
    onVerse: (String) -> Unit,
    onSettings: () -> Unit, onIllustrations: (String) -> Unit,
    vm: ChapterViewModel = hiltViewModel()
) {
    val chapter by vm.chapter.collectAsState(null)
    val book by vm.book.collectAsState(null)
    val verses by vm.verses.collectAsState(emptyList())
    val illus by vm.illustrations.collectAsState(emptyList())
    val bm by vm.bookmark.collectAsState(null)
    val ctx = LocalContext.current
    val clipScope = rememberCoroutineScope()
    val fontL by vm.settings.fontList.collectAsState(15f)
    val align by vm.settings.paraAlign.collectAsState("justify")
    val listAlign = when (align) {
        "center" -> TextAlign.Center
        "justify" -> TextAlign.Justify
        else -> TextAlign.Start
    }
    // Кнопки громкости — размер шрифта списка (только пока открыт этот экран)
    val volOwner = remember { Any() }
    DisposableEffect(Unit) {
        VolumeFont.set(volOwner) { d -> clipScope.launch { vm.settings.bumpListFont(d) } }
        onDispose { VolumeFont.clear(volOwner) }
    }
    // Восстановление позиции скролла: закладка при входе, последнее место при возврате
    val listState = androidx.compose.foundation.lazy.rememberLazyListState()
    LaunchedEffect(vm.chapterId) {
        val i = if (vm.startIndex != 0 || vm.startOffset != 0) vm.startIndex to vm.startOffset
        else vm.lastIndex to vm.lastOffset
        if (i.first != 0 || i.second != 0) {
            try { listState.scrollToItem(i.first, i.second) } catch (_: Exception) { }
        }
    }
    // Уход с экрана (на стих и т.п.) — запоминаем место для кнопки «назад»
    DisposableEffect(vm.chapterId) {
        onDispose {
            try { vm.savePos(listState.firstVisibleItemIndex, listState.firstVisibleItemScrollOffset) }
            catch (_: Exception) { }
        }
    }
    Scaffold(topBar = {
        Column(
            Modifier.fillMaxWidth()
                .windowInsetsPadding(WindowInsets.statusBars)
                .padding(top = 2.dp, bottom = 2.dp),
            horizontalAlignment = androidx.compose.ui.Alignment.CenterHorizontally
        ) {
            Text(
                chapter?.title ?: "Глава",
                maxLines = 2, overflow = TextOverflow.Ellipsis,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                style = MaterialTheme.typography.titleMedium
            )
            Row(
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = androidx.compose.ui.Alignment.CenterVertically
            ) {
                TextButton(onClick = {
                    vm.saveChapterBookmark(listState.firstVisibleItemIndex, listState.firstVisibleItemScrollOffset)
                }) {
                    val b = bm
                    Text(
                        if (b != null && b.chapterId == vm.chapterId && b.verseId == null) "★" else "☆",
                        style = MaterialTheme.typography.titleLarge
                    )
                }
                IconButton(onClick = onSettings) { Text("⚙️", style = MaterialTheme.typography.titleLarge) }
            }
        }
    }) { pad ->
        LazyColumn(Modifier.padding(pad), state = listState) {
            if (illus.isNotEmpty() && book != null) {
                val eng = book?.language == "eng"
                item(key = "illus") {
                    ListItem(
                        headlineContent = { Text(if (eng) "Illustrations (${illus.size})" else "Иллюстрации (${illus.size})") },
                        supportingContent = { Text(if (eng) "Open chapter pictures" else "Открыть картинки главы") },
                        modifier = Modifier.clickable { onIllustrations(book!!.id) }
                    )
                    HorizontalDivider()
                }
            }
            verseItems(
                verses = verses,
                fontSizeSp = fontL,
                textAlign = listAlign,
                onVerse = onVerse,
                onCopy = { id ->
                    clipScope.launch {
                        vm.copyVerse(id) { text ->
                            val cm = ctx.getSystemService(ClipboardManager::class.java)
                            cm.setPrimaryClip(ClipData.newPlainText("verse", text))
                        }
                    }
                },
                onCards = { vm.toCards(it) }
            )
        }
    }
}

/** Общий список стихов главы: полный текст, тап — детали, долгое нажатие — копировать/в избранное.
 *  Состояние меню — на уровне ряда: открытие не рекомпозирует весь список. */
fun androidx.compose.foundation.lazy.LazyListScope.verseItems(
    verses: List<com.vedalibrary.app.ui.vm.VerseItem>,
    fontSizeSp: Float = 0f,
    textAlign: TextAlign = TextAlign.Start,
    onVerse: (String) -> Unit,
    onCopy: (String) -> Unit,
    onCards: (String) -> Unit
) {
    items(verses, key = { it.row.id }) { item ->
        // Полный текст стиха: главу можно читать целиком, не открывая каждый стих
        val full = remember(item.row.id) { GbHtml.plain(item.row.translation ?: item.row.text) }
        var showMenu by remember(item.row.id) { mutableStateOf(false) }
        // Box-якорь: иначе DropdownMenu в LazyColumn всплывает вверху экрана
        androidx.compose.foundation.layout.Box {
                    ListItem(
                        headlineContent = {
                            Text(
                                item.ref,
                                fontWeight = androidx.compose.ui.text.font.FontWeight.Bold
                            )
                        },
                        supportingContent = {
                            Text(
                                full,
                                fontFamily = ReadSerif,
                                textAlign = textAlign,
                                fontSize = if (fontSizeSp > 0) fontSizeSp.sp else androidx.compose.material3.LocalTextStyle.current.fontSize
                            )
                        },
                modifier = Modifier.combinedClickable(
                    onClick = { onVerse(item.row.id) },
                    onLongClick = { showMenu = true }
                )
            )
            if (showMenu) {
                DropdownMenu(expanded = true, onDismissRequest = { showMenu = false }) {
                    DropdownMenuItem(
                        text = { Text("Скопировать") },
                        onClick = { showMenu = false; onCopy(item.row.id) }
                    )
                    DropdownMenuItem(
                        text = { Text("В избранное") },
                        onClick = { showMenu = false; onCards(item.row.id) }
                    )
                }
            }
        }
        HorizontalDivider()
    }
}
