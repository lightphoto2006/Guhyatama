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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import com.vedalibrary.app.ui.util.VolumeFont
import kotlinx.coroutines.launch
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.zIndex
import kotlin.math.roundToInt
import androidx.hilt.navigation.compose.hiltViewModel
import coil.compose.AsyncImage
import com.vedalibrary.app.data.local.Book
import com.vedalibrary.app.ui.vm.FavoritesViewModel
import com.vedalibrary.app.ui.vm.LibraryViewModel
import com.vedalibrary.app.ui.vm.NotesViewModel

/** Библиотека — три формата: плитки (2 колонки), книжная полка (торцы), список
 *  (1 колонка, строки ~48dp). Долгое нажатие — удалить. Звезда — переход к закладке. */
@Composable
fun LibraryScreen(
    onOpen: (String) -> Unit, onSettings: () -> Unit,
    onOpenBookmark: (com.vedalibrary.app.data.local.Bookmark) -> Unit = {},
    vm: LibraryViewModel = hiltViewModel()
) {
    val bySection by vm.bySection.collectAsState(emptyMap())
    val collapsed by vm.settings.collapsedSections.collectAsState(setOf(2, 3, 4))
    val lang by vm.settings.bookLang.collectAsState("all")
    val view by vm.settings.mainView.collectAsState("tiles")
    val shelf = view == "shelf"
    val listView = view == "list"
    // «Книжная полка»: торцы 5-6 в ряд (узкий не влезает — 5), ширина как у
    // ячейки сетки, высота торца = высота плитки (квадрат обложки + блок названия)
    val screenW = LocalConfiguration.current.screenWidthDp.dp
    val shelfCols = if ((screenW - 24.dp - 4.dp * 5) / 6 >= 46.dp) 6 else 5
    val spineW = (screenW - 24.dp - 4.dp * (shelfCols - 1)) / shelfCols
    val spineH = (screenW - 36.dp) / 2 + 52.dp
    val bookmarked by vm.bookmarkedBooks.collectAsState(emptyList())
    var menuFor by remember { mutableStateOf<String?>(null) }
    var confirmDelete by remember { mutableStateOf<String?>(null) }
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
            // Без windowInsetsPadding: система уже резервирует зону иконок (как в Telegram),
            // наш инсет давал двойную полосу. Строка начинается сразу под шторкой
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 4.dp),
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
            columns = GridCells.Fixed(if (listView) 1 else if (shelf) shelfCols else 2),
            modifier = Modifier.padding(pad).fillMaxSize(),
            contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 4.dp, bottom = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(if (listView) 0.dp else if (shelf) 4.dp else 12.dp),
            verticalArrangement = Arrangement.spacedBy(if (listView) 0.dp else 12.dp),
            userScrollEnabled = draggingId == null
        ) {
            titles.indices.forEach { i ->
                val list = (bySection[i] ?: emptyList())
                    .filter { lang == "all" || it.language == lang }
                if (list.isNotEmpty()) {
                    item(span = { GridItemSpan(maxLineSpan) }, key = "h-$i-$lang") {
                        Row(
                            Modifier.fillMaxWidth().clickable { vm.toggleSection(i) }
                                .padding(vertical = 2.dp),
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
                        .onSizeChanged { cellPx = it } // ячейка меняет размер при переключении формата
                        .pointerInput(b.id, view) {
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
                                        // ±колонок — строка выше/ниже: 1 в списке,
                                        // 2 в плитках, 5-6 на полке; ±1 — сосед по строке.
                                        // Индексы считает VM по свежим данным — жест можно вести далеко.
                                        val cols = if (listView) 1 else if (shelf) shelfCols else 2
                                        var di = 0
                                        if (acc.x >= w) { di = 1; acc = acc.copy(x = acc.x - w) }
                                        else if (acc.x <= -w) { di = -1; acc = acc.copy(x = acc.x + w) }
                                        else if (acc.y >= h) { di = cols; acc = acc.copy(y = acc.y - h) }
                                        else if (acc.y <= -h) { di = -cols; acc = acc.copy(y = acc.y + h) }
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
                    if (listView) {
                        // Список: строка + разделитель (ритм без вертикальных зазоров)
                        Column(Modifier.fillMaxWidth()) {
                            BookRow(
                                book = b,
                                vm = vm,
                                bookmarked = bookmarked.contains(b.id),
                                onBookmark = { vm.openBookmark(b.id, onOpenBookmark) }
                            )
                            HorizontalDivider()
                        }
                    } else if (shelf) {
                        BookSpine(
                            book = b,
                            spineW = spineW,
                            spineH = spineH,
                            bookmarked = bookmarked.contains(b.id),
                            onBookmark = { vm.openBookmark(b.id, onOpenBookmark) }
                        )
                    } else {
                        BookCard(
                            book = b,
                            vm = vm,
                            bookmarked = bookmarked.contains(b.id),
                            onBookmark = { vm.openBookmark(b.id, onOpenBookmark) }
                        )
                    }
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
                            DropdownMenuItem(
                                text = { Text("🗑 Удалить", color = MaterialTheme.colorScheme.error) },
                                onClick = { menuFor = null; confirmDelete = b.id }
                            )
                        }
                    }
                }
            } // конец items
            } // конец if (i !in collapsed)
            } // конец forEach по секциям
        }
    }
    // Подтверждение удаления книги из меню плитки
    val delId = confirmDelete
    if (delId != null) {
        AlertDialog(
            onDismissRequest = { confirmDelete = null },
            title = { Text("Удалить книгу?") },
            text = { Text("Книга будет удалена со всеми стихами и закладками. Действие необратимо.") },
            confirmButton = {
                TextButton(onClick = {
                    confirmDelete = null
                    vm.deleteBook(delId)
                }) { Text("Удалить", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = {
                TextButton(onClick = { confirmDelete = null }) { Text("Отмена") }
            }
        )
    }
}

/** Карточка книги: миниатюра (первая иллюстрация) + название. Сюда позже встанет обложка (Book.coverPath). */@Composable
private fun BookCard(
    book: Book, vm: LibraryViewModel, bookmarked: Boolean, onBookmark: () -> Unit
) {
    // Обложка из тулзы — в первую очередь, иначе первая иллюстрация книги.
    // remember+LaunchedEffect вместо produceState: тот же эффект (пересчёт при смене
    // ключей), но без ложной ошибки lint ProduceStateDoesNotAssignValue (K2).
    // stat() и запрос — на IO (композиция живёт на главном потоке)
    var coverPath by remember(book.id, book.coverPath) { mutableStateOf<String?>(null) }
    LaunchedEffect(book.id, book.coverPath) {
        coverPath = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            book.coverPath?.takeIf { java.io.File(it).exists() } ?: vm.coverPath(book.id)
        }
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
                    minLines = 2,
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                    modifier = Modifier.fillMaxWidth()
                )
                // Подписей нет (ни автора, ни минут) — только статус незавершённого импорта
                if (!book.isReady) {
                    Spacer(Modifier.height(2.dp))
                    Text(
                        if (book.language == "eng") "⏳ Importing…" else "⏳ Импорт идёт…",
                        style = MaterialTheme.typography.bodySmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }
        }
        } // конец Card
        // Звезда закладки — поверх карточки справа вверху
        if (bookmarked) {
            Text(
                "★",
                color = androidx.compose.ui.graphics.Color(0xFFFFB300),
                style = MaterialTheme.typography.titleLarge,
                fontSize = 33.sp,
                modifier = Modifier.align(Alignment.TopEnd).clickable { onBookmark() }.padding(8.dp)
            )
        }
    }
}

