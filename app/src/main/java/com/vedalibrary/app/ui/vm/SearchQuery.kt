package com.vedalibrary.app.ui.vm

import com.vedalibrary.app.ui.components.GbHtml
import java.text.Normalizer

/**
 * Разбор поискового запроса и сборка MATCH-выражения для FTS.
 *
 * Почему раньше не работало (жалоба: «пишу праламб — ничего не находит;
 * с большой буквы — одно вхождение»):
 *
 *  1. Токенизатор FTS4 `simple` (его использует Room) сворачивает регистр
 *     ТОЛЬКО для ASCII. Кириллица в индексе остаётся с исходным регистром,
 *     поэтому «праламб» не находил «Праламба» — а слово в книге написано
 *     с большой буквы.
 *  2. Точная фраза `"праламб"` не ловит частичное слово: токен в индексе —
 *     «праламба», а не «праламб». Нужен префикс.
 *  3. `col:"фраза"` в FTS4 фильтр по колонке не применяет (возвращает 0 строк),
 *     а `col:(...)` фильтрует только первый терм. Поэтому scope-фильтр
 *     («Санскрит»/«Стих»/«Коммент.») делаем в Kotlin, по токенам поля.
 *
 * Что делаем:
 *  - режем запрос на слова (только буквы/цифры): спецсимволы FTS (дефис-минус,
 *    скобки, звёздочка) иначе роняют запрос в пустую выдачу;
 *  - на каждое слово — OR-группа вариантов регистра (ASCII-слова не трогаем:
 *    токенизатор сам приводит их к нижнему; для кириллицы — нужно);
 *  - последнее слово ищем по ПРЕФИКСУ («праламб» → «Праламба», «Праламбасура»);
 *    префикс ставим от 4 букв — на 2–3 буквах выдача взрывается
 *    (десятки тысяч стихов, каждая строка — десятки килобайт текста).
 */
object SearchQuery {

    /** Служебные слова FTS — в кавычках, иначе это оператор. */
    private val RESERVED = setOf("and", "or", "not", "near")

    /**
     * Буква/цифра слова. Диапазоны покрывают латиницу с диакритикой
     * (ś ī ṛ ṇ), греческий, кириллицу, деванагари и комбинирующие знаки
     * (составные буквы вроде й, ё). Запрос нормализуем в NFC — иначе
     * «śrī» в разложенном виде не совпадёт с токеном индекса.
     */
    private val WORD = Regex(
        "[0-9A-Za-z\\u00C0-\\u024F\\u0370-\\u03FF\\u0400-\\u04FF" +
            "\\u0900-\\u097F\\u1E00-\\u1EFF\\u0300-\\u036F]+"
    )

    /** Слова запроса: только буквы/цифры, до 3 слов. */
    fun words(q: String): List<String> =
        WORD.findAll(Normalizer.normalize(q, Normalizer.Form.NFC))
            .map { it.value }.take(3).toList()

    /**
     * Варианты написания слова. ASCII-слова не трогаем (токенизатор сам
     * приводит их к нижнему регистру), для остальных добавляем строчное,
     * С-заглавной и ПРОПИСНОЕ.
     */
    private fun variants(w: String): List<String> {
        val out = ArrayList<String>(4)
        fun add(x: String) { if (x.isNotEmpty() && !out.contains(x)) out.add(x) }
        add(w)
        if (w.any { it.code > 127 }) {
            val low = w.lowercase()
            add(low)
            add(low.replaceFirstChar { it.uppercaseChar() })
            add(low.uppercase())
        }
        return out
    }

    /**
     * MATCH-выражение для запроса. null — запрос пустой или из одних
     * спецсимволов. exact=true — без префикса (словарь: ищем слово целиком).
     */
    fun ftsExpr(q: String, exact: Boolean = false): String? {
        val ws = words(q)
        if (ws.isEmpty()) return null
        val last = ws.lastIndex
        val groups = ArrayList<String>(ws.size)
        for (i in ws.indices) {
            val w = ws[i]
            // Префикс — только у последнего слова (его пользователь дописывает
            // прямо сейчас) и не короче 4 букв: «пра*» даёт 15+ тысяч стихов.
            val prefix = !exact && i == last && w.length >= 4
            val parts = ArrayList<String>(6)
            for (v in variants(w)) {
                parts += if (v.lowercase() in RESERVED) "\"$v\""
                else if (prefix) "$v*" else v
            }
            groups += "(" + parts.joinToString(" OR ") + ")"
        }
        return groups.joinToString(" ")
    }

    /** Токен текста: его диапазон в строке и сам текст. */
    private data class Tok(val range: IntRange, val text: String)

    /** Токены текста (для подсветки и scope-фильтра). */
    private fun tokens(text: String): List<Tok> =
        WORD.findAll(text).map { Tok(it.range, it.value) }.toList()

    /** Токен текста, совпадающий со словом запроса (без диакритики и регистра). */
    private fun tokenMatches(tok: Tok, needle: String, prefix: Boolean): Boolean {
        val t = GbHtml.foldDia(tok.text).lowercase()
        val n = GbHtml.foldDia(needle).lowercase()
        return if (prefix) t.startsWith(n) else t == n
    }

    /**
     * Scope-фильтр: все слова запроса должны быть токенами этого поля.
     * Последнее слово сравниваем по префиксу (его пользователь дописывает) —
     * так же, как их ищет FTS.
     */
    fun matchesScope(field: String?, q: String, exact: Boolean = false): Boolean {
        val ws = words(q)
        if (ws.isEmpty() || field.isNullOrBlank()) return false
        val toks = tokens(field)
        val last = ws.lastIndex
        for (i in ws.indices) {
            val prefix = !exact && i == last && ws[i].length >= 4
            if (toks.none { tokenMatches(it, ws[i], prefix) }) return false
        }
        return true
    }

    /**
     * Позиция слова запроса в тексте (для сниппета и подсветки). Возвращаем
     * диапазон ЦЕЛОГО токена: в тексте может быть «Праламба», а пользователь
     * искал «праламб» — подсветить надо всё слово, а не его хвост.
     */
    fun findToken(text: String, q: String, exact: Boolean = false): IntRange? {
        val ws = words(q)
        if (ws.isEmpty()) return null
        val toks = tokens(text)
        val last = ws.lastIndex
        // Сначала последнее слово (его пользователь обычно и дописывает)
        for (i in ws.indices.reversed()) {
            val prefix = !exact && i == last && ws[i].length >= 4
            val hit = toks.firstOrNull { tokenMatches(it, ws[i], prefix) } ?: continue
            return hit.range
        }
        return null
    }

    /** Все вхождения слов запроса в тексте — для подсветки в выдаче. */
    fun findTokens(text: String, q: String, exact: Boolean = false): List<IntRange> {
        val ws = words(q)
        if (ws.isEmpty()) return emptyList()
        val toks = tokens(text)
        val last = ws.lastIndex
        val out = ArrayList<IntRange>()
        for (i in ws.indices) {
            val prefix = !exact && i == last && ws[i].length >= 4
            for (t in toks) {
                if (tokenMatches(t, ws[i], prefix)) out.add(t.range)
            }
        }
        return out.sortedBy { it.first }
    }
}
