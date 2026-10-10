package com.vedalibrary.app.data.update

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.Settings
import androidx.core.content.FileProvider
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import javax.inject.Inject
import javax.inject.Singleton

/** Проверка, скачивание и установка обновлений приложения.
 *  Качалка общая (Downloader), состояние — в UpdatePrefs. */
@Singleton
class AppUpdater @Inject constructor(
    @ApplicationContext private val ctx: Context,
    private val downloader: Downloader,
    private val prefs: UpdatePrefs
) {
    /** Текущие (имя, код) установленного APK */
    fun currentVersion(): Pair<String, Long> {
        return try {
            val pm = ctx.packageManager
            val pi = if (Build.VERSION.SDK_INT >= 33) {
                pm.getPackageInfo(ctx.packageName, PackageManager.PackageInfoFlags.of(0))
            } else {
                @Suppress("DEPRECATION") pm.getPackageInfo(ctx.packageName, 0)
            }
            val vc = if (Build.VERSION.SDK_INT >= 28) pi.longVersionCode
            else @Suppress("DEPRECATION") pi.versionCode.toLong()
            (pi.versionName ?: "?") to vc
        } catch (_: Exception) { "?" to 0L }
    }

    /** Каталог с сервера (null = сеть/разбор не удались, молча). */
    suspend fun fetchCatalog(): JSONObject? = withContext(Dispatchers.IO) {
        var conn: HttpURLConnection? = null
        try {
            conn = (URL(CATALOG_URL).openConnection() as HttpURLConnection).apply {
                connectTimeout = 15000
                readTimeout = 15000
            }
            if (conn.responseCode != 200) return@withContext null
            JSONObject(conn.inputStream.bufferedReader().readText())
        } catch (_: Exception) { null }
        finally { try { conn?.disconnect() } catch (_: Exception) { } }
    }

    /** Папка скачанных APK (та же, куда качает download) */
    fun updatesDir(): File =
        File(ctx.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "updates").apply { mkdirs() }

    /** Скачать APK (готовый целый файл переиспользуется). Кидает исключение с текстом для UI. */
    suspend fun download(info: ApkInfo, onProgress: (done: Long, total: Long) -> Unit): File =
        withContext(Dispatchers.IO) {
            // Fail closed: без контрольной суммы в каталоге не качаем и не ставим —
            // иначе битый или подменённый APK проходил бы «проверку» пустым полем
            if (info.sha256.isBlank())
                throw IllegalStateException("В каталоге нет контрольной суммы для ${info.versionName} — обновление отменено")
            val out = File(updatesDir(), "Guhyatama-${info.versionCode}.apk")
            if (out.exists() && out.length() > 1024 && sha256hex(out) == info.sha256)
                return@withContext out
            try { out.delete() } catch (_: Exception) { }
            downloader.fetch(info.url, out, "Гухьятама ${info.versionName}", onProgress)
            if (sha256hex(out) != info.sha256) {
                try { out.delete() } catch (_: Exception) { }
                throw IllegalStateException("Контрольная сумма не сошлась — файл битый")
            }
            out
        }

    /** Применяет bsdiff-патч к установленному APK (sourceDir) → новый APK.
     *  Путь как в Play Market: качаем маленький патч, воспроизводим целый APK
     *  байт-в-байт (подпись нового APK валидна — приватный ключ клиенту не нужен).
     *  Fallback null = битый патч: нет исходного APK, Bspatch не воспроизвёл,
     *  sha256 нового APK не сошёлся — вызывающий тихо уходит на полный APK. */
    fun applyApkDelta(patchFile: File, info: ApkInfo): File? {
        try {
            val oldApk = File(ctx.applicationInfo.sourceDir)  // установленный base.apk
            if (!oldApk.exists()) return null
            val oldBytes = oldApk.readBytes()
            val newBytes = Bspatch.apply(oldBytes, patchFile.readBytes())
            if (sha256hex(newBytes) != info.sha256) return null   // sha нового APK не сошёлся
            val out = File(updatesDir(), "Guhyatama-${info.versionCode}.apk")
            try { out.delete() } catch (_: Exception) { }
            out.writeBytes(newBytes)
            return out
        } catch (_: Exception) { return null }
    }

    /** Удаляет скачанные APK уже установленных версий (vc <= текущего), их .part-сироты
     *  и осиротевшие bsdiff-патчи (процесс убили до конца обновления). Тихо, без исключений. */
    fun cleanupInstalledApks() {
        try {
            val vcNow = currentVersion().second
            val re = Regex("^Guhyatama-(\\d+)\\.apk(?:\\.part)?$")
            // патчи перекачиваются и удаляются после применения в download() —
            // осиротевший (крэш посреди дельты) только жрёт место
            val rePatch = Regex("^Guhyatama-delta-.*\\.bsdiff(?:\\.part)?$")
            for (f in updatesDir().listFiles() ?: return) {
                if (rePatch.matches(f.name)) {
                    try { f.delete() } catch (_: Exception) { }
                    continue
                }
                val m = re.matchEntire(f.name) ?: continue // чужие файлы (books/ и пр.) не трогаем
                val vc = m.groupValues[1].toLongOrNull() ?: continue
                // vc > текущего — скачано, но ещё не установлено: файл нужен для установки
                if (vc <= vcNow) {
                    try { f.delete() } catch (_: Exception) { }
                }
            }
        } catch (_: Exception) { }
    }

    fun cancelDownload() = downloader.cancelAll()

    fun lastCheck(): Long = prefs.lastCheck()
    fun skippedVersion(): Long = prefs.skippedVersion()
    fun markChecked() = prefs.markChecked()
    fun skip(vc: Long) = prefs.skip(vc)

    /** Запуск установки. false = нет права «установка из этого источника»:
     *  открыты системные настройки, после возврата нажать «Установить» ещё раз. */
    fun install(apk: File): Boolean {
        if (!ctx.packageManager.canRequestPackageInstalls()) {
            ctx.startActivity(
                Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${ctx.packageName}"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
            return false
        }
        val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.provider", apk)
        ctx.startActivity(
            Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, "application/vnd.android.package-archive")
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
            }
        )
        return true
    }
}
