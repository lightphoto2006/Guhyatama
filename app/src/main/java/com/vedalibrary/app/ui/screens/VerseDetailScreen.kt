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
import androidx.hilt.navigation.compose.hiltViewModel
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
                Modifier.fillMaxWidth()
                    .windowInsetsPadding(WindowInsets.statusBars)
                    .padding(top = 2.dp, bottom = 2.dp),
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
                    TextButton(onClick = { vm.toggleBookmark() }) {
                        Text(
                            if (v != null && bm?.verseId == v?.id) "★" else "☆",
                            style = MaterialTheme.typography.titleLarge
                        )
                    }
                    other?.let { (ov, ob) ->
                        TextButton(onClick = { go(ov.id) }) {
                            Text(if (ob?.language == "rus") "RU" else "EN")
                        }
                    }
                    IconButton(onClick = onSettings) { Text("⚙️", style = MaterialTheme.typography.titleLarge) }
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
        var timedOut by remember { mutableStateOf(false) }
        LaunchedEffect(Unit) { kotlinx.coroutines.delay(3000); timedOut = true }
        val scope = rememberCoroutineScope()
        val ctx = androidx.compose.ui.platform.LocalContext.current
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
        val hl = vm.highlight
        val listState = androidx.compose.foundation.lazy.rememberLazyListState()
        val target = remember(verse?.id, hl, san, tra, syn, trl, pur, book?.language) {
            data class T(val idx: Int, val frac: Float)
            if (verse == null || hl.isBlank()) T(-1, 0f)
            else {
                var idx = 0
                var res: T? = null
                fun section(present: Boolean, text: String) {
                    if (!present) return
                    if (res == null) {
                        val at = com.vedalibrary.app.ui.components.GbHtml.foldDia(text).lowercase()
                            .indexOf(com.vedalibrary.app.ui.components.GbHtml.foldDia(hl).lowercase())
                        if (at >= 0 && text.isNotEmpty()) {
                            res = T(idx, (at.toFloat() / text.length).coerceIn(0f, 1f))
                        }
                    }
                    idx++
                }
                val gb = com.vedalibrary.app.ui.components.GbHtml
                val rus = book?.language == "rus"
                section(san && !verse.sanskrit.isNullOrBlank(), gb.plain(verse.sanskrit))
                section(audioSrc != null, "")
                section(tra && verse.text.isNotBlank(),
                    if (rus) gb.cyrillicTranslit(verse.text) else gb.plain(verse.text))
                section(syn && !verse.synonyms.isNullOrBlank(),
                    gb.synonymLines(verse.synonyms).joinToString("\n") { line ->
                        val (w, t) = gb.splitHead(line)
                        (if (rus) com.vedalibrary.app.ui.components.IastCyrillic.convert(w) else w) + " " + t
                    })
                section(trl && !verse.translation.isNullOrBlank(),
                    if (rus) gb.cyrillicTerms(verse.translation) else gb.plain(verse.translation))
                section(pur && !verse.purport.isNullOrBlank(),
                    if (rus) gb.cyrillicTerms(verse.purport) else gb.plain(verse.purport))
                res ?: T(-1, 0f)
            }
        }
        LaunchedEffect(verse?.id, hl) {
            if (target.idx >= 0) {
                try { listState.scrollToItem(target.idx) } catch (_: Exception) { }
                // Совпадение глубоко внутри секции — дотягиваем, чтобы было видно
                if (target.frac > 0.15f) {
                    try { kotlinx.coroutines.delay(250) } catch (_: Exception) { }
                    try {
                        val vh = listState.layoutInfo.viewportSize.height
                        if (vh > 0) listState.scrollBy(vh * target.frac * 0.5f)
                    } catch (_: Exception) { }
                }
            }
        }
        if (verse == null) {
            Box(Modifier.padding(pad).fillMaxSize()) {
                Text(
                    if (timedOut) "Стих не найден — возможно, книга была удалена или импортирована заново под другим именем файла."
                    else "Загрузка…",
                    Modifier.padding(16.dp)
                )
            }
        }
        else LazyColumn(
            Modifier.padding(pad).padding(horizontal = 16.dp)
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
                val player = remember { com.vedalibrary.app.ui.audio.VerseAudioPlayer(ctx) }
                var playing by remember(verse.id) { mutableStateOf(false) }
                DisposableEffect(Unit) { onDispose { player.release() } }
                LaunchedEffect(verse.id) { player.stop(); playing = false }
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
                val synLines = remember(verse.id) { GbHtml.synonymLines(verse.synonyms) }
                Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
                    synLines.forEach { line ->
                            SynonymLine(line, font - 1, onWordClick = { w -> onWord(w, book?.language ?: "eng", book?.id?.split("-")?.getOrNull(1) ?: "") }, modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp), cyrillic = book?.language == "rus", highlight = hl)
                    }
                }
            }
            if (trl && !verse.translation.isNullOrBlank()) item {
                val translationHtml = remember(verse.id, book?.language) {
                    if (book?.language == "rus") GbHtml.cyrillicTerms(verse.translation) else verse.translation!!
                }
                HtmlText(translationHtml, Modifier.fillMaxWidth().padding(vertical = 8.dp), center = centerBlock, justify = justifyBlock, fontSizeSp = font, bold = true, onSaveNote = { vm.addNote(verse.id, it) }, onAsk = ::askIt, highlight = hl, onVerseRef = ::openRef)
            }
            if (pur && !verse.purport.isNullOrBlank()) item {
                val purportHtml = remember(verse.id, book?.language) {
                    if (book?.language == "rus") GbHtml.cyrillicTerms(verse.purport) else verse.purport!!
                }
                HtmlText(purportHtml, Modifier.fillMaxWidth().padding(vertical = 8.dp), center = centerBlock, justify = justifyBlock, fontSizeSp = font, onSaveNote = { vm.addNote(verse.id, it) }, onAsk = ::askIt, highlight = hl, onVerseRef = ::openRef)
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
                Text("Где встречается этот стих", style = MaterialTheme.typography.titleMedium)
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
