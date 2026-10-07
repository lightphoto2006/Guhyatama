package com.vedalibrary.app.data.local

import androidx.room.*
import kotlinx.serialization.Serializable

/**
 * Схема покрывает все 21 фичу читалки-книжницы:
 * Book/Chapter/Verse = библиотека + главы на санскрите + переводы (comparison via Verse.translations)
 * VerseFts = Search all books (FTS5 по sanskrit/verse/purport) + Dictionary tab
 * Highlight/Note/Tag = highlights & notes, topics & tags, nested tags, general notes
 * CrossRef = cross-references ([[СБ 1.1.1]] и ссылки из комментариев)
 * Illustration = illustrations
 * Flashcard = memory cards (SM-2)
 * BookPackage = Bookstore/пакеты .gbpkg (книги одним файлом)
 */
@Entity(tableName = "books")
data class Book(
    @PrimaryKey val id: String,
    val title: String,
    val author: String?,
    val language: String, // rus/eng/san ...
    val coverPath: String?,
    val sourceType: String, // IMPORT_PDF, IMPORT_TXT, PACKAGE
    val totalReadingMinutes: Int = 0, // reading time estimator
    val addedAt: Long = System.currentTimeMillis(),
    val isReady: Boolean = false // false пока идёт фоновый импорт (русские тома идут минутами)
)

@Entity(tableName = "chapters", foreignKeys = [ForeignKey(Book::class, ["id"], ["bookId"], onDelete = ForeignKey.CASCADE)], indices = [Index("bookId")])
data class Chapter(
    @PrimaryKey val id: String, // "$bookId/$index"
    val bookId: String,
    val index: Int,
    val title: String,
    val sanskritTitle: String? = null,
    /** Имя раздела верхнего уровня из songs.songname (темы писем); null = построить из кода */
    val songTitle: String? = null
)

@Entity(tableName = "verses", foreignKeys = [ForeignKey(Chapter::class, ["id"], ["chapterId"], onDelete = ForeignKey.CASCADE)], indices = [Index("chapterId"), Index("bookId")])
data class Verse(
    @PrimaryKey override val id: String, // "$bookId/$chapter/$number"
    val chapterId: String,
    val bookId: String,
    val number: String, // "1.1.1" или "Лекция 3, абз. 12" для лекций
    val sanskrit: String? = null, // деванагари (сырой HTML из исходной базы)
    val text: String, // транслитерация стиха / абзац лекции (сырой HTML)
    val purport: String? = null, // комментарий (сырой HTML)
    val pageLabel: String? = null, // page-by-page reading
    override val synonyms: String? = null, // пословный перевод transl1 (сырой HTML)
    override val translation: String? = null // литературный перевод transl2 (сырой HTML)
) : VerseText

/** Минимум для списков/сниппетов/похожих: id + лёгкие текстовые поля (без purport/sanskrit) */
interface VerseText {
    val id: String
    val synonyms: String?
    val translation: String?
}

/**
 * Лёгкая строка списков (главы, поиск, словарь, цитирования): JOIN books одним запросом,
 * без тяжёлых purport/sanskrit. Полный Verse грузится только по PK на экране стиха.
 */
data class VerseRow(
    override val id: String,
    val chapterId: String,
    val bookId: String,
    val number: String,
    val text: String,
    override val translation: String?,
    override val synonyms: String?,
    val bookTitle: String?,
    val bookLang: String?
) : VerseText

/** Строка поиска: VerseRow + поля FTS (sanskrit/purport) — сниппет показывает
 *  контекст в поле, где реально нашлось слово (стих/перевод/комментарий). */
data class SearchRow(
    val id: String,
    val chapterId: String,
    val bookId: String,
    val number: String,
    val text: String,
    val translation: String?,
    val synonyms: String?,
    val sanskrit: String?,
    val purport: String?,
    val bookTitle: String?,
    val bookLang: String?
)

// FTS для мгновенного офлайн-поиска (тренд: всё на устройстве, zero-network)
@Fts4(contentEntity = Verse::class)
@Entity(tableName = "verses_fts")
data class VerseFts(
    @PrimaryKey @ColumnInfo(name = "rowid") val rowId: Int,
    val sanskrit: String?,
    val text: String,
    val purport: String?,
    val synonyms: String?,
    val translation: String?
)

