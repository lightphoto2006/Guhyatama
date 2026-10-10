package com.vedalibrary.app.data.update

import android.app.DownloadManager
import android.content.Context
import android.net.Uri
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest
import java.util.Collections
import javax.inject.Inject
import javax.inject.Singleton

fun sha256hex(f: File): String {
    val d = MessageDigest.getInstance("SHA-256")
    f.inputStream().use { ins ->
        val buf = ByteArray(65536)
        while (true) {
            val n = ins.read(buf)
            if (n < 0) break
            d.update(buf, 0, n)
        }
    }
    return d.digest().joinToString("") { "%02x".format(it) }
}

/** SHA-256 от байтов в памяти (тот же hex-формат, что у File-версии) */
fun sha256hex(bytes: ByteArray): String =
    MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

/** Заголовок "SQLite format 3\0" (16 байт): битый/чужой контент (JSON-ошибка
 *  сервера, HTML-страница) не уходит в импорт, а получает внятную ошибку. */
fun isSqliteFile(f: File): Boolean = try {
    val magic = "SQLite format 3\u0000".toByteArray(Charsets.US_ASCII)
    f.inputStream().use { ins ->
        val h = ByteArray(16)
        var n = 0
        while (n < h.size) {
            val r = ins.read(h, n, h.size - n)
            if (r < 0) break
            n += r
        }
        n == h.size && h.contentEquals(magic)
    }
} catch (_: Exception) { false }

/** Общая качалка (APK, книги, аудиопаки): системный DownloadManager с докачкой.
 *  Кидает исключение с текстом для UI. */
@Singleton
class Downloader @Inject constructor(@ApplicationContext private val ctx: Context) {
    private val active = Collections.synchronizedSet(mutableSetOf<Long>())

    suspend fun fetch(
        url: String, out: File, title: String,
        onProgress: (done: Long, total: Long) -> Unit = { _, _ -> },
        headers: Map<String, String> = emptyMap()
    ): File = withContext(Dispatchers.IO) {
        try { out.parentFile?.mkdirs() } catch (_: Exception) { }
        val dm = ctx.getSystemService(DownloadManager::class.java)
            ?: throw IllegalStateException("Нет DownloadManager")
        // Качаем во временный *.part и подменяем конечный файл rename'ом:
        // обрыв/крэш не оставляет кусок на месте целевого файла — иначе
        // «недокачанный >1 КБ» проходил бы проверку переиспользования у вызывающих
        val part = File(out.path + ".part")
        try { part.delete() } catch (_: Exception) { }
        val id = dm.enqueue(DownloadManager.Request(Uri.parse(url)).apply {
            setTitle(title)
            setDescription("Загрузка")
            setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE)
            setDestinationUri(Uri.fromFile(part))
            setAllowedOverMetered(true)
            // Приватные релизы GitHub: Authorization заголовком (DownloadManager умеет)
            headers.forEach { (k, v) -> addRequestHeader(k, v) }
        })
        active.add(id)
        try {
            var doneFile: File? = null
            while (doneFile == null) {
                dm.query(DownloadManager.Query().setFilterById(id)).use { cur ->
                    if (!cur.moveToFirst()) throw IllegalStateException("Загрузка отменена")
                    val st = cur.getInt(cur.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS))
                    val done = cur.getLong(cur.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR))
                    val total = cur.getLong(cur.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES))
                    when (st) {
                        DownloadManager.STATUS_SUCCESSFUL -> {
                            if (!part.exists() || part.length() < 1024)
                                throw IllegalStateException("Файл не докачался")
                            try { if (out.exists()) out.delete() } catch (_: Exception) { }
                            if (!part.renameTo(out))
                                throw IllegalStateException("Не удалось сохранить файл")
                            doneFile = out
                        }
                        DownloadManager.STATUS_FAILED -> {
                            val reason = try {
                                cur.getInt(cur.getColumnIndexOrThrow(DownloadManager.COLUMN_REASON))
                            } catch (_: Exception) { -1 }
                            throw IllegalStateException("Ошибка загрузки ($reason)")
                        }
                        else -> onProgress(done, total)
                    }
                }
                if (doneFile == null) delay(500)
            }
            return@withContext doneFile!!
        } catch (e: Exception) {
            try { dm.remove(id) } catch (_: Exception) { }
            try { part.delete() } catch (_: Exception) { }
            throw e
        } finally {
            active.remove(id)
        }
    }

    fun cancelAll() {
        val dm = ctx.getSystemService(DownloadManager::class.java) ?: return
        synchronized(active) {
            active.toList().forEach { try { dm.remove(it) } catch (_: Exception) { } }
            active.clear()
        }
    }
}
