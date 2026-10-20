package com.vedalibrary.app.ui.components

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.PathFillType
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.path
import androidx.compose.ui.unit.dp

/** Звезда закладки — собственный вектор, а не текстовый глиф «★» и не иконка
 *  из material-icons-core: у core-звезды нет контурного варианта (неактивная
 *  закладка выглядела бы так же, как активная), а у текстового символа свои
 *  метрики — в одном ряду с шестерёнкой они разъезжались по вертикали.
 *  Оба состояния построены из одного контура, поэтому центры совпадают. */
object StarIcons {

    /** Залитая звезда (активная закладка). */
    val Filled: ImageVector by lazy {
        ImageVector.Builder(
            name = "StarFilled",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 24f,
            viewportHeight = 24f
        ).apply {
            path(fill = SolidColor(Color.Black), pathFillType = PathFillType.NonZero) {
                moveTo(12f, 2f)
                // верхний луч
                lineTo(14.9f, 8.6f)
                lineTo(22f, 9.3f)
                lineTo(16.7f, 14.0f)
                lineTo(18.1f, 21.0f)
                lineTo(12f, 17.4f)
                lineTo(5.9f, 21.0f)
                lineTo(7.3f, 14.0f)
                lineTo(2f, 9.3f)
                lineTo(9.1f, 8.6f)
                close()
            }
        }.build()
    }

    /** Контурная звезда (неактивная закладка) — тот же контур, но вырезанный. */
    val Outlined: ImageVector by lazy {
        ImageVector.Builder(
            name = "StarOutlined",
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 24f,
            viewportHeight = 24f
        ).apply {
            path(fill = SolidColor(Color.Black), pathFillType = PathFillType.EvenOdd) {
                // внешний контур
                moveTo(12f, 2f)
                lineTo(14.9f, 8.6f)
                lineTo(22f, 9.3f)
                lineTo(16.7f, 14.0f)
                lineTo(18.1f, 21.0f)
                lineTo(12f, 17.4f)
                lineTo(5.9f, 21.0f)
                lineTo(7.3f, 14.0f)
                lineTo(2f, 9.3f)
                lineTo(9.1f, 8.6f)
                close()
                // внутренний контур — вырезает середину
                moveTo(12f, 5.3f)
                lineTo(13.6f, 10.0f)
                lineTo(18.4f, 10.4f)
                lineTo(14.6f, 13.6f)
                lineTo(15.5f, 18.4f)
                lineTo(12f, 15.9f)
                lineTo(8.5f, 18.4f)
                lineTo(9.4f, 13.6f)
                lineTo(5.6f, 10.4f)
                lineTo(10.4f, 10.0f)
                close()
            }
        }.build()
    }
}
