package com.vedalibrary.app.ui.components

import android.view.ActionMode
import android.view.Gravity
import android.view.Menu
import android.view.MenuItem
import android.widget.TextView
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.text.HtmlCompat
import com.vedalibrary.app.ui.theme.readTypeface
import java.text.Normalizer

/**
 * Работа с HTML из Gitabase:
 * - gb:// ссылки словаря -> оставляем слово plain-text (словарь-таб позже)
 * - <P>/<br> -> абзацы, &#257; -> диакритика (через HtmlCompat)
 */
object GbHtml {
    private val linkRe = Regex("""<A\s+HREF="gb://[^"]*"[^>]*>(.*?)</A>""", setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL))
    private val tagRe = Regex("<[^>]+>")
    // Компилируются один раз: plain() вызывается сотнями раз на экран
    private val spaceRunRe = Regex("[ \\t\\x0B\\f\\r]+")
    private val wsRunRe = Regex("\\s+")

    fun rich(raw: String?): String {
        if (raw == null) return ""
        // Мусор навигации сайта (разделители между ссылками цитат) — режем
        val noPipes = raw.replace(Regex("</a>\\s*\\|"), "</a>")
        return fixPua(linkRe.replace(noPipes, "$1"))
    }

    /**
     * Шрифт-хак Gitabase: транслит/пословник закодированы символами
     * Private Use Area кастомного шрифта. ВАЖНО: шрифт разный для языков!
     * eng-книги: PUA = IAST-латиница (ā→\uF101, ṛ→\uF115...);
     * rus-книги: PUA = КИРИЛЛИЦА (а→\uF101, р→\uF115...), напр.
     * дх\uf115тар\uf101ш\uf119ра = «дхритараштра» (НЕ dhṛtarāṣṭra!).
     * Таблица восстановлена по текстам (мамаках, пандаваш, шанкхам, питрин...).
     * Без замены — кракозябры; с чужой таблицей — сквозная латиница.
     */
    private val PUA = mapOf(
        '\uF101' to 'ā', '\uF103' to 'ḍ', '\uF105' to 'ḷ', '\uF107' to 'n',
        '\uF109' to 'ṃ', '\uF10D' to 'ṃ', '\uF10F' to 'ṅ', '\uF111' to 'ṇ',
        '\uF113' to 'ñ', '\uF115' to 'ṛ', '\uF117' to 'ṝ', '\uF119' to 'ṭ',
        '\uF11B' to 'ḥ', '\uF11D' to 'ś'
    )

    /** PUA-шрифт русских книг: те же кодпоинты — кириллица.
     *  Несколько кодов бьются в одну букву (н←F107/F10F/F111/F113 — разные диакритики
     *  ñ/ṅ/ṇ/n; р←F105/F115/F117 — r/ṛ/ṝ): для русской транслитерации это корректно. */
    private val PUA_CYR = mapOf(
        '\uF101' to 'а', '\uF103' to 'д', '\uF105' to 'р', '\uF107' to 'н',
        '\uF109' to 'м', '\uF10D' to 'м', '\uF10F' to 'н', '\uF111' to 'н',
        '\uF113' to 'н', '\uF115' to 'р', '\uF117' to 'р', '\uF119' to 'т',
        '\uF11B' to 'х', '\uF11D' to 'ш'
    )

    fun fixPua(s: String, cyrillic: Boolean = false): String {
        var j = -1
        for (i in s.indices) if (s[i] in '\uE000'..'\uF8FF') { j = i; break }
        if (j < 0) return s
        val map = if (cyrillic) PUA_CYR else PUA
        val sb = StringBuilder(s)
        for (i in j until sb.length) {
            val c = sb[i]
            if (c in '\uE000'..'\uF8FF') map[c]?.let { sb.setCharAt(i, it) }
        }
        return sb.toString()
    }

    /**
     * Русский транслит целиком кириллицей: IAST-диакритика (ā, ṛ, ṭ…) в текстовых
     * кусках HTML -> кириллица, теги и сущности не трогаем. Только для rus-книг.
     */
    fun cyrillicTranslit(raw: String?): String {
        if (raw.isNullOrBlank()) return ""
        val fixed = fixPua(raw)
        val out = StringBuilder(fixed.length + 16)
        var last = 0
        for (m in tagRe.findAll(fixed)) {
            out.append(IastCyrillic.convert(fixed.substring(last, m.range.first)))
            out.append(m.value)
            last = m.range.last + 1
        }
        out.append(IastCyrillic.convert(fixed.substring(last)))
        return out.toString()
    }

    /**
     * Русская проза (перевод/комментарий): санскритские термины с диакритикой
     * (оṃ, намаḥ, астрāйа — после fixPua) -> кириллица (ом, намах, астрайа).
     * Трогаем ТОЛЬКО слова с диакритикой; чистый ASCII (английские слова) не трогаем.
     * Только для rus-книг.
     */
    private const val DIA = "āīūṛṝḷṃḥṅñṇṭḍśṣĀĪŪṚṜḶṂḤṄÑṆṬḌŚṢ"
    private val DIA_WORD = Regex("[A-Za-z$DIA-]+")

    fun cyrillicTerms(raw: String?): String {
        if (raw.isNullOrBlank()) return ""
        val fixed = fixPua(raw)
        val out = StringBuilder(fixed.length + 16)
        var last = 0
        for (m in tagRe.findAll(fixed)) {
            out.append(convertTerms(fixed.substring(last, m.range.first)))
            out.append(m.value)
            last = m.range.last + 1
        }
        out.append(convertTerms(fixed.substring(last)))
        return out.toString()
    }

    private fun convertTerms(text: String): String =
        DIA_WORD.replace(text) { m ->
            val w = m.value
            if (w.any { it in DIA }) IastCyrillic.convert(w) else w
        }

    /** NFC: склеивает combining-диакритику (&#803; из eng-баз) в готовые буквы */
    fun nfc(s: String): String =
        if (s.none { it.code in 0x300..0x36F }) s
        else try { Normalizer.normalize(s, Normalizer.Form.NFC) } catch (_: Exception) { s }

    /** NFC для отформатированного текста с сохранением спанов */
    fun normalizeSpanned(s: CharSequence): CharSequence {
        val str = s.toString()
        if (str.none { it.code in 0x300..0x36F }) return s
        val norm = try { Normalizer.normalize(str, Normalizer.Form.NFC) } catch (_: Exception) { return s }
        if (norm == str || s !is android.text.Spanned) return norm
        val map = IntArray(str.length + 1)
        for (i in 0..str.length) {
            map[i] = try { Normalizer.normalize(str.substring(0, i), Normalizer.Form.NFC).length } catch (_: Exception) { i }
        }
        val out = android.text.SpannableString(norm)
        for (span in s.getSpans(0, str.length, Any::class.java)) {
            val st = map[s.getSpanStart(span).coerceIn(0, str.length)]
            val en = map[s.getSpanEnd(span).coerceIn(0, str.length)]
            if (st <= en) out.setSpan(span, st, en, s.getSpanFlags(span))
        }
        return out
    }

    /** Плейнтекст с декодированными сущностями (&#257; -> ā, &lt; -> <) */
    fun plain(raw: String?): String {
        if (raw.isNullOrBlank()) return ""
        return try {
            nfc(HtmlCompat.fromHtml(rich(raw), HtmlCompat.FROM_HTML_MODE_LEGACY, null, null)
                .toString().replace(spaceRunRe, " ").trim())
        } catch (_: Exception) {
            nfc(tagRe.replace(rich(raw), " ").replace("&nbsp;", " ").replace("&amp;", "&")
                .replace(wsRunRe, " ").trim())
        }
    }

    /** Пословник transl1: записи разделены ';' (или переводами строк в старых изданиях) */
    fun synonymLines(raw: String?): List<String> =
        plain(raw).split(";", "\n").map { it.trim() }.filter { it.isNotEmpty() }

    /** «слово — перевод» -> (слово, остаток). Разделители как в книгах: — / – / - / --.
     *  Запасные варианты для старых изданий (БГ-1972: «tayoh--of the two» без пробелов):
     *  голые — / – / --, иначе голова — первое слово строки. */
    fun splitHead(line: String): Pair<String, String> {
        val e = line.trim()
        for (sep in listOf(" — ", " – ", " - ", " -- ", " —", " –", " -", "--", "—", "–")) {
            val i = e.indexOf(sep)
            if (i > 0) {
                var rest = e.substring(i).trim()
                // Склеенный «--of ...»: двойной дефис — разделитель, не часть слова
                if (rest.startsWith("--") && rest.length > 2 && rest[2] != ' ')
                    rest = rest.substring(2).trimStart()
                return e.substring(0, i).trim() to rest
            }
        }
        val sp = e.indexOf(' ')
        if (sp > 0 && sp + 1 < e.length) {
            val head = e.substring(0, sp).trim().trimEnd(':', ';', ',')
            if (head.isNotEmpty() && ' ' !in head) return head to e.substring(sp).trim()
        }
        return "" to e
    }

    /** Целое слово (границы по юникод-буквам/цифрам): «ca» не матчит «caiva», диакритика не рвёт слово.
     *  Диакритика сворачивается (prāptam == praptam): FTS так же режет её при поиске. */
    fun wholeWord(haystack: String, needle: String): Boolean {
        if (needle.isBlank()) return false
        val h = foldDia(haystack).lowercase()
        val n = foldDia(needle).lowercase()
        if (n.isBlank()) return false
        return Regex("(?<![\\p{L}\\p{N}_])" + Regex.escape(n) + "(?![\\p{L}\\p{N}_])")
            .containsMatchIn(h)
    }

    /** Снять диакритику (ā->a, ṛ->r, ñ->n): поиск/подсветка не зависят от неё */
    fun foldDia(s: String): String {
        val sb = StringBuilder(s.length)
        for (i in s.indices) {
            val d = try { Normalizer.normalize(s[i].toString(), Normalizer.Form.NFD) }
            catch (_: Exception) { s[i].toString() }
            for (c in d) {
                if (c.category != CharCategory.NON_SPACING_MARK) sb.append(c)
            }
        }
        return sb.toString()
    }

    /** Подстрока без учёта диакритики и регистра */
    fun containsFold(haystack: String, needle: String): Boolean {
        if (needle.isBlank()) return false
        return foldDia(haystack).lowercase().contains(foldDia(needle).lowercase())
    }

    /** Диапазоны совпадений в ОРИГИНАЛЬНЫХ индексах (для спанов подсветки) */
    fun highlightRanges(text: String, needle: String): List<IntRange> {
        val out = mutableListOf<IntRange>()
        if (needle.isBlank() || text.isEmpty()) return out
        val folded = StringBuilder(text.length)
        val map = ArrayList<Int>(text.length)
        for (i in text.indices) {
            val d = try { Normalizer.normalize(text[i].toString(), Normalizer.Form.NFD) }
            catch (_: Exception) { text[i].toString() }
            for (c in d) {
                if (c.category != CharCategory.NON_SPACING_MARK) {
                    folded.append(c.lowercaseChar())
                    map.add(i)
                }
            }
        }
        val n = foldDia(needle).lowercase()
        if (n.isEmpty() || folded.isEmpty()) return out
        var j = folded.indexOf(n)
        while (j >= 0) {
            val end = map[j + n.length - 1] + 1
            out.add(map[j]..end)
            j = folded.indexOf(n, j + n.length)
        }
        return out
    }
}

