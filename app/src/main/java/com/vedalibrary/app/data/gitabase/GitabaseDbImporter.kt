package com.vedalibrary.app.data.gitabase

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import com.vedalibrary.app.data.local.*
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Прямой импорт оригинальных .db Gitabase (SQLite, FTS3).
 * Проверено на твоих файлах: gitabase_gita_eng.db, songs_rus, texts_*.
 *
 * Схема Gitabase:
 *  books(_id,title,author,type,hasSanskrit,hasPurport)
 *  chapters(_id,book_id,book,song,number,title,desc) — number = номер главы
 *  songs(...) — для песенников (isSongBook=1), когда chapters пустые
 *  textnums(_id,book_id,song,ch_no,txt_no,preview,url) JOIN texts(_id,sanskrit,translit,transl1,transl2,comment)
 *    texts._id == textnums._id, text=translit/transl1, purport=comment (HTML)
 *  textrefs(thisBook,thisSong,thisChapter,thisTextNo, refby...) — кросс-ссылки
 *  meanings/eind/links — словарь (покрывается нашим FTS, отдельно не тянем)
 * Отдельный файл gitabase-reader-notes-v5.db: notes/tags/tagging/bms — заметки и закладки.
 */
@Singleton
class GitabaseDbImporter @Inject constructor(
    @ApplicationContext private val ctx: Context,
    private val db: AppDatabase
) {
    data class Result(val bookIds: List<String>, val verses: Int, val notes: Int = 0, val failed: List<String> = emptyList(), val perBook: List<Pair<String, Int>> = emptyList())

    companion object {
        private val SAFE_DIR_RE = Regex("[^A-Za-z0-9_-]")
    }

    suspend fun importFile(src: File, langHint: String = "rus", onProgress: (done: Int, total: Int, label: String) -> Unit = { _, _, _ -> }): Result =
        withContext(Dispatchers.IO) {
            val sq = SQLiteDatabase.openDatabase(src.absolutePath, null, SQLiteDatabase.OPEN_READONLY)
            try {
                if (hasTable(sq, "notes")) return@withContext importNotesDb(sq)
                // Аудио-файл от dbcomposer (только таблица verse_audio, без книг):
                // раскладываем MP3 по уже импортированным книгам этого типа (rus+eng)
                if (hasTable(sq, "verse_audio") && !hasTable(sq, "books")) {
                    return@withContext importAudioDb(sq, onProgress)
                }
                val bookIds = mutableListOf<String>()
                val failed = mutableListOf<String>()
                val perBook = mutableListOf<Pair<String, Int>>()
                var totalVerses = 0
                // type (MA) -> _id (1) — для textrefs: thisBook=MA -> ищем в keyToId с gbBook=1
                val typeToGbId = mutableMapOf<String, Long>()
                data class GbBook(val id: Long, val title: String, val author: String?, val type: String)
                val gbBooks = mutableListOf<GbBook>()
                // Один проход по books (курсор SQLite нельзя перечитать, поэтому сразу в память)
                sq.rawQuery("SELECT _id,title,author,type FROM books", null).use {
                    while (it.moveToNext()) {
                        val gbId = it.getLong(0)
                        val type = it.getString(3) ?: "GB"
                        typeToGbId[type] = gbId
                        gbBooks += GbBook(gbId, it.getString(1) ?: "Без названия", it.getString(2)?.ifBlank { null }, type)
                    }
                }
                for ((gbId, title, author, type) in gbBooks) {
                    // bookId БЕЗ имени файла: один и тот же труд из разных файлов
                    // (texts_eng vs texts2_eng — побуквенно одинаковые) — одна книга, а не дубли
                    val bookId = "gb-${type.lowercase()}-$gbId-$langHint"
                    // Чистка legacy-дублей со старым суффиксом имени файла.
                    // Варианты -xN (разные книги под одним id) — НЕ трогаем.
                    try {
                        for (old in db.library().booksWithPrefix("$bookId-")) {
                            if (old.id == bookId) continue
                            if (Regex("-x\\d+$").containsMatchIn(old.id)) continue
                            db.library().deleteVersesOfBook(old.id)
                            db.library().deleteChaptersOfBook(old.id)
                            db.library().deleteIllustrationsOfBook(old.id)
                            db.library().deleteRefsFrom(old.id)
                            db.library().deleteBookmarksOfBook(old.id)
                            db.library().deleteBookRow(old.id)
                            try {
                                File(ctx.filesDir, "illustrations/${old.id.replace(SAFE_DIR_RE, "_")}")
                                    .let { if (it.exists()) it.deleteRecursively() }
                            } catch (_: Exception) { }
                        }
                    } catch (_: Exception) { }
                    // Коллизия id: та же книга из другого файла (main SB vs выборка VCT
                    // под одним gb-sb-3-eng) — разным книгам разные id, иначе импорт
                    // затирает чужую книгу целиком
                    val finalId = resolveBookIdCollision(sq, gbId, bookId)
                    try {
                        db.library().deleteVersesOfBook(finalId)
                        db.library().deleteChaptersOfBook(finalId)
                        db.library().deleteIllustrationsOfBook(finalId)
                        db.library().deleteRefsFrom(finalId)
                        db.library().upsertBooks(listOf(Book(finalId, "$title [$type]", author, langHint, null, "GITABASE_DB", 0)))
                            val chapters = readChapters(sq, gbId, finalId, langHint)
                        db.library().upsertChapters(chapters.values.toList())
                        onProgress(0, 1, title)
                        val (count, words, keyToId) = importVersesStreaming(sq, gbId, finalId, chapters) { d, t ->
                            onProgress(d, t, title)
                        }
                        db.library().markBookReady(finalId, words / 150)
                        importTextRefs(sq, typeToGbId, type, keyToId)
                        importIllustrations(sq, gbId, finalId, keyToId)
                        totalVerses += count
                        bookIds += finalId
                        perBook += title to count
                    } catch (e: Exception) {
                        failed += "$title: ${e.message}"
                    }
                }
                Result(bookIds, totalVerses, 0, failed, perBook)
            } finally { sq.close() }
        }

    /** Коллизия app-id: один gb-TYPE-gbId-lang из разных файлов — разные книги
     *  (main SB 13248 стихов vs выборка VCT 741 под тем же gb-sb-3-eng).
     *  Сверяем размеры (стихи+главы): совпали — тот же труд, замена по месту;
     *  нет — ищем/создаём вариант "$bookId-x$verses" (стабилен между переимпортами). */
    private suspend fun resolveBookIdCollision(
        sq: android.database.sqlite.SQLiteDatabase, gbId: Long, bookId: String
    ): String {
        return try {
            val ex = db.library().book(bookId) ?: return bookId
            if (!ex.isReady) return bookId
            val nNewV = sq.rawQuery(
                "SELECT COUNT(*) FROM textnums WHERE book_id=$gbId", null).use {
                if (it.moveToFirst()) it.getInt(0) else -1
            }
            val nNewC = try {
                sq.rawQuery("SELECT COUNT(*) FROM chapters WHERE book_id=$gbId", null).use {
                    if (it.moveToFirst()) it.getInt(0) else -1
                }
            } catch (_: Exception) { -1 }
            val nOldV = try { db.library().countVerses(bookId) } catch (_: Exception) { -2 }
            val nOldC = try { db.library().chapters(bookId).size } catch (_: Exception) { -2 }
            if (nOldV == nNewV && nOldC == nNewC) return bookId
            for (cand in db.library().booksWithPrefix("$bookId-x")) {
                val cv = try { db.library().countVerses(cand.id) } catch (_: Exception) { -3 }
                val cc = try { db.library().chapters(cand.id).size } catch (_: Exception) { -3 }
                if (cv == nNewV && cc == nNewC) return cand.id
            }
            "$bookId-x$nNewV"
        } catch (_: Exception) { bookId }
    }

    /** Главы книги + имена разделов верхнего уровня (темы писем из songs.songname).
     *  Префиксы — по языку и смыслу: пусто -> «Глава N»/«Chapter N», цифра в начале -> как есть
     *  («1967 год»), иначе номер без слова («2. Divinity...» — одинаково для rus/eng). */
    private fun readChapters(sq: SQLiteDatabase, gbBook: Long, bookId: String, lang: String): Map<String, Chapter> {
        val map = linkedMapOf<String, Chapter>()
        // Имена разделов (темы писем, иначе пустышка) — таблица songs есть не везде
        val songNames = try {
            mutableMapOf<String, String>().also { m ->
                sq.rawQuery("SELECT song,songname FROM songs WHERE book_id=$gbBook", null).use { c ->
                    while (c.moveToNext()) {
                        c.getString(1)?.trim()?.takeIf { it.isNotBlank() }?.let { m[c.getString(0) ?: "?"] = it }
                    }
                }
            }
        } catch (_: Exception) { emptyMap() }
        sq.rawQuery("SELECT song,number,title FROM chapters WHERE book_id=$gbBook ORDER BY song,number", null).use { c ->
            var found = false
            while (c.moveToNext()) {
                val song = c.getString(0) ?: "1"; val num = c.getInt(1)
                val raw = c.getString(2)?.trim()?.replace(Regex("\\s+"), " ")
                val title = when {
                    raw.isNullOrBlank() -> if (lang == "rus") "Глава $num" else "Chapter $num"
                    raw.first().isDigit() -> raw
                    num > 0 -> "$num. $raw"
                    else -> raw
                }
                val key = "$gbBook/$song/$num"
                map[key] = Chapter("$bookId/ch-$song-$num", bookId, map.size, title, songTitle = songNames[song])
                found = true
            }
            if (found) return map
        }
        sq.rawQuery("SELECT song,songname FROM songs WHERE book_id=$gbBook ORDER BY sort,song", null).use { c ->
            while (c.moveToNext()) {
                val s = c.getString(0) ?: "?"; var name = c.getString(1)?.trim() ?: if (lang == "rus") "Песня" else "Song"
                if (!name.firstOrNull()?.isDigit().let { it == true }) name = (if (lang == "rus") "Песня $s. " else "Song $s. ") + name
                // Для песенников ch_no=0 в textnums, поэтому ключ "$gbBook/$song/0"
                map["$gbBook/$s/0"] = Chapter("$bookId/ch-$s", bookId, map.size, name)
            }
        }
        if (map.isEmpty()) map["$gbBook/1/0"] = Chapter("$bookId/ch-1-0", bookId, 0, if (lang == "rus") "Текст" else "Text")
        return map
    }

    /** Читает курсор и сразу пишет батчами в Room. Возвращает (кол-во, слова, ключ->verseId). */
    private suspend fun importVersesStreaming(
        sq: SQLiteDatabase, gbBook: Long, bookId: String, chapters: Map<String, Chapter>,
        onProgress: (Int, Int) -> Unit
    ): Triple<Int, Int, Map<String, String>> {
        val total = sq.rawQuery("SELECT COUNT(*) FROM textnums WHERE book_id=$gbBook", null).use { it.moveToFirst(); it.getInt(0) }
        var done = 0
        var words = 0
        val keyToId = HashMap<String, String>(total.coerceAtMost(60000))
        var batch = ArrayList<Verse>(300)
        suspend fun flush() { if (batch.isNotEmpty()) { db.library().upsertVerses(batch); batch = ArrayList(300) } }
        sq.rawQuery(
            "SELECT n.song,n.ch_no,n.txt_no,n.preview,t.sanskrit,t.translit,t.transl1,t.transl2,t.comment " +
            "FROM textnums n LEFT JOIN texts t ON t._id=n._id WHERE n.book_id=$gbBook ORDER BY n.song,n.ch_no,n._id", null
        ).use { c ->
            while (c.moveToNext()) {
                val song = c.getString(0) ?: "1"; val ch = c.getString(1) ?: "0"; val txtNo = c.getString(2) ?: "$done"
                val preview = c.getString(3) ?: ""
                val chKey = "$gbBook/$song/$ch"
                // Точное совпадение, иначе любая глава книги с таким ch_no (беседы: song='' в textnums)
                val chId = chapters[chKey]?.id
                    ?: chapters.entries.firstOrNull { it.key.endsWith("/$ch") }?.value?.id
                    ?: (chapters.values.find { it.bookId == bookId }?.id ?: chapters.values.first().id)
                // PUA-шрифт Gitabase чиним СРАЗУ при импорте: иначе FTS индексирует кракозябры
                // и поиск слов (словарь) по русским книгам ничего не находит.
                // Шрифт разный для языков: rus = кириллица, остальные = IAST-латынь.
                val cyr = bookId.substringAfterLast("-") == "rus"
                val fix = { s: String -> com.vedalibrary.app.ui.components.GbHtml.fixPua(s, cyr) }
                val sanskrit = c.getString(4)?.ifBlank { null }?.let(fix)?.take(2000)
                val translit = c.getString(5); val tr1 = c.getString(6); val tr2 = c.getString(7); val comment = c.getString(8)
                val text = translit?.ifBlank { null }?.let(fix)?.take(8000) ?: preview
                val synonyms = tr1?.ifBlank { null }?.let(fix)?.take(12000)
                val translation = (tr2?.ifBlank { null }?.let(fix) ?: preview.ifBlank { null })?.take(8000)
                val purport = comment?.ifBlank { null }?.let(fix)?.take(30000)
                val id = "$bookId/$song/$ch/$txtNo"
                batch += Verse(id, chId, bookId, txtNo, sanskrit, text, purport, "гл. $ch · № $txtNo", synonyms, translation)
                // Ключ включает gbBook: "1/1/1" уникален для каждой книги (song/ch_no могут совпадать)
                keyToId["$gbBook/$song/$ch/$txtNo"] = id
                words += text.length / 6 + (purport?.length ?: 0) / 6
                if (++done % 300 == 0) { flush(); onProgress(done, total) }
            }
        }
        flush()
        onProgress(total, total)
        return Triple(done, words, keyToId)
    }

    /** Кросс-ссылки из комментариев: this(SONG/ch/txt) -> ext:BOOK/song/ch/txt (refbySong обязателен!). */
    private suspend fun importTextRefs(sq: SQLiteDatabase, typeToGbId: Map<String, Long>, thisBook: String, byKey: Map<String, String>) {
        try {
            val refs = mutableListOf<CrossRef>()
            sq.rawQuery("SELECT thisSong,thisChapter,thisTextNo,refbyBook,refbySong,refbyChapter,refbyTextNo,refbyText FROM textrefs WHERE thisBook='$thisBook' LIMIT 20000", null).use { c ->
                while (c.moveToNext()) {
                    val song = c.getString(0); val ch = c.getString(1); val txt = c.getString(2) ?: ""
                    val gbBook = typeToGbId[thisBook] ?: continue
                    val from = byKey["$gbBook/$song/$ch/$txt"] ?: continue
                    val rb = c.getString(3)?.uppercase() ?: continue
                    val rs = c.getString(4) ?: ""
                    val rc = c.getString(5) ?: ""
                    val rt = c.getString(6) ?: ""
                    val label = c.getString(7)?.take(120) ?: "$rb $rc.$rt"
                    refs += CrossRef(fromVerseId = from, toVerseId = "ext:$rb/$rs/$rc/$rt", label = label)
                    if (refs.size >= 20000) { db.library().insertCrossRefs(refs.toList()); refs.clear() }
                }
            }
            if (refs.isNotEmpty()) db.library().insertCrossRefs(refs)
        } catch (_: Exception) { /* старых базах может не быть textrefs — не критично */ }
    }

    /** Иллюстрации: images.content — base64 JPEG (BLOB с текстом) или сырой JPEG;
     *  привязка через image_nums (sid/cid/tnum). Колонки ищем ПО ИМЕНАМ: схема плавает
     *  (9 колонок с bid/text_id/type/kind либо старая 5-колоночная). */
    private suspend fun importIllustrations(sq: SQLiteDatabase, gbBook: Long, bookId: String, keyToId: Map<String, String>) {
        try {
            val dir = File(ctx.filesDir, "illustrations/${bookId.replace(SAFE_DIR_RE, "_")}").apply { mkdirs() }
            data class ImgRow(val sid: String?, val cid: String?, val tnum: String?, val imageId: String, val caption: String?)
            val rows = mutableListOf<ImgRow>()
            // bid-фильтр — только если колонка есть (в старой схеме её нет)
            var hasBid = false
            try {
                sq.rawQuery("SELECT * FROM image_nums LIMIT 0", null).use { probe ->
                    hasBid = probe.columnNames.any { it.equals("bid", true) }
                }
            } catch (_: Exception) { return }
            val where = if (hasBid) "WHERE bid=$gbBook" else ""
            sq.rawQuery("SELECT * FROM image_nums $where LIMIT 3000", null).use { c ->
                val names = c.columnNames.map { it.lowercase() }
                fun col(name: String, fallback: Int): Int {
                    val i = names.indexOf(name)
                    return if (i in 0 until c.columnCount) i else fallback
                }
                val iSid = col("sid", 0); val iCid = col("cid", 1); val iTnum = col("tnum", 2)
                val iImg = col("image_id", 3); val iDesc = col("desc", 4)
                while (c.moveToNext()) {
                    val imageId = if (iImg < c.columnCount) c.getString(iImg) ?: continue else continue
                    val caption = if (iDesc < c.columnCount) c.getString(iDesc)?.take(300) else null
                    rows += ImgRow(
                        if (iSid < c.columnCount) c.getString(iSid) else null,
                        if (iCid < c.columnCount) c.getString(iCid) else null,
                        if (iTnum < c.columnCount) c.getString(iTnum) else null,
                        imageId, caption
                    )
                }
            }
            // Один запрос контента чанками по 500 (лимит переменных SQLite).
            // Обложка (таблица covers из dbcomposer) едет тем же батчем —
            // поэтому раннего выхода при пустых rows нет: обложка может быть без image_nums.
            val coverId: String? = try {
                sq.rawQuery("SELECT image_id FROM covers WHERE book_id=$gbBook LIMIT 1", null).use {
                    if (it.moveToFirst()) it.getString(0) else null
                }
            } catch (_: Exception) { null }
            val contentById = HashMap<String, ByteArray>(rows.size + 1)
            (rows.map { it.imageId }.distinct() + listOfNotNull(coverId)).distinct().chunked(500).forEach { chunk ->
                val q = chunk.joinToString(",") { "?" }
                sq.rawQuery("SELECT image_id,content FROM images WHERE image_id IN ($q)", chunk.toTypedArray()).use { ic ->
                    val idI = ic.columnNames.indexOfFirst { it.equals("image_id", true) }.takeIf { it >= 0 } ?: 0
                    val coI = ic.columnNames.indexOfFirst { it.equals("content", true) }.takeIf { it >= 0 } ?: 1
                    while (ic.moveToNext()) {
                        try {
                            val blob = ic.getBlob(coI) ?: continue
                            if (blob.isNotEmpty()) contentById[ic.getString(idI)] = blob
                        } catch (_: Exception) { }
                    }
                }
            }
            val out = mutableListOf<Illustration>()
            for (r in rows) {
                val verseId = keyToId["$gbBook/${r.sid}/${r.cid}/${r.tnum}"]
                val raw = contentById[r.imageId] ?: continue
                // BLOB бывает base64-текстом и сырым JPEG — пробуем оба варианта
                val bytes = try {
                    android.util.Base64.decode(raw, android.util.Base64.DEFAULT)
                } catch (_: Exception) { null }?.takeIf { it.size in 100..8_000_000 }
                    ?: raw.takeIf {
                        it.size in 100..8_000_000 &&
                                ((it[0] == 0xFF.toByte() && it[1] == 0xD8.toByte()) || // JPEG
                                 (it[0] == 0x89.toByte() && it[1] == 0x50.toByte())) // PNG
                    } ?: continue
                try {
                    val f = File(dir, "${r.imageId.replace(Regex("[^A-Za-z0-9_-]"), "_")}.jpg")
                    if (!f.exists()) f.writeBytes(bytes)
                    out += Illustration(bookId = bookId, verseId = verseId, imagePath = f.absolutePath, caption = r.caption)
                    if (out.size >= 200) { db.library().upsertIllustrations(out.toList()); out.clear() }
                } catch (_: Exception) { }
            }
            if (out.isNotEmpty()) db.library().upsertIllustrations(out)
            // Обложка -> cover.jpg + Book.coverPath (показывается на карточке книги)
            if (coverId != null) {
                try {
                    val raw = contentById[coverId]
                    val bytes = raw?.let {
                        try {
                            android.util.Base64.decode(it, android.util.Base64.DEFAULT)
                        } catch (_: Exception) { null }?.takeIf { b -> b.size in 100..8_000_000 }
                            ?: it.takeIf { b ->
                                b.size in 100..8_000_000 &&
                                        ((b[0] == 0xFF.toByte() && b[1] == 0xD8.toByte()) ||
                                         (b[0] == 0x89.toByte() && b[1] == 0x50.toByte()))
                            }
                    }
                    if (bytes != null) {
                        val f = File(dir, "cover.jpg")
                        f.writeBytes(bytes)
                        db.library().setCover(bookId, f.absolutePath)
                    }
                } catch (_: Exception) { }
            }
        } catch (_: Exception) { /* нет таблиц картинок — не критично */ }
    }

    /**
     * Импорт аудио-БД (verse_audio от dbcomposer): MP3/OGG раскладываются файлами
     * audio/<bookId>/<song>_<ch>_<txt>.mp3 (.ogg для Opus) для ВСЕХ книг этого типа
     * (rus+eng — начитка санскрита безъязыкая). Совпадение — по существующему стиху.
     */
    private suspend fun importAudioDb(
        sq: SQLiteDatabase,
        onProgress: (done: Int, total: Int, label: String) -> Unit
    ): Result {
        data class AR(val type: String, val song: String, val ch: String, val txt: String, val content: ByteArray, val ogg: Boolean)
        val rows = mutableListOf<AR>()
        // mime есть во всех паках dbcomposer; старые файлы без колонки — считаем mp3
        val hasMime = try {
            sq.rawQuery("SELECT mime FROM verse_audio LIMIT 1", null).use { true }
        } catch (_: Exception) { false }
        sq.rawQuery("SELECT book_type,song,ch_no,txt_no,content" + (if (hasMime) ",mime" else "") + " FROM verse_audio LIMIT 20000", null).use { c ->
            if (c.columnCount < 5) return Result(emptyList(), 0, 0, listOf("В аудио-БД нет таблицы verse_audio"))
            while (c.moveToNext()) {
                val blob = try { c.getBlob(4) } catch (_: Exception) { null }
                if (blob == null || blob.size < 5 * 1024 || blob.size > 8 * 1024 * 1024) continue
                val type = c.getString(0)?.uppercase() ?: continue
                val mime = try { c.getString(5) ?: "" } catch (_: Exception) { "" }
                rows += AR(type, c.getString(1) ?: "1", c.getString(2) ?: "", c.getString(3) ?: "", blob,
                    mime.contains("ogg") || mime.contains("opus"))
            }
        }
        if (rows.isEmpty()) return Result(emptyList(), 0, 0, listOf("В аудио-БД нет записей"))
        val bookIds = mutableListOf<String>()
        val failed = mutableListOf<String>()
        val perBook = mutableListOf<Pair<String, Int>>()
        var linked = 0
        var done = 0
        val total = rows.size
        for ((type, list) in rows.groupBy { it.type }) {
            // Префикс: пак BG раздаётся и на BG72/BG-S (совпадение — по существующему стиху)
            val books = try {
                (db.library().booksByType(type.lowercase()) +
                        db.library().booksByTypePrefix(type.lowercase())).distinctBy { it.id }
            } catch (_: Exception) { emptyList() }
            if (books.isEmpty()) {
                failed += "Нет книг типа $type — сначала импортируй тексты"
                continue
            }
            for (b in books) {
                var n = 0
                for (r in list) {
                    // точное совпадение, иначе первая часть диапазона ("8" -> "8-10")
                    var hit = false
                    for (t in listOf(r.txt, r.txt.substringBefore("-")).distinct()) {
                        val id = "${b.id}/${r.song}/${r.ch}/$t"
                        try {
                            if (db.library().verse(id) != null) { hit = true; break }
                        } catch (_: Exception) { }
                    }
                    if (!hit) continue
                    try {
                        val f = com.vedalibrary.app.data.local.AudioFiles.file(
                            ctx, b.id, r.song, r.ch, r.txt, if (r.ogg) ".ogg" else ".mp3")
                        f.parentFile?.mkdirs()
                        if (!f.exists()) f.writeBytes(r.content)
                        n++
                    } catch (_: Exception) { }
                    if (++done % 25 == 0) onProgress(done, total, "Аудио $type")
                }
                if (n > 0) {
                    bookIds += b.id
                    perBook += ("Аудио " + b.title.take(40)) to n
                }
                linked += n
            }
        }
        onProgress(total, total, "Аудио")
        return Result(bookIds.distinct(), linked, 0, failed, perBook)
    }

    private suspend fun importNotesDb(sq: SQLiteDatabase): Result {        var n = 0
        sq.rawQuery("SELECT book_id,txt_row_id,note,comment,startpos,endpos FROM notes LIMIT 10000", null).use { c ->
            while (c.moveToNext()) {
                val txt = c.getString(1) ?: continue
                db.library().insertNote(GeneralNote(text = listOfNotNull(c.getString(2), c.getString(3)).joinToString("\n").take(2000)))
                n++
            }
        }
        return Result(emptyList(), 0, n)
    }

    private fun hasTable(sq: SQLiteDatabase, t: String) = sq.rawQuery("SELECT 1 FROM sqlite_master WHERE name='$t' LIMIT 1", null).use { it.count > 0 }

    /** Разовый backfill PUA для книг, импортированных до fixPua на импорте.
     *  Иначе FTS индексирует кракозябры и словарь по русским книгам молчит.
     *  Карта зависит от языка книги (rus = кириллица). Идём чанками по id
     *  (только строки с PUA), FTS-триггеры переиндексируют сами. */
    suspend fun backfillPua(onProgress: (done: Int, total: Int) -> Unit = { _, _ -> }): Int =
        withContext(Dispatchers.IO) {
            val ids = try { db.library().versesWithPua() } catch (_: Exception) { return@withContext 0 }
            if (ids.isEmpty()) return@withContext 0
            var fixed = 0
            var done = 0
            ids.chunked(200).forEach { chunk ->
                val rows = try { db.library().fullVersesByIds(chunk) } catch (_: Exception) { emptyList() }
                val langs = try {
                    db.library().booksByIds(rows.map { it.bookId }.distinct())
                        .associate { it.id to it.language }
                } catch (_: Exception) { emptyMap() }
                val upd = rows.mapNotNull { v ->
                    val cyr = langs[v.bookId] == "rus"
                    fun fix(s: String) = com.vedalibrary.app.ui.components.GbHtml.fixPua(s, cyr)
                    val t = fix(v.text); val tr = v.translation?.let(::fix); val s = v.synonyms?.let(::fix)
                    val p = v.purport?.let(::fix); val sa = v.sanskrit?.let(::fix)
                    if (t == v.text && tr == v.translation && s == v.synonyms && p == v.purport && sa == v.sanskrit) null
                    else v.copy(text = t, translation = tr, synonyms = s, purport = p, sanskrit = sa)
                }
                if (upd.isNotEmpty()) {
                    try { db.library().updateVerses(upd); fixed += upd.size } catch (_: Exception) { }
                }
                done += chunk.size
                onProgress(done, ids.size)
            }
            fixed
        }
}