@Entity(tableName = "highlights", foreignKeys = [ForeignKey(Verse::class, ["id"], ["verseId"], onDelete = ForeignKey.CASCADE)], indices = [Index("verseId")])
@Serializable
data class Highlight(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val verseId: String,
    val start: Int,
    val end: Int,
    val color: Int,
    val note: String? = null,
    val createdAt: Long = System.currentTimeMillis()
)

@Entity(tableName = "tags")
@Serializable
data class Tag(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val name: String,
    val parentId: Long? = null, // nested tags: папки и подтемы
    val color: Int = 0
)

@Entity(tableName = "verse_tags", primaryKeys = ["verseId", "tagId"])
@Serializable
data class VerseTagCrossRef(val verseId: String, val tagId: Long)

@Entity(tableName = "notes")
@Serializable
data class GeneralNote(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val verseId: String? = null, // null = general notes & questions без привязки
    val text: String,
    val createdAt: Long = System.currentTimeMillis()
)

@Entity(tableName = "cross_refs", indices = [Index("fromVerseId"), Index("toVerseId")])
data class CrossRef(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val fromVerseId: String,
    val toVerseId: String, // может быть внешним: "sb/1/1/1"
    val label: String
)

@Entity(tableName = "illustrations", indices = [Index("verseId"), Index("bookId")])
data class Illustration(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val bookId: String,
    val verseId: String?, // jump to place where illustration appears
    val imagePath: String,
    val caption: String?
)

@Entity(tableName = "bookmarks", indices = [Index("bookId")])
data class Bookmark(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val bookId: String,
    val verseId: String? = null, // режим стиха: открыть стих
    val chapterId: String? = null, // режим главы: открыть главу на позиции
    val scrollIndex: Int = 0, // индекс стиха в списке главы
    val scrollOffset: Int = 0, // смещение в px
    val createdAt: Long = System.currentTimeMillis()
)

@Entity(tableName = "questions")
@Serializable
data class Question(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val verseId: String, // стих, по которому вопрос
    val verseLabel: String, // "БГ 2.11" на момент создания
    val title: String, // "О чём вопрос" — подпись в списке
    val quote: String, // выделенный кусок текста
    val text: String, // сам вопрос
    val createdAt: Long = System.currentTimeMillis()
)

@Entity(tableName = "flashcards", indices = [Index("verseId")])
@Serializable
data class Flashcard(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val verseId: String,
    val front: String,
    val back: String,
    val ease: Float = 2.5f, // SM-2
    val intervalDays: Int = 1,
    val nextReview: Long = System.currentTimeMillis(),
    val repetitions: Int = 0
)

@Dao
interface LibraryDao {
    @Query("SELECT * FROM books ORDER BY addedAt DESC") fun booksFlow(): kotlinx.coroutines.flow.Flow<List<Book>>
    @Query("SELECT * FROM chapters WHERE bookId = :bookId ORDER BY `index`") suspend fun chapters(bookId: String): List<Chapter>
    @Query("SELECT * FROM chapters WHERE id = :id") suspend fun chapter(id: String): Chapter?
    @Query("SELECT * FROM verses WHERE id = :id") suspend fun verse(id: String): Verse?
    @Query("SELECT * FROM books WHERE id = :id") suspend fun book(id: String): Book?
    /** Книги с префиксом id (чистка legacy-дублей после смены схемы bookId) */
    @Query("SELECT * FROM books WHERE id LIKE :prefix || '%'") suspend fun booksWithPrefix(prefix: String): List<Book>
    /** Число стихов по главам книги — диагностика пустоты + подписи плиток */
    data class ChapterCount(val cid: String, val n: Int)
    @Query("SELECT chapterId AS cid, COUNT(*) AS n FROM verses WHERE bookId = :bookId GROUP BY chapterId")
    suspend fun verseCounts(bookId: String): List<ChapterCount>
    /** Номера строк по главам — для честного подсчёта (сдвоенные «23-24» раскрываются) */
    data class ChapterVerseNum(val cid: String, val num: String)
    @Query("SELECT chapterId AS cid, number AS num FROM verses WHERE bookId = :bookId")
    suspend fun verseNumbers(bookId: String): List<ChapterVerseNum>

