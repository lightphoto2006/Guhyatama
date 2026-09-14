package com.vedalibrary.app.ui.vm

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import androidx.lifecycle.*
import com.vedalibrary.app.data.local.AppDatabase
import com.vedalibrary.app.data.local.Book
import com.vedalibrary.app.data.local.GeneralNote
import com.vedalibrary.app.data.local.VerseRow
import com.vedalibrary.app.data.local.VerseText
import com.vedalibrary.app.data.settings.ReaderSettings
import com.vedalibrary.app.ui.components.VerseShare
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import javax.inject.Inject

@HiltViewModel
class LibraryViewModel @Inject constructor(
    private val db: AppDatabase,
    val settings: com.vedalibrary.app.data.settings.ReaderSettings,
    private val gdb: com.vedalibrary.app.data.gitabase.GitabaseDbImporter,
    @ApplicationContext private val ctx: Context
) : ViewModel() {
    val books: Flow<List<Book>> = db.library().booksFlow()
    /** Книги по секциям (ручная раскладка перекрывает defaultSection).
     *  Внутри секции — ручной порядок (перетаскивание), новые — в конец. */
    val bySection: StateFlow<Map<Int, List<Book>>> =
        combine(books, settings.bookSections, settings.bookOrder) { list, map, order ->
            val pos = order.withIndex().associate { it.value to it.index }
            list.groupBy { map[it.id] ?: com.vedalibrary.app.data.settings.ReaderSettings.defaultSection(it) }
                .mapValues { (_, bs) ->
                    bs.sortedWith(compareBy({ pos[it.id] ?: Int.MAX_VALUE }, { -it.addedAt }, { it.title }))
                }
        }.stateIn(viewModelScope, SharingStarted.Lazily, emptyMap())
    /** Обмен двух книг местами (перетаскивание). Первый вызов материализует текущий порядок. */
    fun swapBooks(a: String, b: String) = viewModelScope.launch {
        try {
            val all = books.first()
            val sec = settings.bookSections.first()
            val cur = currentOrder(all, sec)
            val ia = cur.indexOf(a)
            val ib = cur.indexOf(b)
            if (ia < 0 || ib < 0) {
                if (ia < 0) cur += a
                if (ib < 0) cur += b
            } else {
                cur[ia] = b
                cur[ib] = a
            }
            settings.setBookOrder(cur)
        } catch (_: Exception) { }
    }
    /** Материализованный глобальный порядок (ручной + новые в конце) */
    private suspend fun currentOrder(all: List<Book>, sec: Map<String, Int>): MutableList<String> {
        val cur = settings.bookOrder.first().toMutableList()
        val known = all.map { it.id }.toSet()
        cur.retainAll(known) // выкидываем давно удалённые
        if (cur.size < known.size) {
            // Первый запуск / новые книги: докладываем в порядке отображения
            val pos = cur.withIndex().associate { it.value to it.index }
            val missing = all.filter { it.id !in cur }.sortedWith(compareBy(
                { sec[it.id] ?: com.vedalibrary.app.data.settings.ReaderSettings.defaultSection(it) },
                { pos[it.id] ?: Int.MAX_VALUE }, { -it.addedAt }, { it.title }))
            cur += missing.map { it.id }
        }
        return cur
    }
    /** Книги секции в порядке отображения (без языкового фильтра UI) */
    private fun inSection(all: List<Book>, sec: Map<String, Int>, order: List<String>, id: String): List<Book> {
        val pos = order.withIndex().associate { it.value to it.index }
        val my = all.firstOrNull { it.id == id } ?: return emptyList()
        val mySec = sec[id] ?: com.vedalibrary.app.data.settings.ReaderSettings.defaultSection(my)
        return all.filter { (sec[it.id] ?: com.vedalibrary.app.data.settings.ReaderSettings.defaultSection(it)) == mySec }
            .sortedWith(compareBy({ pos[it.id] ?: Int.MAX_VALUE }, { -it.addedAt }, { it.title }))
    }
    /** Сдвиг книги на delta внутри своей секции (для перетаскивания — считает свежие данные) */
    fun nudge(id: String, delta: Int) = viewModelScope.launch {
        try {
            val all = books.first()
            val sec = settings.bookSections.first()
            val inSec = inSection(all, sec, currentOrder(all, sec), id)
            val ci = inSec.indexOfFirst { it.id == id }
            val j = ci + delta
            if (ci >= 0 && j in inSec.indices) swapBooks(id, inSec[j].id)
        } catch (_: Exception) { }
    }
    /** В начало / в конец своей секции */
    fun moveEdge(id: String, toTop: Boolean) = viewModelScope.launch {
        try {
            val all = books.first()
            val sec = settings.bookSections.first()
            val order = currentOrder(all, sec)
            val inSecIds = inSection(all, sec, order, id).map { it.id }
            order.remove(id)
            val anchor = if (toTop) inSecIds.firstOrNull { it != id } else inSecIds.lastOrNull { it != id }
            if (anchor == null) order += id
            else {
                val ai = order.indexOf(anchor)
                if (ai < 0) order += id else order.add(if (toTop) ai else ai + 1, id)
            }
            settings.setBookOrder(order)
        } catch (_: Exception) { }
    }
    fun toggleSection(i: Int) = viewModelScope.launch {
        try {
            val cur = settings.collapsedSections.first()
            settings.toggleSectionCollapsed(i, i !in cur)
        } catch (_: Exception) { }
    }
    fun cycleLang() = viewModelScope.launch {
        try { settings.cycleBookLang() } catch (_: Exception) { }
    }
    /** Книги с закладками — для звёздочек на ячейках */
    val bookmarkedBooks: Flow<List<String>> = db.library().bookmarkedBooks()
    fun deleteBook(id: String) = viewModelScope.launch {
        try {
            db.library().deleteVersesOfBook(id)
            db.library().deleteChaptersOfBook(id)
            db.library().deleteIllustrationsOfBook(id)
            db.library().deleteRefsFrom(id)
            db.library().deleteBookmarksOfBook(id)
            db.library().deleteBookRow(id)
        } catch (_: Exception) { }
        coverCache.remove(id)
        // JPEG-иллюстрации лежат файлами — чистим каталог, иначе утечка места
        try {
            val dir = java.io.File(ctx.filesDir, "illustrations/${id.replace(Regex("[^A-Za-z0-9_-]"), "_")}")
            if (dir.exists()) dir.deleteRecursively()
        } catch (_: Exception) { }
    }
    /** Путь к первой иллюстрации книги — миниатюра карточки (обложек в .db нет).
     *  Результат кэшируется на жизнь VM; инвалидируется при удалении книги. */
    private val coverCache = mutableMapOf<String, String?>()
    suspend fun coverPath(bookId: String): String? {
        if (coverCache.containsKey(bookId)) {
            val hit = coverCache[bookId]
            if (hit == null || java.io.File(hit).exists()) return hit
        }
        val path = try {
            db.library().firstIllustration(bookId)?.imagePath?.takeIf { java.io.File(it).exists() }
        } catch (_: Exception) { null }
        coverCache[bookId] = path
        return path
    }
    /** Открыть закладку книги: отдать наружу для навигации */
    fun openBookmark(bookId: String, go: (com.vedalibrary.app.data.local.Bookmark) -> Unit) = viewModelScope.launch {
        try { db.library().bookmark(bookId)?.let(go) } catch (_: Exception) { }
    }
    /** Разовый backfill PUA (v2: карта зависит от языка книги).
     *  Один раз на установку; новые импорты уже чистые. */
    fun backfillPuaIfNeeded() = viewModelScope.launch {
        try {
            val done = ctx.backfillPrefs.data.map { it[PUA_DONE] ?: false }.first()
            if (done) return@launch
            withContext(Dispatchers.IO) { gdb.backfillPua() }
            ctx.backfillPrefs.edit { it[PUA_DONE] = true }
        } catch (_: Exception) { }
    }
}

