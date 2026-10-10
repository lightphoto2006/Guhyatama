@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.vedalibrary.app.ui.screens

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.vedalibrary.app.ui.components.BookmarkStar
import com.vedalibrary.app.ui.components.GbHtml
import com.vedalibrary.app.ui.components.HtmlText
import com.vedalibrary.app.ui.components.SynonymLine
import com.vedalibrary.app.ui.components.VerseShare
import com.vedalibrary.app.ui.util.VolumeFont
import com.vedalibrary.app.ui.vm.VerseDetailViewModel
import kotlinx.coroutines.launch

/** Детали стиха: санскрит по центру -> транслит -> пословник -> перевод -> комментарий.
 *  Свайп влево/вправо или кнопки — соседние стихи. */
@Composable
fun VerseDetailScreen(
    onSettings: () -> Unit, onWord: (String, String, String) -> Unit,
    onNavigate: (String) -> Unit, onNavigateReplace: (String) -> Unit,
    onAskQuestion: (verseId: String, label: String, quote: String) -> Unit = { _, _, _ -> },
    vm: VerseDetailViewModel = hiltViewModel()
) {
    val v by vm.verse.collectAsState(null)
    val book by vm.book.collectAsState(null)
    val other by vm.otherLang.collectAsState(null)
    val bm by vm.bookmark.collectAsState(null)
    val audioSrc by vm.audio.collectAsState(null)
    val loaded by vm.loaded.collectAsState()
    val neighbors by vm.neighbors.collectAsState(null to null)
    val prevId = neighbors.first
    val nextId = neighbors.second
    val san by vm.settings.showSanskrit.collectAsState(true)
    val tra by vm.settings.showTranslit.collectAsState(true)
    val syn by vm.settings.showSynonyms.collectAsState(true)
    val trl by vm.settings.showTranslation.collectAsState(true)
    val pur by vm.settings.showPurport.collectAsState(true)
    val font by vm.settings.fontVerse.collectAsState(17f)
    val align by vm.settings.paraAlign.collectAsState("justify")
    // Выравнивание текстовых блоков: по ширине | по центру | влево (санскрит/транслит всегда по центру)
    val centerBlock = align == "center"
    val justifyBlock = align == "justify"
    fun go(id: String?) { if (id != null) onNavigateReplace(id) }

    Scaffold(
        topBar = {
            Column(
                Modifier.fillMaxWidth().padding(top = 2.dp, bottom = 2.dp),
                horizontalAlignment = androidx.compose.ui.Alignment.CenterHorizontally
            ) {
                Text(
                    VerseShare.cleanTitle(book?.title ?: VerseShare.bookCode(book)),
                    maxLines = 2, overflow = TextOverflow.Ellipsis,
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                    style = MaterialTheme.typography.titleMedium
                )
                Text(
                    v?.let { VerseShare.ref(book, it) } ?: "",
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                    style = MaterialTheme.typography.labelLarge
                )
                Row(
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = androidx.compose.ui.Alignment.CenterVertically
                ) {
                    // ★: тап — поставить/переставить на текущий стих,
                    // удержание 1с — снять (вибро)
                    BookmarkStar(
                        active = v != null && bm?.verseId == v?.id,
                        style = MaterialTheme.typography.titleLarge,
                        onSave = { vm.setBookmark() },
                        onRemove = { vm.removeBookmark() }
                    )
                    other?.let { (ov, ob) ->
                        TextButton(onClick = { go(ov.id) }) {
                            Text(if (ob?.language == "rus") "RU" else "EN")
                        }
                    }
                    IconButton(onClick = onSettings) {
                        Text(
                            "⚙️",
                            style = MaterialTheme.typography.titleLarge,
                            fontSize = MaterialTheme.typography.titleLarge.fontSize * 1.2f
                        )
                    }
                }
            }
        },
        bottomBar = {
            Row(Modifier.fillMaxWidth().padding(8.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                TextButton(onClick = { go(prevId) }, enabled = prevId != null) { Text("← Пред") }
                TextButton(onClick = { go(nextId) }, enabled = nextId != null) { Text("След →") }
            }
        }
    ) { pad ->
        val verse = v
        val scope = rememberCoroutineScope()
        val ctx = androidx.compose.ui.platform.LocalContext.current
        // Аудио живёт на уровне экрана, а НЕ в элементе списка: раньше прокрутка
        // кнопки за экран роняла плеер release() посреди трека/TTS. Смена стиха —
        // stop (и погасить «Слушать»), уход с экрана — stop + release
        val player = remember { com.vedalibrary.app.ui.audio.VerseAudioPlayer(ctx) }
        var playing by remember { mutableStateOf(false) }
        DisposableEffect(Unit) { onDispose { player.stop(); player.release() } }
        LaunchedEffect(verse?.id) { player.stop(); playing = false }
        // Кнопки громкости — размер шрифта стиха (только пока открыт этот экран)
        val volOwner = remember { Any() }
        DisposableEffect(Unit) {
            VolumeFont.set(volOwner) { d -> scope.launch { vm.settings.bumpVerseFont(d) } }
            onDispose { VolumeFont.clear(volOwner) }
        }
        // Тап по цитате (БГ 2.13 / ШБ 1.2.3) -> тот стих; у gr://-ссылок язык зашит в URL.
        // Цели нет — тост с точной причиной (нет книги / нет стиха в книге).
        fun openRef(code: String, song: String, ch: String, txt: String, lang: String? = null) {
            scope.launch {
                val id = vm.resolveVerseRef(code, song, ch, txt, lang)
                if (id != null) onNavigate(id)
                else {
                    val b = vm.bookTitleFor(code, lang)
                    val msg = if (b == null) "Нет книги $code — импортируй её"
                    else "Нет стиха $code $song.$ch.$txt в «$b»"
                    android.widget.Toast.makeText(ctx, msg, android.widget.Toast.LENGTH_SHORT).show()
                }
            }
        }
        // Контекст лекции для голых номеров стихов («(8.134)», «1.6.82», «ЧЧ Ади Лила 1.1»):
        // песнь/глава — из самой лекции, произведение — из типа книги. Обычным книгам — null
        val lecCtx = remember(verse?.id, book?.id) {
            val k = verse?.let { com.vedalibrary.app.ui.components.VerseShare.verseKey(it) }
            val work = when (book?.id?.split("-")?.getOrNull(1)?.uppercase()) {
                "SCC" -> "CC"
                "SSB" -> "SB"
                "SBG" -> "BG"
                "SBRS" -> "BRS"
                else -> null
            }
            if (k != null && work != null) Triple(k.first, k.second, work) else null
        }
        // «Вопрос» из меню выделения -> редактор вопроса с цитатой
        fun askIt(q: String) {
            val vv = verse ?: return
            onAskQuestion(vv.id, com.vedalibrary.app.ui.components.VerseShare.ref(book, vv), q)
        }
        // Диалог TTS: нет движка/голоса — ведём устанавливать
        var ttsDlg by remember(verse?.id) { mutableStateOf<String?>(null) }
        var ttsEngines by remember(verse?.id) { mutableStateOf(emptyList<String>()) }
        // Подсветка из поиска (?hl=): секция совпадения + доводка, чтобы совпадение
        // оказалось в видимой части (длинные секции: top.item показывает только верх).
        // Ищем по отображаемому тексту (rus = кириллица после cyrillicTranslit/Terms).
        // frac — доля позиции совпадения внутри секции (0 = начало).
        // audioSrc в КЛЮЧАХ: появление аудио-строки сдвигает номера секций вниз —
        // без пересчёта цель уезжала на секцию выше
        val hl = vm.highlight
        val hp = vm.highlightField
        val listState = androidx.compose.foundation.lazy.rememberLazyListState()
        val target = remember(verse?.id, hl, hp, san, tra, syn, trl, pur, book?.language, audioSrc != null) {
            data class T(val idx: Int, val frac: Float)
            if (verse == null || hl.isBlank()) T(-1, 0f)
            else {
                val gb = com.vedalibrary.app.ui.components.GbHtml
                val rus = book?.language == "rus"
                // Тексты present-секций один раз; имена = поля ?hp= из поиска.
                // audio в ключах: появление аудио-строки сдвигает номера секций.
                val names = arrayOf("sanskrit", "audio", "text", "synonyms", "translation", "purport")
                val texts = arrayOf(
                    if (san && !verse.sanskrit.isNullOrBlank()) gb.plain(verse.sanskrit) else null,
                    if (audioSrc != null) "" else null,
                    if (tra && verse.text.isNotBlank())
                        (if (rus) gb.cyrillicTranslit(verse.text) else gb.plain(verse.text)) else null,
                    if (syn && !verse.synonyms.isNullOrBlank())
                        gb.synonymLines(verse.synonyms).joinToString("\n") { line ->
                            val (w, t) = gb.splitHead(line)
                            (if (rus) com.vedalibrary.app.ui.components.IastCyrillic.convert(w) else w) + " " + t
                        } else null,
                    if (trl && !verse.translation.isNullOrBlank())
                        (if (rus) gb.cyrillicTerms(verse.translation) else gb.plain(verse.translation)) else null,
                    if (pur && !verse.purport.isNullOrBlank())
                        (if (rus) gb.cyrillicTerms(verse.purport) else gb.plain(verse.purport)) else null
                )
                val hlFold = gb.foldDia(hl).lowercase()
                fun fracAt(text: String): Float? {
                    if (text.isEmpty()) return null
                    val at = gb.foldDia(text).lowercase().indexOf(hlFold)
                    return if (at >= 0) (at.toFloat() / text.length).coerceIn(0f, 1f) else null
                }
                var res: T? = null
                // 1-й проход: поле-подсказка ?hp= — поиск нашёл слово в ЭТОЙ секции,
                // иначе первое вхождение в соседнем поле (шлока/пословник) цепляло
                // чужую секцию и скролл уезжал мимо комментария
                var idx = 0
                for (i in texts.indices) {
                    val text = texts[i] ?: continue
                    if (names[i] == hp) res = fracAt(text)?.let { T(idx, it) }
                    idx++
                }
                // 2-й проход: первая секция с совпадением (без ?hp= — как раньше)
                if (res == null) {
                    idx = 0
                    for (i in texts.indices) {
                        val text = texts[i] ?: continue
                        if (res == null) res = fracAt(text)?.let { T(idx, it) }
                        idx++
                    }
                }
                res ?: T(-1, 0f)
            }
        }
        LaunchedEffect(verse?.id, hl) {
            // takeHl: доводка только при первом входе — возврат «назад» со
            // связанного стиха не сбрасывает позицию чтения обратно к ?hl=
            if (target.idx >= 0 && vm.takeHl()) {
                try { listState.scrollToItem(target.idx) } catch (_: Exception) { return@LaunchedEffect }
                // Меряем РЕАЛЬНУЮ высоту секции и мотаем на её долю. Старая
                // эвристика «пол-экрана × доля» на длинных комментариях не
                // дотягивала — слово оставалось ниже экрана и приходилось
                // скроллить вручную. Слово целим на ~30% высоты экрана.
                var size = 0
                for (attempt in 0 until 10) {
                    val info = listState.layoutInfo.visibleItemsInfo
                        .firstOrNull { i -> i.index == target.idx }
                    if (info != null) { size = info.size; break }
                    try { kotlinx.coroutines.delay(32) } catch (_: Exception) { }
                }
                val vh = listState.layoutInfo.viewportEndOffset - listState.layoutInfo.viewportStartOffset
                val delta = size * target.frac - vh * 0.30f
                if (size > 0 && vh > 0 && delta > 0f) {
                    try { listState.scrollBy(delta) } catch (_: Exception) { }
                }
            }
        }
        if (verse == null) {
            Box(Modifier.padding(pad).fillMaxSize()) {
                Text(
                    // По реальному состоянию загрузки, а не по таймеру: таймер
                    // врал на медленной БД (ложное «Стих не найден»)
                    if (loaded) "Стих не найден — возможно, книга была удалена или импортирована заново под другим именем файла."
                    else "Загрузка…",
                    Modifier.padding(16.dp)
                )
            }
        }
        else LazyColumn(
            // 6dp вместо 16: больше текста на экране — как в поиске и списке главы
            Modifier.padding(pad).padding(horizontal = 8.dp)
                .pointerInput(prevId, nextId) {
                    var dx = 0f
                    detectHorizontalDragGestures(
                        onHorizontalDrag = { _, d -> dx += d },
                        onDragEnd = { if (dx < -120) go(nextId) else if (dx > 120) go(prevId); dx = 0f }
                    )
                },
            state = listState
        ) {
            if (san && !verse.sanskrit.isNullOrBlank()) item {
                HtmlText(verse.sanskrit!!, Modifier.fillMaxWidth().padding(vertical = 12.dp), center = true, fontSizeSp = font + 2, onSaveNote = { vm.addNote(verse.id, it) }, onAsk = ::askIt, highlight = hl)
            }
            if (audioSrc != null) item {
                Row(
                    Modifier.fillMaxWidth().padding(bottom = 4.dp),
                    horizontalArrangement = Arrangement.Center
                ) {
                    TextButton(onClick = {
                        val a = audioSrc
                        if (playing) {
                            player.stop(); playing = false
                        } else if (a != null) {
                            if (a.path != null) {
                                player.onDone = { playing = false }
                                player.playFile(a.path)
                                playing = true
                            } else if (a.ttsText != null) {
                                player.checkTts { st ->
                                    when (st) {
                                        is com.vedalibrary.app.ui.audio.VerseAudioPlayer.TtsCheck.Ready -> {
                                            player.onDone = { playing = false }
                                            player.speak(a.ttsText)
                                            playing = true
                                        }
                                        is com.vedalibrary.app.ui.audio.VerseAudioPlayer.TtsCheck.NoEngine -> {
                                            ttsEngines = st.engines
                                            ttsDlg = "engine"
                                        }
                                        is com.vedalibrary.app.ui.audio.VerseAudioPlayer.TtsCheck.NoVoice -> {
                                            ttsEngines = st.engines
                                            ttsDlg = "voice"
                                        }
                                    }
                                }
                            }
                        }
                    }) {
                        Text(
                            if (playing) "■ Стоп"
                            else if (audioSrc?.path != null) "▶ Слушать"
                            else "▶ Слушать (TTS)"
                        )
                    }
                }
            }
            if (tra && verse.text.isNotBlank()) item {
                val translitHtml = remember(verse.id, book?.language) {
                    if (book?.language == "rus") GbHtml.cyrillicTranslit(verse.text) else verse.text
                }
                HtmlText(translitHtml, Modifier.fillMaxWidth().padding(vertical = 8.dp), center = true, fontSizeSp = font, onSaveNote = { vm.addNote(verse.id, it) }, onAsk = ::askIt, highlight = hl)
            }
            if (syn && !verse.synonyms.isNullOrBlank()) item {
                // Привязка лекции («ЧЧ 1.4.73-82») — кнопка перехода к первому стиху,
                // а не словарь (там по «ЧЧ» смотреть нечего)
                val lecRef = remember(verse.id, book?.id) {
                    parseLectureRef(verse.synonyms!!, lecCtx)
                }
                if (lecRef != null) {
                    Row(
                        Modifier.fillMaxWidth().clickable {
                            openRef(lecRef.code, lecRef.song, lecRef.ch, lecRef.txt)
                        }.padding(vertical = 10.dp),
                        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically
                    ) {
                        Text(
                            verse.synonyms!!.trim(),
                            fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                            fontSize = font.sp,
                            modifier = Modifier.weight(1f)
                        )
                        Text(
                            "→",
                            style = MaterialTheme.typography.titleLarge,
                            color = MaterialTheme.colorScheme.primary
                        )
                    }
                } else {
                    val synLines = remember(verse.id) { GbHtml.synonymLines(verse.synonyms) }
                    // Раздел пословника: межстрочный шаг как в обычных строках
                    // (−20% к прежним 3dp+темовому lineHeight — просят плотнее)
                    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
                        synLines.forEach { line ->
                            SynonymLine(line, font - 1, onWordClick = { w -> onWord(w, book?.language ?: "eng", book?.id?.split("-")?.getOrNull(1) ?: "") }, modifier = Modifier.fillMaxWidth().padding(vertical = 1.dp), cyrillic = book?.language == "rus", highlight = hl)
                        }
                    }
                }
            }
            if (trl && !verse.translation.isNullOrBlank()) item {
                val translationHtml = remember(verse.id, book?.language) {
                    if (book?.language == "rus") GbHtml.cyrillicTerms(verse.translation) else verse.translation!!
                }
                // Тело лекции — обычным начертанием (жирным только короткие переводы стихов)
                val lectureBody = remember(book?.id) { VerseShare.isLectureBook(book?.id) }
                val proseBody = remember(book?.id) { VerseShare.isProseBook(book?.id) }
                HtmlText(translationHtml, Modifier.fillMaxWidth().padding(vertical = 8.dp), center = centerBlock, justify = justifyBlock, fontSizeSp = font, bold = !lectureBody && !proseBody, onSaveNote = { vm.addNote(verse.id, it) }, onAsk = ::askIt, highlight = hl, onVerseRef = ::openRef,
                    refSong = lecCtx?.first, refCh = lecCtx?.second, refWork = lecCtx?.third)
            }
            if (pur && !verse.purport.isNullOrBlank()) item {
                val purportHtml = remember(verse.id, book?.language) {
                    if (book?.language == "rus") GbHtml.cyrillicTerms(verse.purport) else verse.purport!!
                }
                HtmlText(purportHtml, Modifier.fillMaxWidth().padding(vertical = 8.dp), center = centerBlock, justify = justifyBlock, fontSizeSp = font, onSaveNote = { vm.addNote(verse.id, it) }, onAsk = ::askIt, highlight = hl, onVerseRef = ::openRef,
                    refSong = lecCtx?.first, refCh = lecCtx?.second, refWork = lecCtx?.third)
            }
            item { RelatedSections(vm, onNavigate) }
            item { SimilarSection(vm, verse, onNavigate, font) }
            item { Spacer(Modifier.height(24.dp)) }
        }
        // Диалог нехватки TTS: вести устанавливать движок / скачивать голос
        if (ttsDlg != null) {
            val isEngine = ttsDlg == "engine"
            AlertDialog(
                onDismissRequest = { ttsDlg = null },
                title = { Text(if (isEngine) "Нет синтеза речи" else "Нет голоса хинди/санскрита") },
                text = {
                    Text(
                        (if (isEngine) "Для озвучки нужен движок синтеза речи (например Google TTS)."
                        else "Санскрит озвучивает хинди-голос (в Google TTS есть и голос санскрита). Скачай его: экран настроек речи → Google TTS → установка голосовых данных → хинди или санскрит (желательно офлайн-пакет).") +
                        (if (ttsEngines.isEmpty()) "\n\nДвижки в системе не найдены."
                        else "\n\nНайденные движки: " + ttsEngines.joinToString(", "))
                    )
                },
                confirmButton = {
                    TextButton(onClick = {
                        ttsDlg = null
                        if (isEngine) openPlayTts(ctx) else openTtsSettings(ctx)
                    }) { Text(if (isEngine) "Установить" else "Настройки речи") }
                },
                dismissButton = {
                    TextButton(onClick = {
                        ttsDlg = null
                        if (isEngine) openTtsSettings(ctx)
                    }) { Text(if (isEngine) "Настройки речи" else "Позже") }
                }
            )
        }
    }
}

