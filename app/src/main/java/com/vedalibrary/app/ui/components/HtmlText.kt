package com.vedalibrary.app.ui.components

import android.view.ActionMode
import android.view.Gravity
import android.view.Menu
import android.view.MenuItem
import android.widget.TextView
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.text.HtmlCompat
import com.vedalibrary.app.ui.theme.readTypeface
import java.text.Normalizer

/**
 * Работа с HTML из исходных баз:
 * - gb:// ссылки словаря -> оставляем слово plain-text (словарь-таб позже)
 * - <P>/<br> -> абзацы, &#257; -> диакритика (через HtmlCompat)
 */
object GbHtml {
    private val linkRe = Regex("""<A\s+HREF="gb://[^"]*"[^>]*>(.*?)</A>""", setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL))
    private val tagRe = Regex("<[^>]+>")
    // Компилируются один раз: plain() вызывается сотнями раз на экран
    private val spaceRunRe = Regex("[ \\t\\x0B\\f\\r]+")
    private val wsRunRe = Regex("\\s+")
    private val navBarRe = Regex("</a>\\s*\\|")
    private val ulRe = Regex("</?ul[^>]*>", RegexOption.IGNORE_CASE)
    private val olRe = Regex("</?ol[^>]*>", RegexOption.IGNORE_CASE)
    private val liRe = Regex("<li[^>]*>", RegexOption.IGNORE_CASE)
    private val liEndRe = Regex("</li>", RegexOption.IGNORE_CASE)
    private val bqRe = Regex("<blockquote[^>]*>", RegexOption.IGNORE_CASE)
    private val bqEndRe = Regex("</blockquote>", RegexOption.IGNORE_CASE)

    /** Разрыв слова посреди строки в данных (перенос строк при выгрузке из
     *  сайта): «пада-\r\nсеванам», «атма- ниведанам». Дефис приклеиваем к
     *  следующему слову. Реальное тире не страдает: перед ним всегда пробел
     *  (?<=\S не совпадёт), «-» между цифрами склеивается в «5-6» — так и есть. */
    val brokenHyphenRe = Regex(
        """(?<=\S)-[ \t ]*(?:(?:\r\n|\r|\n)[ \t ]*)+(?=\S)|(?<=\S)-[ \t ]+(?=\S)"""
    )

    fun rich(raw: String?): String {
        if (raw == null) return ""
        // Мусор навигации сайта (разделители между ссылками цитат) — режем
        var t = raw.replace(navBarRe, "</a>")
        // «пада-\r\nсеванам» до разметки: иначе \n = конец абзаца и слово рвётся
        t = t.replace(brokenHyphenRe, "-")
        // Списки/цитаты в обычный текст: BulletSpan/LeadingMarginSpan ломают
        // выравнивание по ширине (абзац с ними всегда рваный) и отступы
        t = t.replace(ulRe, "")
        t = t.replace(olRe, "")
        t = t.replace(liRe, "<p>• ")
        t = t.replace(liEndRe, "</p>")
        t = t.replace(bqRe, "<p>")
        t = t.replace(bqEndRe, "</p>")
        return fixPua(linkRe.replace(t, "$1"))
    }

    /**
     * Шрифт-хак исходных баз: транслит/пословник закодированы символами
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

    /** NFC для отформатированного текста с сохранением спанов.
     *  Карта смещений — линейная: сегмент = стартер + следующие combining-метки,
     *  длина NFC считается только на крошечном сегменте (старый вариант гонял
     *  normalize растущего префикса на каждую позицию — O(n²): 22 КБ комментария
     *  с ударениями вешали главный поток на десятки секунд). */
    fun normalizeSpanned(s: CharSequence): CharSequence {
        val str = s.toString()
        if (str.none { it.code in 0x300..0x36F }) return s
        val norm = try { Normalizer.normalize(str, Normalizer.Form.NFC) } catch (_: Exception) { return s }
        if (norm == str || s !is android.text.Spanned) return norm
        fun isMark(c: Char) = c.code in 0x300..0x36F
        val map = IntArray(str.length + 1)
        var ni = 0
        var i = 0
        val n = str.length
        while (i < n) {
            var j = i + 1
            while (j < n && isMark(str[j])) j++
            var k = i
            while (k <= j) {
                map[k] = ni + try {
                    Normalizer.normalize(str.substring(i, k), Normalizer.Form.NFC).length
                } catch (_: Exception) { k - i }
                k++
            }
            ni = map[j]
            i = j
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
    private val wholeWordCache = object : LinkedHashMap<String, Regex>(8, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, Regex>) = size > 8
    }

    fun wholeWord(haystack: String, needle: String): Boolean {
        if (needle.isBlank()) return false
        val h = foldDia(haystack).lowercase()
        val n = foldDia(needle).lowercase()
        if (n.isBlank()) return false
        val re = synchronized(wholeWordCache) {
            wholeWordCache.getOrPut(n) {
                Regex("(?<![\\p{L}\\p{N}_])" + Regex.escape(n) + "(?![\\p{L}\\p{N}_])")
            }
        }
        return re.containsMatchIn(h)
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

    /** Диапазоны совпадений в ОРИГИНАЛЬНЫХ индексах (для спанов подсветки).
     *  IntRange включительный: конец — map[...] БЕЗ +1 (иначе substring/setSpan
     *  вылетают за границу, когда совпадение в конце строки — краш из поиска). */
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
            val end = map[j + n.length - 1]
            out.add(map[j]..end)
            j = folded.indexOf(n, j + n.length)
        }
        return out
    }
}

