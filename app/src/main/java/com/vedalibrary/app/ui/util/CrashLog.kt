package com.vedalibrary.app.ui.util

import android.content.Context
import java.io.File

/** Минимальный репортер падений: стектрейс в файл + показ при следующем запуске.
 *  Нужен, чтобы чинить падения на устройствах без adb (Oppo/Samsung пользователя). */
object CrashLog {
    private const val NAME = "crash_last.txt"

    fun install(ctx: Context) {
        val appCtx = ctx.applicationContext
        val prev = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { t, e ->
            try {
                val sw = java.io.StringWriter()
                e.printStackTrace(java.io.PrintWriter(sw))
                val head = try {
                    android.os.Build.MANUFACTURER + " " + android.os.Build.MODEL +
                        " API " + android.os.Build.VERSION.SDK_INT
                } catch (_: Exception) { "?" }
                File(appCtx.filesDir, NAME).writeText(
                    head + "\n" + t.name + ": " + e.toString() + "\n" +
                        sw.toString().take(8000)
                )
            } catch (_: Exception) { }
            try { prev?.uncaughtException(t, e) } catch (_: Exception) { }
        }
    }

    fun read(ctx: Context): String? = try {
        File(ctx.filesDir, NAME).takeIf { it.isFile }?.readText()?.takeIf { it.isNotBlank() }
    } catch (_: Exception) { null }

    /** Компактная выжимка: устройство, поток+исключение, первые кадры. Для диалога
     *  и буфера обмена — полный лог в Telegram не влезает, а нужен именно верх. */
    fun digest(s: String): String {
        val lines = s.split("\n")
        val sb = StringBuilder()
        var header = 0
        for (ln in lines) {
            val t = ln.trim()
            if (t.startsWith("at ") || t.isEmpty()) continue
            if (header >= 4) break
            sb.append(t).append('\n'); header++
        }
        val ats = lines.filter { it.trim().startsWith("at ") }
        for (a in ats.take(10)) sb.append(a.trim()).append('\n')
        if (ats.size > 10) sb.append("... ещё ").append(ats.size - 10)
            .append(" строк стека (полный лог в ").append(NAME).append(")")
        return sb.toString().take(1400)
    }

    fun clear(ctx: Context) {
        try { File(ctx.filesDir, NAME).delete() } catch (_: Exception) { }
    }
}
