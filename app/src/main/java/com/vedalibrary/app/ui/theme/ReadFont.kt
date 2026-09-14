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
 * Noto Serif для читаемых текстов: полное покрытие IAST-диакритики
 * (ā ī ū ṛ ṃ ḥ ṅ ñ ṇ ṭ ḍ ś ṣ) + кириллица. Без него системный Roboto подменяет
 * отсутствующие глифы запасным шрифтом — отсюда «жирные» буквы с точками.
 * UI-хром (заголовки, кнопки, меню) остаётся системным.
 */
val ReadSerif = FontFamily(
    Font(R.font.noto_serif_regular, FontWeight.Normal),
    Font(R.font.noto_serif_bold, FontWeight.Bold),
    Font(R.font.noto_serif_italic, FontWeight.Normal, FontStyle.Italic)
)

private val typefaceCache = mutableMapOf<Boolean, Typeface?>()

/** Typeface для TextView (HtmlText). Кэшируется на процесс. */
@Synchronized
fun readTypeface(ctx: Context, bold: Boolean): Typeface? {
    typefaceCache[bold]?.let { return it }
    val tf = try {
        ResourcesCompat.getFont(ctx.applicationContext, if (bold) R.font.noto_serif_bold else R.font.noto_serif_regular)
    } catch (_: Exception) { null }
    typefaceCache[bold] = tf
    return tf
}
