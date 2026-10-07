package com.vedalibrary.app.ui.vm

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vedalibrary.app.data.library.LibraryDbImporter
import com.vedalibrary.app.data.local.AppDatabase
import com.vedalibrary.app.data.update.ApkInfo
import com.vedalibrary.app.data.update.AppUpdater
import com.vedalibrary.app.data.update.BookInfo
import com.vedalibrary.app.data.update.Downloader
import com.vedalibrary.app.data.update.UpdatePrefs
import com.vedalibrary.app.data.update.parseApkInfo
import com.vedalibrary.app.data.update.parseBookInfos
import com.vedalibrary.app.data.update.sha256hex
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.io.File
import javax.inject.Inject

/** Состояние обновления приложения. Один на всё приложение (scope activity):
 *  диалог в NavGraph и секция в настройках смотрят в него же. */
@HiltViewModel
class UpdateViewModel @Inject constructor(
    private val updater: AppUpdater,
    private val downloader: Downloader,
    private val prefs: UpdatePrefs,
    private val importer: LibraryDbImporter,
    private val db: AppDatabase
) : ViewModel() {
    sealed interface State {
        data object Idle : State
        data object Checking : State
        data object UpToDate : State
        data class Available(val info: ApkInfo, val silent: Boolean) : State
        data class Downloading(val done: Long, val total: Long) : State
        data class Ready(val file: File, val info: ApkInfo) : State
        data object AwaitingPermission : State
        data class Error(val msg: String) : State
    }

    /** Строка каталога книг/аудио + локальный статус.
     *  have: стихов в одноимённой установленной книге (-1 = такой книги нет) —
     *  диагностика несовпадения отпечатка. */
    data class BookItem(
        val info: BookInfo,
        val installed: Int,
        val missing: Boolean = false,
        val busy: Busy = Busy.Idle,
        val note: String? = null,
        val audio: Boolean = false,
        val have: Int = -1,
        val want: Int = -1,
        /** Диагностика: совпало книг из файла + первая несовпавшая */
        val match: String = ""
    ) {
        sealed interface Busy {
            data object Idle : Busy
            data class Downloading(val done: Long, val total: Long) : Busy
            data class Importing(val label: String) : Busy
        }
        val hasUpdate: Boolean get() = installed < info.version || missing
    }

    private val _state = MutableStateFlow<State>(State.Idle)
    val state: StateFlow<State> = _state
    val current: Pair<String, Long> = updater.currentVersion()
    private val _books = MutableStateFlow<List<BookItem>>(emptyList())
    val books: StateFlow<List<BookItem>> = _books
    private val _audio = MutableStateFlow<List<BookItem>>(emptyList())
    val audio: StateFlow<List<BookItem>> = _audio
    /** Сколько книг/аудио ждёт обновления/установки — бейдж для секции настроек */
    val booksPending: Int get() =
        (_books.value + _audio.value).count { it.hasUpdate && it.busy is BookItem.Busy.Idle }
    private var lastInfo: ApkInfo? = null
    private var dlJob: Job? = null
    private var catalog: org.json.JSONObject? = null

    /** Тихая автопроверка при старте (не чаще раза в сутки). Диалог — только если есть
     *  новая версия и её не пропускали. */
    fun autoCheck() = viewModelScope.launch {
        if (_state.value != State.Idle) return@launch
        if (System.currentTimeMillis() - updater.lastCheck() < 24L * 3600 * 1000) return@launch
        val info = fetchNewer() ?: return@launch
        if (info.versionCode != updater.skippedVersion()) {
            lastInfo = info
            _state.value = State.Available(info, silent = true)
        }
    }

    private val _booksBusy = MutableStateFlow(false)
    val booksBusy: StateFlow<Boolean> = _booksBusy
    private val _booksMsg = MutableStateFlow<String?>(null)
    val booksMsg: StateFlow<String?> = _booksMsg

    /** Ручная проверка приложения (кнопка 1): результат виден всегда. Книги не трогает. */
    fun checkApp() = viewModelScope.launch {
        _state.value = State.Checking
        val cat = try { updater.fetchCatalog() } catch (e: Exception) {
            _state.value = State.Error(e.message ?: "Нет связи с сервером")
            return@launch
        }
        if (cat == null) {
            _state.value = State.Error("Нет связи с сервером")
            return@launch
        }
        updater.markChecked()
        catalog = cat
        val info = parseApkInfo(cat)?.takeIf { it.versionCode > current.second }
        if (info == null) _state.value = State.UpToDate
        else {
            lastInfo = info
            _state.value = State.Available(info, silent = false)
        }
    }

    /** Ручное обновление списка книг/аудио (кнопка 2): приложение не трогает. */
    fun checkBooks() = viewModelScope.launch {
        if (_booksBusy.value) return@launch
        _booksBusy.value = true
        _booksMsg.value = null
        try {
            val cat = updater.fetchCatalog()
            if (cat == null) {
                _booksMsg.value = "Нет связи с сервером"
                return@launch
            }
            updater.markChecked()
            catalog = cat
            refreshBooks(cat)
            val n = booksPending
            _booksMsg.value = if (n == 0) "Всё последнее" else "К обновлению: $n"
        } catch (e: Exception) {
            _booksMsg.value = "Ошибка: ${e.message}"
        } finally {
            _booksBusy.value = false
        }
    }

    fun download() = viewModelScope.launch {
        val info = lastInfo ?: return@launch
        dlJob?.cancel()
        _state.value = State.Downloading(0, info.size)
        dlJob = viewModelScope.launch {
            try {
                val f = updater.download(info) { d, t ->
                    _state.value = State.Downloading(d, t)
                }
                _state.value = State.Ready(f, info)
            } catch (e: kotlinx.coroutines.CancellationException) {
                updater.cancelDownload()
                _state.value = State.Idle
                throw e
            } catch (e: Exception) {
                _state.value = State.Error(e.message ?: "Не скачалось")
            }
        }
    }

    fun cancelDownload() {
        dlJob?.cancel()
        dlJob = null
        updater.cancelDownload()
        _state.value = State.Idle
    }

    fun install() = viewModelScope.launch {
        val cur = _state.value
        val file = (cur as? State.Ready)?.file
            ?: lastInfo?.let { i ->
                val dir = updater.updatesDir()
                java.io.File(dir, "Guhyatama-${i.versionCode}.apk").takeIf { it.exists() }
            } ?: return@launch
        try {
            if (!updater.install(file)) _state.value = State.AwaitingPermission
        } catch (e: Exception) {
            _state.value = State.Error(e.message ?: "Не ставится")
        }
    }

    fun retryInstall() = install()

    fun skip(info: ApkInfo) {
        updater.skip(info.versionCode)
        _state.value = State.Idle
    }

    fun dismiss() {
        if (_state.value !is State.Downloading) _state.value = State.Idle
    }

    private suspend fun fetchNewer(): ApkInfo? {
        val cat = updater.fetchCatalog() ?: return null
        updater.markChecked()
        catalog = cat
        refreshBooks(cat)
        return parseApkInfo(cat)?.takeIf { it.versionCode > current.second }
    }

    /** Перестроить списки книг и аудио из каталога + локальных версий.
     *  Сверка с базой (книгу могли удалить вручную) — на IO: PK-lookup'ы по id.
     *  Аудио сверяем по манифестам паков (имя файла из ссылки).
     *  Усыновление: книга стоит вручную (версий нет), но содержимое один в один
     *  с каталожным (тип/id/язык/число стихов) — считаем установленной, качать не надо. */
    private suspend fun refreshBooks(cat: org.json.JSONObject) {
        val bookInfos = parseBookInfos(cat, "books")
        val audioInfos = parseBookInfos(cat, "audio")
        val packs = try { importer.audioPacks().map { it.name } } catch (_: Exception) { emptyList() }
        val items = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            // Усыновление — один проход по всем книгам
            val adopt = mutableMapOf<String, List<String>>()
            // Для диагностики: число стихов в одноимённых книгах (тип+id+язык)
            val haveMap = mutableMapOf<String, Pair<Int, Int>>()
            // Диагностика совпадения отпечатка: "совпало 12/15 · нет bg-ss-1: ..."
            val matchMap = mutableMapOf<String, String>()
            try {
                val mine = db.library().booksAll()
                // Один GROUP BY вместо N countVerses; книги без стихов дают 0,
                // при сбое запроса — -1 (как раньше, «неизвестно»)
                val counts: Map<String, Int> = try {
                    val m = db.library().verseCountsByBook().associate { it.bookId to it.n }
                    mine.associate { it.id to (m[it.id] ?: 0) }
                } catch (_: Exception) { mine.associate { it.id to -1 } }
                fun sameBook(b: com.vedalibrary.app.data.local.Book, f: com.vedalibrary.app.data.update.FpRow, lang: String): Boolean {
                    val m = BOOK_ID_RE.matchEntire(b.id) ?: return false
                    return m.groupValues[1].lowercase() == f.t &&
                            m.groupValues[2].toLongOrNull() == f.g &&
                            m.groupValues[3].lowercase() == lang
                }
                for (info in bookInfos) {
                    if (info.fp.isEmpty() || !info.adopt || prefs.bookVersion(info.key) > 0) continue
                    // диагностика: первая одноимённая книга: есть/надо
                    for (f in info.fp) {
                        val cand = mine.firstOrNull { sameBook(it, f, info.lang) }
                        if (cand != null) {
                            haveMap[info.key] = (counts[cand.id] ?: -1) to f.v
                            break
                        }
                    }
                    val hit = mutableListOf<String>()
                    var okCount = 0
                    var firstMiss = ""
                    for (f in info.fp) {
                        val cand = mine.firstOrNull { sameBook(it, f, info.lang) }
                        val n = cand?.let { counts[it.id] } ?: -1
                        if (cand != null && (n == f.v || (f.vg >= 0 && n == f.vg))) {
                            hit += cand.id
                            okCount++
                        } else if (firstMiss.isEmpty()) {
                            firstMiss = "${f.t}-${f.g}: " +
                                    (if (cand == null) "нет книги"
                                    else "у тебя $n, надо ${f.v}")
                        }
                    }
                    val ok = okCount == info.fp.size
                    matchMap[info.key] = "$okCount/${info.fp.size}" +
                            (if (firstMiss.isNotEmpty()) " · $firstMiss" else "")
                    if (ok) {
                        prefs.setBookVersion(info.key, info.version)
                        prefs.setBookIds(info.key, hit)
                        adopt[info.key] = hit
                    }
                }
            } catch (_: Exception) { }
            bookInfos.map { info ->
                val prev = _books.value.firstOrNull { it.info.key == info.key }
                val installed = prefs.bookVersion(info.key)
                var missing = false
                if (installed > 0) {
                    try {
                        val ids = prefs.bookIds(info.key)
                        missing = ids.isNotEmpty() &&
                                ids.any { db.library().book(it) == null }
                    } catch (_: Exception) { }
                }
                val hw = haveMap[info.key]
                BookItem(info, installed, missing,
                    busy = prev?.busy ?: BookItem.Busy.Idle,
                    note = prev?.note, have = hw?.first ?: -1, want = hw?.second ?: -1,
                    match = matchMap[info.key] ?: "")
            }
        }
        _books.value = items.sortedWith(
            compareByDescending<BookItem> { it.hasUpdate }.thenBy { it.info.title })
        _audio.value = audioInfos.map { info ->
            val prev = _audio.value.firstOrNull { it.info.key == info.key }
            val installed = prefs.bookVersion(info.key)
            val missing = installed > 0 && fileNameFromUrl(info.url) !in packs
            BookItem(info, installed, missing,
                busy = prev?.busy ?: BookItem.Busy.Idle,
                note = prev?.note, audio = true)
        }.sortedWith(
            compareByDescending<BookItem> { it.hasUpdate }.thenBy { it.info.title })
    }

    private fun fileNameFromUrl(url: String): String {
        return try {
            java.net.URLDecoder.decode(url.substringAfterLast('/'), "UTF-8").trim()
        } catch (_: Exception) { url.substringAfterLast('/').trim() }
    }

    /** id книги библиотеки: gb-ТИП-gbId-язык[-xN]; тип может содержать дефис/цифры (bg-ss, bg72) */
    private val BOOK_ID_RE = Regex("^gb-(.+)-(\\d+)-([a-z]+)(?:-x\\d+)?$")

    /** Скачать файл книги/аудио и импортировать. Аудио едет тем же путём
     *  (importFile сам видит verse_audio), имя пака — из ссылки (для манифеста). */
    fun downloadBook(key: String) = viewModelScope.launch {
        val item = (_books.value + _audio.value).firstOrNull { it.info.key == key } ?: return@launch
        if (item.busy !is BookItem.Busy.Idle) return@launch
        val info = item.info
        val isAudio = item.audio
        fun set(busy: BookItem.Busy, note: String? = null) {
            _books.value = _books.value.map {
                if (it.info.key == key) it.copy(busy = busy, note = note) else it
            }
            _audio.value = _audio.value.map {
                if (it.info.key == key) it.copy(busy = busy, note = note) else it
            }
        }
        fun finish(installed: Int, missing: Boolean, note: String) {
            _books.value = _books.value.map {
                if (it.info.key == key) it.copy(installed = installed, missing = missing,
                    busy = BookItem.Busy.Idle, note = note) else it
            }
            _audio.value = _audio.value.map {
                if (it.info.key == key) it.copy(installed = installed, missing = missing,
                    busy = BookItem.Busy.Idle, note = note) else it
            }
        }
        try {
            // Дельта — своим с версии deltaFrom; новичкам и отставшим — полный файл
            val useDelta = !isAudio && info.deltaUrl.isNotBlank() &&
                    item.installed == info.deltaFrom && info.deltaFrom >= 0
            val url = if (useDelta) info.deltaUrl else info.url
            val sha = if (useDelta) info.deltaSha else info.sha256
            // Fail closed: каталог без контрольной суммы — не качаем и не импортируем
            if (sha.isBlank())
                throw IllegalStateException("В каталоге нет контрольной суммы для «${info.title}» — пропущено")
            val total = if (useDelta) info.deltaSize else info.size
            val dir = File(updater.updatesDir(), "books").apply { mkdirs() }
            // key приходит из каталога: белый список символов — из «../» не соберётся
            // выход из папки обновлений (путь файла от ключа изолирован)
            val safeKey = key.replace(Regex("[^A-Za-z0-9._-]"), "_")
            val out = File(dir, "$safeKey-v${info.version}" + (if (useDelta) "-delta" else "") + ".db")
            if (!(out.exists() && out.length() > 1024 && sha256hex(out) == sha)
            ) {
                try { out.delete() } catch (_: Exception) { }
                set(BookItem.Busy.Downloading(0, total))
                val headers = if (info.auth == "github" &&
                    com.vedalibrary.app.BuildConfig.GITHUB_FILES_TOKEN.isNotBlank()
                ) {
                    // Приватные релизы: без Accept API отдаст JSON-метаданные вместо байтов
                    mapOf("Authorization" to
                            "Bearer ${com.vedalibrary.app.BuildConfig.GITHUB_FILES_TOKEN}",
                        "Accept" to "application/octet-stream")
                } else emptyMap()
                downloader.fetch(url, out,
                    info.title + (if (useDelta) " (обновление)" else ""), { d, t ->
                    set(BookItem.Busy.Downloading(d, t))
                }, headers)
                if (sha256hex(out) != sha) {
                    try { out.delete() } catch (_: Exception) { }
                    throw IllegalStateException("Контрольная сумма не сошлась — файл битый")
                }
            }
            // Скачанный файл должен быть SQLite: JSON/HTML-ошибка сервера под видом
            // книги не должна уходить в импорт (глюк-диагноз вместо SQL-исключения)
            if (!com.vedalibrary.app.data.update.isSqliteFile(out))
                throw IllegalStateException("Файл не похож на базу SQLite — обновление отменено")
            set(BookItem.Busy.Importing("Импорт…"))
            val packName = if (isAudio) fileNameFromUrl(info.url) else null
            val res = importer.importFile(out, info.lang, replace = true, packName = packName, delta = useDelta) { d, t, label ->
                set(BookItem.Busy.Importing("$label ($d/$t)"))
            }
            if (res.failed.isNotEmpty() && res.bookIds.isEmpty())
                throw IllegalStateException(res.failed.first())
            prefs.setBookVersion(key, info.version)
            prefs.setBookIds(key, res.bookIds)
            val note = if (isAudio) "Готово: ${res.verses} записей"
            else if (useDelta) "Готово: обновлено ${res.verses} стихов" +
                    (if (res.failed.isNotEmpty()) " · пропущено: ${res.failed.size}" else "")
            else "Готово: ${res.bookIds.size} кн., ${res.verses} стихов" +
                    (if (res.failed.isNotEmpty()) " · пропущено: ${res.failed.size}" else "")
            finish(info.version, false, note)
        } catch (e: kotlinx.coroutines.CancellationException) {
            // Отмена (уход с экрана) — не показываем как «Ошибка»
            throw e
        } catch (e: Exception) {
            set(BookItem.Busy.Idle, "Ошибка: ${e.message}")
        }
    }
}