    // Search all books: фильтр по полям через FTS + книга одним JOIN (без N+1).
    // Без LIMIT: все совпадения (память под контролем — популярные слова дают
    // сотни строк, а не десятки тысяч)
    @Query("SELECT v.id AS id, v.chapterId AS chapterId, v.bookId AS bookId, v.number AS number, v.text AS text, v.translation AS translation, v.synonyms AS synonyms, v.sanskrit AS sanskrit, v.purport AS purport, b.title AS bookTitle, b.language AS bookLang FROM verses v JOIN verses_fts f ON v.rowid = f.rowid JOIN books b ON b.id = v.bookId WHERE verses_fts MATCH :q")
    suspend fun searchLight(q: String): List<SearchRow>
    /** Тот же поиск, но в одной книге (scope «В книге») */
    @Query("SELECT v.id AS id, v.chapterId AS chapterId, v.bookId AS bookId, v.number AS number, v.text AS text, v.translation AS translation, v.synonyms AS synonyms, v.sanskrit AS sanskrit, v.purport AS purport, b.title AS bookTitle, b.language AS bookLang FROM verses v JOIN verses_fts f ON v.rowid = f.rowid JOIN books b ON b.id = v.bookId WHERE verses_fts MATCH :q AND v.bookId = :bookId")
    suspend fun searchLightBook(q: String, bookId: String): List<SearchRow>

    // Dictionary tab: все стихи где встречается слово (точное совпадение токена)
    @Query("SELECT v.id AS id, v.chapterId AS chapterId, v.bookId AS bookId, v.number AS number, v.text AS text, v.translation AS translation, v.synonyms AS synonyms, b.title AS bookTitle, b.language AS bookLang FROM verses v JOIN verses_fts f ON v.rowid = f.rowid JOIN books b ON b.id = v.bookId WHERE verses_fts MATCH :token LIMIT 200")
    suspend fun dictLight(token: String): List<VerseRow>

    /** Лёгкие строки главы (без purport/sanskrit): списки, похожие, цитирования.
     *  Хвост v.rowid — детерминированный порядок при равных номерах (лекции одного стиха). */
    @Query("SELECT v.id AS id, v.chapterId AS chapterId, v.bookId AS bookId, v.number AS number, v.text AS text, v.translation AS translation, v.synonyms AS synonyms, b.title AS bookTitle, b.language AS bookLang FROM verses v JOIN books b ON b.id = v.bookId WHERE v.chapterId = :chapterId ORDER BY CAST(v.number AS REAL), LENGTH(v.number), v.number, v.rowid")
    suspend fun versesLight(chapterId: String): List<VerseRow>
    /** id стихов главы (до 2 шт): глава с единственной лекцией открывается сразу, без списка */
    @Query("SELECT id FROM verses WHERE chapterId = :chapterId LIMIT 2")
    suspend fun verseIds(chapterId: String): List<String>

    /** Одна лёгкая строка по PK (сниппеты цитирований, избранное) */
    @Query("SELECT v.id AS id, v.chapterId AS chapterId, v.bookId AS bookId, v.number AS number, v.text AS text, v.translation AS translation, v.synonyms AS synonyms, b.title AS bookTitle, b.language AS bookLang FROM verses v JOIN books b ON b.id = v.bookId WHERE v.id = :id")
    suspend fun verseLight(id: String): VerseRow?

    /** Пакет лёгких строк по id (заметки/избранное/цитирования — один запрос вместо N+1) */
    @Query("SELECT v.id AS id, v.chapterId AS chapterId, v.bookId AS bookId, v.number AS number, v.text AS text, v.translation AS translation, v.synonyms AS synonyms, b.title AS bookTitle, b.language AS bookLang FROM verses v JOIN books b ON b.id = v.bookId WHERE v.id IN (:ids)")
    suspend fun verseLightsByIds(ids: List<String>): List<VerseRow>

    @Query("SELECT * FROM books WHERE id IN (:ids)") suspend fun booksByIds(ids: List<String>): List<Book>

