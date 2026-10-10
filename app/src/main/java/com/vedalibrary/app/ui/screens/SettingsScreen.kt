@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.vedalibrary.app.ui.screens

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.draw.scale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.datastore.preferences.core.edit
import androidx.hilt.navigation.compose.hiltViewModel
import com.vedalibrary.app.data.backup.BackupManager
import com.vedalibrary.app.data.library.LibraryDbImporter
import com.vedalibrary.app.data.importer.DocxImporter
import com.vedalibrary.app.data.importer.PdfImporter
import com.vedalibrary.app.data.importer.TxtImporter
import com.vedalibrary.app.data.settings.ReaderSettings
import com.vedalibrary.app.ui.components.VerseShare
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import javax.inject.Inject

@HiltViewModel
class SettingsViewModel @Inject constructor(
    val s: ReaderSettings,
    private val txt: TxtImporter,
    private val pdf: PdfImporter,
    private val docx: DocxImporter,
    private val gdb: LibraryDbImporter,
    private val backup: BackupManager,
    private val db: com.vedalibrary.app.data.local.AppDatabase,
    @ApplicationContext private val ctx: Context
) : ViewModel() {
    fun toggle(setter: suspend (Boolean) -> Unit, v: Boolean) = viewModelScope.launch { setter(!v) }
    fun font(v: Float) = viewModelScope.launch { s.setFontSize(v) }
    fun fontList(v: Float) = viewModelScope.launch { s.setFontListSize(v) }
    fun align(v: String) = viewModelScope.launch { s.setParaAlign(v) }
    fun mainView(v: String) = viewModelScope.launch { s.setMainView(v) }
    fun bookSection(bookId: String, section: Int) = viewModelScope.launch { s.setBookSection(bookId, section) }
    /** Полное удаление книги: БД — одной транзакцией (deleteBookCascade),
     *  плюс аудио, обложный кэш-нет (у этой VM его нет) и файлы картинок */
    fun deleteBook(id: String) = viewModelScope.launch {
        try {
            db.library().deleteBookCascade(id)
            try { gdb.deleteAudioOfBook(id) } catch (_: Exception) { }
            refreshAudioPacks()
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (_: Exception) { }
        try {
            val dir = java.io.File(ctx.filesDir, "illustrations/${id.replace(Regex("[^A-Za-z0-9_-]"), "_")}")
            if (dir.exists()) dir.deleteRecursively()
        } catch (_: Exception) { }
    }
    val books: kotlinx.coroutines.flow.Flow<List<com.vedalibrary.app.data.local.Book>> = db.library().booksFlow()
    val bookSections = s.bookSections

    private val _status = MutableStateFlow<String?>(null)
    val status: StateFlow<String?> = _status

    /** Импортированные аудиопаки (строки секции Аудио) */
    private val _packs = MutableStateFlow<List<LibraryDbImporter.AudioPack>>(emptyList())
    val audioPacks: StateFlow<List<LibraryDbImporter.AudioPack>> = _packs

    fun refreshAudioPacks() = viewModelScope.launch {
        // Санация: лекции Шьямакунды не должны носить паковую озвучку шлок —
        // до 1.2.25 она в них затесалась (совпадение координат). Метод идемпотентен.
        try { gdb.purgeLectureAudio() } catch (_: Exception) { }
        _packs.value = try { gdb.audioPacks() } catch (_: Exception) { emptyList() }
    }

    fun deleteAudioPack(key: String) = viewModelScope.launch {
        val n = try { gdb.deleteAudioPack(key) } catch (_: Exception) { 0 }
        _status.value = "Аудиопак удалён: файлов $n"
        refreshAudioPacks()
    }

    fun deleteAllAudio() = viewModelScope.launch {
        val n = try { gdb.deleteAllAudio() } catch (_: Exception) { 0 }
        _status.value = "Всё аудио удалено: файлов $n"
        refreshAudioPacks()
    }

    fun importTxt(u: Uri) = viewModelScope.launch {
        try { _status.value = "Импорт TXT…"; txt.import(u); _status.value = "Готово" }
        catch (e: Exception) { _status.value = "Ошибка: ${e.message}" }
    }
    fun importPdf(u: Uri) = viewModelScope.launch {
        try { _status.value = "Импорт PDF…"; pdf.import(u); _status.value = "Готово" }
        catch (e: Exception) { _status.value = "Ошибка: ${e.message}" }
    }
    fun importDocx(u: Uri, name: String?) = viewModelScope.launch {
        try {
            _status.value = "Импорт DOCX…"
            val display = name ?: "Импорт DOCX"
            docx.import(u, display.substringBeforeLast('.', display))
            _status.value = "Готово"
        } catch (e: Exception) { _status.value = "Ошибка: ${e.message}" }
    }
    fun importDb(u: Uri) = importDbList(listOf(u))

    /** Несколько .db за раз (множественный выбор) */
    fun importDbList(uris: List<Uri>) = viewModelScope.launch {
        if (uris.isEmpty()) return@launch
        try {
            var books = 0
            var verses = 0
            val failed = mutableListOf<String>()
            val perBook = mutableListOf<Pair<String, Int>>()
            uris.forEachIndexed { i, u ->
                _status.value = "Файл ${i + 1}/${uris.size}…"
                try {
                    // Долговременный доступ, чтобы довезти импорт до конца
                    try {
                        ctx.contentResolver.takePersistableUriPermission(
                            u, android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION
                        )
                    } catch (_: Exception) { }
                    val r = withContext(Dispatchers.IO) { copyAndImportDb(u) }
                    books += r.bookIds.size
                    verses += r.verses
                    failed += r.failed
                    perBook += r.perBook
                } catch (e: Exception) {
                    failed += "${displayName(u)}: ${e.message}"
                }
            }
            _status.value = buildString {
                append("Готово: файлов ${uris.size}, книг $books, стихов $verses")
                if (failed.isNotEmpty()) append(". Ошибки: ${failed.take(3).joinToString("; ")}")
                perBook.take(10).forEach { (t, n) -> append("\n• $t: $n") }
            }
        } catch (e: Exception) {
            _status.value = "Ошибка импорта: ${e.message}"
        }
    }

    /** Папка с .db: сканируем детей (кроме -journal/-wal/-shm) и импортируем по очереди */
    fun importFolder(tree: Uri) = viewModelScope.launch {
        _status.value = "Сканирую папку…"
        try {
            try {
                ctx.contentResolver.takePersistableUriPermission(
                    tree,
                    android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION
                )
            } catch (_: Exception) { }
            val treeId = android.provider.DocumentsContract.getTreeDocumentId(tree)
            val children = android.provider.DocumentsContract.buildChildDocumentsUriUsingTree(tree, treeId)
            val found = mutableListOf<Uri>()
            withContext(Dispatchers.IO) {
                ctx.contentResolver.query(
                    children,
                    arrayOf(
                        android.provider.DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                        android.provider.DocumentsContract.Document.COLUMN_DISPLAY_NAME
                    ),
                    null, null, null
                )?.use { c ->
                    val idI = c.getColumnIndex(android.provider.DocumentsContract.Document.COLUMN_DOCUMENT_ID)
                    val nameI = c.getColumnIndex(android.provider.DocumentsContract.Document.COLUMN_DISPLAY_NAME)
                    while (c.moveToNext()) {
                        val name = if (nameI >= 0) c.getString(nameI) ?: "" else ""
                        val low = name.lowercase()
                        if (low.endsWith(".db") && !low.contains("-journal") &&
                            !low.endsWith("-wal.db") && !low.endsWith("-shm.db")
                        ) {
                            val docId = if (idI >= 0) c.getString(idI) else null
                            if (docId != null) {
                                found += android.provider.DocumentsContract.buildDocumentUriUsingTree(tree, docId)
                            }
                        }
                    }
                }
            }
            if (found.isEmpty()) {
                _status.value = "В папке нет .db файлов"
                return@launch
            }
            importDbList(found).join()
        } catch (e: Exception) {
            _status.value = "Ошибка импорта папки: ${e.message}"
        }
    }

    private fun displayName(u: Uri): String = try {
        ctx.contentResolver.query(u, null, null, null, null)?.use { c ->
            val i = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
            if (c.moveToFirst() && i >= 0) c.getString(i) else u.toString()
        } ?: u.toString()
    } catch (_: Exception) { u.toString() }

    /** Тяжёлая часть импорта .db: файл + SQLite + Room — только IO-поток, не Main. */
    private suspend fun copyAndImportDb(u: Uri): LibraryDbImporter.Result {
        val expected = try {
            ctx.contentResolver.query(u, null, null, null, null)?.use { c ->
                val i = c.getColumnIndex(android.provider.OpenableColumns.SIZE)
                if (c.moveToFirst() && i >= 0) c.getLong(i) else -1L
            } ?: -1L
        } catch (_: Exception) { -1L }
        val name = try {
            ctx.contentResolver.query(u, null, null, null, null)?.use { c ->
                val i = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
                if (c.moveToFirst() && i >= 0) c.getString(i) else null
            }
        } catch (_: Exception) { null }
        val tmp = File.createTempFile("library", ".db", ctx.cacheDir)
        try {
            var copied = 0L
            ctx.contentResolver.openInputStream(u)!!.use { inp ->
                tmp.outputStream().use { out ->
                    val buf = ByteArray(1 shl 20)
                    var n = inp.read(buf)
                    while (n > 0) { out.write(buf, 0, n); copied += n; n = inp.read(buf) }
                }
            }
            if (expected > 0 && copied != expected) {
                error("Файл скопировался не полностью ($copied из $expected байт). Перекиньте файл заново (не -journal).")
            }
            val head = ByteArray(16)
            java.io.FileInputStream(tmp).use { it.read(head) }
            if (String(head, Charsets.US_ASCII) != "SQLite format 3\u0000") {
                val hex = head.take(8).joinToString(" ") { "%02X".format(it) }
                error("Это не SQLite-база (байты: $hex, размер $copied). Нужен именно .db.")
            }
            val rawName = (name ?: u.toString()).lowercase()
            // Лекции Шьямакунды (SCC/SSB/SBG/SBRS) — всегда русские, как бы файл ни звался
            val peekLang = try {
                android.database.sqlite.SQLiteDatabase.openDatabase(
                    tmp.absolutePath, null,
                    android.database.sqlite.SQLiteDatabase.OPEN_READONLY
                ).use { sq ->
                    val types = mutableListOf<String>()
                    sq.rawQuery("SELECT DISTINCT type FROM books", null).use { c ->
                        while (c.moveToNext()) types += (c.getString(0) ?: "").uppercase()
                    }
                    if (types.isNotEmpty() && types.all { it == "SCC" || it == "SSB" || it == "SBG" || it == "SBRS" }) "rus"
                    else null
                }
            } catch (_: Exception) { null }
            // rus / _ru_ / -ru / eng — файлы могут зваться bg_ru.db, texts_eng.db и т.п.
            val lang = peekLang ?: when {
                "rus" in rawName || Regex("(^|[^a-z])ru([^a-z]|$)").containsMatchIn(rawName) -> "rus"
                else -> "eng"
            }
            return gdb.importFile(tmp, lang, packName = name) { d, t, label -> _status.value = "Импорт: $label — $d/$t" }
        } finally {
            tmp.delete()
        }
    }

    fun clearStatus() { _status.value = null }

    fun exportBackup(uri: Uri) = viewModelScope.launch {
        try {
            _status.value = "Экспорт заметок…"
            ctx.contentResolver.openOutputStream(uri)!!.use { backup.exportTo(it) }
            _status.value = "Бэкап сохранён"
        } catch (e: Exception) { _status.value = "Ошибка: ${e.message}" }
    }
    fun importBackup(uri: Uri) = viewModelScope.launch {
        try {
            _status.value = "Восстановление…"
            ctx.contentResolver.openInputStream(uri)!!.use {
                _status.value = backup.importFrom(it)
            }
        } catch (e: Exception) { _status.value = "Ошибка: ${e.message}" }
    }
    /** Авто-бэкап раз в неделю во внутреннюю папку (как в оригинале — ротация по дням) */
    fun autoBackupIfDue() = viewModelScope.launch {
        try {
            val last = ctx.readerBackupPrefs.data.map { it[LAST_AUTO] ?: 0L }.first()
            if (System.currentTimeMillis() - last < 7L * 24 * 3600 * 1000) return@launch
            val f = java.io.File(ctx.filesDir, "auto_notes_backup.json")
            f.outputStream().use { backup.exportTo(it) }
            ctx.readerBackupPrefs.edit { it[LAST_AUTO] = System.currentTimeMillis() }
        } catch (_: Exception) { }
    }

    companion object {
        private val LAST_AUTO = androidx.datastore.preferences.core.longPreferencesKey("last_auto_backup")
    }
}

private val Context.readerBackupPrefs by androidx.datastore.preferences.preferencesDataStore("backup_prefs")

@Composable
fun SettingsScreen(vm: SettingsViewModel = hiltViewModel(), updateVm: com.vedalibrary.app.ui.vm.UpdateViewModel) {
    val san by vm.s.showSanskrit.collectAsState(true)
    val tra by vm.s.showTranslit.collectAsState(true)
    val syn by vm.s.showSynonyms.collectAsState(true)
    val trl by vm.s.showTranslation.collectAsState(true)
    val pur by vm.s.showPurport.collectAsState(true)
    val fontV by vm.s.fontVerse.collectAsState(17f)
    val fontL by vm.s.fontList.collectAsState(15f)
    val align by vm.s.paraAlign.collectAsState("justify")
    val view by vm.s.mainView.collectAsState("tiles")
    val booksList by vm.books.collectAsState(emptyList())
    val sectionsMap by vm.bookSections.collectAsState(emptyMap())
    val packs by vm.audioPacks.collectAsState(emptyList())
    LaunchedEffect(Unit) { vm.refreshAudioPacks() }
    val status by vm.status.collectAsState(null)
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val pickPdf = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { u: Uri? -> u?.let { vm.importPdf(it) } }
    val pickDocx = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { u: Uri? ->
        u?.let {
            var name: String? = null
            try {
                ctx.contentResolver.query(it, null, null, null, null)?.use { c ->
                    val i = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
                    if (c.moveToFirst() && i >= 0) name = c.getString(i)
                }
            } catch (_: Exception) { }
            vm.importDocx(it, name)
        }
    }
    val exportNotes = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { u: Uri? -> u?.let { vm.exportBackup(it) } }
    val importNotes = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { u: Uri? -> u?.let { vm.importBackup(it) } }
    LaunchedEffect(Unit) { vm.autoBackupIfDue() }
    val volScope = rememberCoroutineScope()
    val volOwner = remember { Any() }
    DisposableEffect(Unit) {
        com.vedalibrary.app.ui.util.VolumeFont.set(volOwner) { d -> volScope.launch { vm.s.bumpListFont(d) } }
        onDispose { com.vedalibrary.app.ui.util.VolumeFont.clear(volOwner) }
    }
    Scaffold(topBar = { TopAppBar(title = { Text("Настройки") })     }) { pad ->
        Column(Modifier.padding(pad)) {
        LazyColumn(Modifier.weight(1f).padding(16.dp)) {
            item { Text("Импорт книг", style = MaterialTheme.typography.titleMedium) }
            item {
                // Только свои файлы: PDF / DOCX. Книги из сети — через «Обновления» ниже.
                // Кнопки в размер текста — обе в одну строку.
                Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = { pickPdf.launch("application/pdf") }) { Text("PDF") }
                        OutlinedButton(onClick = { pickDocx.launch(arrayOf("application/vnd.openxmlformats-officedocument.wordprocessingml.document")) }) { Text("DOCX") }
                    }
                    Text("Лекции и книги: PDF / DOCX.", style = MaterialTheme.typography.bodySmall)
                }
            }
            item {
                // Версия для опознания сборок: имя + код + дата установки APK
                val appVer = remember {
                    try {
                        val pm = ctx.packageManager
                        val pi = if (android.os.Build.VERSION.SDK_INT >= 33) {
                            pm.getPackageInfo(ctx.packageName, android.content.pm.PackageManager.PackageInfoFlags.of(0))
                        } else {
                            @Suppress("DEPRECATION") pm.getPackageInfo(ctx.packageName, 0)
                        }
                        val vc = if (android.os.Build.VERSION.SDK_INT >= 28) pi.longVersionCode
                        else @Suppress("DEPRECATION") pi.versionCode.toLong()
                        val dt = java.text.SimpleDateFormat("dd.MM HH:mm", java.util.Locale.getDefault())
                            .format(java.util.Date(pi.lastUpdateTime))
                        "${pi.versionName ?: "?"} ($vc) · $dt"
                    } catch (_: Exception) { "?" }
                }
                Text("Версия приложения: $appVer", style = MaterialTheme.typography.bodySmall)
            }
            item { Spacer(Modifier.height(12.dp)); Text("Обновления", style = MaterialTheme.typography.titleMedium) }
            item { com.vedalibrary.app.ui.components.UpdateSection(updateVm) }
            item { Spacer(Modifier.height(12.dp)); Text("Настройки отображения", style = MaterialTheme.typography.titleMedium) }
            item {
                // Формат главного экрана: та же строка-сегмент, что «Выравнивание текста»
                Text("Формат главного экрана", style = MaterialTheme.typography.bodyMedium)
                Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("tiles" to "Плитки", "shelf" to "Полка", "list" to "Список").forEach { (v, l) ->
                        FilterChip(view == v, { vm.mainView(v) }, { Text(l, maxLines = 1) })
                    }
                }
            }
            item { SwitchRow("Санскрит (деванагари)", san) { vm.toggle(vm.s::setShowSanskrit, san) } }
            item { SwitchRow("Транслитерация", tra) { vm.toggle(vm.s::setShowTranslit, tra) } }
            item { SwitchRow("Пословный перевод", syn) { vm.toggle(vm.s::setShowSynonyms, syn) } }
            item { SwitchRow("Перевод", trl) { vm.toggle(vm.s::setShowTranslation, trl) } }
            item { SwitchRow("Комментарий", pur) { vm.toggle(vm.s::setShowPurport, pur) } }
            item {
                Spacer(Modifier.height(8.dp))
                // Пишем в DataStore только по окончании драга, а не на каждый тик
                var sliderV by remember { mutableStateOf<Float?>(null) }
                Text("Шрифт стиха: ${(sliderV ?: fontV).toInt()}", style = MaterialTheme.typography.titleMedium)
                Slider(
                    sliderV ?: fontV, { sliderV = it }, valueRange = 12f..30f,
                    onValueChangeFinished = { sliderV?.let { vm.font(it) }; sliderV = null }
                )
                var sliderL by remember { mutableStateOf<Float?>(null) }
                Text("Шрифт списка главы: ${(sliderL ?: fontL).toInt()}", style = MaterialTheme.typography.titleMedium)
                Slider(
                    sliderL ?: fontL, { sliderL = it }, valueRange = 12f..30f,
                    onValueChangeFinished = { sliderL?.let { vm.fontList(it) }; sliderL = null }
                )
                Text("Выравнивание текста", style = MaterialTheme.typography.titleMedium)
                Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("left" to "Влево", "justify" to "По ширине", "center" to "По центру").forEach { (v, l) ->
                        FilterChip(align == v, { vm.align(v) }, { Text(l, maxLines = 1) })
                    }
                }
                Text("Громкость меняет шрифт открытого экрана чтения.", style = MaterialTheme.typography.bodySmall)
            }
            item { Spacer(Modifier.height(12.dp)); Text("Книги по разделам", style = MaterialTheme.typography.titleMedium) }
            item {
                Text("Выбери раздел для каждой книги. Пустые разделы скрыты.",
                    style = MaterialTheme.typography.bodySmall)
            }
            items(booksList, key = { it.id }) { b ->
                val cur = sectionsMap[b.id] ?: ReaderSettings.defaultSection(b)
                var expanded by remember(b.id) { mutableStateOf(false) }
                var confirmDelete by remember(b.id) { mutableStateOf(false) }
                Box {
                    // Название почти во всю ширину (две строки), справа только
                    // компактные корзня и стрелка — листайте списки книг спокойно
                    Row(
                        Modifier.fillMaxWidth().padding(vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(
                                VerseShare.cleanTitle(b.title),
                                style = MaterialTheme.typography.bodyLarge,
                                maxLines = 2, overflow = TextOverflow.Ellipsis
                            )
                            Text(
                                vm.s.sectionTitles[cur],
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        Box(
                            Modifier.clickable { confirmDelete = true }.padding(10.dp)
                        ) { Text("🗑", fontSize = 20.sp) }
                        Box(
                            Modifier.clickable { expanded = true }.padding(10.dp)
                        ) { Text("▾", fontSize = 30.sp) }
                    }
                    DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                        vm.s.sectionTitles.forEachIndexed { i, t ->
                            DropdownMenuItem(
                                text = { Text(t) },
                                onClick = { expanded = false; vm.bookSection(b.id, i) }
                            )
                        }
                    }
                    if (confirmDelete) {
                        AlertDialog(
                            onDismissRequest = { confirmDelete = false },
                            title = { Text("Удалить книгу?") },
                            text = { Text("«${VerseShare.cleanTitle(b.title)}» будет удалена со всеми стихами, закладками и заметками. Действие необратимо.") },
                            confirmButton = {
                                TextButton(onClick = {
                                    confirmDelete = false
                                    vm.deleteBook(b.id)
                                }) { Text("Удалить", color = MaterialTheme.colorScheme.error) }
                            },
                            dismissButton = {
                                TextButton(onClick = { confirmDelete = false }) { Text("Отмена") }
                            }
                        )
                    }
                }
                HorizontalDivider()
            }
            item { Spacer(Modifier.height(12.dp)); Text("Аудио", style = MaterialTheme.typography.titleMedium) }
            item {
                Text("Файлы аудиобаз: удаление убирает только звук, тексты и закладки остаются.",
                    style = MaterialTheme.typography.bodySmall)
            }
            if (packs.isEmpty()) {
                item { Text("Аудио не импортировано.", style = MaterialTheme.typography.bodySmall) }
            } else {
                items(packs, key = { it.key }) { p ->
                    var confirmPack by remember(p.key) { mutableStateOf(false) }
                    val date = remember(p.at) {
                        try {
                            java.text.SimpleDateFormat("dd.MM.yyyy", java.util.Locale.getDefault())
                                .format(java.util.Date(p.at))
                        } catch (_: Exception) { "" }
                    }
                    Row(
                        Modifier.fillMaxWidth().padding(vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(p.name, style = MaterialTheme.typography.bodyLarge,
                                maxLines = 2, overflow = TextOverflow.Ellipsis)
                            Text(
                                "${p.types.joinToString("+")} · стихов ${p.verses} · файлов ${p.files} (${p.bytes / 1048576} МБ) · $date",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        Box(
                            Modifier.clickable { confirmPack = true }.padding(10.dp)
                        ) { Text("🗑", fontSize = 20.sp) }
                    }
                    if (confirmPack) {
                        AlertDialog(
                            onDismissRequest = { confirmPack = false },
                            title = { Text("Удалить аудиопак?") },
                            text = { Text("«${p.name}»: ${p.files} файлов. Уберётся только звук этого пака.") },
                            confirmButton = {
                                TextButton(onClick = {
                                    confirmPack = false
                                    vm.deleteAudioPack(p.key)
                                }) { Text("Удалить", color = MaterialTheme.colorScheme.error) }
                            },
                            dismissButton = {
                                TextButton(onClick = { confirmPack = false }) { Text("Отмена") }
                            }
                        )
                    }
                    HorizontalDivider()
                }
                item {
                    var confirmAll by remember { mutableStateOf(false) }
                    OutlinedButton(onClick = { confirmAll = true }) { Text("Удалить всё аудио") }
                    if (confirmAll) {
                        AlertDialog(
                            onDismissRequest = { confirmAll = false },
                            title = { Text("Удалить всё аудио?") },
                            text = { Text("Снесёт весь звук, включая старые паки. Тексты не тронет.") },
                            confirmButton = {
                                TextButton(onClick = {
                                    confirmAll = false
                                    vm.deleteAllAudio()
                                }) { Text("Удалить", color = MaterialTheme.colorScheme.error) }
                            },
                            dismissButton = {
                                TextButton(onClick = { confirmAll = false }) { Text("Отмена") }
                            }
                        )
                    }
                }
            }
            item { Spacer(Modifier.height(12.dp)); Text("Заметки и бэкап", style = MaterialTheme.typography.titleMedium) }
            item {
                Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { exportNotes.launch("vedalibrary-notes.json") }, modifier = Modifier.weight(1f)) { Text("Экспорт") }
                    OutlinedButton(onClick = { importNotes.launch("application/json") }, modifier = Modifier.weight(1f)) { Text("Импорт") }
                }
                Text("JSON со всеми заметками, темами и карточками. Авто-копия раз в неделю лежит в папке приложения.", style = MaterialTheme.typography.bodySmall)
            }
        }
        // Статус операций — фиксированной плашкой ВНИЗУ экрана: всегда в поле
        // зрения (там же, где фокус после нажатия кнопки), не скроллится,
        // контрастный фон secondaryContainer — не растворяется в теме
        status?.let {
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp)
                    .background(MaterialTheme.colorScheme.secondaryContainer, RoundedCornerShape(12.dp))
                    .padding(horizontal = 12.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                if (it.startsWith("Импорт") || it.startsWith("Копирую")) CircularProgressIndicator(Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text(it, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                TextButton(onClick = { vm.clearStatus() }) { Text("×") }
            }
        }
        }
    }
}

@Composable
private fun SwitchRow(label: String, checked: Boolean, onToggle: () -> Unit) {
    // Вертикальные отступы в 1.5 раза меньше (строки плотнее), текст по центру
    // кнопки, сам переключатель в 2 раза компактнее
    Row(Modifier.fillMaxWidth().padding(vertical = 1.33.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f))
        Switch(checked, { onToggle() }, modifier = Modifier.scale(0.5f))
    }
}