/** Рендер formatted HTML через TextView (диакритика, курсив, абзацы). Цвет берём из M3-схемы.
 *  onSaveNote != null — в меню выделения первым пунктом "В заметку", вторым "Вопрос".
 *  onVerseRef != null — цитаты вида БГ 2.13 / ШБ 1.2.3 становятся ссылками (code/song/ch/txt). */
@Composable
fun HtmlText(
    html: String, modifier: Modifier = Modifier, center: Boolean = false, justify: Boolean = false,
    fontSizeSp: Float = 17f, bold: Boolean = false,
    onSaveNote: ((String) -> Unit)? = null,
    onAsk: ((String) -> Unit)? = null,
    highlight: String = "",
    onVerseRef: ((code: String, song: String, ch: String, txt: String, lang: String?) -> Unit)? = null
) {
    val color = MaterialTheme.colorScheme.onSurface
    val linkColor = MaterialTheme.colorScheme.primary
    val spanned = remember(html) {
        GbHtml.normalizeSpanned(HtmlCompat.fromHtml(GbHtml.rich(html), HtmlCompat.FROM_HTML_MODE_LEGACY, null, null).trim())
    }
    val noteCb = rememberUpdatedState(onSaveNote)
    val askCb = rememberUpdatedState(onAsk)
    val refCb = rememberUpdatedState(onVerseRef)
    val withRefs = remember(spanned) {
        if (onVerseRef == null) spanned else attachVerseRefs(spanned, refCb)
    }
    // Свой MovementMethod: системный LinkMovementMethod проигрывает борьбу за тап
    // selectable-тексту (ссылка срабатывает через раз) — этот бьёт точно по спану
    val linkMovement = remember { VerseLinkMovementMethod() }
    AndroidView(
        modifier = modifier,
        factory = { ctx -> TextView(ctx).apply { setTextIsSelectable(true) } },
        update = { tv ->
            // Свежая копия спанов на каждое обновление — иначе подсветка накапливается
            val base = android.text.SpannableString(withRefs)
            if (highlight.isNotBlank()) {
                for (r in GbHtml.highlightRanges(base.toString(), highlight)) {
                    base.setSpan(
                        android.text.style.BackgroundColorSpan(0xFFFFFF00.toInt()),
                        r.first, r.last + 1,
                        android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
                    )
                }
            }
            tv.text = base
            tv.textSize = fontSizeSp
            tv.setTextColor(color.toArgb())
            // Noto Serif вместо системного: диакритика из того же файла, без «жирных» подмен
            readTypeface(tv.context, bold)?.let { tv.typeface = it }
                ?: tv.setTypeface(null, if (bold) android.graphics.Typeface.BOLD else android.graphics.Typeface.NORMAL)
            tv.gravity = if (center) Gravity.CENTER_HORIZONTAL else Gravity.START
            // Выравнивание по ширине (перевод, комментарий), API 26+.
            // breakStrategy выставляем явно: на части прошивок дефолт SIMPLE, с ним
            // justification местами не применяется. Остальным секциям стратегию не трогаем.
            if (android.os.Build.VERSION.SDK_INT >= 26) {
                if (justify && !center) {
                    tv.breakStrategy = android.text.Layout.BREAK_STRATEGY_HIGH_QUALITY
                    tv.justificationMode = android.text.Layout.JUSTIFICATION_MODE_INTER_WORD
                } else {
                    tv.justificationMode = android.text.Layout.JUSTIFICATION_MODE_NONE
                }
            }
            tv.customSelectionActionModeCallback =
                if (noteCb.value == null && askCb.value == null) null
                else NoteActionMode(tv, noteCb.value, askCb.value)
            if (onVerseRef != null) {
                tv.movementMethod = linkMovement
                tv.setLinkTextColor(linkColor.toArgb())
            }
        }
    )
}