    @Query("SELECT COUNT(*) FROM verses WHERE bookId = :bookId") suspend fun countVerses(bookId: String): Int
    /** Сколько стихов в каждой книге — одним запросом вместо N countVerses (обновление списка книг) */
    data class BookVerseCount(val bookId: String, val n: Int)
    @Query("SELECT bookId, COUNT(*) AS n FROM verses GROUP BY bookId")
    suspend fun verseCountsByBook(): List<BookVerseCount>
    /** Точная лёгкая строка по номеру внутри главы (открытие лекции по подписи — без загрузки главы) */
    @Query("SELECT v.id AS id, v.chapterId AS chapterId, v.bookId AS bookId, v.number AS number, v.text AS text, v.translation AS translation, v.synonyms AS synonyms, b.title AS bookTitle, b.language AS bookLang FROM verses v JOIN books b ON b.id = v.bookId WHERE v.chapterId = :chapterId AND v.number = :number ORDER BY v.rowid LIMIT 1")
    suspend fun verseLightByNumber(chapterId: String, number: String): VerseRow?
    /** (id, номер) всех строк главы в порядке стихов — только для выбора диапазона («34-35») */
    data class VerseNumId(val id: String, val number: String)
    @Query("SELECT id, number FROM verses WHERE chapterId = :chapterId ORDER BY CAST(number AS REAL), LENGTH(number), number, rowid")
    suspend fun verseNumIds(chapterId: String): List<VerseNumId>
    /** id краёв главы (соседняя глава при поиске) — без загрузки строк */
    @Query("SELECT id FROM verses WHERE chapterId = :chapterId ORDER BY CAST(number AS REAL), LENGTH(number), number, rowid LIMIT 1")
    suspend fun firstVerseId(chapterId: String): String?
    @Query("SELECT id FROM verses WHERE chapterId = :chapterId ORDER BY CAST(number AS REAL) DESC, LENGTH(number) DESC, number DESC, rowid DESC LIMIT 1")
    suspend fun lastVerseId(chapterId: String): String?
    /** id из списка (чанки ≤500): импорт аудио определяет попадания, не читая blob'ы */
    @Query("SELECT id FROM verses WHERE id IN (:ids)")
    suspend fun verseIdsIn(ids: List<String>): List<String>
    @Query("SELECT * FROM verses WHERE bookId = :bookId LIMIT 1 OFFSET :offset") suspend fun verseAtOffset(bookId: String, offset: Int): Verse?
    /** Цитата на код лекции/текста без главы (пустой refbyChapter): ищем по номеру в книге */
    @Query("SELECT * FROM verses WHERE bookId = :bookId AND number = :number LIMIT 1")
    suspend fun verseByBookAndNumber(bookId: String, number: String): Verse?
    /** Полные строки батчем (PUA-backfill): лёгких проекций мало — нужны все 5 текстовых полей */
    @Query("SELECT * FROM verses WHERE id IN (:ids)") suspend fun fullVersesByIds(ids: List<String>): List<Verse>
    @Update suspend fun updateVerses(v: List<Verse>)
    /** id стихов с символами шрифта-иконок исходных баз (U+E000–U+F8FF) — GLOB по диапазону работает на UTF-8 */
    @Query("SELECT id FROM verses WHERE text GLOB '*[' || char(57344) || '-' || char(63743) || ']*' OR translation GLOB '*[' || char(57344) || '-' || char(63743) || ']*' OR synonyms GLOB '*[' || char(57344) || '-' || char(63743) || ']*' OR purport GLOB '*[' || char(57344) || '-' || char(63743) || ']*' OR sanskrit GLOB '*[' || char(57344) || '-' || char(63743) || ']*'")
    suspend fun versesWithPua(): List<String>

    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun upsertBooks(b: List<Book>)
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun upsertChapters(c: List<Chapter>)
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun upsertVerses(v: List<Verse>)
    @Insert suspend fun insertHighlight(h: Highlight): Long
    @Insert suspend fun insertNote(n: GeneralNote): Long
    @Insert suspend fun insertTag(t: Tag): Long
    @Insert suspend fun linkTag(x: VerseTagCrossRef)
    /** Батчи для восстановления бэкапа — одна транзакция вместо N */
    @Insert suspend fun insertHighlights(l: List<Highlight>)
    @Insert suspend fun insertNotes(l: List<GeneralNote>)
    @Insert suspend fun insertQuestions(l: List<Question>)
    @Insert suspend fun insertTags(l: List<Tag>)
    @Insert suspend fun insertFlashcards(l: List<Flashcard>)
    @Insert suspend fun linkTags(l: List<VerseTagCrossRef>)
    @Query("SELECT * FROM highlights") suspend fun highlightsAll(): List<Highlight>
    @Query("SELECT * FROM notes") suspend fun notesAll(): List<GeneralNote>
    @Query("SELECT * FROM tags") suspend fun tagsAll(): List<Tag>
    @Query("SELECT * FROM verse_tags") suspend fun verseTagsAll(): List<VerseTagCrossRef>
    @Query("SELECT * FROM flashcards") suspend fun flashcardsAll(): List<Flashcard>
    @Query("SELECT * FROM questions") suspend fun questionsAll(): List<Question>