/** Мини-обложка для строки списка: та же загрузка coverPath, что у плитки */
@Composable
private fun MiniCover(book: Book, vm: LibraryViewModel, size: Dp) {
    var coverPath by remember(book.id, book.coverPath) { mutableStateOf<String?>(null) }
    LaunchedEffect(book.id, book.coverPath) {
        coverPath = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            book.coverPath?.takeIf { java.io.File(it).exists() } ?: vm.coverPath(book.id)
        }
    }
    val cover = coverPath
    if (cover != null) {
        AsyncImage(
            model = coil.request.ImageRequest.Builder(LocalContext.current)
                .data(java.io.File(cover))
                .size(512)
                .crossfade(true)
                .build(),
            contentDescription = book.title,
            modifier = Modifier.size(size).clip(RoundedCornerShape(4.dp)),
            contentScale = ContentScale.Crop
        )
    } else {
        Box(
            Modifier.size(size).background(MaterialTheme.colorScheme.primaryContainer, RoundedCornerShape(4.dp)),
            contentAlignment = Alignment.Center
        ) {
            Text(
                book.title.take(1).uppercase(),
                color = MaterialTheme.colorScheme.onPrimaryContainer,
                fontSize = 18.sp
            )
        }
    }
}

/** Строка списка: мини-обложка 40dp + заголовок одной строкой, ★/⏳ справа.
 *  Высота ~48dp — на экран помещается в 3-4 раза больше книг, чем в плитках. */