private val Context.backfillPrefs by preferencesDataStore("backfill_prefs")
private val PUA_DONE = androidx.datastore.preferences.core.booleanPreferencesKey("pua_backfill_v2")

@HiltViewModel
class SearchViewModel @Inject constructor(
    private val db: AppDatabase,
    val settings: com.vedalibrary.app.data.settings.ReaderSettings,
    @ApplicationContext private val ctx: Context
) : ViewModel() {
    data class Hit(val item: VerseItem)
    private val _r = MutableStateFlow(emptyList<Hit>())
    val results: StateFlow<List<Hit>> = _r
    /** Запрос/скоп/язык живут в VM — возврат «назад» восстанавливает выдачу, а не чистый экран */
    val query = MutableStateFlow("")
    val scope = MutableStateFlow("all")
    val langFilter = MutableStateFlow("all")
    private val H_KEY = stringPreferencesKey("history")
    val history: StateFlow<List<String>> = ctx.searchStore.data
        .map { (it[H_KEY] ?: "").split("\n").filter { s -> s.isNotBlank() } }
        .stateIn(viewModelScope, SharingStarted.Lazily, emptyList())

    fun search() = viewModelScope.launch {
        val q = query.value.trim()
        if (q.length < 2) return@launch
        val sc = scope.value
        // scope как в Gitabase: sanskrit/verse/purport — маппим на FTS-запрос
        val fts = when (sc) { "sanskrit" -> "sanskrit:$q"; "verse" -> "text:$q"; "purport" -> "purport:$q"; else -> q }
        _r.value = try {
            db.library().searchLight(fts).map { Hit(it.toItem()) }
        } catch (_: Exception) { emptyList() }
        saveHistory(q)
    }
    fun dictionary(word: String) = viewModelScope.launch {
        _r.value = try {
            db.library().dictLight(word).map { Hit(it.toItem()) }
        } catch (_: Exception) { emptyList() }
    }
    fun clearHistory() = viewModelScope.launch { ctx.searchStore.edit { it[H_KEY] = "" } }
    private suspend fun saveHistory(q: String) {
        if (q.length < 2) return
        try {
            ctx.searchStore.edit { p ->
                val cur = (p[H_KEY] ?: "").split("\n").filter { it.isNotBlank() && it != q }
                p[H_KEY] = (listOf(q) + cur).take(10).joinToString("\n")
            }
        } catch (_: Exception) { }
    }
}

private val Context.searchStore by preferencesDataStore("search_history")

/** Строка списков: лёгкие поля + готовая подпись (считается один раз в VM, а не на рекомпозицию) */
data class VerseItem(val row: VerseRow, val ref: String)

private fun VerseRow.toItem() =
    VerseItem(this, VerseShare.refLight(bookLang, bookId, chapterId, number))

