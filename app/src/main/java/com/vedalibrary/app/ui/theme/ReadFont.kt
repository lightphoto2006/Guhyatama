package com.vedalibrary.app.ui.theme

import android.content.Context
import android.graphics.Typeface
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.core.content.res.ResourcesCompat
import com.vedalibrary.app.R

/**
 * Шрифт чтения — DejaVu Sans (проверенная читалка электронных книг):
 * отличная кириллица + IAST-диакритика (ā ī ū ṛ ṃ ḥ...), читается крупным кеглем.
 * Три настоящих начертания (regular/bold/oblique), жирность в пословнике — настоящим болдом.
 * UI-хром (заголовки, кнопки, меню) остаётся системным.
 */
val ReadFont = FontFamily(
    Font(R.font.dejavu_sans, FontWeight.Normal),
    Font(R.font.dejavu_sans_bold, FontWeight.Bold),
    Font(R.font.dejavu_sans_italic, FontWeight.Normal, FontStyle.Italic)
)

private val typefaceCache = mutableMapOf<Boolean, Typeface?>()

/** Typeface для TextView (HtmlText). Кэшируется на процесс. */
@Synchronized
fun readTypeface(ctx: Context, bold: Boolean): Typeface? {
    // containsKey: неудачная загрузка (null) тоже кэшируется, без повторных попыток
    if (typefaceCache.containsKey(bold)) return typefaceCache[bold]
    val tf = try {
        ResourcesCompat.getFont(
            ctx.applicationContext,
            if (bold) R.font.dejavu_sans_bold else R.font.dejavu_sans
        )
    } catch (_: Exception) { null }
    typefaceCache[bold] = tf
    return tf
}