/** Привязка лекции («ЧЧ 1.4.73-82», «БГ 2.13», «ШБ 1.8.34») -> цель для openRef.
 *  Диапазон режется до первого стиха («73-82» -> «73»): ведут на первый стих ссылки */
private data class LecRef(val code: String, val song: String, val ch: String, val txt: String)

private val LEC_REF_RE = Regex(
    """^\s*(?:(ЧЧ|ШБ|БГ|CC|SB|BG)\s+)?(\d{1,2})\s*[.]\s*(\d{1,3})(?:\s*[.]\s*([\d–—\-, ]+))?\s*$"""
)
private val LEC_CODE = mapOf(
    "ЧЧ" to "CC", "CC" to "CC", "ШБ" to "SB", "SB" to "SB", "БГ" to "BG", "BG" to "BG"
)

private fun parseLectureRef(
    ref: String, lecCtx: Triple<String, String, String>?
): LecRef? {
    val m = LEC_REF_RE.matchEntire(ref.trim()) ?: return null
    val code = m.groupValues[1].uppercase().let { if (it.isBlank()) null else LEC_CODE[it] }
        ?: lecCtx?.third ?: return null
    val a = m.groupValues[2]
    val b = m.groupValues[3]
    val rest = m.groupValues[4]
    val (song, ch, txtRaw) = if (rest.isBlank()) {
        // Две цифры: глава.стих в песне лекции («БГ 2.13»)
        Triple(lecCtx?.first ?: "1", a, b)
    } else {
        Triple(a, b, rest)
    }
    val txt = txtRaw.split(Regex("[-–—,\\s]+")).firstOrNull()?.trim().orEmpty()
    if (txt.isBlank()) return null
    return LecRef(code, song, ch, txt)
}