@HiltViewModel
class ReaderViewModel @Inject constructor(
    private val db: AppDatabase,
    val settings: com.vedalibrary.app.data.settings.ReaderSettings,
    saved: SavedStateHandle
) : ViewModel() {
    private val bookId: String = saved.get<String>("bookId") ?: ""
    val book = flow { emit(db.library().book(bookId)) }.stateIn(viewModelScope, SharingStarted.Lazily, null)
    val chapters = flow { emit(db.library().chapters(bookId)) }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())
    /** Разделы верхнего уровня (песни ШБ, темы писем, годы бесед).
     *  Имя — из songs.songname (темы), иначе Песнь/Часть/год. Показываем уровень,
     *  только если разделов 2+ (у БГ один раздел — сразу главы). */
    data class SongGroup(val song: String, val title: String, val chapters: List<com.vedalibrary.app.data.local.Chapter>, val showCount: Boolean = true)
    val songGroups: StateFlow<List<SongGroup>> = combine(chapters, book) { ch, b ->
        if (ch.any { com.vedalibrary.app.ui.components.VerseShare.chapterNum(it.id) != null }) {
            val groups = ch.groupBy { com.vedalibrary.app.ui.components.VerseShare.chapterSong(it.id) ?: "1" }
                .map { (s, list) ->
                    val t = list.firstOrNull()?.songTitle?.trim()?.takeIf { it.isNotEmpty() }
                    if (t != null) SongGroup(s, t, list, false)
                    else SongGroup(s, com.vedalibrary.app.ui.components.VerseShare.songTitle(b, s), list, true)
                }
                .sortedWith(compareBy({ it.song.toIntOrNull() ?: Int.MAX_VALUE }, { it.song }))
            if (groups.size >= 2) groups else emptyList()
        } else emptyList()
    }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())
    val illustrations = flow { emit(try { db.library().illustrations(bookId) } catch (_: Exception) { emptyList() }) }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())
    /** Число стихов по главам — подписи плиток и диагностика пустоты */
    val verseCounts: StateFlow<Map<String, Int>> = flow {
        emit(try {
            db.library().verseCounts(bookId).associate { it.cid to it.n }
        } catch (_: Exception) { emptyMap() })
    }.stateIn(viewModelScope, SharingStarted.Lazily, emptyMap())
    /** Книга из единственного фейкового раздела «Текст» (нет глав): стихи показываем сразу, без плитки */
    val flatChapter: StateFlow<com.vedalibrary.app.data.local.Chapter?> = chapters.map { list ->
        if (list.size != 1) null
        else {
            val c = list[0]
            if (c.id.endsWith("/ch-1-0") || c.title == "Текст") c else null
        }
    }.stateIn(viewModelScope, SharingStarted.Lazily, null)
    val flatVerses: StateFlow<List<VerseItem>> = flatChapter.map { c ->
        if (c == null) emptyList()
        else try { db.library().versesLight(c.id).map { it.toItem() } } catch (_: Exception) { emptyList() }
    }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())
    /** Текст для копирования стиха (плоский режим): полный стих грузится один раз по тапу */
    fun copyVerse(verseId: String, put: (String) -> Unit) = viewModelScope.launch {
        try {
            val r = db.library().verseLight(verseId) ?: return@launch
            put(com.vedalibrary.app.ui.components.VerseShare.copyTextLight(r))
        } catch (_: Exception) { }
    }
    /** Случайный стих книги: COUNT + OFFSET вместо ORDER BY RANDOM() (без full scan+сортировки) */
    fun randomInBook(onOpen: (String) -> Unit) = viewModelScope.launch {
        try {
            val n = db.library().countVerses(bookId)
            if (n <= 0) return@launch
            db.library().verseAtOffset(bookId, (0 until n).random())?.let { onOpen(it.id) }
        } catch (_: Exception) { }
    }
    /** В избранное: номер (БГ 2.13) + перевод. Повторный тап дубль не плодит. */
    fun toCards(verseId: String) = viewModelScope.launch {
        try {
            if (db.library().flashcardIdFor(verseId) != null) return@launch
            val r = db.library().verseLight(verseId) ?: return@launch
            db.library().insertFlashcard(
                com.vedalibrary.app.data.local.Flashcard(
                    verseId = r.id,
                    front = VerseShare.refLight(r.bookLang, r.bookId, r.chapterId, r.number),
                    back = com.vedalibrary.app.ui.components.GbHtml.plain(r.translation ?: r.text).take(1000)
                )
            )
        } catch (_: Exception) { }
    }
}

/** Экран главы: стихи + иллюстрации, привязанные к её стихам */
@HiltViewModel
class ChapterViewModel @Inject constructor(
    private val db: AppDatabase,
    val settings: com.vedalibrary.app.data.settings.ReaderSettings,
    saved: SavedStateHandle
) : ViewModel() {
    val chapterId: String = run {
        val raw = saved.get<String>("chapterId") ?: ""
        try { android.net.Uri.decode(raw) } catch (_: Exception) { raw }
    }
    /** Стартовая позиция скролла (переход по закладке) */
    val startIndex: Int = saved.get<Int>("index") ?: 0
    val startOffset: Int = saved.get<Int>("offset") ?: 0
    /** Последняя позиция (уход на стих и возврат «назад» — в то же место, а не наверх) */
    var lastIndex: Int = startIndex
        private set
    var lastOffset: Int = startOffset
        private set
    fun savePos(i: Int, o: Int) {
        lastIndex = i
        lastOffset = o
    }
    private val chDef = viewModelScope.async {
        try { db.library().chapter(chapterId) } catch (_: Exception) { null }
    }
    private val ch: StateFlow<com.vedalibrary.app.data.local.Chapter?> = flow { emit(chDef.await()) }
        .stateIn(viewModelScope, SharingStarted.Lazily, null)
    val chapter: StateFlow<com.vedalibrary.app.data.local.Chapter?> = ch
    val book: StateFlow<Book?> = ch.map { c ->
        if (c != null) try { db.library().book(c.bookId) } catch (_: Exception) { null } else null
    }.stateIn(viewModelScope, SharingStarted.Lazily, null)
    /** Стихи главы лёгкими строками (без purport/sanskrit) + готовые подписи */
    val verses: StateFlow<List<VerseItem>> = flow {
        emit(try { db.library().versesLight(chapterId).map { it.toItem() } } catch (_: Exception) { emptyList() })
    }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())
    val illustrations = verses.map { items ->
        if (items.isEmpty()) emptyList()
        else {
            val c = chDef.await()
            if (c == null) emptyList()
            else {
                val ids = items.map { it.row.id }.toSet()
                try { db.library().illustrations(c.bookId).filter { it.verseId in ids } }
                catch (_: Exception) { emptyList() }
            }
        }
    }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())
    /** В избранное: номер (БГ 2.13) + перевод. Повторный тап дубль не плодит. */
    fun toCards(verseId: String) = viewModelScope.launch {
        try {
            if (db.library().flashcardIdFor(verseId) != null) return@launch
            val r = db.library().verseLight(verseId) ?: return@launch
            db.library().insertFlashcard(
                com.vedalibrary.app.data.local.Flashcard(
                    verseId = r.id,
                    front = VerseShare.refLight(r.bookLang, r.bookId, r.chapterId, r.number),
                    back = com.vedalibrary.app.ui.components.GbHtml.plain(r.translation ?: r.text).take(1000)
                )
            )
        } catch (_: Exception) { }
    }
    /** Текст для копирования стиха (долгое нажатие): полный стих грузится один раз по тапу */
    fun copyVerse(verseId: String, put: (String) -> Unit) = viewModelScope.launch {
        try {
            val r = db.library().verseLight(verseId) ?: return@launch
            put(com.vedalibrary.app.ui.components.VerseShare.copyTextLight(r))
        } catch (_: Exception) { }
    }
    /** Закладка книги (одна на книгу). Подсвечена, если стоит на эту главу. */
    val bookmark: StateFlow<com.vedalibrary.app.data.local.Bookmark?> =
        flow {
            val c = chDef.await()
            if (c == null) emit(null)
            else db.library().bookmarkFlow(c.bookId).collect { emit(it) }
        }.stateIn(viewModelScope, SharingStarted.Lazily, null)
    /** Запомнить позицию скролла главы */
    fun saveChapterBookmark(index: Int, offset: Int) = viewModelScope.launch {
        try {
            val c = chDef.await() ?: return@launch
            db.library().deleteBookmarksOfBook(c.bookId)
            db.library().insertBookmark(
                com.vedalibrary.app.data.local.Bookmark(
                    bookId = c.bookId, verseId = null, chapterId = chapterId,
                    scrollIndex = index, scrollOffset = offset
                )
            )
        } catch (_: Exception) { }
    }
}

