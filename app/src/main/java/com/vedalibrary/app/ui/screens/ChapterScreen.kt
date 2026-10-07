@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class, androidx.compose.foundation.ExperimentalFoundationApi::class)

package com.vedalibrary.app.ui.screens

import android.content.ClipData
import android.content.ClipboardManager
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.*
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.vedalibrary.app.ui.theme.ReadFont
import com.vedalibrary.app.ui.util.VolumeFont
import com.vedalibrary.app.ui.vm.ChapterViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** Глава -> список стихов. Тап -> детали, долгое нажатие -> копировать с номером / в карточки.
 *  Свайп на краю списка — соседняя глава (влево в конце -> первая глава следующей песни). */
@Composable
fun ChapterScreen(
    onVerse: (String) -> Unit,
    onSettings: () -> Unit, onIllustrations: (String) -> Unit,
    onChapterReplace: (String) -> Unit = {},
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
    // Восстановление позиции скролла: якорь закладки — только при первом входе,
    // при возврате «назад» (со стиха) и после поворота — последняя позиция.
    // Ключ Unit (а не chapterId!): после поворота VM жива, chapterId тот же — эффект обязан
    // отработать заново, иначе список остаётся наверху. Повторы с паузой — список может
    // ещё не подгрузиться из базы к моменту первого прохода
    val listState = androidx.compose.foundation.lazy.rememberLazyListState()
    LaunchedEffect(Unit) {
        val pending = vm.anchorPending
        val i = if (pending) vm.startIndex to vm.startOffset
        else vm.lastIndex to vm.lastOffset
        if (i.first == 0 && i.second == 0) return@LaunchedEffect
        // Ждём появления стихов: scrollToItem по пустому списку не бросает
        // исключения — он применяется вхолостую, а якорь сгорает зря.
        // Не дождались — якорь НЕ гасим, повторим при следующем входе
        var waited = 0
        while (vm.verses.value.isEmpty() && waited < 5000) {
            delay(50)
            waited += 50
        }
        if (vm.verses.value.isEmpty()) return@LaunchedEffect
        repeat(4) {
            try {
                listState.scrollToItem(i.first, i.second)
                if (pending) vm.anchorDone()
                return@LaunchedEffect
            } catch (_: Exception) { }
            delay(250)
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
        // Две строки по центру (название + произведение) + ряд кнопок разделителем:
        // длинное название влезает целиком, шапка отделена от списка стихов
        Column(
            Modifier.fillMaxWidth().padding(start = 12.dp, end = 12.dp, top = 8.dp),
            horizontalAlignment = androidx.compose.ui.Alignment.CenterHorizontally
        ) {
            Text(
                chapter?.title ?: "Глава",
                maxLines = 3, overflow = TextOverflow.Ellipsis,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                style = MaterialTheme.typography.titleMedium
            )
            book?.title?.let { com.vedalibrary.app.ui.components.VerseShare.cleanTitle(it) }
                ?.takeIf { it.isNotBlank() }?.let {
                    Text(
                        it,
                        maxLines = 1, overflow = TextOverflow.Ellipsis,
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                        style = MaterialTheme.typography.labelLarge
                    )
                }
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                TextButton(
                    onClick = {
                        vm.saveChapterBookmark(listState.firstVisibleItemIndex, listState.firstVisibleItemScrollOffset)
                    },
                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp)
                ) {
                    val b = bm
                    Text(
                        if (b != null && b.chapterId == vm.chapterId && b.verseId == null) "★" else "☆",
                        style = MaterialTheme.typography.titleMedium,
                        fontSize = 33.sp
                    )
                }
                Text(
                    "⚙️",
                    style = MaterialTheme.typography.titleMedium,
                    fontSize = MaterialTheme.typography.titleMedium.fontSize * 1.2f,
                    modifier = Modifier.clickable { onSettings() }.padding(8.dp)
                )
            }
        }
    }) { pad ->
        val neighbors by vm.neighborChapters.collectAsState(null to null)
        LazyColumn(
            Modifier.padding(pad).pointerInput(neighbors) {
                var dx = 0f
                detectHorizontalDragGestures(
                    onHorizontalDrag = { _, d -> dx += d },
                    onDragEnd = {
                        // Только на краях списка, иначе мешаем обычному скроллу/выделению
                        val atStart = listState.firstVisibleItemIndex == 0 &&
                                listState.firstVisibleItemScrollOffset == 0
                        val vis = listState.layoutInfo.visibleItemsInfo
                        val atEnd = vis.isNotEmpty() &&
                                vis.last().index >= listState.layoutInfo.totalItemsCount - 1
                        if (dx < -120 && atEnd) neighbors.second?.let(onChapterReplace)
                        else if (dx > 120 && atStart) neighbors.first?.let(onChapterReplace)
                        dx = 0f
                    }
                )
            },
            state = listState
        ) {
            if (illus.isNotEmpty() && book != null) {
                val eng = book?.language == "eng"
                item(key = "illus") {
                    // Вместо ListItem: у M3-ListItem нет contentPadding (внутренние
                    // 16dp не отключить) — отступы строк 8dp по краям
                    Column(
                        Modifier.fillMaxWidth()
                            .clickable { onIllustrations(book!!.id) }
                            .padding(horizontal = 8.dp, vertical = 8.dp)
                    ) {
                        Text(
                            if (eng) "Illustrations (${illus.size})" else "Иллюстрации (${illus.size})",
                            style = MaterialTheme.typography.bodyLarge
                        )
                        Text(
                            if (eng) "Open chapter pictures" else "Открыть картинки главы",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
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

/** Общий список стихов главы: тап — детали, долгое нажатие — копировать/в избранное.
 *  Лекции: только название строкой + нумерация подписью (тела в списке нет).
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
        // Лекции целиком живут в translation (десятки КБ): в списке их нет вообще,
        // только подпись с нумерацией (ЧЧ 2.8.134-149); полный текст — по тапу
        val isLecture = remember(item.row.id) {
            com.vedalibrary.app.ui.components.VerseShare.isLectureBook(item.row.bookId)
        }
        val full = remember(item.full) {
            val t = item.full
            if (t.length > 800) t.take(800).trimEnd() + "… (открыть)" else t
        }
        val lectureRef = remember(item.row.id) {
            // Введение (номер 000): подписи нет — заголовка достаточно
            if (isLecture && item.row.number != "000") com.vedalibrary.app.ui.components.VerseShare.refLight(
                item.row.bookLang, item.row.bookId, item.row.chapterId, item.row.number)
            else ""
        }
        var showMenu by remember(item.row.id) { mutableStateOf(false) }
        // Box-якорь: иначе DropdownMenu в LazyColumn всплывает вверху экрана
        androidx.compose.foundation.layout.Box {
            // Вместо ListItem: у M3-ListItem нет contentPadding (внутренние 16dp
            // не отключить) — отступы строк 8dp по краям, 8dp сверху/снизу;
            // стили как у ListItem: headline = bodyLarge, supporting = bodyMedium
            Column(
                Modifier.fillMaxWidth()
                    .combinedClickable(
                        onClick = { onVerse(item.row.id) },
                        onLongClick = { showMenu = true }
                    )
                    .padding(horizontal = 8.dp, vertical = 8.dp)
            ) {
                if (isLecture) {
                    // Лекции — одной строкой: «БРС1.20-22 Лекция №18. Стихи 20-22»
                    val onVar = MaterialTheme.colorScheme.onSurfaceVariant
                    val line = buildAnnotatedString {
                        if (lectureRef.isNotBlank()) {
                            withStyle(SpanStyle(fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)) {
                                // Без пробела после кода — как в поиске («БГ2.40»)
                                append(lectureRef.replace(Regex("""^(\p{Lu}{2,4}) (?=\d)"""), "$1"))
                            }
                            withStyle(SpanStyle(color = onVar)) {
                                // «Лекция №18 по стихам 20-22» → «Лекция №18. Стихи 20-22»
                                append(" " + item.ref.replace(" по стихам ", ". Стихи "))
                            }
                        } else {
                            // Введение (номер 000): только заголовок
                            withStyle(SpanStyle(fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)) {
                                append(item.ref)
                            }
                        }
                    }
                    val lineSize = if (fontSizeSp > 0) fontSizeSp.sp else MaterialTheme.typography.bodyLarge.fontSize
                    Text(
                        line,
                        style = MaterialTheme.typography.bodyLarge,
                        fontSize = lineSize,
                        lineHeight = lineSize * 1.35f
                    )
                } else {
                    Text(
                        item.ref,
                        style = MaterialTheme.typography.bodyLarge,
                        fontWeight = androidx.compose.ui.text.font.FontWeight.Bold
                    )
                    val listSize = if (fontSizeSp > 0) fontSizeSp.sp else MaterialTheme.typography.bodyMedium.fontSize
                    Text(
                        full,
                        style = MaterialTheme.typography.bodyMedium,
                        fontFamily = ReadFont,
                        textAlign = textAlign,
                        fontSize = listSize,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        // Воздух между строками: крупным кеглем без него всё сливается
                        lineHeight = listSize * 1.35f
                    )
                }
            }
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