/** Рендер formatted HTML через TextView (диакритика, курсив, абзацы). Цвет берём из M3-схемы.
 *  onSaveNote != null — в меню выделения первым пунктом "В заметку", вторым "Вопрос".
 *  onVerseRef != null — цитаты вида БГ 2.13 / ШБ 1.2.3 становятся ссылками (code/song/ch/txt).
 *  refSong/refCh/refWork — контекст лекции: голые номера (8.134), тройки без кода (1.6.82)
 *  и «ЧЧ Ади Лила 1.1» тоже становятся ссылками на стихи (только для лекций). */
// InlinedApi: константы LineBreaker.* (STUB помечен API 29) — static final int,
// инлайнятся компилятором и на minSdk 26 работают (те же значения, что у Layout.*)
@Suppress("InlinedApi")
@Composable
fun HtmlText(
    html: String, modifier: Modifier = Modifier, center: Boolean = false, justify: Boolean = false,
    fontSizeSp: Float = 17f, bold: Boolean = false,
    onSaveNote: ((String) -> Unit)? = null,
    onAsk: ((String) -> Unit)? = null,
    highlight: String = "",
    onVerseRef: ((code: String, song: String, ch: String, txt: String, lang: String?) -> Unit)? = null,
    refSong: String? = null, refCh: String? = null, refWork: String? = null
) {
    val color = MaterialTheme.colorScheme.onSurface
    val linkColor = MaterialTheme.colorScheme.primary
    val colorOs = remember { isColorOs() }
    // Фон для стирания стоковой строки при своей оправке (см. JustifyTextView)
    val bgArgb = MaterialTheme.colorScheme.background.toArgb()
    val spanned = remember(html) {
        GbHtml.normalizeSpanned(HtmlCompat.fromHtml(GbHtml.rich(html), HtmlCompat.FROM_HTML_MODE_LEGACY, null, null).trim())
    }
    val noteCb = rememberUpdatedState(onSaveNote)
    val askCb = rememberUpdatedState(onAsk)
    val refCb = rememberUpdatedState(onVerseRef)
    val withRefs = remember(spanned, refSong, refCh, refWork) {
        if (onVerseRef == null) spanned
        else attachVerseRefs(spanned, refCb, refSong, refCh, refWork)
    }
    // Готовый текст с подсветкой: считается только при смене html/highlight.
    // ВАЖНО: tv.text НЕ трогаем при каждой рекомпозиции (скролл!), иначе слетает
    // активное выделение — ставим только когда содержимое реально изменилось.
    // Центр — ещё и спаном (прошивки вроде ColorOS игнорируют gravity/TextView-параметры,
    // а спан — уровень Layout, его не перебить).
    val rendered = remember(withRefs, highlight, center) {
        val base = android.text.SpannableString(withRefs)
        if (center) {
            base.setSpan(
                android.text.style.AlignmentSpan.Standard(android.text.Layout.Alignment.ALIGN_CENTER),
                0, base.length, android.text.Spanned.SPAN_INCLUSIVE_INCLUSIVE
            )
        }
        if (highlight.isNotBlank()) {
            for (r in GbHtml.highlightRanges(base.toString(), highlight)) {
                base.setSpan(
                    android.text.style.BackgroundColorSpan(0xFFFFFF00.toInt()),
                    r.first, r.last + 1,
                    android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
                )
            }
        }
        base
    }
    // Свой MovementMethod: системный LinkMovementMethod проигрывает борьбу за тап
    // selectable-тексту (ссылка срабатывает через раз) — этот бьёт точно по спану
    val linkMovement = remember { VerseLinkMovementMethod() }
    // Колбэк выделения ставится ОДИН раз в factory: пересоздание при рекомпозиции
    // роняет активное выделение. Свежесть обработчиков — через State-держатели
    val hasRefs = onVerseRef != null
    AndroidView(
        // Чуть полей по бокам: глифы у самого края экрана зрительно обрезаются
        modifier = modifier.padding(horizontal = 4.dp),
        factory = { ctx ->
            JustifyTextView(ctx).apply {
                setTextIsSelectable(true)
                if (hasRefs) movementMethod = linkMovement
                customSelectionActionModeCallback =
                    if (onSaveNote == null && onAsk == null) null
                    else NoteActionMode(this, noteCb, askCb)
            }
        },
        update = { tv ->
            // ВАЖНО: текст ставим только когда содержимое реально изменилось,
            // иначе слетает активное выделение при скролле/рекомпозиции.
            if (tv.getTag() !== rendered) {
                tv.setTag(rendered)
                tv.text = rendered
            }
            tv.textSize = fontSizeSp
            tv.setTextColor(color.toArgb())
            // Переносы для ровного края. Межстрочку не трогаем (=1.0).
            // ColorOS рвёт слова без дефиса («ука зывает») — там переносы выключаем.
            tv.hyphenationFrequency = if (colorOs) android.text.Layout.HYPHENATION_FREQUENCY_NONE
                else android.text.Layout.HYPHENATION_FREQUENCY_FULL
            // Noto Serif вместо системного: диакритика из того же файла, без «жирных» подмен
            readTypeface(tv.context, bold)?.let { tv.typeface = it }
                ?: tv.setTypeface(null, if (bold) android.graphics.Typeface.BOLD else android.graphics.Typeface.NORMAL)
            tv.gravity = if (center) Gravity.CENTER_HORIZONTAL else Gravity.START
            // Глифы у края (бреве й, курсивные выносы) не режем границей контейнера:
            // сам TextView резать не умеет (clipToPadding — только у ViewGroup),
            // поэтому снимаем клиппинг с родителя (Compose по умолчанию не клиппит)
            try {
                (tv.parent as? android.view.ViewGroup)?.let {
                    it.clipChildren = false
                    it.clipToPadding = false
                }
            } catch (_: Exception) { }
            // textAlignment старше gravity: прошивки вроде ColorOS иногда подменяют
            // дефолт выравнивания — явным значением их не перебить иначе.
            // Не-центр возвращаем в INHERIT (стоковое поведение, justify не ломаем).
            tv.textAlignment = if (center) android.view.View.TEXT_ALIGNMENT_CENTER
            else android.view.View.TEXT_ALIGNMENT_INHERIT
            // Выравнивание по ширине (перевод, комментарий). Константы — graphics.text.LineBreaker
            // (Layout.* те же значения, lint WrongConstant). minSdk 26 — гейт по SDK не нужен.
            // breakStrategy выставляем явно: на части прошивок дефолт SIMPLE, с ним
            // justification местами не применяется. Остальным секциям стратегию не трогаем.
            val manual = justify && !center && colorOs
            (tv as? JustifyTextView)?.let { it.justifyManual = manual; it.eraseArgb = bgArgb }
            if (justify && !center) {
                if (colorOs) {
                    // Стоковая INTER_WORD на ColorOS переполняла строки — правый край
                    // обрезался (патч прошивки, react-native#58652). Своё растяжение
                    // пробелов рисует JustifyTextView. Строка — SIMPLE (жадный разрыв):
                    // BALANCED делил абзац ~пополам и extra на первой строке вырастал
                    // до половины ширины — отсюда гигантские пробелы «в пустоту влезло
                    // бы слово следующей строки». Жадный разрыв: extra < ширины слова.
                    tv.breakStrategy = android.graphics.text.LineBreaker.BREAK_STRATEGY_SIMPLE
                    tv.justificationMode = android.graphics.text.LineBreaker.JUSTIFICATION_MODE_NONE
                } else {
                    // HIGH_QUALITY на части прошивок молча не работает — там BALANCED
                    tv.breakStrategy = android.graphics.text.LineBreaker.BREAK_STRATEGY_HIGH_QUALITY
                    tv.justificationMode = android.graphics.text.LineBreaker.JUSTIFICATION_MODE_INTER_WORD
                }
            } else {
                tv.justificationMode = android.graphics.text.LineBreaker.JUSTIFICATION_MODE_NONE
            }
            if (hasRefs) tv.setLinkTextColor(linkColor.toArgb())
        }
    )
}