@HiltViewModel
class VerseDetailViewModel @Inject constructor(
    private val db: AppDatabase,
    val settings: ReaderSettings,
    @ApplicationContext private val ctx: Context,
    saved: SavedStateHandle
) : ViewModel() {
    private val verseId: String = run {
        val raw = saved.get<String>("verseId") ?: ""
        // ID содержит '/' (book/song/ch/txt) — в route он encoded
        try { android.net.Uri.decode(raw) } catch (_: Exception) { raw }
    }
    /** Подсветка из поиска (?hl=): мотаем к месту и красим совпадение */
    val highlight: String = run {
        val raw = saved.get<String>("hl") ?: ""
        try { android.net.Uri.decode(raw) } catch (_: Exception) { raw }
    }
    /** Стих + книга грузятся ОДИН раз; потребители ждут через await (StateFlow.first()
     *  возвращал бы начальное значение мгновенно — так терялись бы цитирования/соседи/перевод). */
    private val vbDef = viewModelScope.async {
        val v = try { db.library().verse(verseId) } catch (_: Exception) { null }
        v to (v?.let { try { db.library().book(it.bookId) } catch (_: Exception) { null } })
    }
    private val vb: StateFlow<Pair<com.vedalibrary.app.data.local.Verse?, Book?>> = flow { emit(vbDef.await()) }
        .stateIn(viewModelScope, SharingStarted.Lazily, null to null)
    val verse: StateFlow<com.vedalibrary.app.data.local.Verse?> = vb.map { it.first }
        .stateIn(viewModelScope, SharingStarted.Lazily, null)
    val book: StateFlow<Book?> = vb.map { it.second }
        .stateIn(viewModelScope, SharingStarted.Lazily, null)
    /** Фрагмент выделенного текста -> заметка к стиху */
    fun addNote(verseId: String, text: String) = viewModelScope.launch {
        if (text.isBlank()) return@launch
        db.library().insertNote(com.vedalibrary.app.data.local.GeneralNote(verseId = verseId, text = text.take(2000)))
    }

    /** Название книги-цели для диагностики ссылок (null = книги нет) */
    suspend fun bookTitleFor(code: String, forLang: String? = null): String? = try {
        val cur = db.library().verse(verseId) ?: return null
        val lang = forLang?.lowercase()?.takeIf { it == "rus" || it == "eng" }
            ?: db.library().book(cur.bookId)?.language ?: "rus"
        val lc = code.lowercase()
        val books = db.library().booksByType(lc)
        val exact = books.filter { it.id.startsWith("gb-$lc-") }
        ((exact.ifEmpty { books }).firstOrNull { it.language == lang }
            ?: (exact.ifEmpty { books }).firstOrNull())?.title
    } catch (_: Exception) { null }

    /** Размер книги (число стихов) — кэш на жизнь VM. Полная книга всегда
     *  выигрывает у выборки (main SB 13248 vs VCT 741 под одним типом). */
    private val sizeCache = mutableMapOf<String, Int>()
    private suspend fun bookSize(id: String): Int = sizeCache.getOrPut(id) {
        try { db.library().countVerses(id) } catch (_: Exception) { 0 }
    }

    /** Порядок кандидатов: точное совпадение типа -> свой язык -> БОЛЬШЕ стихов */
    private suspend fun orderBooksFull(code: String, lang: String, books: List<Book>): List<Book> {
        val sizes = books.associate { it.id to bookSize(it.id) }
        return books.sortedWith(compareBy(
            { if (it.id.startsWith("gb-$code-")) 0 else 1 },
            { if (it.language == lang) 0 else 1 },
            { -(sizes[it.id] ?: 0) }
        ))
    }

    /** Inline-цитата вида БГ 2.13 / ШБ 1.2.3 -> id стиха в книге нужного языка:
     *  forLang (из gr://) либо язык текущего стиха. Точное совпадение типа первым.
     *  Книг одного типа и языка бывает несколько (полная ШБ + частичная из Ачарьев!) —
     *  пробуем ВСЕ по порядку, а не первую попавшуюся. */
    suspend fun resolveVerseRef(code: String, song: String, ch: String, txt: String, forLang: String? = null): String? = try {
        val cur = db.library().verse(verseId) ?: return null
        val lang = forLang?.lowercase()?.takeIf { it == "rus" || it == "eng" }
            ?: db.library().book(cur.bookId)?.language ?: "rus"
        val lc = code.lowercase()
        val books = db.library().booksByType(lc)
        val ordered = orderBooksFull(lc, lang, books)
        var hit: String? = null
        for (book in ordered) {
            try {
                val found = db.library().verse("${book.id}/$song/$ch/$txt")
                if (found != null) {
                    hit = found.id
                    break
                }
            } catch (_: Exception) { }
            // Сдвоенные стихи (SB 7.5.23 лежит как '23-24'): тот же номер в той же главе
            if (hit == null && ch.isNotBlank() && txt.isNotBlank()) {
                val chs = try { db.library().chapters(book.id) } catch (_: Exception) { emptyList() }
                val inCh = findInChapter(book.id, song, ch, txt, chs)
                if (inCh != null) {
                    hit = inCh.id
                    break
                }
            }
        }
        hit
    } catch (_: Exception) { null }

    /** Закладка книги (одна на книгу). Подсвечена, если стоит на этот стих. */
    val bookmark: StateFlow<com.vedalibrary.app.data.local.Bookmark?> =
        flow {
            val (v, _) = vbDef.await()
            if (v == null) emit(null)
            else db.library().bookmarkFlow(v.bookId).collect { emit(it) }
        }.stateIn(viewModelScope, SharingStarted.Lazily, null)

    /** Поставить/снять закладку на текущий стих */
    fun toggleBookmark() = viewModelScope.launch {
        try {
            val v = db.library().verse(verseId) ?: return@launch
            val cur = db.library().bookmark(v.bookId)
            if (cur != null && cur.verseId == verseId) db.library().deleteBookmarksOfBook(v.bookId)
            else {
                db.library().deleteBookmarksOfBook(v.bookId)
                db.library().insertBookmark(
                    com.vedalibrary.app.data.local.Bookmark(bookId = v.bookId, verseId = verseId, chapterId = v.chapterId)
                )
            }
        } catch (_: Exception) { }
    }

    data class ResolvedRef(val label: String, val targetVerseId: String?, val targetRef: String?, val snippet: String? = null)

    /** Исходящие ссылки из комментариев. Книги и стихи-цели грузятся батчами (без N+1).
     *  На каждый код — цепочка книг (свой язык вперёд): rus-лекций часто нет,
     *  тогда открывается eng-вариант, а не мёртвая строка. Дубли строк схлопываются. */
    val relatedOut: StateFlow<List<ResolvedRef>> = flow {
        val (v, b) = vbDef.await()
        if (v == null) return@flow emit(emptyList())
        val lang = b?.language ?: "rus"
        val refs = try { db.library().outgoingRefs(v.id) } catch (_: Exception) { emptyList() }
        if (refs.isEmpty()) return@flow emit(emptyList())
        data class Parsed(val ref: com.vedalibrary.app.data.local.CrossRef, val code: String, val song: String, val ch: String, val txt: String)
        val parsed = refs.mapNotNull { r ->
            if (!r.toVerseId.startsWith("ext:")) null
            else {
                val parts = r.toVerseId.removePrefix("ext:").split("/")
                when {
                    // ext:BG/1/2/13 (глава может быть пустой: ext:TLKS/1//1CC96 — код лекции)
                    parts.size == 4 -> Parsed(r, parts[0].lowercase(), parts[1], parts[2], parts[3])
                    // Старые записи без song (ext:BG/2/13): пробуем song=1, не найдётся — строка без ссылки
                    parts.size == 3 -> Parsed(r, parts[0].lowercase(), "1", parts[1], parts[2])
                    else -> null
                }
            }
        }
        // Цепочка книг на код: точное+свой язык -> свой язык -> точное -> остальные;
        // внутри группы — сначала ПОЛНАЯ книга (main SB, а не выборка VCT)
        val allBooks = parsed.map { it.code }.distinct().flatMap { code ->
            try { db.library().booksByType(code) } catch (_: Exception) { emptyList() }
        }.distinctBy { it.id }
        val sizes = allBooks.associate { it.id to bookSize(it.id) }
        fun orderBooks(code: String, all: List<com.vedalibrary.app.data.local.Book>) =
            all.sortedWith(compareBy(
                { if (it.id.startsWith("gb-$code-")) 0 else 1 },
                { if (it.language == lang) 0 else 1 },
                { -(sizes[it.id] ?: 0) }
            ))
        val booksByCode = parsed.map { it.code }.distinct().associateWith { code ->
            val all = try { db.library().booksByType(code) } catch (_: Exception) { emptyList() }
            orderBooks(code, all)
        }
        // Батч прямых id по всем книгам цепочки
        val ids = parsed.flatMap { p ->
            (booksByCode[p.code] ?: emptyList()).map { "${it.id}/${p.song}/${p.ch}/${p.txt}" }
        }
        val versesById = if (ids.isEmpty()) emptyMap()
        else try { db.library().verseLightsByIds(ids) } catch (_: Exception) { emptyList() }.associateBy { it.id }
        val byRefId = parsed.associate { it.ref.id to it }
        // Главы книг — кэшем (для резолва лекций по подписи)
        val chaptersCache = mutableMapOf<String, List<com.vedalibrary.app.data.local.Chapter>>()
        suspend fun chaptersOf(bookId: String) = chaptersCache.getOrPut(bookId) {
            try { db.library().chapters(bookId) } catch (_: Exception) { emptyList() }
        }
        suspend fun resolveIn(p: Parsed, r: com.vedalibrary.app.data.local.CrossRef): com.vedalibrary.app.data.local.VerseRow? {
            for (bk in booksByCode[p.code] ?: return null) {
                // 1) Точный id
                versesById["${bk.id}/${p.song}/${p.ch}/${p.txt}"]?.let { return it }
                // 2) Тот же номер в ТОЙ ЖЕ главе (страхует рассинхрон id: точное или диапазон)
                if (p.ch.isNotBlank() && p.txt.isNotBlank()) {
                    findInChapter(bk.id, p.song, p.ch, p.txt, chaptersOf(bk.id))?.let { return it }
                }
                // 3) Fallback для кодов вообще без главы (TLKS): номер по всей книге
                if (p.ch.isBlank() && p.txt.isNotBlank()) {
                    try { db.library().verseByBookAndNumber(bk.id, p.txt)?.let { full ->
                        db.library().verseLight(full.id)?.let { return it }
                    } } catch (_: Exception) { }
                }
                // 4) Лекции: номер-предмет в подписи («ЛекШБ 1.8.34: ...»)
                if (p.code in LECTURE_TYPES) {
                    resolveLectureVerse(bk.id, p.song, p.ch, r.label, chaptersOf(bk.id))?.let { return it }
                }
            }
            return null
        }
        val out = refs.map { r ->
            val target = byRefId[r.id]?.let { p -> resolveIn(p, r) }
            if (target == null) ResolvedRef(r.label, null, null)
            else ResolvedRef(
                r.label,
                target.id,
                com.vedalibrary.app.ui.components.VerseShare.refLight(target.bookLang, target.bookId, target.chapterId, target.number),
                com.vedalibrary.app.ui.components.GbHtml.plain(target.translation ?: target.text).take(140)
            )
        }
        // Дубли исходных строк (тот же ref дважды) — одна строка
        emit(out.distinctBy { Triple(it.label, it.targetVerseId, it.targetRef) })
    }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())

    /** Коды лекционных книг (резолв по подписи) */
    private val LECTURE_TYPES = setOf("lsb", "lbg", "tlks", "lcc", "liso", "ltrs", "ltr")

    /** Стих с номером/диапазоном внутри главы (song/ch). Точное совпадение раньше диапазонного. */
    private suspend fun findInChapter(
        bookId: String, song: String, ch: String, txt: String,
        chapters: List<com.vedalibrary.app.data.local.Chapter>
    ): com.vedalibrary.app.data.local.VerseRow? {
        return try {
            if (ch.isBlank() || txt.isBlank()) return null
            val chId = chapters.firstOrNull {
                com.vedalibrary.app.ui.components.VerseShare.chapterSong(it.id) == song &&
                        com.vedalibrary.app.ui.components.VerseShare.chapterNum(it.id) == ch
            }?.id ?: return null
            val verses = try {
                db.library().versesLight(chId)
            } catch (_: Exception) { return null }
            val t = txt.toIntOrNull()
            verses.firstOrNull { it.number == txt }
                ?: verses.firstOrNull { t != null && txtRangeHit(it.number, t) }
        } catch (_: Exception) { null }
    }
    /** Стих лекции по подписи («ЛекШБ 1.8.34: дата» -> глава song/ch, номер 34 или диапазон) */
    private suspend fun resolveLectureVerse(
        bookId: String,
        pSong: String, pCh: String, label: String,
        chapters: List<com.vedalibrary.app.data.local.Chapter>
    ): com.vedalibrary.app.data.local.VerseRow? {
        return try {
            val m3 = Regex("(\\d+)\\.(\\d+)\\.(\\d+)").find(label)
            val triple: Triple<String, String, String> = if (m3 != null) {
                val (a, b2, c) = m3.destructured
                Triple(a, b2, c)
            } else {
                val m2 = Regex("(\\d+)\\.(\\d+)").find(label)
                if (m2 == null) null
                else {
                    val (a, c) = m2.destructured
                    // Двухуровневая («ЛекБГ 2.11»): глава.стих, песнь из ref
                    Triple(pSong.ifBlank { "1" }, a, c)
                }
            } ?: return null
            val (song, ch, num) = triple
            findInChapter(bookId, song, ch, num, chapters)
        } catch (_: Exception) { null }
    }

    /** Номер лекции vs txt_no («34», «34-35», «30-34»): точное или вхождение в диапазон */
    private fun txtRangeHit(txtNo: String, target: Int): Boolean {
        val s = txtNo.trim()
        if (s == target.toString()) return true
        val parts = s.split("-").mapNotNull { it.trim().toIntOrNull() }
        if (parts.size == 2) {
            val (a, b2) = parts
            if (a <= target && target <= b2) return true
        }
        return false
    }

    /** Стихи, в чьих комментариях упомянут текущий: цитирующие грузятся одним батчем (без N+1).
     *  Свой язык — первым (иначе та же лекция дважды: rus+eng). */
    val relatedIn: StateFlow<List<ResolvedRef>> = flow {
        val (v, b) = vbDef.await()
        if (v == null) return@flow emit(emptyList())
        val lang = b?.language ?: "rus"
        val key = com.vedalibrary.app.ui.components.VerseShare.incomingKey(b, v)
            ?: return@flow emit(emptyList())
        val refs = try { db.library().incomingRefs(key) } catch (_: Exception) { emptyList() }
        if (refs.isEmpty()) return@flow emit(emptyList())
        val byId = try {
            db.library().verseLightsByIds(refs.map { it.fromVerseId }.distinct())
        } catch (_: Exception) { emptyList() }.associateBy { it.id }
        emit(refs.mapNotNull { r ->
            byId[r.fromVerseId]
        }.sortedWith(compareBy({ if ((it.bookLang ?: "") == lang) 0 else 1 })).map { fv ->
            val ref = com.vedalibrary.app.ui.components.VerseShare.refLight(fv.bookLang, fv.bookId, fv.chapterId, fv.number)
            ResolvedRef(
                ref, fv.id, ref,
                com.vedalibrary.app.ui.components.GbHtml.plain(fv.translation ?: fv.text).take(140)
            )
        })
    }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())

    /** Тот же стих того же произведения на другом языке (кнопка Перевод), null = нет пары.
     *  Без LIKE-скана: книги типа — дешёвым запросом, стихи — точечными PK-lookup'ами. */
    val otherLang = flow<Pair<com.vedalibrary.app.data.local.Verse, com.vedalibrary.app.data.local.Book?>?> {
        val (v, b) = vbDef.await()
        if (v == null || b == null) return@flow emit(null)
        val k = com.vedalibrary.app.ui.components.VerseShare.verseKey(v) ?: return@flow emit(null)
        val type = b.id.split("-").getOrNull(1) ?: return@flow emit(null)
        // Точное совпадение типа первым (BG раньше BG72), затем полные книги (main раньше выборок)
        val candidates = try { db.library().booksByType(type) } catch (_: Exception) { emptyList() }
        val sizes = candidates.associate { it.id to bookSize(it.id) }
        val ordered = candidates.sortedWith(compareBy(
            { if (it.id.startsWith("gb-$type-")) 0 else 1 },
            { -(sizes[it.id] ?: 0) }
        ))
        for (cand in ordered) {
            if (cand.language == b.language || cand.id == b.id) continue
            val id = "${cand.id}/${k.first}/${k.second}/${k.third}"
            val sv = try { db.library().verse(id) } catch (_: Exception) { null }
            if (sv != null) return@flow emit(sv to cand)
        }
        emit(null)
    }.stateIn(viewModelScope, SharingStarted.Lazily, null)

    /** Источник озвучки санскрита: файл (mp3/ogg, если импортирован) иначе TTS по деванагари */
    data class AudioSource(val path: String?, val ttsText: String?)
    val audio: StateFlow<AudioSource?> = flow {
        val (v, _) = vbDef.await()
        if (v == null) return@flow emit(null)
        val k = com.vedalibrary.app.ui.components.VerseShare.verseKey(v)
        if (k != null) {
            val f = com.vedalibrary.app.data.local.AudioFiles.fileAny(ctx, v.bookId, k.first, k.second, k.third)
            if (f.exists()) return@flow emit(AudioSource(f.absolutePath, null))
        }
        val d = com.vedalibrary.app.ui.components.GbHtml.plain(v.sanskrit)
        emit(if (d.isNotBlank()) AudioSource(null, d) else null)
    }.stateIn(viewModelScope, SharingStarted.Lazily, null)

    /** Стихи той же главы лёгкими строками — для похожих и свайпа (без purport/sanskrit) */
    val siblings: StateFlow<List<VerseItem>> = flow {
        val (v, _) = vbDef.await()
        if (v == null) return@flow emit(emptyList())
        emit(try { db.library().versesLight(v.chapterId).map { it.toItem() } } catch (_: Exception) { emptyList() })
    }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())

    /** Похожие в главе: пересечение слов-голов пословника (транслит санскрита).
     *  Перевод НЕ участвует: иначе русское «море» из перевода матчит unrelated-стихи. */
    fun similar(cur: VerseText, all: List<VerseItem>): List<VerseItem> {
        val gb = com.vedalibrary.app.ui.components.GbHtml
        fun heads(s: String?): Set<String> =
            gb.synonymLines(s)
                .map { gb.splitHead(it).first }
                .flatMap { it.lowercase().split(Regex("[^\\p{L}]+")) }
                .filter { it.length > 3 }.toSet()
        val base = heads(cur.synonyms)
        if (base.isEmpty()) return emptyList()
        return all.filter { it.row.id != cur.id }
            .map { it to (heads(it.row.synonyms) intersect base).size }
            .filter { it.second >= 2 }
            .sortedByDescending { it.second }
            .take(5).map { it.first }
    }
    /** Соседи для свайпа и кнопок: на границе главы — первый/последний стих соседней главы */
    val neighbors: StateFlow<Pair<String?, String?>> = siblings.map { list ->
        val (v, _) = vbDef.await()
        if (v == null || list.isEmpty()) return@map (null to null)
        val ids = list.map { it.row.id }
        val i = ids.indexOf(verseId)
        var prev: String? = ids.getOrNull(i - 1)
        var next: String? = ids.getOrNull(i + 1)
        if (prev == null || next == null) {
            val chs = try { db.library().chapters(v.bookId) } catch (_: Exception) { emptyList() }
            val ci = chs.indexOfFirst { it.id == v.chapterId }
            if (ci >= 0) {
                if (prev == null) {
                    prev = chs.getOrNull(ci - 1)?.let { pc ->
                        try { db.library().versesLight(pc.id) } catch (_: Exception) { emptyList() }.lastOrNull()?.id
                    }
                }
                if (next == null) {
                    next = chs.getOrNull(ci + 1)?.let { nc ->
                        try { db.library().versesLight(nc.id) } catch (_: Exception) { emptyList() }.firstOrNull()?.id
                    }
                }
            }
        }
        prev to next
    }.stateIn(viewModelScope, SharingStarted.Lazily, null to null)
}

