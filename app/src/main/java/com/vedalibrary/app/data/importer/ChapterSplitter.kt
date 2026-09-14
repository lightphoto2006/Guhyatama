package com.vedalibrary.app.data.importer

import javax.inject.Inject
import javax.inject.Singleton

data class ParsedChapter(val title: String, val paragraphs: List<String>)

/**
 * Разбивка прозы/лекций на главы:
 * 1) явные маркеры: "Глава 1", "ЛЕКЦИЯ 3", "## ", "Текст 12"
 * 2) иначе — чанки по ~4000 символов с границей по абзацу (для page-by-page + TTS + карточек)
 */
@Singleton
class ChapterSplitter @Inject constructor() {
    private val marker = Regex("""^(?:глава|лекция|лекция\s*№|часть|раздел|chapter|lecture|canto|текст)\s+[\d\w\-–.]+.*$|^(?:#{1,3}\s+.+)$""", RegexOption.IGNORE_CASE)
    private val paraSplit = Regex("""\n\s*\n""")

    fun split(cleaned: String, chunkSize: Int = 4000): List<ParsedChapter> {
        val paras = cleaned.split(paraSplit).map { it.trim() }.filter { it.isNotEmpty() }
        val chapters = mutableListOf<ParsedChapter>()
        var curTitle = "Введение"
        var cur = mutableListOf<String>()
        var curLen = 0
        fun flush() { if (cur.isNotEmpty()) { chapters += ParsedChapter(curTitle, cur.toList()); cur = mutableListOf(); curLen = 0 } }
        for (p in paras) {
            val singleLine = !p.contains('\n')
            if (singleLine && (marker.matches(p.trim()) || (p.length < 80 && p == p.uppercase() && p.length > 4))) {
                flush(); curTitle = p.trim(); continue
            }
            cur += p; curLen += p.length
            if (curLen >= chunkSize) { flush(); curTitle = "Продолжение" }
        }
        flush()
        return chapters.ifEmpty { listOf(ParsedChapter("Текст", paras)) }
    }
}
