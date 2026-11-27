package com.vedalibrary.app.ui.components

import android.text.SpannableStringBuilder

/**
 * Расстановщик мягких переносов (U+00AD) для рендера на ColorOS, где
 * системный hyphenationFrequency сломан (рвёт слова без дефиса).
 * Вставляется ТОЛЬКО в отображаемую копию текста; поиск и копирование не трогает.
 */
object Hyphenator {
    private const val SHY = '\u00AD'
    private const val RU_VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"
    private const val RU_SONORANT = "йрлмнЙРЛМН"
    private const val RU_NO_BREAK_BEFORE = "ьъйЬЪЙ"
    private const val EN_VOWELS = "aeiouyAEIOUY"
    private val EN_DIGRAPHS = setOf("ch", "sh", "th", "ph", "wh", "ck", "qu")

    private fun isRuLetter(c: Char): Boolean = c in 'а'..'я' || c in 'А'..'Я' || c == 'ё' || c == 'Ё'
    private fun isEnLetter(c: Char): Boolean = c in 'a'..'z' || c in 'A'..'Z'

    /** Индексы внутри [word], куда можно вставить SHY. */
    fun breakPoints(word: String): List<Int> {
        if (word.length < 5) return emptyList()
        if (word.all { isRuLetter(it) }) return breakRu(word)
        if (word.length >= 6 && word.all { isEnLetter(it) }) return breakEn(word)
        return emptyList()
    }

    private fun breakRu(w: String): List<Int> {
        val n = w.length
        val out = ArrayList<Int>(4)
        var i = 0
        // Ищем пары соседних гласных и расставляем перенос между ними
        var prevVowel = -1
        while (i < n) {
            if (w[i] in RU_VOWELS) {
                if (prevVowel >= 0) {
                    val gap = i - prevVowel - 1
                    val bp = when {
                        gap == 0 -> i // две гласные подряд: на-ука, по-эт
                        gap == 1 -> prevVowel + 1 // V-CV: го-ло-сом
                        gap == 2 -> {
                            val c2 = w[prevVowel + 2]
                            if (c2 in RU_NO_BREAK_BEFORE) prevVowel + 1 // ста-тья, пла-тье
                            else prevVowel + 2 // глав-ных, Брах-мы, воз-мож-но, ван-на
                        }
                        else -> {
                            val c1 = w[prevVowel + 1]
                            val c2 = w[prevVowel + 2]
                            val c3 = w[prevVowel + 3]
                            when {
                                c1 in RU_NO_BREAK_BEFORE -> prevVowel + 2 // воль-ство
                                c2 in RU_NO_BREAK_BEFORE -> prevVowel + 3 // кресть-ян
                                c1 in RU_SONORANT && c3 !in RU_NO_BREAK_BEFORE -> prevVowel + 3 // жерт-во, серд-це
                                else -> prevVowel + 2 // об-ще-ство, от-кры-тие
                            }
                        }
                    }
                    if (bp in 2..(n - 2) && w[bp] !in RU_NO_BREAK_BEFORE && w[bp - 1] != SHY) {
                        if (out.isEmpty() || bp - out.last() >= 2) {
                            out.add(bp)
                        }
                    }
                }
                prevVowel = i
            }
            i++
        }
        return out
    }

    private fun breakEn(w: String): List<Int> {
        val n = w.length
        val out = ArrayList<Int>(4)
        var prevVowel = -1
        for (i in 0 until n) {
            if (w[i] in EN_VOWELS) {
                if (prevVowel >= 0) {
                    val gap = i - prevVowel - 1
                    val bp = when {
                        gap <= 1 -> prevVowel + 1
                        else -> {
                            val pair = w.substring(prevVowel + 1, prevVowel + 3).lowercase()
                            if (pair in EN_DIGRAPHS) prevVowel + 1 else prevVowel + 2
                        }
                    }
                    if (bp in 2..(n - 3)) {
                        if (out.isEmpty() || bp - out.last() >= 2) {
                            out.add(bp)
                        }
                    }
                }
                prevVowel = i
            }
        }
        return out
    }

    /** Вставляет SHY в слова текста, сохраняя все спаны (для Spannable / CharSequence). */
    fun hyphenate(cs: CharSequence): CharSequence {
        if (cs.length < 5) return cs
        val ssb = SpannableStringBuilder(cs)
        // Собираем вставки (позиция в исходном тексте) и применяем справа налево,
        // чтобы не сбивать индексы и корректно сдвигать спаны.
        val inserts = ArrayList<Int>()
        var i = 0
        val n = ssb.length
        while (i < n) {
            if (ssb[i].isLetter()) {
                val start = i
                while (i < n && ssb[i].isLetter()) i++
                val word = ssb.subSequence(start, i).toString()
                for (bp in breakPoints(word)) {
                    inserts.add(start + bp)
                }
            } else {
                i++
            }
        }
        if (inserts.isEmpty()) return cs
        for (k in inserts.indices.reversed()) {
            ssb.insert(inserts[k], SHY.toString())
        }
        return ssb
    }
}