    /** Восстановление бэкапа — одна транзакция, ИДЕМПОТЕНТНО:
     *  1) дубли по естественному ключу пропускаются (повторный restore того же
     *     файла ничего не удваивает);
     *  2) теги резолвятся по (name, parentId): существующий — используем его id,
     *     новый — вставляем; ссылки verse_tags переносятся через маппинг
     *     старый-id → фактический-id (раньше ссылки указывали на id чужой БД,
     *     а повтор падал на PK verse_tags и откатывал всю транзакцию);
     *  3) ошибки НЕ глотаются — исключение уходит вызывающему в статус.
     *  Возвращает (добавлено, пропущено как дубли). */
    @Transaction
    suspend fun importBackupData(
        h: List<Highlight>, n: List<GeneralNote>, t: List<Tag>,
        c: List<Flashcard>, l: List<VerseTagCrossRef>, q: List<Question> = emptyList()
    ): Pair<Int, Int> {
        var added = 0
        var skipped = 0

        // Подсветки: ключ (verseId, start, end, color, note). FK на verses —
        // подсветки без книги упадут честной ошибкой (сначала ставим книги)
        val hKeys = highlightsAll()
            .map { "${it.verseId}|${it.start}|${it.end}|${it.color}|${it.note}" }.toHashSet()
        val hNew = h.filter { hKeys.add("${it.verseId}|${it.start}|${it.end}|${it.color}|${it.note}") }
        added += hNew.size; skipped += h.size - hNew.size
        if (hNew.isNotEmpty()) insertHighlights(hNew)

        // Заметки: ключ (verseId, text)
        val nKeys = notesAll().map { "${it.verseId}|${it.text}" }.toHashSet()
        val nNew = n.filter { nKeys.add("${it.verseId}|${it.text}") }
        added += nNew.size; skipped += n.size - nNew.size
        if (nNew.isNotEmpty()) insertNotes(nNew)

        // Теги: резолв id (старый id бэкапа → существующий или свежевставленный)
        val idMap = HashMap<Long, Long>()
        val byKey = HashMap<String, Tag>()
        for (tg in tagsAll()) byKey["${tg.name}|${tg.parentId}"] = tg
        for (tg in t) {
            val key = "${tg.name}|${tg.parentId}"
            val hit = byKey[key]
            if (hit != null) {
                idMap[tg.id] = hit.id
                skipped++
            } else {
                val newId = insertTag(tg.copy(id = 0))
                byKey[key] = tg.copy(id = newId)
                idMap[tg.id] = newId
                added++
            }
        }

        // Ссылки: только через маппинг тегов, без сирот на чужие id.
        // Неразрешённый tagId (тега нет в бэкапе/БД) молча пропускается
        val lKeys = verseTagsAll().map { "${it.verseId}|${it.tagId}" }.toHashSet()
        val lNew = ArrayList<VerseTagCrossRef>()
        for (link in l) {
            val resolved = idMap[link.tagId] ?: continue
            if (lKeys.add("${link.verseId}|$resolved")) lNew += VerseTagCrossRef(link.verseId, resolved)
        }
        added += lNew.size
        skipped += l.size - lNew.size
        if (lNew.isNotEmpty()) linkTags(lNew)

        // Карточки: ключ (verseId, front, back) — прогресс существующих не трогаем
        val cKeys = flashcardsAll().map { "${it.verseId}|${it.front}|${it.back}" }.toHashSet()
        val cNew = c.filter { cKeys.add("${it.verseId}|${it.front}|${it.back}") }
        added += cNew.size; skipped += c.size - cNew.size
        if (cNew.isNotEmpty()) insertFlashcards(cNew)

        // Вопросы: ключ (verseId, title, quote, text)
        val qKeys = questionsAll().map { "${it.verseId}|${it.title}|${it.quote}|${it.text}" }.toHashSet()
        val qNew = q.filter { qKeys.add("${it.verseId}|${it.title}|${it.quote}|${it.text}") }
        added += qNew.size; skipped += q.size - qNew.size
        if (qNew.isNotEmpty()) insertQuestions(qNew)

        return added to skipped
    }

