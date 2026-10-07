package com.vedalibrary.app.ui.components

import com.vedalibrary.app.data.local.Book
import com.vedalibrary.app.data.local.Verse
import com.vedalibrary.app.data.local.VerseRow

/** Ссылка вида "БГ 2.13" / "BG 2.13" + текст для копирования */
object VerseShare {
    private val RU = mapOf(
        "BG" to "БГ", "SB" to "ШБ", "CC" to "ЧЧ", "ISO" to "Шри Ишопанишад",
        "NOD" to "Нектар преданности", "NOI" to "Нектар наставлений",
        "TLC" to "Учение Шри Чайтаньи", "KB" to "Кришна", "BS" to "Брахма-самхита",
        "TQK" to "Учение царицы Кунти",
        "SCC" to "ЧЧ", "SSB" to "ШБ", "SBG" to "БГ", "SBRS" to "БРС"
    )

    /** Ключ (song, chapter, txt) из id ".../song/ch/txt" — только для стихов из .db (chapterId содержит /ch-).
     *  Суффикс дублей (~2 у лекций одного стиха) отрезаем: ключ — адрес стиха, не строки. */
    fun verseKey(verse: Verse): Triple<String, String, String>? {
        if (!verse.chapterId.contains("/ch-")) return null
        val parts = verse.id.split("/")
        if (parts.size < 4) return null
        val txt = parts[parts.size - 1].substringBefore("~")
        return Triple(parts[parts.size - 3], parts[parts.size - 2], txt.ifBlank { parts[parts.size - 1] })
    }

    /** Ключ обратной ссылки textrefs: ext:BG/1/2/13 (song/ch/txt) */
    fun incomingKey(book: Book?, verse: Verse): String? {
        val k = verseKey(verse) ?: return null
        val code = book?.id?.split("-")?.getOrNull(1)?.uppercase() ?: return null
        return "ext:$code/${k.first}/${k.second}/${k.third}"
    }

    /** Номер главы числом, включая 0 (Введение — первая).
     *  chapterNum() даёт null для 0 — для сортировки соседей это неверно (Введение уходило в конец) */
    fun chapterNumInt(chapterId: String): Int {
        val tail = chapterId.substringAfterLast("ch-", "")
        if (tail.isEmpty()) return 999
        return tail.split("-").getOrNull(1)?.toIntOrNull() ?: 999
    }

    /** Номер главы из Chapter.id (".../ch-1-2" -> "2"), null для прозы */
    fun chapterNum(chapterId: String): String? {
        val tail = chapterId.substringAfterLast("ch-", "")
        if (tail.isEmpty()) return null
        val parts = tail.split("-")
        return parts.getOrNull(1)?.takeIf { it != "0" }
    }

    /** Раздел верхнего уровня из Chapter.id (".../ch-1-2" -> "1", ".../ch-5" -> "5") */
    fun chapterSong(chapterId: String): String? {
        val tail = chapterId.substringAfterLast("ch-", "")
        if (tail.isEmpty()) return null
        return tail.split("-").getOrNull(0)
    }

    /** Подпись раздела: ШБ → «Песнь N», годы (1967) — как есть, иначе «Часть N»; нечисловой — как есть */
    fun songTitle(book: Book?, song: String): String {
        if (song.toIntOrNull() == null) return song.replaceFirstChar { it.uppercase() }
        if (song.length == 4 && (song.startsWith("19") || song.startsWith("20"))) return song
        val code = book?.id?.split("-")?.getOrNull(1)?.uppercase() ?: ""
        val rus = book?.language == "rus"
        return if (code == "SB") (if (rus) "Песнь $song" else "Canto $song")
        else (if (rus) "Часть $song" else "Part $song")
    }

    /** Книги лекций Шьямакунды: в списках показываем только названия лекций (без тела) */
    fun isLectureBook(bookId: String?): Boolean =
        bookId?.split("-")?.getOrNull(1)?.uppercase() in setOf("SCC", "SSB", "SBG", "SBRS")

