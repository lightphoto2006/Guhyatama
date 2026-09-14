package com.vedalibrary.app.data.local

import androidx.room.*
import kotlinx.serialization.Serializable

/**
 * Схема покрывает все 21 фичу Gitabase:
 * Book/Chapter/Verse = библиотека + главы на санскрите + переводы (comparison via Verse.translations)
 * VerseFts = Search all books (FTS5 по sanskrit/verse/purport) + Dictionary tab
 * Highlight/Note/Tag = highlights & notes, topics & tags, nested tags, general notes
 * CrossRef = cross-references ([[СБ 1.1.1]] и ссылки из комментариев)
 * Illustration = illustrations
 * Flashcard = memory cards (SM-2)
 * BookPackage = Bookstore/пакеты .gbpkg (аналог .db у Gitabase)
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
    val sanskrit: String? = null, // деванагари (сырой HTML из Gitabase)
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

    // Search all books: фильтр по полям через FTS + книга одним JOIN (без N+1)
    @Query("SELECT v.id AS id, v.chapterId AS chapterId, v.bookId AS bookId, v.number AS number, v.text AS text, v.translation AS translation, v.synonyms AS synonyms, b.title AS bookTitle, b.language AS bookLang FROM verses v JOIN verses_fts f ON v.rowid = f.rowid JOIN books b ON b.id = v.bookId WHERE verses_fts MATCH :q LIMIT :limit")
    suspend fun searchLight(q: String, limit: Int = 200): List<VerseRow>

    // Dictionary tab: все стихи где встречается слово (точное совпадение токена)
    @Query("SELECT v.id AS id, v.chapterId AS chapterId, v.bookId AS bookId, v.number AS number, v.text AS text, v.translation AS translation, v.synonyms AS synonyms, b.title AS bookTitle, b.language AS bookLang FROM verses v JOIN verses_fts f ON v.rowid = f.rowid JOIN books b ON b.id = v.bookId WHERE verses_fts MATCH :token LIMIT 200")
    suspend fun dictLight(token: String): List<VerseRow>

    /** Лёгкие строки главы (без purport/sanskrit): списки, похожие, цитирования */
    @Query("SELECT v.id AS id, v.chapterId AS chapterId, v.bookId AS bookId, v.number AS number, v.text AS text, v.translation AS translation, v.synonyms AS synonyms, b.title AS bookTitle, b.language AS bookLang FROM verses v JOIN books b ON b.id = v.bookId WHERE v.chapterId = :chapterId ORDER BY CAST(v.number AS REAL), LENGTH(v.number), v.number")
    suspend fun versesLight(chapterId: String): List<VerseRow>

    /** Одна лёгкая строка по PK (сниппеты цитирований, избранное) */
    @Query("SELECT v.id AS id, v.chapterId AS chapterId, v.bookId AS bookId, v.number AS number, v.text AS text, v.translation AS translation, v.synonyms AS synonyms, b.title AS bookTitle, b.language AS bookLang FROM verses v JOIN books b ON b.id = v.bookId WHERE v.id = :id")
    suspend fun verseLight(id: String): VerseRow?

    /** Пакет лёгких строк по id (заметки/избранное/цитирования — один запрос вместо N+1) */
    @Query("SELECT v.id AS id, v.chapterId AS chapterId, v.bookId AS bookId, v.number AS number, v.text AS text, v.translation AS translation, v.synonyms AS synonyms, b.title AS bookTitle, b.language AS bookLang FROM verses v JOIN books b ON b.id = v.bookId WHERE v.id IN (:ids)")
    suspend fun verseLightsByIds(ids: List<String>): List<VerseRow>

    @Query("SELECT * FROM books WHERE id IN (:ids)") suspend fun booksByIds(ids: List<String>): List<Book>

    @Query("SELECT COUNT(*) FROM verses WHERE bookId = :bookId") suspend fun countVerses(bookId: String): Int
    @Query("SELECT * FROM verses WHERE bookId = :bookId LIMIT 1 OFFSET :offset") suspend fun verseAtOffset(bookId: String, offset: Int): Verse?
    /** Цитата на код лекции/текста без главы (пустой refbyChapter): ищем по номеру в книге */
    @Query("SELECT * FROM verses WHERE bookId = :bookId AND number = :number LIMIT 1")
    suspend fun verseByBookAndNumber(bookId: String, number: String): Verse?
    /** Полные строки батчем (PUA-backfill): лёгких проекций мало — нужны все 5 текстовых полей */
    @Query("SELECT * FROM verses WHERE id IN (:ids)") suspend fun fullVersesByIds(ids: List<String>): List<Verse>
    @Update suspend fun updateVerses(v: List<Verse>)
    /** id стихов с символами PUA-шрифта Gitabase (U+E000–U+F8FF) — GLOB по диапазону работает на UTF-8 */
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
    @Transaction
    suspend fun importBackupData(
        h: List<Highlight>, n: List<GeneralNote>, t: List<Tag>,
        c: List<Flashcard>, l: List<VerseTagCrossRef>, q: List<Question> = emptyList()
    ) {
        if (h.isNotEmpty()) insertHighlights(h)
        if (n.isNotEmpty()) insertNotes(n)
        if (t.isNotEmpty()) insertTags(t)
        if (c.isNotEmpty()) insertFlashcards(c)
        if (l.isNotEmpty()) linkTags(l)
        if (q.isNotEmpty()) insertQuestions(q)
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
    @Query("DELETE FROM chapters WHERE bookId = :bookId") suspend fun deleteChaptersOfBook(bookId: String)
    @Query("DELETE FROM illustrations WHERE bookId = :bookId") suspend fun deleteIllustrationsOfBook(bookId: String)
    @Query("DELETE FROM cross_refs WHERE fromVerseId LIKE :bookId || '/%' ESCAPE '\\'") suspend fun deleteRefsFrom(bookId: String)
    @Query("DELETE FROM books WHERE id = :bookId") suspend fun deleteBookRow(bookId: String)
    /** Помечает книгу готовой БЕЗ REPLACE (REPLACE сносит главы/стихи через FK CASCADE). */
    @Query("UPDATE books SET totalReadingMinutes = :minutes, isReady = 1 WHERE id = :bookId")
    suspend fun markBookReady(bookId: String, minutes: Int)
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
    version = 7, exportSchema = false
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
    }
}
