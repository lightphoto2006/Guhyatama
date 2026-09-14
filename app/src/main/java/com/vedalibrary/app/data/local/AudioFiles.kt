package com.vedalibrary.app.data.local

import android.content.Context
import java.io.File

/**
 * Аудио стихов (санскрит): файлы лежат рядом с книгой, путь детерминирован —
 * отдельная Room-таблица не нужна. Та же схема используется импортёром и плеером.
 * filesDir/audio/<bookId>/<song>_<ch>_<txt>.mp3 (.ogg для Opus-паков Vagdhenu)
 */
object AudioFiles {
    private val SAFE = Regex("[^A-Za-z0-9_-]")

    fun dir(ctx: Context, bookId: String): File =
        File(ctx.filesDir, "audio/" + bookId.replace(SAFE, "_"))

    fun file(ctx: Context, bookId: String, song: String, ch: String, txt: String, ext: String = ".mp3"): File {
        val name = "${song}_${ch}_${txt}".replace(SAFE, "_") + ext
        return File(dir(ctx, bookId), name)
    }

    /** Что лежит: mp3 (старые паки) или ogg/opus (Vagdhenu) */
    fun fileAny(ctx: Context, bookId: String, song: String, ch: String, txt: String): File {
        val m = file(ctx, bookId, song, ch, txt, ".mp3")
        if (m.exists()) return m
        return file(ctx, bookId, song, ch, txt, ".ogg")
    }
}