/** Цитаты стихов в комментариях/лекциях: ШБ 1.2.3 (3 части), БГ 2.13 (глава.стих).
 *  \b не работает с кириллицей (ASCII-only), поэтому граница — через lookbehind. */
private val REF3 = Regex(
    """(?:^|(?<=[\s(«"“']))(ШБ|шб|SB|Sb|sb|ЧЧ|чч|CC|Cc|cc)[.,]?\s*(\d+)\s*[.]\s*(\d+)\s*[.]\s*(\d+)"""
)
private val REF2 = Regex(
    """(?:^|(?<=[\s(«"“']))(БГ|бг|BG|Bg|bg)[.,]?\s*(\d+)\s*[.]\s*(\d+)(?!\s*[.]\s*\d)"""
)
private val REF_CODE = mapOf("ШБ" to "SB", "SB" to "SB", "ЧЧ" to "CC", "CC" to "CC", "БГ" to "BG", "BG" to "BG")
/** Коды произведений для gr:// ссылок (верхний регистр).
 *  vedic/gaudia-коды (KU/SVU/...) книг, которых нет — резолв честно скажет «нет книги». */
private val GR_CODE = setOf(
    "SB", "BG", "CC", "BS", "ISO", "NOD", "NOI", "TLC", "KB", "TQK", "MM", "NBS",
    "LBG", "LSB", "TLKS", "LCC", "LISO", "LTRS", "LTR", "BG72",
    "KU", "SVU", "MU", "VS", "VP", "BAU", "BRS", "GGD"
)
/** Код перед цифрами («SB 5.5.3», «ШБ 1.8.19») — чтобы вся цитата была ссылкой */
private val GR_CODE_BEFORE = Regex(
    """(SB|BG|CC|BS|ISO|NOD|NOI|TLC|KB|TQK|ШБ|БГ|ЧЧ)\s*$""",
    setOf(RegexOption.IGNORE_CASE)
)