@HiltViewModel
class DictViewModel @Inject constructor(
    private val db: AppDatabase,
    val settings: com.vedalibrary.app.data.settings.ReaderSettings,
    saved: SavedStateHandle
) : ViewModel() {
    /** Язык книги, откуда тапнули слово: свои вхождения показываем первыми и на нём */
    val lang: String = saved.get<String>("lang") ?: "eng"
    /** Тип произведения-источника (sb/bg/cc): задаёт порядок произведений в выдаче */
    val sourceType: String = (saved.get<String>("type") ?: "").uppercase()
    val word: String = run {
        val raw = saved.get<String>("word") ?: ""
        try { android.net.Uri.decode(raw) } catch (_: Exception) { raw }
    }
    /** Слово для заголовка — на языке источника */
    val titleWord: String = if (lang == "rus") com.vedalibrary.app.ui.components.IastCyrillic.convert(word) else word

    /** Строка выдачи: head — слово (жирным), tail — перевод (курсивом), ref — ссылка */
    data class DictRow(
        val verseId: String, val head: String, val tail: String, val ref: String,
        val rank: Int, val blang: String
    )

    /** Порядок произведений: свои → БГ/ШБ/ЧЧ по источнику → остальные */
    private fun workRank(type: String): Int {
        val order = when (sourceType) {
            "BG" -> listOf("BG", "SB", "CC")
            "CC" -> listOf("CC", "SB", "BG")
            else -> listOf("SB", "BG", "CC")
        }
        val i = order.indexOf(type.uppercase())
        return if (i >= 0) i else order.size
    }

    /** Вхождения одним FTS-запросом; сниппеты считаем в Default (не на Main).
     *  Показываем ТОЛЬКО строки пословника со словом (слово — перевод, 1-3 слова).
     *  Предложений из переводов здесь нет: если слова нет в пословнике стиха — стих пропускаем. */
    private val allRows: StateFlow<List<DictRow>> = flow {
        // Кавычки: дефис в FTS означает NOT, без кавычек "какой-то" сломает запрос
        val q = "\"" + word.replace("\"", "") + "\""
        val light = try { db.library().dictLight(q) } catch (_: Exception) { emptyList() }
        if (light.isEmpty()) return@flow emit(emptyList())
        val computed = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.Default) {
            light.mapNotNull { r ->
                val synLine = com.vedalibrary.app.ui.components.GbHtml.synonymLines(r.synonyms)
                    .firstOrNull { com.vedalibrary.app.ui.components.GbHtml.wholeWord(it, word) }
                    ?: return@mapNotNull null
                val type = r.bookId.split("-").getOrNull(1)?.uppercase() ?: ""
                val rank = workRank(type)
                val ref = com.vedalibrary.app.ui.components.VerseShare.refLight(r.bookLang, r.bookId, r.chapterId, r.number)
                val (w, t) = com.vedalibrary.app.ui.components.GbHtml.splitHead(synLine)
                val hw = if (r.bookLang == "rus") com.vedalibrary.app.ui.components.IastCyrillic.convert(w) else w
                DictRow(r.id, hw, t, ref, rank, r.bookLang ?: "")
            }.sortedWith(compareBy({ it.rank }))
        }
        emit(computed)
    }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())

    /** Фильтр языков: по умолчанию только язык источника, «Все языки» — всё */
    val showAllLangs = MutableStateFlow(false)
    fun toggleShowAll() { showAllLangs.value = !showAllLangs.value }
    val rows: StateFlow<List<DictRow>> = combine(allRows, showAllLangs) { list, all ->
        if (all) list else list.filter { it.blang == lang }
    }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())
}

