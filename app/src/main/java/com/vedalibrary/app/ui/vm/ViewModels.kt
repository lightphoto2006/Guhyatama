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
import com.vedalibrary.app.ui.components.GbHtml
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
    private val gdb: com.vedalibrary.app.data.library.LibraryDbImporter,
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
            db.library().deleteBookCascade(id)
            // Аудио своей книги — иначе файлы оставались сиротами (этот путь
            // раньше их не чистил, в отличие от Настроек; теперь везде одно)
            try { gdb.deleteAudioOfBook(id) } catch (_: Exception) { }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (_: Exception) { }
        coverCache.remove(id)
        // JPEG-иллюстрации лежат файлами — чистим каталог, иначе утечка места
        try {
            val dir = java.io.File(ctx.filesDir, "illustrations/${id.replace(Regex("[^A-Za-z0-9_-]"), "_")}")
            if (dir.exists()) dir.deleteRecursively()
        } catch (_: Exception) { }
    }
    /** Путь к первой иллюстрации книги — миниатюра карточки (обложек в .db нет).
     *  Кэшируются только НАЙДЕННЫЕ пути: негатив не кэшируется, иначе обложка,
     *  добавленная после первой загрузки, не появится до пересоздания VM.
     *  Инвалидация — при удалении книги. */
    private val coverCache = mutableMapOf<String, String?>()
    suspend fun coverPath(bookId: String): String? {
        val hit = coverCache[bookId]
        if (hit != null && java.io.File(hit).exists()) return hit
        val path = try {
            db.library().firstIllustration(bookId)?.imagePath?.takeIf { java.io.File(it).exists() }
        } catch (_: Exception) { null }
        if (path != null) coverCache[bookId] = path else coverCache.remove(bookId)
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
            // Ремонт языка лекций Шьямакунды (импортированы как eng): идемпотентно, каждый запуск
            try { withContext(Dispatchers.IO) { db.library().fixLectureLang() } } catch (_: Exception) { }
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
    data class Hit(val item: VerseItem, val snippet: String, val field: String? = null)
    private val _r = MutableStateFlow(emptyList<Hit>())
    val results: StateFlow<List<Hit>> = _r
    /** Запрос/скоп/язык живут в VM — возврат «назад» восстанавливает выдачу, а не чистый экран.
     *  Снаружи — read-only StateFlow + сеттеры (публичный MutableStateFlow позволял
     *  писать в состояние минуя логику VM) */
    private val _query = MutableStateFlow("")
    val query: StateFlow<String> = _query
    private val _scope = MutableStateFlow("all")
    val scope: StateFlow<String> = _scope
    /** Язык выдачи — тот же сохранённый фильтр, что на главной (cycleBookLang):
     *  одна кнопка в поиске меняет язык сразу везде */
    val langFilter: StateFlow<String> = settings.bookLang
        .stateIn(viewModelScope, SharingStarted.Eagerly, "all")
    /** Книга для scope «В книге» (null = везде) */
    private val _bookFilter = MutableStateFlow<String?>(null)
    val bookFilter: StateFlow<String?> = _bookFilter
    fun setQuery(v: String) { _query.value = v }
    fun setScope(v: String) { _scope.value = v }
    fun cycleLang() = viewModelScope.launch { settings.cycleBookLang() }
    fun setBookFilter(v: String?) { _bookFilter.value = v }
    val allBooks: kotlinx.coroutines.flow.Flow<List<com.vedalibrary.app.data.local.Book>> =
        db.library().booksFlow()
    private val H_KEY = stringPreferencesKey("history")
    val history: StateFlow<List<String>> = ctx.searchStore.data
        .map { (it[H_KEY] ?: "").split("\n").filter { s -> s.isNotBlank() } }
        .stateIn(viewModelScope, SharingStarted.Lazily, emptyList())

    /** Пайплайн поиска: debounce — быстрая печать не гоняет запросы (старый
     *  ответ мог затереть более новый), distinctUntilChanged — повторная
     *  установка того же значения FTS не перезапускает. История сюда НЕ пишется
     *  (см. submitHistory): префиксы при наборе её засоряли. */
    init {
        combine(query, scope, bookFilter) { q, sc, b -> Triple(q, sc, b) }
            .debounce(250)
            .distinctUntilChanged()
            .onEach { (q, sc, b) -> runSearch(q, sc, b) }
            .launchIn(viewModelScope)
    }

    /** FTS: запрос целиком в кавычки-фразу — дефис (в FTS это оператор NOT),
     *  скобки, звёздочки и кавычки становятся литералом: «Шримад-Бхагаватам»
     *  ищется нормально, а не роняет запрос в тихо пустую выдачу.
     *  Как в DictViewModel (там кавычки уже показали себя). */
    private fun ftsQuery(q: String, column: String?): String? {
        val clean = q.replace("\"", "").trim()
        if (clean.isEmpty()) return null
        val phrase = "\"$clean\""
        return if (column == null) phrase else "$column:$phrase"
    }

    private suspend fun runSearch(qRaw: String, sc: String, b: String?) {
        val q = qRaw.trim()
        if (q.length < 2) { _r.value = emptyList(); return }
        val col = when (sc) {
            "sanskrit" -> "sanskrit"; "verse" -> "text"; "purport" -> "purport"; else -> null
        }
        val fts = ftsQuery(q, col) ?: return
        try {
            // Без лимитов и квот: выдаём все совпадения («везде» = все книги).
            // Сниппет считается один раз в VM: поиск/подсветка не гоняют plain()
            // на рекомпозиции. Билд hit'ов — в Default: toItem/plain тяжёлые
            // (fromHtml на каждую строку), main держит только эмиссии.
            val rows = if (b != null) db.library().searchLightBook(fts, b)
            else db.library().searchLight(fts)
            suspend fun build(list: List<com.vedalibrary.app.data.local.SearchRow>): List<Hit> =
                withContext(Dispatchers.Default) {
                    list.map { r ->
                        val vr = VerseRow(
                            r.id, r.chapterId, r.bookId, r.number, r.text,
                            r.translation, r.synonyms, r.bookTitle, r.bookLang
                        )
                        val field = pickField(r, col, q)
                        Hit(vr.toItem(), searchSnippet(fieldText(r, field) ?: r.text, q), field)
                    }
                }
            // Первый экран сразу (40 строк), остальное подтягивается следом:
            // тяжёлые лекции/переводы не держат первый показ результатов
            val first = build(rows.take(40))
            _r.value = first
            if (rows.size > 40) _r.value = first + build(rows.drop(40))
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (_: Exception) {
            _r.value = emptyList()
        }
    }

    private fun fieldText(r: com.vedalibrary.app.data.local.SearchRow, field: String?): String? =
        when (field) {
            "sanskrit" -> r.sanskrit
            "text" -> r.text
            "purport" -> r.purport
            "synonyms" -> r.synonyms
            "translation" -> r.translation
            else -> r.translation ?: r.text
        }

    private val fieldOrder = listOf("text", "translation", "purport", "synonyms", "sanskrit")

    /** Поле, где FTS реально нашёл слово: колонка scope, иначе первое поле
     *  с совпадением (иначе сниппет «зачастую без этого слова»). Быстрый проход
     *  (contains ignoreCase) — обычный случай; fold-поиск (per-char NFKC на
     *  строках в 2 КБ) — только фолбэком: он и был причиной лага первых
     *  результатов на секунды. Имя поля уезжает в ?hp=: экран стиха мотает
     *  сразу в секцию с найденным словом, а не в первое вхождение в другом поле. */
    private fun pickField(r: com.vedalibrary.app.data.local.SearchRow, col: String?, q: String): String? =
        when (col) {
            "sanskrit" -> "sanskrit"
            "text" -> "text"
            "purport" -> "purport"
            else -> fieldOrder.firstOrNull { f ->
                val t = fieldText(r, f); !t.isNullOrBlank() && t.contains(q, true)
            } ?: fieldOrder.firstOrNull { f ->
                val t = fieldText(r, f); !t.isNullOrBlank() && GbHtml.containsFold(t, q)
            } ?: "translation"
        }

    /** Сниппет вокруг ПЕРВОГО совпадения: ~2 строки контекста до строки со словом,
     *  строка слова и ~1 строка после (≈4 экран-строки, слово всегда видно).
     *  Сырые поля с тегами (<i>, <br/>, </blockquote>) чистим через plain() —
     *  иначе теги показывались текстом самой выдачи. «пада-\nсеванам» склеиваем,
     *  серии пробельных (табы/переносы строк таблиц) схлопываем. Совпадение ищем
     *  быстрым indexOf; fold/highlightRanges (NFKC на каждом символе) — только
     *  фолбэк для диакритики в запросе. */
    private fun searchSnippet(src: String?, q: String): String {
        val raw = src ?: return ""
        val stripped = if (raw.indexOf('<') >= 0) GbHtml.plain(raw) else raw
        val t = stripped.replace(GbHtml.brokenHyphenRe, "-")
            .replace(Regex("""[\s ]+"""), " ").trim()
        if (t.isEmpty()) return ""
        var st = t.indexOf(q, ignoreCase = true)
        var en = if (st >= 0) st + q.length else -1
        if (st < 0) {
            val r = GbHtml.highlightRanges(t, q).firstOrNull()
            if (r != null) { st = r.first; en = r.last + 1 }
        }
        if (st < 0 || en < 0) return t.take(220) // совпадения в поле нет — контекст начала (как раньше)
        var start = (st - 110).coerceAtLeast(0)
        var end = (en + 60).coerceAtMost(t.length)
        if (start > 0) {
            val sp = t.indexOf(' ', start)
            if (sp in (start + 1) until st) start = sp + 1
        }
        if (end < t.length) {
            val sp = t.lastIndexOf(' ', end)
            if (sp > en) end = sp
        }
        return (if (start > 0) "…" else "") + t.substring(start, end) +
                (if (end < t.length) "…" else "")
    }

    /** История — только по явному действию: IME-поиск, тап по результату
     *  или по строке истории. На каждой клавише не пишем (kr/kri/krish…). */
    fun submitHistory() {
        val q = query.value.trim()
        if (q.length < 2) return
        viewModelScope.launch { saveHistory(q) }
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

/** Строка списков: лёгкие поля + готовая подпись (считается один раз в VM, а не на рекомпозицию).
 *  full — plain-текст без обрезки для выдачи/списков (лекции не дают: там в ref название) */
data class VerseItem(val row: VerseRow, val ref: String, val full: String = "")

private fun VerseRow.toItem() =
    if (VerseShare.isLectureBook(bookId))
        // Лекции: в списках только название («Лекция №29 по стихам…»), нумерация — в подписи
        VerseItem(this, com.vedalibrary.app.ui.components.GbHtml.plain(text).take(160))
    else VerseItem(
        this,
        VerseShare.refLight(bookLang, bookId, chapterId, number),
        com.vedalibrary.app.ui.components.GbHtml.plain(translation ?: text)
    )

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
    /** Число стихов по главам — подписи плиток («Стихов: 44»).
     *  Сдвоенные номера («23-24») раскрываются в два стиха — иначе плитка врёт.
     *  У лекций/писем number — не номер стиха, там считаем строками как раньше */
    val verseCounts: StateFlow<Map<String, Int>> = flow {
        emit(try {
            if (VerseShare.isLectureLike(bookId)) {
                db.library().verseCounts(bookId).associate { it.cid to it.n }
            } else {
                val rows = db.library().verseNumbers(bookId)
                rows.groupBy({ it.cid }, { it.num }).mapValues { (_, ns) ->
                    ns.sumOf { VerseShare.verseCountOf(it) }
                }
            }
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
    /** Тап по плитке главы: глава с единственной лекцией (Введение и т.п.)
     *  открывается сразу, без списка из одного пункта. Иначе — экран главы. */
    fun openChapterOrVerse(chapterId: String, onVerse: (String) -> Unit, onChapter: (String) -> Unit) =
        viewModelScope.launch {
            try {
                val ids = withContext(Dispatchers.IO) { db.library().verseIds(chapterId) }
                if (ids.size == 1) onVerse(ids[0]) else onChapter(chapterId)
            } catch (_: Exception) { onChapter(chapterId) }
        }
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
    /** Якорь закладки применяется ОДИН раз — при первом входе. При возврате
     *  «назад» со стиха и после поворота нужна последняя позиция, иначе
     *  возврат прыгал бы обратно на закладку и терял место чтения */
    var anchorPending: Boolean = startIndex != 0 || startOffset != 0
        private set
    /** Последняя позиция (уход на стих и возврат «назад» — в то же место, а не наверх) */
    var lastIndex: Int = startIndex
        private set
    var lastOffset: Int = startOffset
        private set
    fun anchorDone() { anchorPending = false }
    fun savePos(i: Int, o: Int) {
        if (anchorPending) {
            // Якорь ещё не долетел (список грузится из базы) — 0,0 ничего не значит;
            // собственная прокрутка пользователя важнее якоря
            if (i == 0 && o == 0) return
            anchorPending = false
        }
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
    /** Соседние НЕПУСТЫЕ главы книги в числовом порядке (для свайпа между главами).
     *  Свайп влево в конце списка — первая глава следующей песни, и т.д. */
    val neighborChapters: StateFlow<Pair<String?, String?>> = flow {
        val c = chDef.await()
        if (c == null) return@flow emit(null to null)
        emit(try {
            val raw = db.library().chapters(c.bookId)
            val counts = try {
                db.library().verseCounts(c.bookId).associate { it.cid to it.n }
            } catch (_: Exception) { emptyMap() }
            val chs = raw.filter { (counts[it.id] ?: 0) > 0 }.sortedWith(compareBy(
                { val s = VerseShare.chapterSong(it.id); if (s?.toIntOrNull() == null) 1 else 0 },
                { VerseShare.chapterSong(it.id)?.toIntOrNull() ?: 999 },
                { VerseShare.chapterNumInt(it.id) },
                { it.index }
            ))
            val ci = chs.indexOfFirst { it.id == chapterId }
            if (ci < 0) null to null
            else chs.getOrNull(ci - 1)?.id to chs.getOrNull(ci + 1)?.id
        } catch (_: Exception) { null to null })
    }.stateIn(viewModelScope, SharingStarted.Lazily, null to null)
    /** Закладка книги (одна на книгу). Подсвечена, если стоит на эту главу. */
    val bookmark: StateFlow<com.vedalibrary.app.data.local.Bookmark?> =
        flow {
            val c = chDef.await()
            if (c == null) emit(null)
            else db.library().bookmarkFlow(c.bookId).collect { emit(it) }
        }.stateIn(viewModelScope, SharingStarted.Lazily, null)
    /** Закладка главы: ★ всегда ПЕРЕПИСЫВАЕТ позицию на текущую (и на первом
     *  нажатии, и на повторных — просто запоминаем, где читатель сейчас).
     *  Замена атомарная (@Transaction), не delete+insert двумя запросами. */
    fun saveChapterBookmark(index: Int, offset: Int) = viewModelScope.launch {
        try {
            val c = chDef.await() ?: return@launch
            db.library().replaceBookmark(
                com.vedalibrary.app.data.local.Bookmark(
                    bookId = c.bookId, verseId = null, chapterId = chapterId,
                    scrollIndex = index, scrollOffset = offset
                )
            )
        } catch (_: Exception) { }
    }

    /** Снять закладку главы (удержание ★ 1 секунду). Одна закладка на книгу —
     *  удаляем, только если она стоит на ЭТОЙ главе, чужую не трогаем. */
    fun removeChapterBookmark() = viewModelScope.launch {
        try {
            val b = bookmark.value ?: return@launch
            if (b.chapterId == chapterId && b.verseId == null) db.library().deleteBookmarksOfBook(b.bookId)
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
    /** Поле подсказка из поиска (?hp=): в какой секции FTS нашёл слово
     *  (sanskrit/text/synonyms/translation/purport) — целимся в НЕЁ, иначе
     *  первое вхождение hl в соседнем поле уводит скролл мимо */
    val highlightField: String = run {
        val raw = saved.get<String>("hp") ?: ""
        try { android.net.Uri.decode(raw) } catch (_: Exception) { raw }
    }
    /** Доводка к ?hl= — ОДИН раз при первом входе: возврат «назад» со
     *  связанного стиха не должен мотать обратно — там уже читали дальше */
    private var hlPending: Boolean = highlight.isNotBlank()
    fun takeHl(): Boolean {
        if (!hlPending) return false
        hlPending = false
        return true
    }
    /** Стих + книга грузятся ОДИН раз; потребители ждут через await (StateFlow.first()
     *  возвращал бы начальное значение мгновенно — так терялись бы цитирования/соседи/перевод). */
    private val _loaded = MutableStateFlow(false)
    /** true после прочтения из БД (даже если стиха там нет): без этого экран
     *  «Стих не найден» гадал по таймеру и врал на медленной базе */
    val loaded: StateFlow<Boolean> = _loaded
    private val vbDef = viewModelScope.async {
        val v = try { db.library().verse(verseId) } catch (_: Exception) { null }
        val pair = v to (v?.let { try { db.library().book(it.bookId) } catch (_: Exception) { null } })
        _loaded.value = true
        pair
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
        try {
            db.library().insertNote(com.vedalibrary.app.data.local.GeneralNote(verseId = verseId, text = text.take(2000)))
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (_: Exception) { }
    }

    /** Название книги-цели для диагностики ссылок (null = книги нет).
     *  Парный код («CC/SB») — первое найденное из цепочки */
    suspend fun bookTitleFor(code: String, forLang: String? = null): String? = try {
        val cur = db.library().verse(verseId) ?: return null
        val lang = forLang?.lowercase()?.takeIf { it == "rus" || it == "eng" }
            ?: db.library().book(cur.bookId)?.language ?: "rus"
        var title: String? = null
        for (lc in code.lowercase().split("/").map { it.trim() }.filter { it.isNotEmpty() }) {
            val books = db.library().booksByType(lc)
            val exact = books.filter { it.id.startsWith("gb-$lc-") }
            title = ((exact.ifEmpty { books }).firstOrNull { it.language == lang }
                ?: (exact.ifEmpty { books }).firstOrNull())?.title
            if (title != null) break
        }
        title
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
     *  пробуем ВСЕ по порядку, а не первую попавшуюся.
     *  code может быть парой через "/" («CC/SB» — голые тройки из лекций): пробуем по порядку.
     *  Диапазоны («134-149», «1-74, 82-115») режем до первого номера. */
    suspend fun resolveVerseRef(code: String, song: String, ch: String, txt: String, forLang: String? = null): String? = try {
        val cur = db.library().verse(verseId) ?: return null
        val lang = forLang?.lowercase()?.takeIf { it == "rus" || it == "eng" }
            ?: db.library().book(cur.bookId)?.language ?: "rus"
        val t = txt.split(Regex("[-–—,\\s]+")).firstOrNull()?.trim().orEmpty().ifEmpty { txt }
        var hit: String? = null
        for (lc in code.lowercase().split("/").map { it.trim() }.filter { it.isNotEmpty() }) {
            val books = db.library().booksByType(lc)
            val ordered = orderBooksFull(lc, lang, books)
            for (book in ordered) {
                try {
                    val found = db.library().verse("${book.id}/$song/$ch/$t")
                    if (found != null) {
                        hit = found.id
                        break
                    }
                } catch (_: Exception) { }
                // Сдвоенные стихи (SB 7.5.23 лежит как '23-24'): тот же номер в той же главе
                if (hit == null && ch.isNotBlank() && t.isNotBlank()) {
                    val chs = try { db.library().chapters(book.id) } catch (_: Exception) { emptyList() }
                    val inCh = findInChapter(book.id, song, ch, t, chs)
                    if (inCh != null) {
                        hit = inCh.id
                        break
                    }
                }
            }
            if (hit != null) break
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

    /** Тап ★ — поставить/переставить закладку на ТЕКУЩИЙ стих (прыгнул по
     *  закладке, читал дальше — один тап переносит её, без «снять+поставить») */
    fun setBookmark() = viewModelScope.launch {
        try {
            val v = db.library().verse(verseId) ?: return@launch
            db.library().replaceBookmark(
                com.vedalibrary.app.data.local.Bookmark(bookId = v.bookId, verseId = verseId, chapterId = v.chapterId)
            )
        } catch (_: Exception) { }
    }

    /** Удержание ★ 1 секунду — снять (только если она на этом стихе) */
    fun removeBookmark() = viewModelScope.launch {
        try {
            val v = db.library().verse(verseId) ?: return@launch
            val cur = db.library().bookmark(v.bookId)
            if (cur != null && cur.verseId == verseId) db.library().deleteBookmarksOfBook(v.bookId)
        } catch (_: Exception) { }
    }

    data class ResolvedRef(val label: String, val targetVerseId: String?, val targetRef: String?, val snippet: String? = null)

    private data class ParsedRef(
        val ref: com.vedalibrary.app.data.local.CrossRef,
        val code: String, val song: String, val ch: String, val txt: String
    )

    /** ext:-код в тройку (старый формат без song — song=1).
     *  С какой стороны строки код — неважно: цитирующая и цитируемая меняются
     *  местами одинаково (thisBook — цитируемый, refbyBook — цитирующий). */
    private fun parseExtCode(code: String, ref: com.vedalibrary.app.data.local.CrossRef): ParsedRef? {
        if (!code.startsWith("ext:")) return null
        val parts = code.removePrefix("ext:").split("/")
        return when {
            // ext:BG/1/2/13 (глава может быть пустой: ext:TLKS/1//1CC96 — код лекции)
            parts.size == 4 -> ParsedRef(ref, parts[0].lowercase(), parts[1], parts[2], parts[3])
            // Старые записи без song (ext:BG/2/13): пробуем song=1, не найдётся — строка без ссылки
            parts.size == 3 -> ParsedRef(ref, parts[0].lowercase(), "1", parts[1], parts[2])
            else -> null
        }
    }

    /** ext:-код с цитирующей стороны (перевёрнутые legacy) в тройку */
    private fun parseExtFromRef(r: com.vedalibrary.app.data.local.CrossRef): ParsedRef? {
        if (!r.fromVerseId.startsWith("ext:")) return null
        return parseExtCode(r.fromVerseId, r)
    }

    private val HUMAN_CODE = mapOf(
        "сб" to "sb", "шб" to "sb", "sb" to "sb",
        "бг" to "bg", "bg" to "bg", "чч" to "cc", "cc" to "cc"
    )

    /** Человеческая ссылка TXT-импортов («[[СБ 1.2.3]]», «БГ 2.13», «см. ЧЧ 1.4.8») в тройку */
    private fun parseHumanRef(raw: String, ref: com.vedalibrary.app.data.local.CrossRef): ParsedRef? {
        return try {
            var t = raw.trim()
            if (t.startsWith("[[") && t.endsWith("]]")) t = t.substring(2, t.length - 2).trim()
            t = t.replace(Regex("^(см\\.?\\s+)"), "").trim()
            val m = Regex("^([А-Яа-яA-Za-z]+)\\s*(\\d+[.\\-–]\\d+(?:[.\\-–]\\d+)?)\\s*$").find(t)
                ?: return null
            val code = HUMAN_CODE[m.groupValues[1].lowercase()] ?: return null
            val nums = m.groupValues[2].split(Regex("[.\\-–]")).map { it.trim() }
                .filter { it.isNotEmpty() }
            when (nums.size) {
                3 -> ParsedRef(ref, code, nums[0], nums[1], nums[2])
                2 -> ParsedRef(ref, code, "1", nums[0], nums[1])
                else -> null
            }
        } catch (_: Exception) { null }
    }

    /** Резолв распарсенных ссылок цепочкой книг: точное+свой язык -> свой язык ->
     *  точное -> остальные; внутри группы сначала ПОЛНАЯ книга. Ненашедшиеся —
     *  мёртвой строкой (книга не импортирована). Дубли строк схлопываются. */
    private suspend fun resolveChainRefs(parsed: List<ParsedRef>, lang: String): List<ResolvedRef> {
        if (parsed.isEmpty()) return emptyList()
        val refs = parsed.map { it.ref }.distinctBy { it.id }
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
        suspend fun resolveIn(p: ParsedRef, r: com.vedalibrary.app.data.local.CrossRef): com.vedalibrary.app.data.local.VerseRow? {
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
        return out.distinctBy { Triple(it.label, it.targetVerseId, it.targetRef) }
    }

    /** Что цитируется в этом стихе (V — цитирующий). Единая раскладка
     *  (from = цитирующий, to = цитируемый):
     *  - fromVerseId = V: цитируемый кодом (патчи) или текстом (TXT) — цепочкой;
     *  - fromVerseId = ext:K(V) (перевёрнутые legacy): цитируемый уже конкретным
     *    id — напрямую, свой язык вперёд. */
    val relatedOut: StateFlow<List<ResolvedRef>> = flow {
        val (v, b) = vbDef.await()
        if (v == null) return@flow emit(emptyList())
        val lang = b?.language ?: "rus"
        val key = com.vedalibrary.app.ui.components.VerseShare.incomingKey(b, v)
        val coded = if (key == null) emptyList() else try {
            db.library().refsFromCode(key)
        } catch (_: Exception) { emptyList() }
        val direct = if (coded.isEmpty()) emptyList() else try {
            val ids = coded.map { it.toVerseId }.distinct().filter { !it.startsWith("ext:") }
            if (ids.isEmpty()) emptyList()
            else {
                val byId = try {
                    db.library().verseLightsByIds(ids)
                } catch (_: Exception) { emptyList() }.associateBy { it.id }
                coded.mapNotNull { r -> byId[r.toVerseId] }
                    .sortedWith(compareBy({ if ((it.bookLang ?: "") == lang) 0 else 1 }))
                    .map { fv ->
                        val ref = com.vedalibrary.app.ui.components.VerseShare.refLight(
                            fv.bookLang, fv.bookId, fv.chapterId, fv.number)
                        ResolvedRef(
                            ref, fv.id, ref,
                            com.vedalibrary.app.ui.components.GbHtml.plain(fv.translation ?: fv.text).take(140)
                        )
                    }
            }
        } catch (_: Exception) { emptyList() }
        val own = try { db.library().outgoingRefs(v.id) } catch (_: Exception) { emptyList() }
        val human = own.filter { !it.toVerseId.startsWith("ext:") }
        val hparsed = human.mapNotNull { r -> parseHumanRef(r.toVerseId, r) }
        val hdead = human.filter { r -> hparsed.none { it.ref.id == r.id } }
            .map { r -> ResolvedRef(r.label, null, null) }
        emit((direct + resolveChainRefs(hparsed, lang) + hdead)
            .distinctBy { Triple(it.label, it.targetVerseId, it.targetRef) })
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
            // 1) точное совпадение номера — один запрос; 2) диапазон «34-35» — только
            // (id, номер) главы, без загрузки всех строк стиха
            val exact = try {
                db.library().verseLightByNumber(chId, txt)
            } catch (_: Exception) { return null }
            if (exact != null) return exact
            val t = txt.toIntOrNull() ?: return null
            val nums = try {
                db.library().verseNumIds(chId)
            } catch (_: Exception) { return null }
            val hitId = nums.firstOrNull { txtRangeHit(it.number, t) }?.id ?: return null
            try { db.library().verseLight(hitId) } catch (_: Exception) { null }
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

    /** Первый/последний стих соседней непустой главы (шаг dir = -1/+1, дальше 50 глав не ищем) */
    private suspend fun neighborVerse(
        chs: List<com.vedalibrary.app.data.local.Chapter>, ci: Int, dir: Int
    ): String? {
        var i = ci + dir
        var guard = 0
        while (i in chs.indices && guard++ < 50) {
            // id края главы одним запросом (в порядке стихов) — без чтения строк
            val id = try {
                if (dir > 0) db.library().firstVerseId(chs[i].id)
                else db.library().lastVerseId(chs[i].id)
            } catch (_: Exception) { null }
            if (id != null) return id
            i += dir
        }
        return null
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

    /** Где цитировался данный стих (V — цитируемый). Два вида записей:
     *  - цитирующий конкретным id (патчи: toVerseId = ext:K(V)) — напрямую,
     *    свой язык вперёд;
     *  - цитирующий кодом (перевёрнутые legacy: toVerseId = id V) — цепочкой книг.
     *  Пусто — секция скрыта экраном. */
    val relatedIn: StateFlow<List<ResolvedRef>> = flow {
        val (v, b) = vbDef.await()
        if (v == null) return@flow emit(emptyList())
        val lang = b?.language ?: "rus"
        val key = com.vedalibrary.app.ui.components.VerseShare.incomingKey(b, v)
        val direct = if (key == null) emptyList() else try {
            val refs = db.library().incomingRefs(key)
            if (refs.isEmpty()) emptyList()
            else {
                val byId = try {
                    db.library().verseLightsByIds(refs.map { it.fromVerseId }.distinct())
                } catch (_: Exception) { emptyList() }.associateBy { it.id }
                refs.mapNotNull { r -> byId[r.fromVerseId] }
                    .sortedWith(compareBy({ if ((it.bookLang ?: "") == lang) 0 else 1 }))
                    .map { fv ->
                        val ref = com.vedalibrary.app.ui.components.VerseShare.refLight(
                            fv.bookLang, fv.bookId, fv.chapterId, fv.number)
                        ResolvedRef(
                            ref, fv.id, ref,
                            com.vedalibrary.app.ui.components.GbHtml.plain(fv.translation ?: fv.text).take(140)
                        )
                    }
            }
        } catch (_: Exception) { emptyList() }
        val coded = try { db.library().refsToVerse(v.id) } catch (_: Exception) { emptyList() }
        val cparsed = coded.mapNotNull { parseExtFromRef(it) }
        emit((direct + resolveChainRefs(cparsed, lang))
            .distinctBy { Triple(it.label, it.targetVerseId, it.targetRef) })
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
            val raw = try { db.library().chapters(v.bookId) } catch (_: Exception) { emptyList() }
            // Числовой порядок песен/глав (в старых импортах index идёт текстом: 1,10,11,..,2):
            // иначе свайп с последней главы песни прыгает не в ту песнь
            val chs = raw.sortedWith(compareBy(
                { val s = VerseShare.chapterSong(it.id); if (s?.toIntOrNull() == null) 1 else 0 },
                { VerseShare.chapterSong(it.id)?.toIntOrNull() ?: 999 },
                { VerseShare.chapterNumInt(it.id) },
                { it.index }
            ))
            val ci = chs.indexOfFirst { it.id == v.chapterId }
            if (ci >= 0) {
                // Через границу главы — в соседнюю НЕПУСТУЮ (пустые типа «Заключения»
                // пропускаем, иначе свайп упрётся в тупик). Главы уже в числовом порядке
                if (prev == null) prev = neighborVerse(chs, ci, -1)
                if (next == null) next = neighborVerse(chs, ci, +1)
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
        // Слово бывает в двух письменностях (латиница IAST в одних книгах, кириллица в других):
        // ищем обе формы, иначе русские варианты теряются. Кавычки: дефис в FTS означает NOT
        val alt = com.vedalibrary.app.ui.components.IastCyrillic.convert(word)
        val queries = listOf(word, alt).map { it.replace("\"", "") }
            .filter { it.isNotBlank() }.distinct().map { "\"$it\"" }
        val light = try {
            queries.flatMap { db.library().dictLight(it) }.distinctBy { it.id }
        } catch (_: Exception) { emptyList() }
        if (light.isEmpty()) return@flow emit(emptyList())
        val computed = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.Default) {
            val gb = com.vedalibrary.app.ui.components.GbHtml
            light.mapNotNull { r ->
                val synLine = gb.synonymLines(r.synonyms)
                    .firstOrNull { gb.wholeWord(it, word) }
                    ?: gb.synonymLines(r.synonyms).firstOrNull { gb.wholeWord(it, alt) }
                    ?: return@mapNotNull null
                val type = r.bookId.split("-").getOrNull(1)?.uppercase() ?: ""
                val rank = workRank(type)
                val ref = com.vedalibrary.app.ui.components.VerseShare.refLight(r.bookLang, r.bookId, r.chapterId, r.number)
                val (w, t) = gb.splitHead(synLine)
                val hw = if (r.bookLang == "rus") com.vedalibrary.app.ui.components.IastCyrillic.convert(w) else w
                DictRow(r.id, hw, t, ref, rank, r.bookLang ?: "")
            }.sortedWith(compareBy({ it.rank }))
        }
        emit(computed)
    }.stateIn(viewModelScope, SharingStarted.Lazily, emptyList())

    /** Фильтр языков: по умолчанию только язык источника, «Все языки» — всё */
    private val _showAllLangs = MutableStateFlow(false)
    val showAllLangs: StateFlow<Boolean> = _showAllLangs
    fun toggleShowAll() { _showAllLangs.value = !_showAllLangs.value }
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
