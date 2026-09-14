package com.vedalibrary.app.data.backup

import com.vedalibrary.app.data.local.*
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.InputStream
import java.io.OutputStream
import javax.inject.Inject
import javax.inject.Singleton
import android.content.Context

@Serializable
data class NotesBackup(
    val v: Int = 2,
    val highlights: List<Highlight> = emptyList(),
    val notes: List<GeneralNote> = emptyList(),
    val tags: List<Tag> = emptyList(),
    val links: List<VerseTagCrossRef> = emptyList(),
    val cards: List<Flashcard> = emptyList(),
    val questions: List<Question> = emptyList()
)

/** Бэкап заметок/тем/карточек в JSON (экспорт/импорт через SAF + авто-копия) */
@Singleton
class BackupManager @Inject constructor(
    private val db: AppDatabase,
    @ApplicationContext private val ctx: Context
) {
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

    suspend fun exportTo(out: OutputStream) = withContext(Dispatchers.IO) {
        out.bufferedWriter().use { it.write(json.encodeToString(exportAll())) }
    }

    /** Восстановление одним батчем в транзакции (без N round-trip'ов) */
    suspend fun importFrom(inp: InputStream): String = withContext(Dispatchers.IO) {
        val b = json.decodeFromString<NotesBackup>(inp.bufferedReader().readText())
        val h = b.highlights.map { it.copy(id = 0) }
        val n = b.notes.map { it.copy(id = 0) }
        val t = b.tags.map { it.copy(id = 0) }
        val c = b.cards.map { it.copy(id = 0) }
        val q = b.questions.map { it.copy(id = 0) }
        try {
            db.library().importBackupData(h, n, t, c, b.links, q)
        } catch (_: Exception) { }
        "Восстановлено записей: ${h.size + n.size + t.size + c.size + b.links.size + q.size}"
    }

    private suspend fun exportAll(): NotesBackup {
        // Room без DAO-листинга: используем низкоуровневый доступ через openHelper
        val h = db.openHelper.readableDatabase
        fun <T> read(sql: String, map: (android.database.Cursor) -> T): List<T> {
            val out = mutableListOf<T>()
            h.query(sql).use { c -> while (c.moveToNext()) out += map(c) }
            return out
        }
        val highlights = read("SELECT verseId,[start],[end],color,note FROM highlights") {
            Highlight(verseId = it.getString(0), start = it.getInt(1), end = it.getInt(2), color = it.getInt(3), note = it.getString(4))
        }
        val notes = read("SELECT verseId,text FROM notes") {
            GeneralNote(verseId = it.getString(0), text = it.getString(1) ?: "")
        }
        val tags = read("SELECT name,parentId,color FROM tags") {
            Tag(name = it.getString(0) ?: "", parentId = if (it.isNull(1)) null else it.getLong(1), color = it.getInt(2))
        }
        val links = read("SELECT verseId,tagId FROM verse_tags") {
            VerseTagCrossRef(it.getString(0), it.getLong(1))
        }
        val cards = read("SELECT verseId,front,back,ease,intervalDays,nextReview,repetitions FROM flashcards") {
            Flashcard(verseId = it.getString(0), front = it.getString(1) ?: "", back = it.getString(2) ?: "", ease = it.getFloat(3), intervalDays = it.getInt(4), nextReview = it.getLong(5), repetitions = it.getInt(6))
        }
        val questions = try {
            read("SELECT verseId,verseLabel,title,quote,text FROM questions") {
                Question(verseId = it.getString(0) ?: "", verseLabel = it.getString(1) ?: "",
                    title = it.getString(2) ?: "", quote = it.getString(3) ?: "", text = it.getString(4) ?: "")
            }
        } catch (_: Exception) { emptyList() }
        return NotesBackup(highlights = highlights, notes = notes, tags = tags, links = links, cards = cards, questions = questions)
    }
}
