package com.vedalibrary.app.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.vedalibrary.app.ui.components.GbHtml
import com.vedalibrary.app.ui.theme.ReadFont
import com.vedalibrary.app.ui.vm.SearchViewModel
import kotlinx.coroutines.launch

/** Поиск по всем книгам со scope (везде/санскрит/стих/комментарий), подсветкой совпадений и историей.
 *  Тап по выдаче открывает стих ровно на месте совпадения (запрос едет в ?hl=). */
@Composable
fun SearchScreen(vm: SearchViewModel, onVerse: (String, String, String?) -> Unit) {
    val q by vm.query.collectAsState()
    val scope by vm.scope.collectAsState()
    val langF by vm.langFilter.collectAsState()
    val volScope = rememberCoroutineScope()
    val volOwner = remember { Any() }
    DisposableEffect(Unit) {
        com.vedalibrary.app.ui.util.VolumeFont.set(volOwner) { d -> volScope.launch { vm.settings.bumpListFont(d) } }
        onDispose { com.vedalibrary.app.ui.util.VolumeFont.clear(volOwner) }
    }
    val res by vm.results.collectAsState(emptyList())
    val history by vm.history.collectAsState(emptyList())
    val bookF by vm.bookFilter.collectAsState()
    val allBooks by vm.allBooks.collectAsState(emptyList())
    val shown = remember(res, langF, bookF) {
        var list = if (langF == "all") res else res.filter { it.item.row.bookLang == langF }
        if (bookF != null) list = list.filter { it.item.row.bookId == bookF }
        list
    }
    // Отступы слева/справа 8dp (16 -> 8): больше текста на экране
    Column(Modifier.fillMaxSize().padding(horizontal = 8.dp, vertical = 16.dp)) {
        // Поиск запускается пайплайном VM (debounce 250 мс) — здесь только
        // мутация состояних. IME «поиск» фиксирует запрос в истории.
        // Без label (плывущий съедал высоту): placeholder + компактная рамка —
        // поле ~22dp вместо стандартных 56 (в 2.5 раза ниже)
        BasicTextField(
            value = q,
            onValueChange = { vm.setQuery(it) },
            singleLine = true,
            textStyle = TextStyle(fontSize = 14.sp, lineHeight = 16.sp, color = MaterialTheme.colorScheme.onSurface),
            cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
            keyboardActions = KeyboardActions(onSearch = { vm.submitHistory() }),
            modifier = Modifier.fillMaxWidth()
                .border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(4.dp))
                .padding(horizontal = 10.dp, vertical = 2.dp),
            decorationBox = { inner ->
                Box(contentAlignment = androidx.compose.ui.Alignment.CenterStart) {
                    if (q.isEmpty()) {
                        Text("Поиск по всем книгам", fontSize = 14.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    inner()
                }
            }
        )
        // Ряд scope — scale-to-fit: natural-ширина замеряется TextMeasurer,
        // весь ряд сжимается/растягивается под ширину экрана без переноса
        BoxWithConstraints(Modifier.fillMaxWidth()) {
            val measurer = rememberTextMeasurer()
            val density = LocalDensity.current
            val base = LocalTextStyle.current.copy(fontSize = 14.sp, lineHeight = 16.sp)
            val chipScale = remember(measurer, base, maxWidth, density) {
                val natural = with(density) {
                    val textPx = listOf("Везде", "Санскрит", "Стих", "Коммент.")
                        .sumOf { measurer.measure(it, base).size.width.toDouble() }
                    textPx + 4 * 12.dp.toPx() // паддинг 6dp×2 на плитку
                }
                if (natural > 0) (with(density) { maxWidth.toPx() }.toDouble() / natural).coerceIn(0.7, 2.2).toFloat() else 1f
            }
            Row(Modifier.padding(vertical = 1.5.dp)) {
                listOf("all" to "Везде", "sanskrit" to "Санскрит", "verse" to "Стих", "purport" to "Коммент.").forEach { (v, l) ->
                    MiniChip(v == scope, { vm.setScope(v) }, l, chipScale)
                }
            }
        }
        // Одна кнопка языка — цикл как на главной (слева), справа тумблер
        // «Везде»/«В книге»: при входе в «В книге» берётся первая книга
        Row(
            Modifier.fillMaxWidth().padding(bottom = 1.5.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically
        ) {
            TextButton(onClick = { vm.cycleLang() }, contentPadding = PaddingValues(horizontal = 8.dp)) {
                Text(when (langF) { "rus" -> "RU"; "eng" -> "EN"; else -> "Все" })
            }
            TextButton(onClick = {
                if (bookF == null) {
                    if (allBooks.isNotEmpty()) vm.setBookFilter(allBooks.first().id)
                } else vm.setBookFilter(null)
            }, contentPadding = PaddingValues(horizontal = 8.dp)) {
                Text(if (bookF == null) "Везде" else "В книге")
            }
        }
        if (bookF != null) {
            var expanded by remember { mutableStateOf(false) }
            val cur = allBooks.firstOrNull { it.id == bookF }
            @OptIn(ExperimentalMaterial3Api::class)
            ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = it }) {
                // Компактное поле той же высоты, что и строка поиска (~22dp
                // вместо 56dp у OutlinedTextField с label): тот же border/padding/кегль
                Row(
                    Modifier.menuAnchor().fillMaxWidth()
                        .border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(4.dp))
                        .padding(horizontal = 10.dp, vertical = 2.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = androidx.compose.ui.Alignment.CenterVertically
                ) {
                    Text(
                        cur?.let { com.vedalibrary.app.ui.components.VerseShare.cleanTitle(it.title) } ?: "…",
                        fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        color = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.weight(1f)
                    )
                    Text("▾", fontSize = 14.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                    // Свои строки вместо DropdownMenuItem: его min-height 48dp
                    // зашит в m3 — contentPadding его не уменьшает, а нужен шаг ~32dp
                    allBooks.forEach { b ->
                        Box(
                            Modifier.fillMaxWidth().clickable {
                                vm.setBookFilter(b.id)
                                expanded = false
                            }.padding(horizontal = 16.dp, vertical = 6.dp)
                        ) {
                            Text(
                                com.vedalibrary.app.ui.components.VerseShare.cleanTitle(b.title),
                                fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.fillMaxWidth()
                            )
                        }
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
        }
        if (q.isBlank() && history.isNotEmpty()) {
            // «История» и «Очистить» — одна строка: тексты по центру (иначе
            // кнопка 40dp тянет свою середину, а заголовок уходил вверх)
            Row(
                Modifier.fillMaxWidth().padding(bottom = 4.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = androidx.compose.ui.Alignment.CenterVertically
            ) {
                Text("История", style = MaterialTheme.typography.titleSmall)
                TextButton(onClick = { vm.clearHistory() }) { Text("Очистить") }
            }
        }
        LazyColumn(Modifier.weight(1f)) {
            if (q.isBlank()) {
                items(history, key = { "h-$it" }) { h ->
                    // Вместо ListItem: у M3-ListItem нет contentPadding —
                    // внутренние 16dp не отключить, текст уходил от края
                    Text(
                        h, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.fillMaxWidth().clickable {
                            vm.setQuery(h)
                            vm.submitHistory()
                        }.padding(vertical = 8.dp)
                    )
                    HorizontalDivider()
                }
            } else {
                items(shown, key = { it.item.row.id }) { h ->
                    // Заголовок — только сокращение «ШБ 1.1.2»: полное название
                    // произведения съедало строку, номер стиха не было видно
                    val ref = remember(h.item.row.id) {
                        com.vedalibrary.app.ui.components.VerseShare.refLight(
                            h.item.row.bookLang, h.item.row.bookId, h.item.row.chapterId, h.item.row.number
                        // Без пробела после кода: «БГ2.40», не «БГ 2.40»
                        ).replace(Regex("""^(\p{Lu}{2,4}) (?=\d)"""), "$1")
                    }
                    // Название жирным + сниппет-контекст (4 строки со словом)
                    // продолжением на той же строке — всё в одном Text
                    val line = remember(ref, h.snippet, q) {
                        buildAnnotatedString {
                            withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(ref) }
                            append("  ")
                            append(if (q.isBlank()) h.snippet else highlightMatch(h.snippet, q))
                        }
                    }
                    // Вместо ListItem: текст вплотную к краю (6dp внешнего),
                    // вертикальный ритм прежний; стиль headline — titleMedium
                    Text(
                        line, maxLines = 5, overflow = TextOverflow.Ellipsis, fontFamily = ReadFont,
                        style = MaterialTheme.typography.titleMedium,
                        lineHeight = MaterialTheme.typography.titleMedium.fontSize * 1.35f,
                        modifier = Modifier.fillMaxWidth().clickable {
                            vm.submitHistory() // реально использованный запрос — в историю
                            onVerse(h.item.row.id, q, h.field)
                        }.padding(vertical = 8.dp)
                    )
                    HorizontalDivider()
                }
            }
        }
    }
}

/** Совпадения — зелёным, как в оригинале (диакритика не важна: praptam найдёт prāptam) */
private fun highlightMatch(text: String, q: String) = buildAnnotatedString {
    append(text)
    if (q.length >= 2) {
        for (r in GbHtml.highlightRanges(text, q)) {
            addStyle(
                SpanStyle(background = Color(0xFF2E7D32), color = Color.White),
                r.first, r.last + 1
            )
        }
    }
}

/** Компактная фильтр-плитка: хватает слово вплотную (без внутренних пустот
 *  M3-FilterChip ~12dp с каждой стороны), без зазоров плитки идут гуськом,
 *  высота ~22dp вместо 32dp. Стиль — как у FilterChip: контур, залитая выбранная.
 *  scale — общий масштаб ряда (только ряд scope): шрифт, паддинги и радиус. */
@Composable
private fun MiniChip(selected: Boolean, onClick: () -> Unit, label: String, scale: Float = 1f) {
    val cs = MaterialTheme.colorScheme
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape((8f * scale).dp),
        color = if (selected) cs.secondaryContainer else Color.Transparent,
        contentColor = if (selected) cs.onSecondaryContainer else cs.onSurfaceVariant,
        border = BorderStroke(1.dp, if (selected) cs.secondaryContainer else cs.outlineVariant)
    ) {
        Text(
            label, maxLines = 1,
            fontSize = (14f * scale).sp, lineHeight = (16f * scale).sp,
            modifier = Modifier.padding(horizontal = (6f * scale).dp, vertical = (3f * scale).dp)
        )
    }
}