/** gr://rus/texts/bg/18/61 -> цель с явным языком; gr://rus/texts/sb/1/8/19 -> песнь/глава/стих.
 *  Раздел любой (texts/vedic/gaudia) — важен только код произведения. */
private data class GrTarget(val code: String, val song: String, val ch: String, val txt: String, val lang: String)

private fun parseGrUrl(url: String?): GrTarget? {
    if (url.isNullOrBlank()) return null
    var u = url.trim()
    if (u.startsWith("gr://", ignoreCase = true)) u = u.substring(5)
    else if (u.startsWith("//")) u = u.substring(2)
    else return null
    val parts = u.split("/").map { it.trim() }.filter { it.isNotEmpty() }
    if (parts.size < 3) return null
    val lang = parts[0].lowercase().takeIf { it == "rus" || it == "eng" } ?: return null
    // код — первый известный после языка (раздел texts/vedic/gaudia пропускаем)
    val ci = parts.indexOfFirst { it.uppercase() in GR_CODE }
    if (ci < 0) return null
    val code = parts[ci].uppercase()
    val rest = parts.drop(ci + 1).filter { it.isNotBlank() }
    val (song, ch, txt) = when (rest.size) {
        3 -> Triple(rest[0], rest[1], rest[2])
        2 -> Triple("1", rest[0], rest[1])
        1 -> Triple("1", "", rest[0])
        else -> return null
    }
    if (txt.isBlank()) return null
    return GrTarget(code, song, ch, txt, lang)
}

