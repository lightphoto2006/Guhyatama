package com.vedalibrary.app.ui.components

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.material3.LocalContentColor
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.withTimeoutOrNull

/** ★ закладки в шапке главы/стиха. Один общий алгоритм вместо toggle:
 *  - короткое нажатие — ПОСТАВИТЬ/переставить на текущее место (прыгнул по
 *    закладке, читал дальше — один тап, и она уже здесь, без «снять+поставить»);
 *  - удержание 1 секунду — СНЯТЬ (с вибро-откликом): снятие только явным
 *    долгим нажатием, случайный тап закладку не теряет.
 *  Свой жест вместо TextButton: дефолтный long-press (0.5с) для снятия легко
 *  задеть, а 1с даёт запас на «просто ткнул». Зона ≥48×40dp как у кнопки.
 *  Значок — векторный (Icons.Filled.Star / Icons.Outlined.Star), а не текстовый
 *  «★»: только так его можно поставить в один ряд с шестерёнкой (Settings) —
 *  у вектора одинаковые метрики, у текста и эмодзи разные, и по вертикали
 *  они разъезжаются. Размер тот же, что у соседних иконок. */
@Composable
fun BookmarkStar(
    active: Boolean,
    style: TextStyle,
    onSave: () -> Unit,
    onRemove: () -> Unit,
    modifier: Modifier = Modifier,
    iconSize: Dp = 26.dp
) {
    val haptic = LocalHapticFeedback.current
    val save = rememberUpdatedState(onSave)
    val remove = rememberUpdatedState(onRemove)
    val tint = if (style.color == androidx.compose.ui.graphics.Color.Unspecified) {
        LocalContentColor.current
    } else {
        style.color
    }
    Box(
        modifier
            .defaultMinSize(minWidth = 48.dp, minHeight = 40.dp)
            .pointerInput(Unit) {
                awaitEachGesture {
                    awaitFirstDown(requireUnconsumed = false)
                    // Палец держит — ждём подъём до 1с; тишина без событий не
                    // мешает: таймаут срабатывает и без движения пальца
                    var released = false
                    withTimeoutOrNull(1_000L) {
                        while (true) {
                            val ev = awaitPointerEvent()
                            if (ev.changes.none { it.pressed }) { released = true; break }
                        }
                    }
                    if (released) {
                        save.value()
                    } else {
                        haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                        remove.value()
                        // Доедываем отпускание, чтобы жест закрылся
                        while (true) {
                            val ev = awaitPointerEvent()
                            if (ev.changes.none { it.pressed }) break
                        }
                    }
                }
            },
        contentAlignment = Alignment.Center
    ) {
        Icon(
            imageVector = if (active) StarIcons.Filled else StarIcons.Outlined,
            contentDescription = null,
            tint = tint,
            modifier = Modifier.size(iconSize)
        )
    }
}
