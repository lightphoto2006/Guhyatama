package com.vedalibrary.app.ui.components

import androidx.compose.foundation.text.ClickableText
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import com.vedalibrary.app.ui.theme.ReadSerif
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.sp

/**
 * Строка пословника: "dehe — in the body" — слово жирным и кликабельно (экран вхождений),
 * перевод на той же строке.
 * cyrillic=true (rus-книги): слово показываем кириллицей (дхритараштрах), а ищем по латыни.
 */
@Composable
fun SynonymLine(entry: String, fontSizeSp: Float, onWordClick: (String) -> Unit, modifier: Modifier = Modifier, cyrillic: Boolean = false, highlight: String = "") {
    val (word, rest) = remember(entry) { GbHtml.splitHead(entry) }
    val shown = remember(entry, cyrillic) { if (cyrillic) IastCyrillic.convert(word) else word }
    val annotated = remember(entry, shown, highlight) {
        buildAnnotatedString {
            if (word.isNotEmpty()) {
                pushStringAnnotation("word", word)
                withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(highlighted(shown, highlight)) }
                pop()
                append(" ")
            }
            // Перевод — обычным начертанием, но курсивом
            withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { append(highlighted(rest, highlight)) }
        }
    }
    ClickableText(
        text = annotated,
        modifier = modifier,
        style = LocalTextStyle.current.copy(fontSize = fontSizeSp.sp, color = MaterialTheme.colorScheme.onSurface, fontFamily = ReadSerif),
        onClick = { off ->
            annotated.getStringAnnotations("word", off, off).firstOrNull()?.let { onWordClick(it.item) }
        }
    )
}

/** Совпадение поиска — жёлтым фоном, остальное как есть (диакритика не важна) */
private fun highlighted(text: String, needle: String): AnnotatedString = buildAnnotatedString {
    if (needle.isBlank()) {
        append(text)
        return@buildAnnotatedString
    }
    val ranges = GbHtml.highlightRanges(text, needle)
    if (ranges.isEmpty()) {
        append(text)
        return@buildAnnotatedString
    }
    var i = 0
    for (r in ranges) {
        append(text.substring(i, r.first))
        withStyle(SpanStyle(background = Color.Yellow)) { append(text.substring(r.first, r.last + 1)) }
        i = r.last + 1
    }
    append(text.substring(i))
}