    /** Прозаические книги (целая глава — один кусок): перевод обычным начертанием,
     *  как тела лекций, а не жирным (жирный — только для коротких переводов стихов) */
    private val PROSE_TYPES = setOf("GC")
    fun isProseBook(bookId: String?): Boolean =
        bookId?.split("-")?.getOrNull(1)?.uppercase() in PROSE_TYPES

    /** Книги, где number — номер лекции/письма, а не стиха: диапазоны («34-35»)
     *  считать строками. Лекции обоих авторов + письма + беседы */
    fun isLectureLike(bookId: String?): Boolean {
        val t = bookId?.split("-")?.getOrNull(1)?.uppercase() ?: return false
        return t in setOf(
            "SCC", "SSB", "SBG", "SBRS", "LBG", "LSB", "LCC", "LISO", "LTRS", "LTR", "TLKS"
        )
    }

    /** Сколько стихов в строке с номером: сдвоенные («23-24») раскрываются в 2.
     *  Мусор вида «1CC96» и пустое — 1. Диапазоны шире 500 — тоже 1 (опечатка, не стихи) */
    private val RANGE_RE = Regex("""^(\d+)\s*[-–—]\s*(\d+)$""")
    fun verseCountOf(number: String): Int {
        val m = RANGE_RE.matchEntire(number.trim()) ?: return 1
        val (a, b) = m.destructured
        val n = b.toInt() - a.toInt() + 1
        return if (n in 1..500) n else 1
    }

    /** Название без технического суффикса импорта ("Шримад Бхагаватам [SB]" -> "Шримад Бхагаватам") */
    fun cleanTitle(title: String?): String =
        title?.replace(Regex("""\s*\[[A-Za-z-]+\]$"""), "") ?: ""

    /** Ссылка: БГ 2.13; трёхуровневые (ШБ 1.12.23 — песнь.глава.стих) для ШБ и разделов ≠1 */
    fun ref(book: Book?, verse: Verse): String =
        refLight(book?.language, book?.id, verse.chapterId, verse.number)

    /** Та же ссылка без сущностей — для лёгких строк списков (считается один раз в VM, а не на рекомпозицию) */
    fun refLight(bookLang: String?, bookId: String?, chapterId: String, number: String): String {
        val type = bookId?.split("-")?.getOrNull(1)?.uppercase() ?: ""
        val code = if (bookLang == "rus") RU[type] ?: type.ifBlank { "•" } else type.ifBlank { "•" }
        val num = chapterNum(chapterId)
        val song = chapterSong(chapterId)
        return if (num != null && (type == "SB" || (song != null && song != "1"))) {
            "$code ${song ?: "1"}.$num.$number".trim()
        } else {
            val ch = num?.let { "$it." } ?: ""
            "$code $ch$number".trim()
        }
    }

    /** Только сокращение произведения: "БГ" / "BG" */
    fun bookCode(book: Book?): String {
        val code = book?.id?.split("-")?.getOrNull(1)?.uppercase() ?: ""
        return if (book?.language == "rus") RU[code] ?: code.ifBlank { "•" } else code.ifBlank { "•" }
    }

    /** "БГ 2.13\n<перевод>\n(Полное имя книги)" — подпись как в оригинале */
    fun copyText(book: Book?, verse: Verse): String = buildString {
        append(ref(book, verse))
        append('\n')
        append(GbHtml.plain(verse.translation ?: verse.text))
        book?.title?.takeIf { it.isNotBlank() }?.let { append("\n($it)") }
    }

    /** То же для лёгкой строки (копирование из списков без загрузки полного стиха) */
    fun copyTextLight(r: VerseRow): String = buildString {
        append(refLight(r.bookLang, r.bookId, r.chapterId, r.number))
        append('\n')
        append(GbHtml.plain(r.translation ?: r.text))
        r.bookTitle?.takeIf { it.isNotBlank() }?.let { append("\n($it)") }
    }
}
