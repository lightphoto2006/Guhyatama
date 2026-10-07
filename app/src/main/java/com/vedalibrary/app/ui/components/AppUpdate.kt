package com.vedalibrary.app.ui.components

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.vedalibrary.app.ui.vm.UpdateViewModel

/** Глобальный диалог обновления: версия, «что нового», скачивание, установка.
 *  Висит в NavGraph поверх всех экранов (состояние — activity-scoped UpdateViewModel). */
@Composable
fun UpdateDialog(vm: UpdateViewModel) {
    val st by vm.state.collectAsState()
    when (val s = st) {
        is UpdateViewModel.State.Available -> AlertDialog(
            onDismissRequest = { vm.dismiss() },
            title = { Text("Доступно обновление ${s.info.versionName}") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    if (s.info.notes.isNotBlank()) Text(s.info.notes)
                    else Text("Новая версия приложения.")
                    if (s.info.size > 0) {
                        Spacer(Modifier.height(8.dp))
                        Text(
                            "Размер: ${s.info.size / 1048576} МБ",
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            },
            confirmButton = { TextButton(onClick = { vm.download() }) { Text("Обновить") } },
            dismissButton = {
                Row {
                    if (s.silent) TextButton(onClick = { vm.skip(s.info) }) { Text("Пропустить") }
                    TextButton(onClick = { vm.dismiss() }) { Text("Позже") }
                }
            }
        )
        is UpdateViewModel.State.Downloading -> AlertDialog(
            onDismissRequest = { },
            title = { Text("Загрузка обновления") },
            text = {
                Column {
                    if (s.total > 0) {
                        LinearProgressIndicator(
                            progress = { (s.done.toFloat() / s.total).coerceIn(0f, 1f) },
                            modifier = Modifier.fillMaxWidth()
                        )
                        Spacer(Modifier.height(8.dp))
                        Text("${s.done / 1048576} / ${s.total / 1048576} МБ")
                    } else {
                        LinearProgressIndicator(Modifier.fillMaxWidth())
                        Spacer(Modifier.height(8.dp))
                        Text("${s.done / 1048576} МБ…")
                    }
                }
            },
            confirmButton = { },
            dismissButton = { TextButton(onClick = { vm.cancelDownload() }) { Text("Отмена") } }
        )
        is UpdateViewModel.State.Ready -> AlertDialog(
            onDismissRequest = { vm.dismiss() },
            title = { Text("Готово к установке ${s.info.versionName}") },
            text = { Text("Файл проверен. Начать установку?") },
            confirmButton = { TextButton(onClick = { vm.install() }) { Text("Установить") } },
            dismissButton = { TextButton(onClick = { vm.dismiss() }) { Text("Позже") } }
        )
        is UpdateViewModel.State.AwaitingPermission -> AlertDialog(
            onDismissRequest = { vm.dismiss() },
            title = { Text("Нужно разрешение") },
            text = {
                Text("Разреши «установку из этого источника» в открывшихся настройках, вернись и нажми «Установить».")
            },
            confirmButton = { TextButton(onClick = { vm.retryInstall() }) { Text("Установить") } },
            dismissButton = { TextButton(onClick = { vm.dismiss() }) { Text("Закрыть") } }
        )
        is UpdateViewModel.State.Error -> AlertDialog(
            onDismissRequest = { vm.dismiss() },
            title = { Text("Не получилось") },
            text = { Text(s.msg) },
            confirmButton = { TextButton(onClick = { vm.dismiss() }) { Text("Понятно") } },
            dismissButton = { }
        )
        else -> { }
    }
}

/** Секция «Обновления» для экрана настроек: версия, ручная проверка, статусы + книги + аудио. */
@Composable
fun UpdateSection(vm: UpdateViewModel) {
    val st by vm.state.collectAsState()
    val books by vm.books.collectAsState()
    val audio by vm.audio.collectAsState()
    val booksBusy by vm.booksBusy.collectAsState()
    val booksMsg by vm.booksMsg.collectAsState()
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Text(
            "Установлена: ${vm.current.first} (${vm.current.second})",
            style = MaterialTheme.typography.bodySmall
        )
        Spacer(Modifier.height(4.dp))
        when (val s = st) {
            is UpdateViewModel.State.Checking ->
                Row { CircularProgressIndicator(Modifier.size(20.dp)); Spacer(Modifier.width(8.dp)); Text("Проверяю…") }
            is UpdateViewModel.State.UpToDate -> Text("У тебя последняя версия.")
            is UpdateViewModel.State.Available ->
                Text("Доступна ${s.info.versionName} — окно обновления открыто.")
            is UpdateViewModel.State.Downloading ->
                Text(if (s.total > 0) "Качаю: ${s.done / 1048576}/${s.total / 1048576} МБ…" else "Качаю…")
            is UpdateViewModel.State.Ready -> Text("Скачано — окно установки открыто.")
            is UpdateViewModel.State.Error -> Text("Ошибка: ${s.msg}")
            else -> { }
        }
        Spacer(Modifier.height(4.dp))
        OutlinedButton(
            onClick = { vm.checkApp() },
            enabled = st !is UpdateViewModel.State.Checking &&
                    st !is UpdateViewModel.State.Downloading
        ) { Text("Проверить обновления приложения") }
        Spacer(Modifier.height(8.dp))
        Text("Книги и аудио", style = MaterialTheme.typography.titleSmall)
        if (booksBusy) {
            Row {
                CircularProgressIndicator(Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text("Обновляю список…")
            }
        }
        booksMsg?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
        OutlinedButton(
            onClick = { vm.checkBooks() },
            enabled = !booksBusy
        ) { Text("Обновить список книг") }
        if (books.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Text("Книги", style = MaterialTheme.typography.titleSmall)
            UpdateGroup(books, vm)
        }
        if (audio.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Text("Аудио", style = MaterialTheme.typography.titleSmall)
            UpdateGroup(audio, vm)
        }
    }
}

/** Строки с обновлениями — всегда видны; установленные без обновлений —
 *  свёрнуты (сразу понятно, надо что-то делать или нет) */
@Composable
private fun UpdateGroup(items: List<UpdateViewModel.BookItem>, vm: UpdateViewModel) {
    val pending = items.filter { it.hasUpdate }
    val done = items.filter { !it.hasUpdate }
    pending.forEach { b -> BookRow(b, vm) }
    if (done.isNotEmpty()) {
        var open by remember { mutableStateOf(false) }
        TextButton(onClick = { open = !open }) {
            Text(if (open) "Установленные (${done.size}) ▾" else "Установленные (${done.size}) ▸")
        }
        if (open) done.forEach { b -> BookRow(b, vm) }
    }
}

/** Строка файла книг: версия, кнопка скачать/обновить, прогресс, ошибки */
@Composable
private fun BookRow(b: UpdateViewModel.BookItem, vm: UpdateViewModel) {
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Text(b.info.title, style = MaterialTheme.typography.bodyMedium)
        val ver = if (b.installed > 0) "v${b.installed} → v${b.info.version}" else "v${b.info.version}"
        val size = if (b.info.size > 0) " · ${b.info.size / 1048576} МБ" else ""
        Text(
            "$ver$size" + (if (b.missing) (if (b.audio) " · пак удалён" else " · удалена из библиотеки")
            else if (b.installed > 0 && !b.hasUpdate) " · последняя" else ""),
            style = MaterialTheme.typography.bodySmall
        )
        if (b.installed == 0 && b.have >= 0 && b.want >= 0 && !b.audio) {
            Text(
                "у тебя: ${b.have}, в файле: ${b.want} стихов",
                style = MaterialTheme.typography.bodySmall
            )
        }
        // Диагностику несовпадения показываем, только если одноимённая книга
        // вообще есть (иначе на чистой установке пугает "совпало 0/20")
        if (b.installed == 0 && b.have >= 0 && b.match.isNotBlank() && !b.audio) {
            Text(
                "совпало: ${b.match}",
                style = MaterialTheme.typography.bodySmall
            )
        }
        if (b.info.notes.isNotBlank() && b.hasUpdate) {
            Text(b.info.notes, style = MaterialTheme.typography.bodySmall, maxLines = 3)
        }
        when (val busy = b.busy) {
            is UpdateViewModel.BookItem.Busy.Downloading -> {
                Spacer(Modifier.height(4.dp))
                if (busy.total > 0) {
                    LinearProgressIndicator(
                        progress = { (busy.done.toFloat() / busy.total).coerceIn(0f, 1f) },
                        modifier = Modifier.fillMaxWidth()
                    )
                    Text("${busy.done / 1048576}/${busy.total / 1048576} МБ…",
                        style = MaterialTheme.typography.bodySmall)
                } else {
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                    Text("${busy.done / 1048576} МБ…", style = MaterialTheme.typography.bodySmall)
                }
            }
            is UpdateViewModel.BookItem.Busy.Importing -> {
                Spacer(Modifier.height(4.dp))
                Row {
                    CircularProgressIndicator(Modifier.size(20.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(busy.label, style = MaterialTheme.typography.bodySmall)
                }
            }
            else -> { }
        }
        b.note?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
        if (b.busy is UpdateViewModel.BookItem.Busy.Idle &&
            (b.hasUpdate || (b.audio && b.installed > 0))
        ) {
            Spacer(Modifier.height(2.dp))
            OutlinedButton(onClick = { vm.downloadBook(b.info.key) }) {
                Text(
                    if (!b.hasUpdate) "Переимпортировать"
                    else if (b.installed > 0 && !b.missing) "Обновить" else "Скачать"
                )
            }
        }
    }
}