private fun attachVerseRefs(
    s: CharSequence,
    cb: State<((String, String, String, String, String?) -> Unit)?>
): CharSequence {
    val str = s.toString()
    val out = android.text.SpannableStringBuilder.valueOf(if (s is android.text.Spanned) s else str)
    val taken = mutableListOf<IntRange>()
    fun free(r: IntRange) = taken.none { it.first <= r.last && r.first <= it.last }
    // Ссылки лекций вида <a href="gr://rus/texts/bg/18/61">18.61</a>:
    // язык цели зашит в URL — резолвим прямо в него, а не в язык текущей книги.
    // Мёртвые (file://, левые схемы) — разлинковываем, чтобы не выглядели кликабельно.
    if (s is android.text.Spanned) {
        for (u in s.getSpans(0, s.length, android.text.style.URLSpan::class.java)) {
            try {
                val raw = (u.url ?: "").trim()
                if (raw.startsWith("file:", ignoreCase = true)) {
                    out.removeSpan(u)
                    continue
                }
                val g = parseGrUrl(raw) ?: continue
                val st0 = s.getSpanStart(u)
                val en = s.getSpanEnd(u)
                if (st0 < 0 || en <= st0) continue
                // Код перед цифрами («SB 5.5.3») — включаем в ссылку целиком
                var st = st0
                GR_CODE_BEFORE.find(out.substring(0, st0))?.let { m ->
                    val w = m.groupValues[1].uppercase()
                    if ((REF_CODE[w] ?: w) == g.code) st = m.range.first
                }
                if (!free(st until en)) continue
                out.removeSpan(u)
                out.setSpan(
                    VerseRefSpan(g.code, g.song, g.ch, g.txt, g.lang, cb),
                    st, en, android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
                )
                taken += st until en
            } catch (_: Exception) { }
        }
    }
    for (m in REF3.findAll(str)) {
        val code = REF_CODE[m.groupValues[1].uppercase()] ?: continue
        if (!free(m.range)) continue
        out.setSpan(
            VerseRefSpan(code, m.groupValues[2], m.groupValues[3], m.groupValues[4], null, cb),
            m.range.first, m.range.last + 1, android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
        )
        taken += m.range
    }
    for (m in REF2.findAll(str)) {
        val code = REF_CODE[m.groupValues[1].uppercase()] ?: continue
        if (!free(m.range)) continue
        out.setSpan(
            VerseRefSpan(code, "1", m.groupValues[2], m.groupValues[3], null, cb),
            m.range.first, m.range.last + 1, android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
        )
        taken += m.range
    }
    return out
}