    /** Полное удаление книги — ОДНА транзакция: раньше шесть отдельных DELETE'ов
     *  без обёртки оставляли при падении полукнигу-сироту (стихи без книги,
     *  главы без стихов). Тип для deleteRefsFrom берётся из id, как и раньше. */
    @Transaction
    suspend fun deleteBookCascade(bookId: String) {
        deleteVersesOfBook(bookId)
        deleteChaptersOfBook(bookId)
        deleteIllustrationsOfBook(bookId)
        deleteRefsFrom(bookId, bookId.split("-").getOrNull(1)?.uppercase() ?: "")
        deleteBookmarksOfBook(bookId)
        deleteBookRow(bookId)
    }

    /** Закладка книги (строка ровно одна): атомарная замена — раньше
     *  delete+insert шли отдельными запросами, падение посреди оставляло
     *  книгу вообще без закладки. */
    @Transaction
    suspend fun replaceBookmark(b: Bookmark) {
        deleteBookmarksOfBook(b.bookId)
        insertBookmark(b)
    }
    @Insert suspend fun insertCrossRefs(r: List<CrossRef>)
    @Insert suspend fun insertIllustrations(i: List<Illustration>)
    /** Закладки: одна на книгу (последняя побеждает) */
    @Insert suspend fun insertBookmark(b: Bookmark): Long
    @Query("DELETE FROM bookmarks WHERE bookId = :bookId") suspend fun deleteBookmarksOfBook(bookId: String)
    @Query("SELECT * FROM bookmarks WHERE bookId = :bookId LIMIT 1") suspend fun bookmark(bookId: String): Bookmark?
    @Query("SELECT * FROM bookmarks WHERE bookId = :bookId LIMIT 1") fun bookmarkFlow(bookId: String): kotlinx.coroutines.flow.Flow<Bookmark?>
    @Query("SELECT bookId FROM bookmarks") fun bookmarkedBooks(): kotlinx.coroutines.flow.Flow<List<String>>
    @Query("SELECT * FROM illustrations WHERE bookId = :bookId") suspend fun illustrations(bookId: String): List<Illustration>
    /** Первая картинка книги — миниатюра для сетки библиотеки */
    @Query("SELECT * FROM illustrations WHERE bookId = :bookId ORDER BY id LIMIT 1") suspend fun firstIllustration(bookId: String): Illustration?
    @Insert suspend fun insertFlashcard(f: Flashcard): Long
    /** Избранное: все карточки, новые сверху */
    @Query("SELECT * FROM flashcards ORDER BY id DESC") fun flashcardsFlow(): kotlinx.coroutines.flow.Flow<List<Flashcard>>
    @Query("SELECT id FROM flashcards WHERE verseId = :verseId LIMIT 1") suspend fun flashcardIdFor(verseId: String): Long?
    @Query("DELETE FROM flashcards WHERE id = :id") suspend fun deleteFlashcard(id: Long)
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun upsertIllustrations(i: List<Illustration>)
    @Query("DELETE FROM verses WHERE bookId = :bookId") suspend fun deleteVersesOfBook(bookId: String)
    /** Все книги разом — для сверки с каталогом (усыновление уже стоящих) */
    @Query("SELECT * FROM books") suspend fun booksAll(): List<Book>
    @Query("DELETE FROM chapters WHERE bookId = :bookId") suspend fun deleteChaptersOfBook(bookId: String)
    @Query("DELETE FROM illustrations WHERE bookId = :bookId") suspend fun deleteIllustrationsOfBook(bookId: String)
    @Query("DELETE FROM cross_refs WHERE fromVerseId LIKE :bookId || '/%' ESCAPE '\\' OR toVerseId LIKE :bookId || '/%' ESCAPE '\\' OR fromVerseId LIKE 'ext:' || :typePart || '/%'")
    suspend fun deleteRefsFrom(bookId: String, typePart: String = "")
    @Query("DELETE FROM books WHERE id = :bookId") suspend fun deleteBookRow(bookId: String)
    /** Помечает книгу готовой БЕЗ REPLACE (REPLACE сносит главы/стихи через FK CASCADE). */
    @Query("UPDATE books SET totalReadingMinutes = :minutes, isReady = 1 WHERE id = :bookId")
    suspend fun markBookReady(bookId: String, minutes: Int)
    /** Дельта: правка названия/автора без REPLACE (REPLACE строки books сносит
     *  главы/стихи через FK CASCADE) — isReady/минуты/обложка не трогаются. */
    @Query("UPDATE books SET title = :title, author = :author WHERE id = :bookId")
    suspend fun updateBookMeta(bookId: String, title: String, author: String?)
    /** Дельта: правка заголовка главы без REPLACE (REPLACE строки chapters
     *  CASCADE-ом снёс бы все стихи главы). songTitle не трогаем — в дельте
     *  таблица songs неполная. */
    @Query("UPDATE chapters SET title = :title WHERE id = :id")
    suspend fun updateChapterTitle(id: String, title: String)
    /** Разовый ремонт: лекции Шьямакунды, импортированные как eng
     *  (имя файла без rus), — переводим в rus, иначе фильтр EN/RU врёт. */
    @Query("UPDATE books SET language = 'rus' WHERE language = 'eng' AND (id LIKE 'gb-scc-%' OR id LIKE 'gb-ssb-%' OR id LIKE 'gb-sbg-%')")
    suspend fun fixLectureLang(): Int
    /** Обложка книги (файл cover.jpg из тулзы dbcomposer, таблица covers в .db) */
    @Query("UPDATE books SET coverPath = :path WHERE id = :bookId")
    suspend fun setCover(bookId: String, path: String)
    /** Все заметки (включая «В заметку» из выделения), новые сверху */
    @Query("SELECT * FROM notes ORDER BY createdAt DESC") fun notesFlow(): kotlinx.coroutines.flow.Flow<List<GeneralNote>>
    @Query("DELETE FROM notes WHERE id = :id") suspend fun deleteNote(id: Long)
    /** Вопросы по стихам: нумерованный список в порядке создания */
    @Query("SELECT * FROM questions ORDER BY createdAt ASC") fun questionsFlow(): kotlinx.coroutines.flow.Flow<List<Question>>
    @Query("SELECT * FROM questions WHERE id = :id") suspend fun question(id: Long): Question?
    @Insert suspend fun insertQuestion(q: Question): Long
    @Update suspend fun updateQuestion(q: Question)
    @Query("DELETE FROM questions WHERE id = :id") suspend fun deleteQuestion(id: Long)
    /** Связанные: стихи, в чьих комментариях упомянут данный (обратные ссылки textrefs) */
    @Query("SELECT * FROM cross_refs WHERE toVerseId = :to") suspend fun incomingRefs(to: String): List<CrossRef>
    /** Строки, где стих — цитируемый кодом (цитирующий конкретным id) */
    @Query("SELECT * FROM cross_refs WHERE fromVerseId = :code") suspend fun refsFromCode(code: String): List<CrossRef>
    /** Строки, где стих — цитируемый конкретным id */
    @Query("SELECT * FROM cross_refs WHERE toVerseId = :id") suspend fun refsToVerse(id: String): List<CrossRef>
    /** Исходящие ссылки стиха */
    @Query("SELECT * FROM cross_refs WHERE fromVerseId = :from") suspend fun outgoingRefs(from: String): List<CrossRef>
    /** Книги по коду типа (gb-bg-...): для разрешения ссылок между томами */
    @Query("SELECT * FROM books WHERE id LIKE 'gb-' || :type || '-%'") suspend fun booksByType(type: String): List<Book>
    /** Книги по префиксу типа (bg -> bg, bg72, bg-s...): раздача аудио по изданиям */
    @Query("SELECT * FROM books WHERE id LIKE 'gb-' || :type || '%'") suspend fun booksByTypePrefix(type: String): List<Book>
    /** Тот же стих в книге того же произведения, но на другом языке (кнопка Перевод) */
    @Query("SELECT v.* FROM verses v JOIN books b ON b.id = v.bookId WHERE b.id LIKE 'gb-' || :type || '-%' AND b.language != :lang AND v.id LIKE '%/' || :song || '/' || :ch || '/' || :txt ESCAPE '\\' LIMIT 5")
    suspend fun findSameVerseOtherLang(type: String, lang: String, song: String, ch: String, txt: String): List<Verse>
}