/** Play Маркет на Google TTS (движок синтеза).
 *  Если Маркета нет или ссылка мертва — запасной выход в настройки речи. */
private fun openPlayTts(ctx: Context) {
    try {
        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=com.google.android.tts"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (_: Exception) {
        try {
            ctx.startActivity(Intent(Intent.ACTION_VIEW,
                Uri.parse("https://play.google.com/store/apps/details?id=com.google.android.tts"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (_: Exception) {
            openTtsSettings(ctx)
        }
    }
}

/** Системные настройки речи (там же скачивание голосов) */
private fun openTtsSettings(ctx: Context) {
    try {
        ctx.startActivity(Intent("com.android.settings.TTS_SETTINGS")
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (_: Exception) {
        try {
            ctx.startActivity(Intent(android.speech.tts.TextToSpeech.Engine.ACTION_INSTALL_TTS_DATA))
        } catch (_: Exception) { }
    }
}

/** Сворачиваемая секция карточки стиха */
@Composable
private fun VerseSection(title: String, font: Float, defaultOpen: Boolean = true, content: @Composable () -> Unit) {
    var open by remember(title, defaultOpen) { mutableStateOf(defaultOpen) }
    Card(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Column(Modifier.padding(12.dp)) {
            Row(Modifier.fillMaxWidth().clickable { open = !open }, horizontalArrangement = Arrangement.SpaceBetween) {
                Text(title, style = MaterialTheme.typography.titleMedium)
                Text(if (open) "▾" else "▸", style = MaterialTheme.typography.titleMedium)
            }
            if (open) { Spacer(Modifier.height(6.dp)); content() }
        }
    }
}

/** Связанные стихи (ссылки из комментариев + упоминания) и другие переводы */
@Composable
private fun RelatedSections(vm: VerseDetailViewModel, onNavigate: (String) -> Unit) {
    val out by vm.relatedOut.collectAsState(emptyList())
    val inc by vm.relatedIn.collectAsState(emptyList())
    if (out.isNotEmpty()) {
        Card(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
            Column(Modifier.padding(12.dp)) {
                Text("Цитаты в этом стихе", style = MaterialTheme.typography.titleMedium)
                out.forEach { r ->
                    val t = r.targetVerseId
                    if (t != null) {
                        ListItem(
                            headlineContent = { Text("→ ${r.targetRef ?: r.label}") },
                            supportingContent = { if (!r.snippet.isNullOrBlank()) Text(r.snippet!!, maxLines = 2) },
                            trailingContent = { Text("›", style = MaterialTheme.typography.titleLarge) },
                            modifier = Modifier.clickable { onNavigate(t) }
                        )
                    } else {
                        Text("→ ${r.label}", modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp))
                    }
                }
            }
        }
    }
    if (inc.isNotEmpty()) {
        Card(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
            Column(Modifier.padding(12.dp)) {
                Text("Где цитировался данный стих (${inc.size})", style = MaterialTheme.typography.titleMedium)
                inc.take(20).forEach { r ->
                    val t = r.targetVerseId
                    if (t != null) {
                        ListItem(
                            headlineContent = { Text("→ ${r.targetRef ?: r.label}") },
                            supportingContent = { if (!r.snippet.isNullOrBlank()) Text(r.snippet!!, maxLines = 2) },
                            trailingContent = { Text("›", style = MaterialTheme.typography.titleLarge) },
                            modifier = Modifier.clickable { onNavigate(t) }
                        )
                    } else {
                        Text("→ ${r.label}", modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp))
                    }
                }
            }
        }
    }
}

/** Похожие стихи главы: только номера, схлопнуто по умолчанию.
 *  Подбор — в Default-потоке (токенизация всей главы), не на Main. */
@Composable
private fun SimilarSection(vm: VerseDetailViewModel, cur: com.vedalibrary.app.data.local.Verse, onNavigate: (String) -> Unit, font: Float) {
    val siblings by vm.siblings.collectAsState(emptyList())
    var sim by remember(cur.id) { mutableStateOf(emptyList<com.vedalibrary.app.ui.vm.VerseItem>()) }
    LaunchedEffect(cur.id, siblings) {
        sim = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.Default) {
            vm.similar(cur, siblings)
        }
    }
    if (sim.isNotEmpty()) {
        VerseSection("Похожие в главе (${sim.size})", font, defaultOpen = false) {
            Column {
                sim.forEach { sv ->
                    ListItem(
                        headlineContent = { Text(sv.ref) },
                        modifier = Modifier.clickable { onNavigate(sv.row.id) }
                    )
                }
            }
        }
    }
}
