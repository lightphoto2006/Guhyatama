package com.vedalibrary.app.data.importer

import android.content.Context
import android.net.Uri
import com.vedalibrary.app.data.local.*
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Импорт TXT/MD: файл -> Book + Chapters + Verses (абзац = Verse, number = "абз. N").
 * Оценка времени чтения: ~150 слов/мин для русского.
 */
@Singleton
class TxtImporter @Inject constructor(
    @ApplicationContext private val ctx: Context,
    private val cleaner: TextCleaner,
    private val splitter: ChapterSplitter,
    private val db: AppDatabase
) {
    companion object {
        private val WS_RE = Regex("""\s+""")
    }
    suspend fun import(uri: Uri, titleHint: String? = null): String = withContext(Dispatchers.IO) {
        val raw = ctx.contentResolver.openInputStream(uri)!!.bufferedReader().readText()
        importText(raw, titleHint ?: "Импорт TXT")
    }

    suspend fun importText(raw: String, title: String): String {
        val cleaned = cleaner.clean(raw)
        val parsed = splitter.split(cleaned)
        val bookId = "import-" + UUID.randomUUID().toString().take(8)
        val words = if (cleaned.isBlank()) 0 else cleaned.count { it.isWhitespace() } + 1
        db.library().upsertBooks(listOf(Book(bookId, title, null, "rus", null, "IMPORT_TXT", words / 150, System.currentTimeMillis(), false)))
        val chapters = parsed.mapIndexed { i, c -> Chapter("$bookId/$i", bookId, i, c.title) }
        db.library().upsertChapters(chapters)
        val verses = parsed.flatMapIndexed { ci, c ->
            c.paragraphs.mapIndexed { pi, p ->
                Verse("$bookId/$ci/$pi", "$bookId/$ci", bookId, "абз. ${pi + 1}", null, p.take(2000), p, "стр. ${pi + 1}")
            }
        }
        // Batch-вставки чанками по 500 для оптимизации
        verses.chunked(500).forEach { db.library().upsertVerses(it) }
        extractCrossRefs(verses)
        db.library().markBookReady(bookId, words / 150)
        return bookId
    }

    // Кросс-ссылки вида [[СБ 1.2.3]] или "см. БГ 2.13"
    private suspend fun extractCrossRefs(verses: List<Verse>) {
        val re = Regex("""\[\[([^\]]+)]]|(?:см\.?\s+)?\b([БB]Г|[СS]Б|ШБ)\s+(\d+[.\-–]\d+[.\-–]?\d*)""")
        val refs = mutableListOf<CrossRef>()
        for (v in verses) {
            val text = (v.text + "\n" + (v.purport ?: "")).take(8000)
            re.findAll(text).forEach { m -> refs += CrossRef(fromVerseId = v.id, toVerseId = m.value, label = m.value) }
        }
        if (refs.isNotEmpty()) db.library().insertCrossRefs(refs)
    }
}