@Database(
    entities = [Book::class, Chapter::class, Verse::class, VerseFts::class, Highlight::class, Tag::class, VerseTagCrossRef::class, GeneralNote::class, CrossRef::class, Illustration::class, Flashcard::class, Bookmark::class, Question::class],
    version = 10, exportSchema = true
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun library(): LibraryDao

    companion object {
        /** v3 -> v4: только новая таблица закладок, данные не трогаем */
        val MIGRATION_3_4 = object : androidx.room.migration.Migration(3, 4) {
            override fun migrate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                db.execSQL("CREATE TABLE IF NOT EXISTS `bookmarks` (`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, `bookId` TEXT NOT NULL, `verseId` TEXT, `chapterId` TEXT, `scrollIndex` INTEGER NOT NULL, `scrollOffset` INTEGER NOT NULL, `createdAt` INTEGER NOT NULL)")
            }
        }
        /** v4 -> v5: индексы bookId (имена — как генерирует Room: index_<таблица>_<колонка>) */
        val MIGRATION_4_5 = object : androidx.room.migration.Migration(4, 5) {
            override fun migrate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_verses_bookId` ON `verses` (`bookId`)")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_illustrations_bookId` ON `illustrations` (`bookId`)")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_bookmarks_bookId` ON `bookmarks` (`bookId`)")
            }
        }
        /** v5 -> v6: имя раздела верхнего уровня (темы писем из songs.songname) */
        val MIGRATION_5_6 = object : androidx.room.migration.Migration(5, 6) {
            override fun migrate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE `chapters` ADD COLUMN `songTitle` TEXT")
            }
        }
        /** v6 -> v7: вопросы по стихам */
        val MIGRATION_6_7 = object : androidx.room.migration.Migration(6, 7) {
            override fun migrate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                db.execSQL("CREATE TABLE IF NOT EXISTS `questions` (`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, `verseId` TEXT NOT NULL, `verseLabel` TEXT NOT NULL, `title` TEXT NOT NULL, `quote` TEXT NOT NULL, `text` TEXT NOT NULL, `createdAt` INTEGER NOT NULL)")
            }
        }
        /** v7 -> v8: переименование типа источника (никаких gitabase-имён) */
        val MIGRATION_7_8 = object : androidx.room.migration.Migration(7, 8) {
            override fun migrate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                db.execSQL("UPDATE books SET sourceType = 'LIBRARY_DB' WHERE sourceType = 'GITABASE_DB'")
            }
        }
        /** v8 -> v9: строки-галереи («Иллюстрации…» вместо стиха): удалить сами строки
         *  и всё, что на них ссылалось (иначе висят сироты). Настоящие стихи, главы,
         *  книги, заметки, вопросы, карточки и закладки не трогаем — только мусор.
         *  FTS-синхронизация — триггерами Room, сами ничего не чистим */
        val MIGRATION_8_9 = object : androidx.room.migration.Migration(8, 9) {
            override fun migrate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                db.execSQL(
                    "CREATE TEMP TABLE IF NOT EXISTS _gal AS " +
                            "SELECT id FROM verses WHERE number IN ('0','') AND (" +
                            "translation LIKE 'Иллюстрац%' OR translation LIKE 'иллюстрац%' OR " +
                            "translation LIKE 'Illustration%' OR translation LIKE 'illustration%')"
                )
                db.execSQL("DELETE FROM flashcards WHERE verseId IN (SELECT id FROM _gal)")
                db.execSQL("DELETE FROM notes WHERE verseId IN (SELECT id FROM _gal)")
                db.execSQL("DELETE FROM questions WHERE verseId IN (SELECT id FROM _gal)")
                db.execSQL("DELETE FROM highlights WHERE verseId IN (SELECT id FROM _gal)")
                db.execSQL("DELETE FROM verse_tags WHERE verseId IN (SELECT id FROM _gal)")
                db.execSQL("DELETE FROM bookmarks WHERE verseId IN (SELECT id FROM _gal)")
                db.execSQL("DELETE FROM verses WHERE id IN (SELECT id FROM _gal)")
                db.execSQL("DROP TABLE _gal")
            }
        }
        /** v9 -> v10: переворот legacy-строк цитат в единую раскладку
         *  (from = цитирующий, to = цитируемый — как у TXT-импортов и патчей).
         *  Было: from = цитируемый конкретный id, to = цитирующий ext:-код
         *  (thisBook — цитируемый, refbyBook — цитирующий). Стало: наоборот.
         *  Чистый SWAP колонок по маске строк (TXT-строки без ext: не трогаем).
         *  Идемпотентно: перевёрнутые (from LIKE 'ext:%') маске не соответствуют. */
        val MIGRATION_9_10 = object : androidx.room.migration.Migration(9, 10) {
            override fun migrate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                db.execSQL(
                    "UPDATE cross_refs SET fromVerseId = toVerseId, toVerseId = fromVerseId" +
                            " WHERE toVerseId LIKE 'ext:%' AND fromVerseId NOT LIKE 'ext:%'"
                )
            }
        }
    }
}