@Composable
private fun BookRow(
    book: Book, vm: LibraryViewModel, bookmarked: Boolean, onBookmark: () -> Unit
) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        MiniCover(book, vm, size = 40.dp)
        Spacer(Modifier.width(10.dp))
        Text(
            com.vedalibrary.app.ui.components.VerseShare.cleanTitle(book.title),
            style = MaterialTheme.typography.titleMedium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f)
        )
        if (bookmarked) {
            Text(
                "★",
                color = androidx.compose.ui.graphics.Color(0xFFFFB300),
                fontSize = 24.sp,
                modifier = Modifier.padding(start = 8.dp).clickable { onBookmark() }
            )
        }
        if (!book.isReady) {
            Text(
                "⏳",
                fontSize = 14.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(start = 8.dp)
            )
        }
    }
}

/** Сплошные «книжные» оттенки торцов: цвет по хешу id книги — стабилен между запусками */
private val spineColors = listOf(
    androidx.compose.ui.graphics.Color(0xFF7B3F2E), androidx.compose.ui.graphics.Color(0xFF3E5C76),
    androidx.compose.ui.graphics.Color(0xFF4A6B4F), androidx.compose.ui.graphics.Color(0xFF6B4E71),
    androidx.compose.ui.graphics.Color(0xFF8A6D3B), androidx.compose.ui.graphics.Color(0xFF2F5D62),
    androidx.compose.ui.graphics.Color(0xFF7A4A4A), androidx.compose.ui.graphics.Color(0xFF4F5D2F)
)

/** Торец книги для режима «Книжная полка»: сплошной цвет, название двумя
 *  строками вдоль торца, звезда закладки и статус незавершённого импорта. */
@Composable
private fun BookSpine(book: Book, spineW: Dp, spineH: Dp, bookmarked: Boolean, onBookmark: () -> Unit) {
    val title = remember(book.title) { com.vedalibrary.app.ui.components.VerseShare.cleanTitle(book.title) }
    val color = remember(book.id) {
        spineColors[(book.id.hashCode() % spineColors.size + spineColors.size) % spineColors.size]
    }
    // Кегль под ширину торца: две строки обязаны поместиться в высоту текста
    val fs = ((spineW.value - 6f) / 2.6f).coerceIn(9f, 15f)
    // Звезде — отдельная зона сверху: заголовок короче и смещён ниже,
    // чтобы ★ не наезжала на текст
    val starZone = if (bookmarked) 54.dp else 0.dp
    Box(Modifier.fillMaxWidth().height(spineH)) {
        Box(
            Modifier.fillMaxSize()
                .alpha(if (book.isReady) 1f else 0.55f)
                .background(color, RoundedCornerShape(3.dp))
                .drawBehind {
                    // Доска полки: тёмная линия под торцом заходит в зазоры —
                    // по всему ряду идёт сплошной чертой
                    val plank = 6.dp.toPx()
                    drawRect(
                        androidx.compose.ui.graphics.Color(0xFF5A4636),
                        topLeft = Offset(-2.dp.toPx(), size.height - plank),
                        size = Size(size.width + 4.dp.toPx(), plank)
                    )
                }
        ) {
            // rotate() поворачивает только отрисовку: обёртка с несжатой
            // шириной даёт Text его естественный размер; сдвиг вниз на половину
            // зоны центрирует текст в оставшейся части (звезда сверху)
            Box(Modifier.align(Alignment.Center).offset(y = starZone / 2).wrapContentSize(unbounded = true)) {
                Text(
                    title,
                    color = androidx.compose.ui.graphics.Color.White,
                    fontSize = fs.sp,
                    lineHeight = (fs * 1.25f).sp,
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    // heightIn вместо height: одна строка занимает свою высоту и
                    // центрируется по горизонту торца, две упираются в максимум
                    modifier = Modifier
                        .width(spineH - 20.dp - starZone) // вдоль торца (после rotate — высота на экране)
                        .heightIn(max = spineW - 6.dp) // две строки в ширину торца
                        .rotate(-90f)
                )
            }
            if (bookmarked) {
                Text(
                    "★",
                    color = androidx.compose.ui.graphics.Color(0xFFFFB300),
                    fontSize = 39.sp,
                    modifier = Modifier.align(Alignment.TopCenter).padding(top = 3.dp).clickable { onBookmark() }
                )
            }
            if (!book.isReady) {
                Text(
                    "⏳",
                    fontSize = 10.sp,
                    color = androidx.compose.ui.graphics.Color.White,
                    modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 3.dp)
                )
            }
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