@HiltViewModel
class FavoritesViewModel @Inject constructor(
    private val db: AppDatabase,
    val settings: com.vedalibrary.app.data.settings.ReaderSettings
) : ViewModel() {
    data class Item(val card: com.vedalibrary.app.data.local.Flashcard, val verseLabel: String?)
    val items: StateFlow<List<Item>> = db.library().flashcardsFlow().map { list ->
        if (list.isEmpty()) return@map emptyList()
        val byId = try {
            db.library().verseLightsByIds(list.map { it.verseId }.distinct())
        } catch (_: Exception) { emptyList() }.associateBy { it.id }
        list.map { c ->
            val r = byId[c.verseId]
            Item(c, r?.let { VerseShare.refLight(it.bookLang, it.bookId, it.chapterId, it.number) })
        }
    }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())
    fun delete(id: Long) = viewModelScope.launch {
        try { db.library().deleteFlashcard(id) } catch (_: Exception) { }
    }
}

@HiltViewModel
class NotesViewModel @Inject constructor(
    private val db: AppDatabase,
    val settings: com.vedalibrary.app.data.settings.ReaderSettings
) : ViewModel() {
    data class Item(val note: GeneralNote, val verseLabel: String?, val verseGone: Boolean)
    /** Заметки + подпись стиха («БГ 2.13»), новые сверху. Стихи — одним батчем. */
    val items: StateFlow<List<Item>> = db.library().notesFlow().map { list ->
        if (list.isEmpty()) return@map emptyList()
        val byId = try {
            db.library().verseLightsByIds(list.mapNotNull { it.verseId }.distinct())
        } catch (_: Exception) { emptyList() }.associateBy { it.id }
        list.map { n ->
            if (n.verseId == null) Item(n, null, false)
            else {
                val r = byId[n.verseId]
                if (r == null) Item(n, null, true)
                else Item(n, VerseShare.refLight(r.bookLang, r.bookId, r.chapterId, r.number), false)
            }
        }
    }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())
    fun delete(id: Long) = viewModelScope.launch {
        try { db.library().deleteNote(id) } catch (_: Exception) { }
    }
}