/** Тап по цитате -> verseId резолвится в экране (книга того же языка; у gr:// язык свой) */
private class VerseRefSpan(
    val code: String, val song: String, val ch: String, val txt: String,
    val lang: String? = null,
    val cb: State<((String, String, String, String, String?) -> Unit)?>
) : android.text.style.ClickableSpan() {
    override fun onClick(widget: android.view.View) { cb.value?.invoke(code, song, ch, txt, lang) }
    override fun updateDrawState(ds: android.text.TextPaint) {
        super.updateDrawState(ds)
        ds.isUnderlineText = false
    }
}

/**
 * MovementMethod для текстов одновременно с выделением и ссылками.
 * Стандартный LinkMovementMethod при setTextIsSelectable(true) отдаёт тап
 * механизму выделения — по ссылке приходится бить по 15 раз. Этот класс
 * при ACTION_DOWN запоминает спан, при ACTION_UP на том же спане — кликает сам.
 */
private class VerseLinkMovementMethod : android.text.method.LinkMovementMethod() {
    private var downSpan: android.text.style.ClickableSpan? = null

    private fun spanAt(widget: TextView, buffer: android.text.Spannable, event: android.view.MotionEvent): android.text.style.ClickableSpan? {
        val x = event.x.toInt() - widget.totalPaddingLeft + widget.scrollX
        val y = event.y.toInt() - widget.totalPaddingTop + widget.scrollY
        val layout = widget.layout ?: return null
        val line = layout.getLineForVertical(y)
        val off = layout.getOffsetForHorizontal(line, x.toFloat())
        return buffer.getSpans(off, off, android.text.style.ClickableSpan::class.java).firstOrNull()
    }

    override fun onTouchEvent(
        widget: TextView, buffer: android.text.Spannable, event: android.view.MotionEvent
    ): Boolean {
        when (event.action) {
            android.view.MotionEvent.ACTION_DOWN ->
                downSpan = try { spanAt(widget, buffer, event) } catch (_: Exception) { null }
            android.view.MotionEvent.ACTION_UP -> {
                val up = try { spanAt(widget, buffer, event) } catch (_: Exception) { null }
                val down = downSpan
                downSpan = null
                if (down != null && up === down) {
                    down.onClick(widget)
                    return true
                }
            }
            android.view.MotionEvent.ACTION_MOVE -> { /* ждём UP на том же спане */ }
            else -> downSpan = null
        }
        return super.onTouchEvent(widget, buffer, event)
    }
}

/** Пункты "В заметку" (первым) и "Вопрос" (вторым) поверх стандартных Копировать/Выделить всё */
private class NoteActionMode(
    val tv: TextView, val onNote: ((String) -> Unit)?, val onAsk: ((String) -> Unit)?
) : ActionMode.Callback {
    companion object { const val ID_NOTE = 0x7E57; const val ID_ASK = 0x7E58 }

    private fun selected(): String? {
        val s = tv.selectionStart
        val e = tv.selectionEnd
        return if (s >= 0 && e > s) tv.text.substring(s, e).toString() else null
    }

    override fun onCreateActionMode(mode: ActionMode?, menu: Menu?) = true

    override fun onPrepareActionMode(mode: ActionMode?, menu: Menu?): Boolean {
        if (onNote != null && menu?.findItem(ID_NOTE) == null) menu?.add(Menu.NONE, ID_NOTE, 0, "В заметку")
        if (onAsk != null && menu?.findItem(ID_ASK) == null) menu?.add(Menu.NONE, ID_ASK, 1, "Вопрос")
        return false
    }

    override fun onActionItemClicked(mode: ActionMode?, item: MenuItem?): Boolean {
        when (item?.itemId) {
            ID_NOTE -> { selected()?.let(onNote!!); mode?.finish(); return true }
            ID_ASK -> { selected()?.let(onAsk!!); mode?.finish(); return true }
        }
        return false
    }

    override fun onDestroyActionMode(mode: ActionMode?) {}
}