/** ColorOS: стоковая оправка (INTER_WORD) переполняла строки — правый край
 *  обрезался. Здесь оправка своя: строки ломает TextView (BALANCED), а пробелы
 *  не-последних строк абзаца растягиваем при рисовании: super.onDraw рисует
 *  стоково, поверх заливаем строку фоном темы и рисуем её заново, добавляя
 *  одинаковый gap после каждого слова кроме последнего (последняя строка
 *  абзаца не оправлена — как в стоке). Выделение НЕ выключает оправку (текст
 *  не прыгает при long-press): фон выделения красится в растянутых координатах,
 *  события тача отображаются в стоковые (mapToStock). Хэндлы при этом стираются
 *  (их позиции считает стоковый layout) — диапазон тянется повторным long-press.
 *  Включается только из HtmlText при justify && !center && isColorOs();
 *  на прочих аппаратах класс просто дублирует TextView. */
private class JustifyTextView(ctx: android.content.Context) : android.widget.TextView(ctx) {
    var justifyManual: Boolean = false
    var eraseArgb: Int = android.graphics.Color.BLACK

    /** Одно слово строки с уже применёнными span-ами (подсветка, ссылки, курсив). */
    private fun wordPaint(sp: android.text.Spanned, s: Int, e: Int): android.text.TextPaint {
        val tp = android.text.TextPaint(paint)
        for (cs in sp.getSpans(s, e, android.text.style.CharacterStyle::class.java)) {
            if (sp.getSpanStart(cs) < e && s < sp.getSpanEnd(cs)) {
                try { cs.updateDrawState(tp) } catch (_: Exception) { }
            }
        }
        return tp
    }

    private fun hasRealSelection(): Boolean = try {
        val s = selectionStart
        val e = selectionEnd
        s >= 0 && e >= 0 && s != e
    } catch (_: Exception) { false }

    /** Слова строки с растянутыми позициями (x0/x1 — рисованные, stockX0 —
     *  стоковая позиция начала слова для обратного маппинга тапов).
     *  null = строку не оправляем (последняя в абзаце, запаса нет, <2 слов). */
    fun lineSegs(line: Int): List<Seg>? {
        if (!justifyManual) return null
        val layout = layout ?: return null
        if (line < 0 || line >= layout.lineCount) return null
        val sp = text as? android.text.Spanned ?: return null
        val le = layout.getLineEnd(line)
        if (le <= 0 || le >= sp.length || sp[le - 1] == '\n') return null
        val ls = layout.getLineStart(line)
        val ve = layout.getLineVisibleEnd(line)
        if (ve <= ls) return null
        // Разбивка на слова по обычному пробелу (NBSP остаётся частью слова)
        val ranges = ArrayList<Pair<Int, Int>>()
        var i = ls
        while (i < ve) {
            while (i < ve && sp[i] == ' ') i++
            if (i >= ve) break
            var j = i
            while (j < ve && sp[j] != ' ') j++
            ranges.add(i to j)
            i = j
        }
        if (ranges.size < 2) return null
        val targetW = (width - paddingLeft - paddingRight).toFloat()
        val extra = targetW - layout.getLineWidth(line)
        if (extra < 1f) return null
        val add = extra / (ranges.size - 1)
        val spaceW = paint.measureText(" ")
        val segs = ArrayList<Seg>(ranges.size)
        var x = 0f
        for ((s, e) in ranges) {
            val w = wordPaint(sp, s, e).measureText(sp, s, e)
            val stockX = try { layout.getPrimaryHorizontal(s) } catch (_: Exception) { 0f }
            segs.add(Seg(s, e, x, x + w, stockX))
            x += w + spaceW + add
        }
        return segs
    }

