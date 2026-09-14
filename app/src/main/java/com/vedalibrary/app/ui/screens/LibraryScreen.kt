@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class, androidx.compose.foundation.ExperimentalFoundationApi::class)

package com.vedalibrary.app.ui.screens
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import com.vedalibrary.app.ui.util.VolumeFont
import kotlinx.coroutines.launch
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import kotlin.math.roundToInt
import androidx.hilt.navigation.compose.hiltViewModel
import coil.compose.AsyncImage
import com.vedalibrary.app.data.local.Book
import com.vedalibrary.app.ui.vm.FavoritesViewModel
import com.vedalibrary.app.ui.vm.LibraryViewModel
import com.vedalibrary.app.ui.vm.NotesViewModel

/** Библиотека — сетка 2 колонки. Долгое нажатие — удалить. Звезда — переход к закладке. */
@Composable
fun LibraryScreen(
    onOpen: (String) -> Unit, onSettings: () -> Unit,
    onOpenBookmark: (com.vedalibrary.app.data.local.Bookmark) -> Unit = {},
    vm: LibraryViewModel = hiltViewModel()
) {
    val bySection by vm.bySection.collectAsState(emptyMap())
    val collapsed by vm.settings.collapsedSections.collectAsState(setOf(2, 3, 4))
    val lang by vm.settings.bookLang.collectAsState("all")
    val bookmarked by vm.bookmarkedBooks.collectAsState(emptyList())
    var menuFor by remember { mutableStateOf<String?>(null) }
    // Перетаскивание плиток: долгое нажатие + ведение; отпуск без движения = меню
    var draggingId by remember { mutableStateOf<String?>(null) }
    var dragOff by remember { mutableStateOf(Offset.Zero) }
    var cellPx by remember { mutableStateOf(IntSize.Zero) }
    val haptic = LocalHapticFeedback.current
    // Кнопки громкости — шрифт списков (только пока открыт этот экран)
    val volScope = rememberCoroutineScope()
    val volOwner = remember { Any() }
    DisposableEffect(Unit) {
        VolumeFont.set(volOwner) { d -> volScope.launch { vm.settings.bumpListFont(d) } }
        onDispose { VolumeFont.clear(volOwner) }
    }
    // Разовый backfill PUA->IAST для старых импортов (фон, один раз)
    LaunchedEffect(Unit) { vm.backfillPuaIfNeeded() }
    val titles = vm.settings.sectionTitles
    Scaffold(
        topBar = {
            // Одна строка: язык слева, название по центру, шестерёнка справа — всё прижато к краям
            Row(
                Modifier.fillMaxWidth()
                    .windowInsetsPadding(WindowInsets.statusBars)
                    .padding(horizontal = 4.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                TextButton(onClick = { vm.cycleLang() }) {
                    Text(when (lang) { "rus" -> "RU"; "eng" -> "EN"; else -> "Все" })
                }
                Text(
                    "Гухьятама",
                    style = MaterialTheme.typography.titleLarge,
                    modifier = Modifier.weight(1f),
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center
                )
                IconButton(onClick = onSettings) { Text("⚙️", style = MaterialTheme.typography.titleLarge) }
            }
        }
    ) { pad ->
        LazyVerticalGrid(
            columns = GridCells.Fixed(2),
            modifier = Modifier.padding(pad).fillMaxSize(),
            contentPadding = PaddingValues(12.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            userScrollEnabled = draggingId == null
        ) {
            titles.indices.forEach { i ->
                val list = (bySection[i] ?: emptyList())
                    .filter { lang == "all" || it.language == lang }
                if (list.isNotEmpty()) {
                    item(span = { GridItemSpan(maxLineSpan) }, key = "h-$i-$lang") {
                        Row(
                            Modifier.fillMaxWidth().clickable { vm.toggleSection(i) }
                                .padding(vertical = 6.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(titles[i], style = MaterialTheme.typography.titleMedium,
                                modifier = Modifier.weight(1f))
                            Text(if (i in collapsed) "▸ ${list.size}" else "▾",
                                style = MaterialTheme.typography.titleMedium)
                        }
                    }
                }
                if (i !in collapsed) {
                    items(list.size, key = { list[it].id }) { idx ->
                        val b = list[idx]
                // Box-якорь для меню + перетаскивания.
                // Меню — системный лонг-пресс (надёжно); жест только двигает и гасит меню.
                Box(
                    Modifier
                        .combinedClickable(
                            onClick = { if (b.isReady) onOpen(b.id) },
                            onLongClick = { menuFor = b.id }
                        )
                        .offset {
                            if (draggingId == b.id) IntOffset(dragOff.x.roundToInt(), dragOff.y.roundToInt())
                            else IntOffset.Zero
                        }
                        .zIndex(if (draggingId == b.id) 1f else 0f)
                        .onSizeChanged { if (b.id == draggingId || cellPx == IntSize.Zero) cellPx = it }
                        .pointerInput(b.id) {
                            var acc = Offset.Zero
                            detectDragGesturesAfterLongPress(
                                onDragStart = {
                                    menuFor = null
                                    haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                                    draggingId = b.id
                                    dragOff = Offset.Zero
                                    acc = Offset.Zero
                                },
                                onDrag = { change, amount ->
                                    change.consume()
                                    menuFor = null
                                    dragOff += amount
                                    acc += amount
                                    val w = cellPx.width
                                    val h = cellPx.height
                                    if (w > 0 && h > 0) {
                                        // ±1 — сосед по строке, ±2 — строка выше/ниже (2 колонки).
                                        // Индексы считает VM по свежим данным — жест можно вести далеко.
                                        var di = 0
                                        if (acc.x >= w) { di = 1; acc = acc.copy(x = acc.x - w) }
                                        else if (acc.x <= -w) { di = -1; acc = acc.copy(x = acc.x + w) }
                                        else if (acc.y >= h) { di = 2; acc = acc.copy(y = acc.y - h) }
                                        else if (acc.y <= -h) { di = -2; acc = acc.copy(y = acc.y + h) }
                                        if (di != 0) vm.nudge(b.id, di)
                                    }
                                },
                                onDragEnd = {
                                    draggingId = null
                                    dragOff = Offset.Zero
                                },
                                onDragCancel = {
                                    draggingId = null
                                    dragOff = Offset.Zero
                                }
                            )
                        }
                ) {
                    BookCard(
                        book = b,
                        vm = vm,
                        bookmarked = bookmarked.contains(b.id),
                        onBookmark = { vm.openBookmark(b.id, onOpenBookmark) }
                    )
                    if (menuFor == b.id) {
                        DropdownMenu(expanded = true, onDismissRequest = { menuFor = null }) {
                            DropdownMenuItem(
                                text = { Text("Открыть") },
                                onClick = { menuFor = null; if (b.isReady) onOpen(b.id) }
                            )
                            DropdownMenuItem(
                                text = { Text("В начало раздела") },
                                onClick = { menuFor = null; vm.moveEdge(b.id, true) }
                            )
                            DropdownMenuItem(
                                text = { Text("В конец раздела") },
                                onClick = { menuFor = null; vm.moveEdge(b.id, false) }
                            )
                            // Точное позиционирование без перетаскивания: соседи по экрану
                            if (idx > 0) DropdownMenuItem(
                                text = { Text("▲ Выше") },
                                onClick = { menuFor = null; vm.swapBooks(b.id, list[idx - 1].id) }
                            )
                            if (idx < list.size - 1) DropdownMenuItem(
                                text = { Text("▼ Ниже") },
                                onClick = { menuFor = null; vm.swapBooks(b.id, list[idx + 1].id) }
                            )
                        }
                    }
                }
            } // конец items
            } // конец if (i !in collapsed)
            } // конец forEach по секциям
        }
    }
}

/** Карточка книги: миниатюра (первая иллюстрация) + название. Сюда позже встанет обложка (Book.coverPath). */@Composable
private fun BookCard(
    book: Book, vm: LibraryViewModel, bookmarked: Boolean, onBookmark: () -> Unit
) {
    val coverPath by produceState<String?>(null, book.id, book.coverPath) {
        // Обложка из тулзы — в первую очередь, иначе первая иллюстрация книги
        value = book.coverPath?.takeIf { java.io.File(it).exists() } ?: vm.coverPath(book.id)
    }
    Box(Modifier.fillMaxWidth()) {
        Card(
            modifier = Modifier.fillMaxWidth()
        ) {
        Column {
            val cover = coverPath
            if (cover != null) {
                AsyncImage(
                    model = coil.request.ImageRequest.Builder(LocalContext.current)
                        .data(java.io.File(cover))
                        .size(512)
                        .crossfade(true)
                        .build(),
                    contentDescription = book.title,
                    modifier = Modifier.fillMaxWidth().aspectRatio(1f),
                    contentScale = ContentScale.Crop
                )
            } else {
                // Плейсхолдер под будущую обложку: первая буква названия
                Box(
                    Modifier.fillMaxWidth().aspectRatio(1f)
                        .background(MaterialTheme.colorScheme.primaryContainer),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        book.title.take(1).uppercase(),
                        style = MaterialTheme.typography.displayMedium,
                        color = MaterialTheme.colorScheme.onPrimaryContainer
                    )
                }
            }
            Column(Modifier.padding(10.dp)) {
                Text(
                    com.vedalibrary.app.ui.components.VerseShare.cleanTitle(book.title),
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    minLines = 2
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    if (!book.isReady) (if (book.language == "eng") "⏳ Importing…" else "⏳ Импорт идёт…")
                    else "${book.author ?: if (book.language == "eng") "Import" else "Импорт"} • ~${book.totalReadingMinutes} ${if (book.language == "eng") "min" else "мин"}",
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
        } // конец Card
        // Звезда закладки — поверх карточки справа вверху
        if (bookmarked) {
            Text(
                "★",
                color = androidx.compose.ui.graphics.Color(0xFFFFB300),
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.align(Alignment.TopEnd).clickable { onBookmark() }.padding(8.dp)
            )
        }
    }
}

@Composable
fun NotesScreen(onVerse: (String) -> Unit = {}, vm: NotesViewModel = hiltViewModel()) {    val items by vm.items.collectAsState(emptyList())
    val volScope = rememberCoroutineScope()
    val volOwner = remember { Any() }
    DisposableEffect(Unit) {
        VolumeFont.set(volOwner) { d -> volScope.launch { vm.settings.bumpListFont(d) } }
        onDispose { VolumeFont.clear(volOwner) }
    }
    val fmt = remember { java.text.SimpleDateFormat("dd.MM.yyyy HH:mm", java.util.Locale.getDefault()) }
    Scaffold(topBar = { TopAppBar(title = { Text("Заметки") }) }) { pad ->
        if (items.isEmpty()) {
            Box(Modifier.padding(pad).fillMaxSize().padding(16.dp)) {
                Text("Пока пусто. Выделите фрагмент текста в стихе и выберите «В заметку».")
            }
        } else {
            LazyColumn(Modifier.padding(pad)) {
                items(items, key = { it.note.id }) { it ->
                    val canOpen = it.note.verseId != null && !it.verseGone
                    ListItem(
                        headlineContent = { Text(it.verseLabel ?: if (it.verseGone) "(стих недоступен)" else "Заметка") },
                        supportingContent = {
                            Text(
                                it.note.text + "\n" + fmt.format(java.util.Date(it.note.createdAt)),
                                maxLines = 4
                            )
                        },
                        trailingContent = {
                            TextButton(onClick = { vm.delete(it.note.id) }) { Text("×") }
                        },
                        modifier = Modifier.clickable(
                            enabled = canOpen,
                            onClick = { it.note.verseId?.let(onVerse) }
                        )
                    )
                    HorizontalDivider()
                }
            }
        }
    }
}

@Composable
fun FavoritesScreen(onVerse: (String) -> Unit = {}, vm: FavoritesViewModel = hiltViewModel()) {
    val items by vm.items.collectAsState(emptyList())
    val volScope = rememberCoroutineScope()
    val volOwner = remember { Any() }
    DisposableEffect(Unit) {
        VolumeFont.set(volOwner) { d -> volScope.launch { vm.settings.bumpListFont(d) } }
        onDispose { VolumeFont.clear(volOwner) }
    }
    Scaffold(topBar = { TopAppBar(title = { Text("Избранное") }) }) { pad ->
        if (items.isEmpty()) {
            Box(Modifier.padding(pad).fillMaxSize().padding(16.dp)) {
                Text("Пока пусто. Долгое нажатие на стих в главе → «В избранное».")
            }
        } else {
            LazyColumn(Modifier.padding(pad)) {
                items(items, key = { it.card.id }) { it ->
                    ListItem(
                        headlineContent = { Text(it.verseLabel ?: it.card.front) },
                        supportingContent = { Text(it.card.back.take(300), maxLines = 3) },
                        trailingContent = {
                            TextButton(onClick = { vm.delete(it.card.id) }) { Text("×") }
                        },
                        modifier = Modifier.clickable(
                            enabled = it.verseLabel != null,
                            onClick = { onVerse(it.card.verseId) }
                        )
                    )
                    HorizontalDivider()
                }
            }
        }
    }
}