@HiltViewModel
class QuestionsViewModel @Inject constructor(
    private val db: AppDatabase,
    val settings: com.vedalibrary.app.data.settings.ReaderSettings
) : ViewModel() {
    /** Вопросы в порядке создания (нумерация 1..N стабильна) */
    val items: StateFlow<List<com.vedalibrary.app.data.local.Question>> =
        db.library().questionsFlow().stateIn(viewModelScope, SharingStarted.Lazily, emptyList())

    fun delete(id: Long) = viewModelScope.launch {
        try { db.library().deleteQuestion(id) } catch (_: Exception) { }
    }

    /** Создать или обновить (editId != null). Без заголовка/текста — молча нет. */
    fun save(title: String, quote: String, text: String, verseId: String, verseLabel: String, editId: Long? = null) =
        viewModelScope.launch {
            val t = title.trim()
            val q = text.trim()
            if (t.isBlank() || q.isBlank()) return@launch
            try {
                if (editId != null) {
                    val old = db.library().question(editId) ?: return@launch
                    db.library().updateQuestion(old.copy(title = t, quote = quote, text = q))
                } else {
                    db.library().insertQuestion(
                        com.vedalibrary.app.data.local.Question(
                            verseId = verseId, verseLabel = verseLabel,
                            title = t, quote = quote.take(2000), text = q.take(5000)))
                }
            } catch (_: Exception) { }
        }

    suspend fun load(id: Long) = try { db.library().question(id) } catch (_: Exception) { null }
}
