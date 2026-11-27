package com.vedalibrary.app.ui.vm

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import android.util.Log
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.workDataOf
import com.vedalibrary.app.data.library.LibraryDbImporter
import com.vedalibrary.app.data.local.AppDatabase
import com.vedalibrary.app.data.update.ApkInfo
import com.vedalibrary.app.data.update.AppUpdater
import com.vedalibrary.app.data.update.BookDownloadWorker
import com.vedalibrary.app.data.update.BookInfo
import com.vedalibrary.app.data.update.Downloader
import com.vedalibrary.app.data.update.fetchStream
import com.vedalibrary.app.data.update.UpdatePrefs
import com.vedalibrary.app.data.update.parseApkInfo
import com.vedalibrary.app.data.update.parseBookInfos
import com.vedalibrary.app.data.update.sha256hex
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
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
    @ApplicationContext private val ctx: Context,
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
        // Обновление — только по версии. missing — диагностика («нет в библиотеке»),
        // но не повод предлагать перекачать установленную книгу (был баг: 150 МБ заново).
        val hasUpdate: Boolean get() = installed < info.version
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
    private var workByKey: Map<String, WorkInfo> = emptyMap()

    init {
        viewModelScope.launch {
            WorkManager.getInstance(ctx).getWorkInfosByTagFlow(BookDownloadWorker.TAG).collect { list ->
                val byKey = HashMap<String, WorkInfo>()
                for (wi in list) {
                    val k = wi.tags.firstOrNull { it.startsWith("book_dl_") }
                        ?.removePrefix("book_dl_")
                        ?: wi.progress.getString(BookDownloadWorker.K_KEY)
                        ?: wi.outputData.getString(BookDownloadWorker.K_KEY)
                        ?: continue
                    byKey[k] = wi
                }
                workByKey = byKey
                applyWorkInfos()
            }
        }
    }

    private fun applyWorkInfos() {
        fun updateList(src: List<BookItem>): List<BookItem> = src.map { item ->
            val wi = workByKey[item.info.key] ?: return@map item
            when (wi.state) {
                WorkInfo.State.ENQUEUED, WorkInfo.State.RUNNING, WorkInfo.State.BLOCKED -> {
                    val stage = wi.progress.getString(BookDownloadWorker.K_STAGE)
                    if (stage == BookDownloadWorker.STAGE_IMPORTING) {
                        val lbl = wi.progress.getString(BookDownloadWorker.K_LABEL) ?: "Импорт…"
                        item.copy(busy = BookItem.Busy.Importing(lbl), note = null)
                    } else {
                        val done = wi.progress.getLong(BookDownloadWorker.K_DONE, 0L)
                        val total = wi.progress.getLong(BookDownloadWorker.K_TOTAL, item.info.size)
                        val partLen = if (done == 0L) partFileLength(item.info) else 0L
                        val shownDone = if (done > 0L) done else partLen
                        val note = if (wi.state == WorkInfo.State.ENQUEUED && shownDone > 0L)
                            "Ожидание сети для докачки…" else null
                        item.copy(busy = BookItem.Busy.Downloading(shownDone, total), note = note)
                    }
                }
                WorkInfo.State.SUCCEEDED -> {
                    val ver = wi.outputData.getInt(BookDownloadWorker.K_VERSION, item.installed)
                    val note = wi.outputData.getString(BookDownloadWorker.K_NOTE)
                    if (item.busy !is BookItem.Busy.Idle || ver > item.installed) {
                        item.copy(
                            installed = maxOf(item.installed, ver),
                            missing = false,
                            busy = BookItem.Busy.Idle,
                            note = note ?: item.note
                        )
                    } else item
                }
                WorkInfo.State.FAILED -> {
                    val err = wi.outputData.getString(BookDownloadWorker.K_ERROR)
                    if (item.busy !is BookItem.Busy.Idle && !err.isNullOrBlank()) {
                        item.copy(busy = BookItem.Busy.Idle, note = "Ошибка: $err")
                    } else item
                }
                else -> item
            }
        }
        _books.value = updateList(_books.value)
        _audio.value = updateList(_audio.value)
    }

    private fun partFileLength(info: BookInfo): Long {
        val safeKey = info.key.replace(Regex("[^A-Za-z0-9._-]"), "_")
        val dir = File(updater.updatesDir(), "books")
        val full = File(dir, "$safeKey-v${info.version}.db.part")
        return if (full.exists()) full.length() else 0L
    }

    /** Тихая автопроверка при старте (не чаще раза в сутки). Диалог — только если есть
     *  новая версия и её не пропускали. */
    fun autoCheck() = viewModelScope.launch {
        // Чистим уже-установленные APK до обращения к серверу и до троттлинга —
        // чтобы место освобождалось при каждом старте, даже без сети
        updater.cleanupInstalledApks()
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
        // Сначала тихо убираем APK уже установленных версий (до сетевого запроса)
        updater.cleanupInstalledApks()
        _state.value = State.Checking
        val cat = try { updater.fetchCatalog() } catch (e: Exception) {
            _state.value = State.Error("Нет связи: ${e.javaClass.simpleName}: ${e.message ?: "причина неизвестна"}")
            return@launch
        }
        if (cat == null) {
            _state.value = State.Error("Нет связи: " + (AppUpdater.lastCatalogError ?: "причина неизвестна"))
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
                _booksMsg.value = "Нет связи: " + (AppUpdater.lastCatalogError ?: "причина неизвестна")
                return@launch
            }
            updater.markChecked()
            catalog = cat
            refreshBooks(cat)
            val n = booksPending
            _booksMsg.value = if (n == 0) "Всё последнее" else "К обновлению: $n"
        } catch (e: Exception) {
            _booksMsg.value = "Ошибка: ${e.javaClass.simpleName}: ${e.message}"
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
                // Дельта — только со своей версии (deltaFrom == текущий versionCode),
                // иначе сразу полный APK. Патч битый/не применился — тоже тихо полный APK.
                val vcNow = updater.currentVersion().second
                if (info.deltaUrl.isNotBlank() && info.deltaFrom >= 0 && vcNow == info.deltaFrom) {
                    val pf = File(
                        updater.updatesDir(),
                        "Guhyatama-delta-${info.deltaFrom}-to-${info.versionCode}.bsdiff"
                    )
                    try {
                        _state.value = State.Downloading(0, info.deltaSize)
                        val hdrs = if (info.deltaUrl.startsWith("https://api.github.com/"))
                            mapOf(
                                "Authorization" to
                                    "Bearer ${com.vedalibrary.app.BuildConfig.GITHUB_FILES_TOKEN}",
                                "Accept" to "application/octet-stream"
                            )
                        else emptyMap()
                        var deltaErr1: Exception? = null
                        try {
                            downloader.fetchStream(
                                info.deltaUrl, pf, "Патч ${info.versionName}",
                                onProgress = { d, t -> _state.value = State.Downloading(d, t) },
                                headers = hdrs,
                                expectedSha = info.deltaSha
                            )
                        } catch (e: Exception) {
                            deltaErr1 = e
                            try { pf.delete() } catch (_: Exception) { }
                        }
                        if (deltaErr1 != null) {
                            Log.e("Updater", "delta stream failed, fallback DownloadManager", deltaErr1)
                            try {
                                downloader.fetch(
                                    info.deltaUrl, pf, "Патч ${info.versionName}",
                                    onProgress = { d, t -> _state.value = State.Downloading(d, t) },
                                    headers = hdrs
                                )
                                deltaErr1 = null
                            } catch (e2: Exception) {
                                try { pf.delete() } catch (_: Exception) { }
                            }
                        }
                        // sha патча из каталога (если задан) — не сошёлся, значит патч
                        // битый/подменённый: удаляем и уходим на полный APK
                        val patchOk = info.deltaSha.isBlank() || sha256hex(pf) == info.deltaSha
                        val f = if (patchOk) updater.applyApkDelta(pf, info) else null
                        try { pf.delete() } catch (_: Exception) { }
                        if (f != null) {
                            _state.value = State.Ready(f, info)
                            return@launch
                        }
                    } catch (e: kotlinx.coroutines.CancellationException) {
                        try { pf.delete() } catch (_: Exception) { }
                        throw e
                    } catch (_: Exception) {
                        // патч не скачался/не применился — тихо падаем в полное скачивание
                        try { pf.delete() } catch (_: Exception) { }
                    }
                }
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
        } catch (t: Throwable) {
            _state.value = State.Error("Установка: ${t.javaClass.simpleName}: ${t.message}")
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
        // Файлы уже скачанных книг: наличие файла важнее старых id в prefs
        val bookFiles = try {
            java.io.File(updater.updatesDir(), "books").listFiles()?.map { it.name } ?: emptyList()
        } catch (_: Exception) { emptyList() }
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
                    val safeKey = info.key.replace(Regex("[^A-Za-z0-9._-]"), "_")
                    val hasFile = bookFiles.any {
                        it.startsWith("$safeKey-v") && it.endsWith(".db")
                    }
                    val ids = prefs.bookIds(info.key)
                    missing = !hasFile && ids.isNotEmpty() &&
                            ids.any { db.library().book(it) == null }
                        // После обновления базы книги могли получить новые gb-id —
                        // сверяем по отпечатку каталога и пересохраняем актуальные id,
                        // чтобы «книга удалена» не показывалась при живых книгах.
                        if (missing && info.fp.isNotEmpty()) {
                            val mineNow = db.library().booksAll()
                            val cntNow = try {
                                db.library().verseCountsByBook().associate { it.bookId to it.n }
                            } catch (_: Exception) { emptyMap<String, Int>() }
                            val hit = linkedSetOf<String>()
                            for (f in info.fp) {
                                val cand = mineNow.firstOrNull {
                                    val m = BOOK_ID_RE.matchEntire(it.id) ?: return@firstOrNull false
                                    m.groupValues[1].lowercase() == f.t &&
                                            m.groupValues[2].toLongOrNull() == f.g &&
                                            m.groupValues[3].lowercase() == info.lang
                                }
                                val n = cand?.let { cntNow[it.id] } ?: -1
                                if (cand != null && (n == f.v || (f.vg >= 0 && n == f.vg))) {
                                    hit += cand.id
                                } else {
                                    hit.clear()
                                    break
                                }
                            }
                            if (hit.size == info.fp.size) {
                                prefs.setBookIds(info.key, hit)
                                missing = false
                            }
                        }
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
        applyWorkInfos()
    }

    private fun fileNameFromUrl(url: String): String {
        return try {
            java.net.URLDecoder.decode(url.substringAfterLast('/'), "UTF-8").trim()
        } catch (_: Exception) { url.substringAfterLast('/').trim() }
    }

    /** id книги библиотеки: gb-ТИП-gbId-язык[-xN]; тип может содержать дефис/цифры (bg-ss, bg72) */
    private val BOOK_ID_RE = Regex("^gb-(.+)-(\\d+)-([a-z]+)(?:-x\\d+)?$")

    /** Запустить фоновое скачивание и импорт книги/аудио через WorkManager.
     *  Переживает закрытие/обновление приложения и продолжает с места остановки. */
    fun downloadBook(key: String) = viewModelScope.launch {
        val item = (_books.value + _audio.value).firstOrNull { it.info.key == key } ?: return@launch
        if (item.busy !is BookItem.Busy.Idle) return@launch
        val info = item.info
        val partLen = partFileLength(info)
        _books.value = _books.value.map {
            if (it.info.key == key) it.copy(busy = BookItem.Busy.Downloading(partLen, info.size), note = null) else it
        }
        _audio.value = _audio.value.map {
            if (it.info.key == key) it.copy(busy = BookItem.Busy.Downloading(partLen, info.size), note = null) else it
        }

        val req = OneTimeWorkRequestBuilder<BookDownloadWorker>()
            .addTag(BookDownloadWorker.TAG)
            .addTag(BookDownloadWorker.uniqueName(key))
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .setInputData(
                workDataOf(
                    BookDownloadWorker.K_KEY to info.key,
                    BookDownloadWorker.K_TITLE to info.title,
                    BookDownloadWorker.K_URL to info.url,
                    BookDownloadWorker.K_SHA to info.sha256,
                    BookDownloadWorker.K_SIZE to info.size,
                    BookDownloadWorker.K_VERSION to info.version,
                    BookDownloadWorker.K_LANG to info.lang,
                    BookDownloadWorker.K_AUTH to info.auth,
                    BookDownloadWorker.K_DELTA_URL to info.deltaUrl,
                    BookDownloadWorker.K_DELTA_SHA to info.deltaSha,
                    BookDownloadWorker.K_DELTA_SIZE to info.deltaSize,
                    BookDownloadWorker.K_DELTA_FROM to info.deltaFrom,
                    BookDownloadWorker.K_IS_AUDIO to item.audio,
                    BookDownloadWorker.K_INSTALLED to item.installed
                )
            )
            .build()

        WorkManager.getInstance(ctx).enqueueUniqueWork(
            BookDownloadWorker.uniqueName(key),
            ExistingWorkPolicy.KEEP,
            req
        )
    }
}
