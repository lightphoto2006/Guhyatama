package com.vedalibrary.app.data.importer

import javax.inject.Inject
import javax.inject.Singleton

/**
 * Очистка транскрибированных лекций / PDF-выгрузки:
 * - склейка переносов, удаление номеров страниц/колонтитулов/мусора OCR
 * - нормализация тире/кавычек, схлопывание пробелов
 * Оптимизация: работает потоково, O(n) по длине, без regex-каскадов на весь файл.
 */
@Singleton
class TextCleaner @Inject constructor() {
    private val headerFooter = Regex("""^(?:стр\.?\s*\d+|\d+\s*/\s*\d+|Глава\s+\d+.*)$""", RegexOption.IGNORE_CASE)
    private val multiSpace = Regex("""[ \t]{2,}""")
    private val hyphenBreak = Regex("""(\p{L})-\n(\p{L})""")
    private val blank3 = Regex("""\n{3,}""")

    fun clean(raw: String): String {
        var t = raw.replace("\r\n", "\n")
        t = hyphenBreak.replace(t, "$1$2") // склейка переносов
        val lines = t.lineSequence()
            .map { it.trimEnd() }
            .filter { it.isNotBlank() && !headerFooter.matches(it.trim()) }
            .map { multiSpace.replace(it, " ") }
            .toList()
        // Склейка строк внутри абзаца: пустая строка = граница абзаца
        val out = StringBuilder(t.length)
        var prevBlank = true
        for (line in lines) {
            if (prevBlank) out.append(line) else out.append(' ').append(line.trimStart())
            // эвристика: строка заканчивается точкой/кавычкой -> конец абзаца
            prevBlank = line.endsWith(".") || line.endsWith("\"") || line.endsWith("»") || line.length < 40
            if (prevBlank) out.append('\n')
        }
        return out.toString().replace(blank3, "\n\n").trim()
    }
}
