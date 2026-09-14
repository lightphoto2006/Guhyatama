package com.vedalibrary.app.ui.components

/**
 * IAST (латиница с диакритикой) -> русская транслитерация кириллицей,
 * как в книгах ББТ: dhṛtarāṣṭraḥ → дхритараштрах, kṛṣṇa → кришна.
 * Только для отображения слов пословника в rus-книгах; поиск идёт по исходной латыни.
 */
object IastCyrillic {
    // Двухбуквенные сочетания — через when (без аллокации строк на символ, locale-независимо)
    private fun multi2(a: Char, b: Char): String? = when (a) {
        'k' -> if (b == 'h') "кх" else null
        'g' -> if (b == 'h') "гх" else null
        'c' -> if (b == 'h') "чх" else null
        'j' -> if (b == 'h') "джх" else null
        'ṭ' -> if (b == 'h') "тх" else null
        'ḍ' -> if (b == 'h') "дх" else null
        't' -> if (b == 'h') "тх" else null
        'd' -> if (b == 'h') "дх" else null
        'p' -> if (b == 'h') "пх" else null
        'b' -> if (b == 'h') "бх" else null
        'a' -> if (b == 'i') "аи" else if (b == 'u') "ау" else null
        else -> null
    }
    private val SINGLE = mapOf(
        'a' to "а", 'ā' to "а", 'i' to "и", 'ī' to "и",
        'u' to "у", 'ū' to "у", 'ṛ' to "ри", 'ṝ' to "рӣ",
        'ḷ' to "ли", 'e' to "е", 'o' to "о", 'ṃ' to "м", 'ḥ' to "х",
        'k' to "к", 'g' to "г", 'ṅ' to "н", 'c' to "ч", 'j' to "дж",
        'ñ' to "н", 'ṭ' to "т", 'ḍ' to "д", 'ṇ' to "н",
        't' to "т", 'd' to "д", 'n' to "н", 'p' to "п",
        'm' to "м", 'y' to "й", 'r' to "р", 'l' to "л",
        'v' to "в", 'ś' to "ш", 'ṣ' to "ш", 's' to "с", 'h' to "х"
    )

    /** Только головка строки пословника («слово — перевод»): слово кириллицей, перевод как есть */
    fun convertHead(line: String): String {
        for (sep in listOf(" — ", " – ", " - ")) {
            val i = line.indexOf(sep)
            if (i > 0) return convert(line.substring(0, i)) + line.substring(i)
        }
        return convert(line)
    }

    fun convert(src: String): String {
        if (src.isBlank() || src.none { it in 'a'..'z' || it in 'A'..'Z' || it.code > 127 }) return src
        val sb = StringBuilder(src.length + 8)
        var i = 0
        while (i < src.length) {
            val c = src[i]
            val lc = c.lowercaseChar()
            if (i + 1 < src.length) {
                val m2 = multi2(lc, src[i + 1].lowercaseChar())
                if (m2 != null) {
                    sb.append(if (c.isUpperCase()) m2.replaceFirstChar { it.uppercase() } else m2)
                    i += 2
                    continue
                }
            }
            val one = SINGLE[lc]
            if (one != null) {
                // Начальное e → «э» (эва), внутри слова → «е»
                val out = if ((c == 'e' || c == 'E') && (i == 0 || src[i - 1] in " -–—'’(")) {
                    if (c.isUpperCase()) "Э" else "э"
                } else one
                sb.append(if (c.isUpperCase() && out == one) one.replaceFirstChar { it.uppercase() } else out)
            } else {
                sb.append(c)
            }
            i++
        }
        return sb.toString()
    }
}
