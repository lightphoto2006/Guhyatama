package com.vedalibrary.app.data.update

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.vedalibrary.app.BuildConfig
import com.vedalibrary.app.data.library.LibraryDbImporter
import com.vedalibrary.app.data.local.AppDatabase
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import java.io.File
import java.io.IOException
import java.net.URLDecoder

/**
 * Фоновый загрузчик и импортёр книг/аудио на базе WorkManager.
 * Переживает закрытие приложения и обновление APK, а благодаря Range-докачке
 * в Downloader.fetchStream продолжает скачивание с последнего сохранённого байта.
 */
@HiltWorker
class BookDownloadWorker @AssistedInject constructor(
    @Assisted appContext: Context,
    @Assisted params: WorkerParameters,
    private val updater: AppUpdater,
    private val downloader: Downloader,
    private val prefs: UpdatePrefs,
    private val importer: LibraryDbImporter,
    private val db: AppDatabase
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val key = inputData.getString(K_KEY) ?: return Result.failure()
        val title = inputData.getString(K_TITLE) ?: key
        val url = inputData.getString(K_URL) ?: return fail(key, "Нет URL книги")
        val sha = inputData.getString(K_SHA) ?: ""
        val size = inputData.getLong(K_SIZE, -1L)
        val version = inputData.getInt(K_VERSION, 0)
        val lang = inputData.getString(K_LANG) ?: "rus"
        val auth = inputData.getString(K_AUTH) ?: ""
        val deltaUrl = inputData.getString(K_DELTA_URL) ?: ""
        val deltaSha = inputData.getString(K_DELTA_SHA) ?: ""
        val deltaSize = inputData.getLong(K_DELTA_SIZE, -1L)
        val deltaFrom = inputData.getInt(K_DELTA_FROM, -1)
        val isAudio = inputData.getBoolean(K_IS_AUDIO, false)
        val installed = inputData.getInt(K_INSTALLED, 0)

        val notifId = NOTIF_BASE + (key.hashCode() and 0x7FFF)
        try {
            setForeground(foregroundInfo(notifId, title, "Подготовка…", 0L, size))
        } catch (_: Exception) { }

        val useDelta = !isAudio && deltaUrl.isNotBlank() && installed == deltaFrom && deltaFrom >= 0
        val attempts = if (useDelta) listOf(true, false) else listOf(false)
        var lastError: Exception? = null

        for ((i, withDelta) in attempts.withIndex()) {
            try {
                val note = runAttempt(
                    key = key, title = title,
                    url = if (withDelta) deltaUrl else url,
                    sha = if (withDelta) deltaSha else sha,
                    totalHint = if (withDelta) deltaSize else size,
                    version = version, lang = lang, auth = auth,
                    isAudio = isAudio, useDelta = withDelta, notifId = notifId
                )
                return Result.success(
                    workDataOf(K_KEY to key, K_VERSION to version, K_NOTE to note)
                )
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                lastError = e
                if (i != attempts.lastIndex && !isTransient(e)) {
                    // Дельта не применилась — пробуем полный файл
                    continue
                }
                if (isTransient(e)) {
                    return Result.retry()
                }
            }
        }
        val msg = (lastError?.message ?: lastError?.javaClass?.simpleName ?: "Неизвестная ошибка").take(200)
        return fail(key, msg)
    }

    private suspend fun runAttempt(
        key: String, title: String, url: String, sha: String, totalHint: Long,
        version: Int, lang: String, auth: String, isAudio: Boolean, useDelta: Boolean,
        notifId: Int
    ): String {
        if (sha.isBlank()) {
            throw PermanentError("В каталоге нет контрольной суммы для «$title» — пропущено")
        }
        val dir = File(updater.updatesDir(), "books").apply { mkdirs() }
        val safeKey = key.replace(Regex("[^A-Za-z0-9._-]"), "_")
        val out = File(dir, "$safeKey-v$version" + (if (useDelta) "-delta" else "") + ".db")
        val prevIds = prefs.bookIds(key)

        // Чистим устаревшие версии той же книги, но не трогаем .part/.part.meta текущей!
        try {
            val staleRe = Regex("^${Regex.escape(safeKey)}-v\\d+(-delta)?\\.db(\\.part(\\.meta)?)?$")
            val keepNames = setOf(out.name, "${out.name}.part", "${out.name}.part.meta")
            for (old in dir.listFiles() ?: emptyArray()) {
                if (old.name !in keepNames && staleRe.matchEntire(old.name) != null) {
                    try { old.delete() } catch (_: Exception) { }
                }
            }
        } catch (_: Exception) { }

        if (!(out.exists() && out.length() > 1024 && sha256hex(out) == sha)) {
            try { out.delete() } catch (_: Exception) { }
            if (auth == "github" && BuildConfig.GITHUB_FILES_TOKEN.isBlank()) {
                throw PermanentError("Токен доступа к книгам не настроен — обновление книг временно недоступно")
            }
            val headers = if (auth == "github" && BuildConfig.GITHUB_FILES_TOKEN.isNotBlank()) {
                mapOf(
                    "Authorization" to "Bearer ${BuildConfig.GITHUB_FILES_TOKEN}",
                    "Accept" to "application/octet-stream"
                )
            } else emptyMap()

            var lastUiMs = 0L
            fun reportDl(done: Long, total: Long) {
                val now = System.currentTimeMillis()
                if (now - lastUiMs < 400L && (total <= 0 || done < total)) return
                lastUiMs = now
                val effTotal = if (total > 0) total else totalHint
                setProgressAsync(
                    workDataOf(
                        K_KEY to key,
                        K_STAGE to STAGE_DOWNLOADING,
                        K_DONE to done,
                        K_TOTAL to effTotal
                    )
                )
                try {
                    setForegroundAsync(foregroundInfo(notifId, title, "Загрузка…", done, effTotal))
                } catch (_: Exception) { }
            }

            reportDl(0L, totalHint)
            try {
                downloader.fetchStream(
                    url = url,
                    out = out,
                    title = title + (if (useDelta) " (обновление)" else ""),
                    onProgress = { d, t -> reportDl(d, t) },
                    headers = headers,
                    expectedSha = sha
                )
            } catch (e: Exception) {
                if (isTransient(e)) throw e
                // Фолбэк на системный DownloadManager только для не-сетевых сбоев fetchStream
                try {
                    downloader.fetch(
                        url, out,
                        title + (if (useDelta) " (обновление)" else ""),
                        { d, t ->
                            setProgressAsync(
                                workDataOf(
                                    K_KEY to key,
                                    K_STAGE to STAGE_DOWNLOADING,
                                    K_DONE to d,
                                    K_TOTAL to t
                                )
                            )
                        },
                        headers
                    )
                } catch (e2: Exception) {
                    throw IllegalStateException(
                        "Не скачалось: ${e.javaClass.simpleName}: ${e.message}; fallback: ${e2.javaClass.simpleName}: ${e2.message}".take(200),
                        e2
                    )
                }
            }

            if (sha256hex(out) != sha) {
                try { out.delete() } catch (_: Exception) { }
                throw PermanentError("Контрольная сумма не сошлась — файл битый")
            }
        }

        if (!isSqliteFile(out)) {
            try { out.delete() } catch (_: Exception) { }
            throw PermanentError("Файл не похож на базу SQLite — обновление отменено")
        }

        setProgress(workDataOf(K_KEY to key, K_STAGE to STAGE_IMPORTING, K_LABEL to "Импорт…"))
        try {
            setForeground(foregroundInfo(notifId, title, "Импорт…", 0L, -1L))
        } catch (_: Exception) { }

        val packName = if (isAudio) fileNameFromUrl(url) else null
        var lastImpMs = 0L
        val res = importer.importFile(out, lang, replace = true, packName = packName, delta = useDelta) { d, t, label ->
            val now = System.currentTimeMillis()
            if (now - lastImpMs >= 350L || d >= t) {
                lastImpMs = now
                setProgressAsync(
                    workDataOf(
                        K_KEY to key,
                        K_STAGE to STAGE_IMPORTING,
                        K_LABEL to "$label ($d/$t)"
                    )
                )
            }
        }
        if (res.failed.isNotEmpty() && res.bookIds.isEmpty()) {
            throw PermanentError(res.failed.first())
        }

        var removed = 0
        if (!useDelta) {
            val stale = prevIds - res.bookIds.toSet() - prefs.allBookIdsExcept(key)
            for (id in stale) {
                try { db.library().deleteBookCascade(id); removed++ } catch (_: Exception) { }
            }
        }
        prefs.setBookVersion(key, version)
        prefs.setBookIds(key, res.bookIds)
        if (res.failed.isEmpty()) {
            try { out.delete() } catch (_: Exception) { }
        }

        return if (isAudio) "Готово: ${res.verses} записей"
        else if (useDelta) "Готово: обновлено ${res.verses} стихов" +
                (if (res.failed.isNotEmpty()) " · пропущено: ${res.failed.size}" else "")
        else "Готово: ${res.bookIds.size} кн., ${res.verses} стихов" +
                (if (removed > 0) " · убрано старых книг: $removed" else "") +
                (if (res.failed.isNotEmpty()) " · пропущено: ${res.failed.size}" else "")
    }

    private fun isTransient(e: Exception): Boolean {
        if (e is PermanentError) return false
        if (e is IOException) return true
        val msg = e.message ?: ""
        return msg.startsWith("HTTP 5") || msg.startsWith("HTTP 429")
    }

    private fun fail(key: String, msg: String): Result =
        Result.failure(workDataOf(K_KEY to key, K_ERROR to msg))

    private fun fileNameFromUrl(url: String): String = try {
        URLDecoder.decode(url.substringAfterLast('/'), "UTF-8").trim()
    } catch (_: Exception) { url.substringAfterLast('/').trim() }

    private fun foregroundInfo(
        notifId: Int, title: String, subtitle: String, done: Long, total: Long
    ): ForegroundInfo {
        ensureChannel()
        val builder = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle(title)
            .setContentText(subtitle)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
        if (total > 0) {
            val max = 1000
            val cur = ((done * max) / total).toInt().coerceIn(0, max)
            builder.setProgress(max, cur, false)
        } else {
            builder.setProgress(0, 0, true)
        }
        val notif: Notification = builder.build()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ForegroundInfo(notifId, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            ForegroundInfo(notifId, notif)
        }
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = applicationContext.getSystemService(NotificationManager::class.java) ?: return
        if (nm.getNotificationChannel(CHANNEL_ID) != null) return
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "Загрузка книг", NotificationManager.IMPORTANCE_LOW)
        )
    }

    private class PermanentError(message: String) : IllegalStateException(message)

    companion object {
        const val TAG = "book_download"
        private const val CHANNEL_ID = "book_downloads"
        private const val NOTIF_BASE = 4100

        const val K_KEY = "key"
        const val K_TITLE = "title"
        const val K_URL = "url"
        const val K_SHA = "sha256"
        const val K_SIZE = "size"
        const val K_VERSION = "version"
        const val K_LANG = "lang"
        const val K_AUTH = "auth"
        const val K_DELTA_URL = "deltaUrl"
        const val K_DELTA_SHA = "deltaSha"
        const val K_DELTA_SIZE = "deltaSize"
        const val K_DELTA_FROM = "deltaFrom"
        const val K_IS_AUDIO = "isAudio"
        const val K_INSTALLED = "installed"

        const val K_STAGE = "stage"
        const val K_DONE = "done"
        const val K_TOTAL = "total"
        const val K_LABEL = "label"
        const val K_NOTE = "note"
        const val K_ERROR = "error"

        const val STAGE_DOWNLOADING = "downloading"
        const val STAGE_IMPORTING = "importing"

        fun uniqueName(key: String) = "book_dl_$key"
    }
}