    data class Seg(val s: Int, val e: Int, val x0: Float, val x1: Float, val stockX0: Float)

    /** Позиция символа в РИСОВАННЫХ координатах оправляемой строки (фон выделения) */
    private fun selX(segs: List<Seg>, off: Int): Float {
        if (off <= segs.first().s) return segs.first().x0
        for (sg in segs) {
            if (off <= sg.e) {
                if (off <= sg.s) return sg.x0
                val f = (off - sg.s).toFloat() / (sg.e - sg.s).coerceAtLeast(1)
                return sg.x0 + f * (sg.x1 - sg.x0)
            }
        }
        return segs.last().x1
    }

    /** x под пальцем (рисованный) -> стоковый: кусочно-линейно внутри слова,
     *  в gap — к началу ближайшего слова. Нужен, чтобы выделение/тап по символу
     *  не бродил по соседним словам оправленной строки. */
    private fun mapToStock(segs: List<Seg>, xDrawn: Float): Float {
        val layout = layout ?: return xDrawn
        val last = segs.last()
        if (xDrawn <= segs.first().x0) return segs.first().stockX0
        if (xDrawn >= last.x1) {
            return try { layout.getPrimaryHorizontal(last.e) } catch (_: Exception) { last.stockX0 }
        }
        for (sg in segs) {
            if (xDrawn <= sg.x1) {
                if (xDrawn <= sg.x0) return sg.stockX0
                val stockW = try {
                    layout.getPrimaryHorizontal(sg.e) - layout.getPrimaryHorizontal(sg.s)
                } catch (_: Exception) { sg.x1 - sg.x0 }
                val f = (xDrawn - sg.x0) / (sg.x1 - sg.x0).coerceAtLeast(1f)
                return sg.stockX0 + f * stockW
            }
        }
        return last.stockX0
    }

    /** Событие приходит в РИСОВАННЫХ координатах, TextView ждёт стоковые —
     *  отдаём super копию со сдвинутым x (все указатели сдвигом одного). */
    private fun transformForJustify(event: android.view.MotionEvent): android.view.MotionEvent? {
        if (!justifyManual) return null
        val layout = layout ?: return null
        val line = try {
            layout.getLineForVertical((event.y - compoundPaddingTop + scrollY).toInt())
        } catch (_: Exception) { return null }
        val segs = lineSegs(line) ?: return null
        val xDrawn = event.x - compoundPaddingLeft + scrollX
        val stockX = mapToStock(segs, xDrawn)
        val out = android.view.MotionEvent.obtain(event)
        out.offsetLocation((stockX + compoundPaddingLeft - scrollX) - event.x, 0f)
        return out
    }

    override fun onTouchEvent(event: android.view.MotionEvent): Boolean {
        val t = try { transformForJustify(event) } catch (_: Exception) { null }
        if (t == null) return super.onTouchEvent(event)
        return try { super.onTouchEvent(t) } finally { t.recycle() }
    }

    /** Оправляемые строки: стоковая строка стирается, выделение красится фоном
     *  (таким же цветом, как сток), слова рисуются с растянутыми gap-ами.
     *  Выделение больше НЕ выключает оправку — текст не прыгает при long-press. */
    private fun paintManual(canvas: android.graphics.Canvas) {
        val layout = layout ?: return
        val sp = text as? android.text.Spanned ?: return
        val targetW = (width - paddingLeft - paddingRight).toFloat()
        if (targetW <= 2f) return
        val erase = android.graphics.Paint().apply { color = eraseArgb }
        val bgs = sp.getSpans(0, sp.length, android.text.style.BackgroundColorSpan::class.java)
        val selS = selectionStart
        val selE = selectionEnd
        val selPaint = if (selS >= 0 && selE > selS) {
            android.graphics.Paint().apply { color = highlightColor }
        } else null
        canvas.save()
        canvas.translate((compoundPaddingLeft - scrollX).toFloat(), (compoundPaddingTop - scrollY).toFloat())
        for (line in 0 until layout.lineCount) {
            val segs = lineSegs(line) ?: continue
            val top = layout.getLineTop(line).toFloat()
            val bottom = layout.getLineBottom(line).toFloat()
            val baseline = layout.getLineBaseline(line).toFloat()
            // Стираем стоковую строку (на ColorOS она была шире вью — обрезана)
            canvas.drawRect(0f, top, maxOf(targetW, layout.getLineWidth(line) + 16f), bottom, erase)
            // Фон выделения — по растянутым словам (штатный рисуется стоково и соврал бы)
            if (selPaint != null && selE > layout.getLineStart(line) && selS < layout.getLineVisibleEnd(line)) {
                val x0 = selX(segs, selS)
                val x1 = selX(segs, selE)
                if (x1 > x0) canvas.drawRect(x0, top, x1, bottom, selPaint)
            }
            // Подсветка из поиска (жёлтый) — по словам, попавшим в диапазон спана
            for (bg in bgs) {
                val bs = sp.getSpanStart(bg)
                val be = sp.getSpanEnd(bg)
                if (be <= segs.first().s || bs >= segs.last().e) continue
                val from = segs.firstOrNull { it.e > bs } ?: continue
                val to = segs.lastOrNull { it.s < be } ?: continue
                if (from.x1 <= from.x0 || to.x1 <= from.x0) continue
                val bp = android.graphics.Paint().apply { color = bg.backgroundColor }
                canvas.drawRect(from.x0, top, to.x1, bottom, bp)
            }
            for (sg in segs) {
                canvas.drawText(sp, sg.s, sg.e, sg.x0, baseline, wordPaint(sp, sg.s, sg.e))
            }
        }
        canvas.restore()
    }

    override fun onDraw(canvas: android.graphics.Canvas) {
        super.onDraw(canvas)
        if (justifyManual) paintManual(canvas)
    }

    override fun draw(canvas: android.graphics.Canvas) {
        super.draw(canvas)
        // Выделение хэндлами/курсором может рисоваться Editor'ом ПОСЛЕ onDraw
        // (поверх оправки, стоковыми координатами) — прогоняем строки ещё раз:
        // стоковое выделение застирается, наше (растянутое) остаётся.
        // Побочно стираются хэндлы: их позиции привязаны к стоковому layout,
        // невосстановимы без reflection — диапазон тянется повторным long-press,
        // меню «В заметку» и копирование работают.
        if (justifyManual && hasRealSelection()) paintManual(canvas)
    }
}

/** ColorOS-семейство (Oppo/OnePlus/Realme): местами чудит нативный Layout —
 *  игнорирует gravity/выравнивание. Таким — запасной путь через спан/брейкер. */
private fun isColorOs(): Boolean {
    val m = try { android.os.Build.MANUFACTURER ?: "" } catch (_: Exception) { "" }
    return m.equals("OPPO", ignoreCase = true) ||
            m.equals("OnePlus", ignoreCase = true) ||
            m.equals("Realme", ignoreCase = true)
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
/** Полные имена произведений в прозе («Шримад-Бхагаватам, 1.8.19») */
private val REF3_FULL = Regex(
    """(?:^|(?<=[\s(«"“']))(Шримад-Бхагаватам[ауы]?|Бхагавад-гит[ауые]|Чайтанья Чаритамрит[ауы]),?\s*(\d+)\s*[.]\s*(\d+)\s*[.]\s*(\d+)""",
    setOf(RegexOption.IGNORE_CASE)
)
private val REF2_FULL = Regex(
    """(?:^|(?<=[\s(«"“']))(Бхагавад-гит[ауые])(?!\s*\d+\s*[.]\s*\d+\s*[.]\s*\d)[.,]?\s*(\d+)\s*[.]\s*(\d+)(?!\s*[.]\s*\d)""",
    setOf(RegexOption.IGNORE_CASE)
)
private val REF_FULL_CODE = mapOf(
    "шримад-бхагаватам" to "SB", "шримад-бхагаватама" to "SB", "шримад-бхагаватаму" to "SB",
    "бхагавад-гита" to "BG", "бхагавад-гиты" to "BG", "бхагавад-гиту" to "BG", "бхагавад-гите" to "BG",
    "чайтанья чаритамрита" to "CC", "чайтанья чаритамриты" to "CC", "чайтанья чаритамриту" to "CC"
)
/** Брахма-самхита: номер — всегда глава.стих при песне 1 главе 5 */
private val REF_BS = Regex(
    """(?:^|(?<=[\s(«"“']))(Брахма-самхит[ауы]|Брахма Самхит[ауы]|БС|BS)\s*,?\s*5\s*[.]\s*(\d{1,2})""",
    setOf(RegexOption.IGNORE_CASE)
)
/** Коды произведений для gr:// ссылок (верхний регистр).
 *  vedic/gaudia-коды (KU/SVU/...) книг, которых нет — резолв честно скажет «нет книги». */
private val GR_CODE = setOf(
    "SB", "BG", "CC", "BS", "ISO", "NOD", "NOI", "TLC", "KB", "TQK", "MM", "NBS",
    "BRS", "SBRS",
    "LBG", "LSB", "TLKS", "LCC", "LISO", "LTRS", "LTR", "BG72",
    "KU", "SVU", "MU", "VS", "VP", "BAU", "BRS", "GGD"
)
/** Код перед цифрами («SB 5.5.3», «ШБ 1.8.19») — чтобы вся цитата была ссылкой */
private val GR_CODE_BEFORE = Regex(
    """(SB|BG|CC|BS|ISO|NOD|NOI|TLC|KB|TQK|ШБ|БГ|ЧЧ)\s*$""",
    setOf(RegexOption.IGNORE_CASE)
)
/** Голые тройки без кода («1.6.82», «(3.1.34-64)»): песнь 1-3 — ЧЧ или ШБ, 4+ — точно ШБ */
private val REF3_BARE = Regex(
    """(?:^|(?<=[\s(«"“']))(\d{1,2})\s*[.]\s*(\d{1,2})\s*[.]\s*(\d{1,3})(?:\s*[–—-]\s*[\d.,\s]+)?"""
)
/** Голые пары («(8.134)», «6.132»): глава.стих в песне текущей лекции */
private val REF2_BARE = Regex(
    """(?:^|(?<=[\s(«"“']))(\d{1,2})\s*[.]\s*(\d{1,3})(?!\s*[.]\s*\d)(?:\s*[–—-]\s*\d{1,3})?"""
)
/** Лила словом («ЧЧ Ади Лила 1.1», «ЧЧ Мадхья 5.12») */
private val REF_LILA = Regex(
    """(?:^|(?<=[\s(«"“']))(ЧЧ|чч|CC|Cc|cc)\s+(Ади|Мадхья|Антья|ади|мадхья|антья)\s*(?:[-–—]?\s*[Лл]ила)?\s*(\d{1,2})\s*[.]\s*(\d{1,3})"""
)
private val LILA_SONG = mapOf("ади" to "1", "мадхья" to "2", "антья" to "3")

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
    cb: State<((String, String, String, String, String?) -> Unit)?>,
    refSong: String? = null,
    refCh: String? = null,
    refWork: String? = null
): CharSequence {
    val str = s.toString()
    val out = android.text.SpannableStringBuilder.valueOf(if (s is android.text.Spanned) s else str)
    val taken = mutableListOf<IntRange>()
    fun free(r: IntRange) = taken.none { it.first <= r.last && r.first <= it.last }
    fun link(code: String, song: String, ch: String, txt: String, range: IntRange) {
        if (!free(range)) return
        out.setSpan(
            VerseRefSpan(code, song, ch, txt, null, cb),
            range.first, range.last + 1, android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
        )
        taken += range
    }
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
    // Полные имена произведений («Шримад-Бхагаватам, 1.8.19», «Бхагавад-гита 2.13»)
    for (m in REF3_FULL.findAll(str)) {
        val code = REF_FULL_CODE[m.groupValues[1].lowercase()] ?: continue
        if (!free(m.range)) continue
        out.setSpan(
            VerseRefSpan(code, m.groupValues[2], m.groupValues[3], m.groupValues[4], null, cb),
            m.range.first, m.range.last + 1, android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
        )
        taken += m.range
    }
    for (m in REF2_FULL.findAll(str)) {
        val code = REF_FULL_CODE[m.groupValues[1].lowercase()] ?: continue
        if (!free(m.range)) continue
        out.setSpan(
            VerseRefSpan(code, "1", m.groupValues[2], m.groupValues[3], null, cb),
            m.range.first, m.range.last + 1, android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
        )
        taken += m.range
    }
    // Брахма-самхита: всегда песнь 1 глава 5 («Брахма-самхита, 5.29», «БС 5.1»)
    for (m in REF_BS.findAll(str)) {
        if (!free(m.range)) continue
        out.setSpan(
            VerseRefSpan("BS", "1", "5", m.groupValues[1], null, cb),
            m.range.first, m.range.last + 1, android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
        )
        taken += m.range
    }
    // Голые номера из лекций (контекст песни/главы — из самой лекции).
    // Нет контекста (обычные книги) — не трогаем во избежание ложных ссылок.
    // Произведение — ТОЛЬКО своё: голые номера лекций БРС ищутся в БРС,
    // а не в ЧЧ/ШБ (иначе совпадающие номера уводят в чужую книгу).
    if (refSong != null && refCh != null) {
        val first = when (refWork ?: "CC") {
            "SB" -> "SB/CC"
            "BRS" -> "BRS"
            else -> "CC/SB"
        }
        for (m in REF3_BARE.findAll(str)) {
            val song = m.groupValues[1]
            // песнь 1-3 — ЧЧ или ШБ, 4+ — точно ШБ; у БРС свои 4 раздела — всегда БРС
            val code = if (first == "BRS") "BRS"
            else if ((song.toIntOrNull() ?: 99) >= 4) "SB" else first
            link(code, song, m.groupValues[2], m.groupValues[3], m.range)
        }
        for (m in REF_LILA.findAll(str)) {
            val song = LILA_SONG[m.groupValues[2].lowercase()] ?: continue
            link("CC", song, m.groupValues[3], m.groupValues[4], m.range)
        }
        for (m in REF2_BARE.findAll(str)) {
            link(refWork ?: "CC", refSong, m.groupValues[1], m.groupValues[2], m.range)
        }
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
 * Активное выделение свято: пока оно есть, жест целиком отдаём TextView
 * (расширение выделения, перемещение курсора), ссылки не кликаем.
 * КЛЮЧЕВОЕ: и ACTION_DOWN не отдаём LinkMovementMethod — он на касании вне
 * ссылки делает Selection.removeSelection (AOSP LinkMovementMethod.java) и
 * выделение падало В МОМЕНТ касания, с которого начинался свайп-скролл.
 * Нативный путь TextView (movement вернул false — как и раньше) хэндлы и
 * скролл ведёт сам, выделение при этом не трогает.
 */
private class VerseLinkMovementMethod : android.text.method.LinkMovementMethod() {
    private var downSpan: android.text.style.ClickableSpan? = null
    private var downX = 0f
    private var downY = 0f
    // Было ли НАСТОЯЩЕЕ выделение (диапазон start!=end) на момент DOWN.
    // TextView.hasSelection() считает и collapsed-курсор — guard по нему
    // блокировал бы клики ссылок после любого тапа, поставившего курсор
    private fun hasRealSelection(widget: TextView): Boolean = try {
        val s = widget.selectionStart
        val e = widget.selectionEnd
        s >= 0 && e >= 0 && s != e
    } catch (_: Exception) { false }
    private var hadSelectionAtDown = false

    private fun spanAt(widget: TextView, buffer: android.text.Spannable, event: android.view.MotionEvent): android.text.style.ClickableSpan? {
        val x = event.x.toInt() - widget.totalPaddingLeft + widget.scrollX
        val y = event.y.toInt() - widget.totalPaddingTop + widget.scrollY
        val layout = widget.layout ?: return null
        // Строка может не успеть за жестом — глушим всё, что бросает Layout
        val line = try {
            layout.getLineForVertical(y)
        } catch (_: Exception) { return null }
        val off = try {
            // JustifyTextView отдаёт события уже в стоковых координатах
            // (transformForJustify в onTouchEvent) — здесь просто offset
            layout.getOffsetForHorizontal(line, x.toFloat())
        } catch (_: Exception) { return null }
        buffer.getSpans(off, off, android.text.style.ClickableSpan::class.java).firstOrNull()?.let { return it }
        // Запасной вариант: тап у самой границы спана (±1px, только строго внутри)
        return try {
            buffer.getSpans(off - 1, off + 1, android.text.style.ClickableSpan::class.java)
                .firstOrNull {
                    buffer.getSpanStart(it) < off && off < buffer.getSpanEnd(it)
                }
        } catch (_: Exception) { null }
    }

    override fun onTouchEvent(
        widget: TextView, buffer: android.text.Spannable, event: android.view.MotionEvent
    ): Boolean {
        if (event.action == android.view.MotionEvent.ACTION_DOWN) {
            hadSelectionAtDown = hasRealSelection(widget)
            if (hadSelectionAtDown) {
                // Выделение свято: DOWN НЕ уходит в super (LinkMovementMethod) —
                // там removeSelection убивал выделение в момент касания, с которого
                // начинался свайп-скролл. Возвращаем false: TextView обрабатывает
                // касание нативно (хэндлы, длинное нажатие для нового выделения),
                // но выделение не снимает. Ссылки при активном выделении не кликаем.
                downSpan = null
                return false
            }
        } else if (hasRealSelection(widget) && hadSelectionAtDown) {
            // Выделение тянул сам пользователь — не мешаем, ссылки не кликаем
            downSpan = null
            return false
        }
        when (event.action) {
            android.view.MotionEvent.ACTION_DOWN -> {
                downSpan = try { spanAt(widget, buffer, event) } catch (_: Exception) { null }
                downX = event.x
                downY = event.y
            }
            android.view.MotionEvent.ACTION_MOVE -> {
                // Увели палец дальше slop — это скролл/выделение, а не тап по ссылке
                val slop = try {
                    android.view.ViewConfiguration.get(widget.context).scaledTouchSlop
                } catch (_: Exception) { 16 }
                if (downSpan != null &&
                    (kotlin.math.abs(event.x - downX) > slop || kotlin.math.abs(event.y - downY) > slop)
                ) {
                    downSpan = null
                    return false
                }
            }
            android.view.MotionEvent.ACTION_UP -> {
                val up = try { spanAt(widget, buffer, event) } catch (_: Exception) { null }
                val down = downSpan
                downSpan = null
                try {
                    android.util.Log.d(
                        "SelMenu",
                        "up downFound=" + (down != null) + " upFound=" + (up != null) +
                            " same=" + (down != null && up === down)
                    )
                } catch (_: Exception) { }
                if (down != null && up === down) {
                    down.onClick(widget)
                    return true
                }
            }
            else -> downSpan = null
        }
        return super.onTouchEvent(widget, buffer, event)
    }
}

/** Порядок меню выделения: В заметку -> Вопрос -> Скопировать -> …системные… -> Перевести.
 *  Прошивка игнорирует order системных пунктов, поэтому системный Translate прячем
 *  (узнаём по подписи) и кладём свой последним — с ручным вызовом переводчика. */
private class NoteActionMode(
    val tv: TextView,
    val onNote: androidx.compose.runtime.State<((String) -> Unit)?>,
    val onAsk: androidx.compose.runtime.State<((String) -> Unit)?>
) : ActionMode.Callback {
    companion object {
        const val ID_NOTE = 0x7E57; const val ID_ASK = 0x7E58; const val ID_COPY = 0x7E59
        const val ID_TRANSLATE = 0x7E5A; const val ID_SELECT_ALL = 0x7E5B
    }

    /** Xiaomi/HyperOS ставит системные пункты первыми, а наши — в «…», игнорируя order.
     *  Там единственный рычаг — физическая пересборка меню. На остальных (Oppo и др.)
     *  работает мягкий вариант, его не трогаем. */
    private fun isXiaomi(): Boolean {
        val m = try { android.os.Build.MANUFACTURER ?: "" } catch (_: Exception) { "" }
        return m.equals("Xiaomi", ignoreCase = true) ||
                m.equals("Redmi", ignoreCase = true) ||
                m.equals("POCO", ignoreCase = true)
    }

    private fun selected(): String? {
        val s = tv.selectionStart
        val e = tv.selectionEnd
        return if (s >= 0 && e > s) tv.text.substring(s, e).toString() else null
    }

    private fun copySel(): Boolean {
        val s = selected() ?: return false
        return try {
            val cm = tv.context.getSystemService(android.content.ClipboardManager::class.java)
            cm.setPrimaryClip(android.content.ClipData.newPlainText("text", s))
            true
        } catch (_: Exception) { false }
    }

    /** Системный пункт переводчика: узнаём по подписи (Перевести/Translate),
     *  запасной признак — пустая подпись + intent PROCESS_TEXT (пункт-иконка без текста) */
    private fun isTranslateItem(mi: MenuItem): Boolean {
        if (mi.itemId == ID_TRANSLATE) return false
        val t = try { mi.title?.toString() ?: "" } catch (_: Exception) { "" }
        val low = t.lowercase()
        if ("еревес" in low || "ranslat" in low) return true.also { logTv(mi, t, true) }
        if (t.isBlank()) {
            val act = try { mi.intent?.action } catch (_: Exception) { null }
            if (act == android.content.Intent.ACTION_PROCESS_TEXT) {
                logTv(mi, t, true)
                return true
            }
        }
        logTv(mi, t, false)
        return false
    }

    private fun logTv(mi: MenuItem, title: String, hit: Boolean) {
        try {
            android.util.Log.d("SelMenu", "item id=${mi.itemId} title='$title' hit=$hit")
        } catch (_: Exception) { }
    }

    private fun translateSel() {
        val s = selected() ?: return
        try {
            val intent = android.content.Intent(android.content.Intent.ACTION_PROCESS_TEXT)
                .setType("text/plain")
                .putExtra(android.content.Intent.EXTRA_PROCESS_TEXT, s)
                .putExtra(android.content.Intent.EXTRA_PROCESS_TEXT_READONLY, true)
            tv.context.startActivity(android.content.Intent.createChooser(intent, s.take(40)))
        } catch (_: Exception) { }
    }

    override fun onCreateActionMode(mode: ActionMode?, menu: Menu?) = true.also {
        try {
            android.util.Log.d("SelMenu", "onCreate n=" + (menu?.size() ?: -1))
        } catch (_: Exception) { }
        menu?.removeItem(android.R.id.copy)
        if (onNote.value != null && menu?.findItem(ID_NOTE) == null) menu?.add(Menu.NONE, ID_NOTE, 0, "В заметку")
        if (onAsk.value != null && menu?.findItem(ID_ASK) == null) menu?.add(Menu.NONE, ID_ASK, 1, "Вопрос")
        if (menu?.findItem(ID_COPY) == null) menu?.add(Menu.NONE, ID_COPY, 2, "Скопировать")
        if (isXiaomi()) {
            // Свой «Выделить всё» (системный ниже выкидываем, чтобы не двоился)
            if (menu?.findItem(ID_SELECT_ALL) == null) menu?.add(Menu.NONE, ID_SELECT_ALL, 3, "Выделить всё")
            rebuildXiaomi(menu)
        }
        hideSystemTranslate(menu)
        // Прошивка дорисовывает системные пункты ПОСЛЕ показа меню (отсюда Translate
        // первым именно на фразах) — перепроверяем дважды с задержкой
        val m = menu
        try {
            tv.postDelayed({ try { hideSystemTranslate(m); mode?.invalidate() } catch (_: Exception) { } }, 250)
            tv.postDelayed({ try { hideSystemTranslate(m); mode?.invalidate() } catch (_: Exception) { } }, 800)
        } catch (_: Exception) { }
    }

    override fun onPrepareActionMode(mode: ActionMode?, menu: Menu?): Boolean {
        try {
            android.util.Log.d("SelMenu", "onPrepare n=" + (menu?.size() ?: -1))
        } catch (_: Exception) { }
        menu?.removeItem(android.R.id.copy)
        if (isXiaomi()) menu?.removeItem(android.R.id.selectAll)
        hideSystemTranslate(menu)
        return false
    }

    /** Xiaomi: снять системные пункты и вернуть после наших (порядок — физическим положением).
     *  Наши Копировать/Выделить всё уже добавлены выше; системные их дубли пропускаем.
     *  Клики системных идут по itemId/intent — переносим один в один */
    private fun rebuildXiaomi(menu: Menu?) {
        data class Saved(
            val group: Int, val id: Int, val order: Int, val title: CharSequence?,
            val icon: android.graphics.drawable.Drawable?,
            val intent: android.content.Intent?
        )
        menu?.let {
            val rest = mutableListOf<Saved>()
            for (i in 0 until it.size()) {
                val mi = it.getItem(i)
                if (mi.itemId == android.R.id.copy || mi.itemId == android.R.id.selectAll) continue
                if (mi.itemId == ID_NOTE || mi.itemId == ID_ASK ||
                    mi.itemId == ID_COPY || mi.itemId == ID_SELECT_ALL || mi.itemId == ID_TRANSLATE
                ) continue
                rest += Saved(mi.groupId, mi.itemId, mi.order, mi.title, mi.icon,
                    try { mi.intent } catch (_: Exception) { null })
            }
            it.clear()
            if (onNote.value != null) it.add(Menu.NONE, ID_NOTE, 0, "В заметку")
            if (onAsk.value != null) it.add(Menu.NONE, ID_ASK, 1, "Вопрос")
            it.add(Menu.NONE, ID_COPY, 2, "Скопировать")
            it.add(Menu.NONE, ID_SELECT_ALL, 3, "Выделить всё")
            for (s in rest) {
                try {
                    it.add(s.group, s.id, s.order, s.title)?.apply {
                        s.icon?.let { icon = it }
                        s.intent?.let { intent = it }
                        setShowAsAction(MenuItem.SHOW_AS_ACTION_IF_ROOM)
                    }
                } catch (_: Exception) { }
            }
        }
    }

    /** Системный Translate — в конец своим пунктом (переносим подпись, клик — наш, рабочий).
     *  Зовём и из onCreate, и из onPrepare: на одних прошивках системные пункты есть
     *  уже в onCreate, на других (многословное выделение) доезжают позже.
     *  ВАЖНО: прячем КАЖДЫЙ найденный (без break!) — прошивка пере-добавляет свой
     *  при каждом invalidate, а гард «наш уже есть» блокировал повторное скрытие */
    private fun hideSystemTranslate(menu: Menu?) {
        menu?.let {
            for (i in 0 until it.size()) {
                val mi = it.getItem(i)
                if (isTranslateItem(mi)) {
                    mi.isVisible = false
                    if (it.findItem(ID_TRANSLATE) == null) {
                        val label = try { mi.title?.toString().takeUnless { s -> s.isNullOrBlank() } ?: "Перевести" }
                        catch (_: Exception) { "Перевести" }
                        it.add(Menu.NONE, ID_TRANSLATE, 100, label)
                    }
                }
            }
        }
    }

    override fun onActionItemClicked(mode: ActionMode?, item: MenuItem?): Boolean {
        when (item?.itemId) {
            ID_NOTE -> { val cb = onNote.value; if (cb != null) selected()?.let(cb); mode?.finish(); return true }
            ID_ASK -> { val cb = onAsk.value; if (cb != null) selected()?.let(cb); mode?.finish(); return true }
            ID_COPY -> { if (copySel()) mode?.finish(); return true }
            ID_SELECT_ALL -> {
                try { tv.onTextContextMenuItem(android.R.id.selectAll) } catch (_: Exception) { }
                return true
            }
            ID_TRANSLATE -> { translateSel(); mode?.finish(); return true }
        }
        return false
    }

    override fun onDestroyActionMode(mode: ActionMode?) {}
}
