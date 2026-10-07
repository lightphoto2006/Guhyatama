package com.vedalibrary.app.ui.audio

import android.content.Context
import android.net.Uri
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import java.io.File
import java.util.Locale

/**
 * Озвучка санскрита стиха: MP3/OGG-файл (импорт аудио-БД) или синтез.
 * Плеер — ExoPlayer: системный MediaPlayer не играет Opus-in-Ogg (паки ШБ молчали).
 * Один инстанс на экран, release() в onDispose. Без внешних зависимостей, кроме media3.
 */
class VerseAudioPlayer(private val ctx: Context) {
    private var exo: ExoPlayer? = null
    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private var pending: String? = null

    /** Вызывается на завершение (естественное или stop) — UI гасит кнопку */
    var onDone: (() -> Unit)? = null
    var playing: Boolean = false
        private set

    fun playFile(path: String) {
        stop()
        try {
            val p = ExoPlayer.Builder(ctx).build()
            exo = p
            p.addListener(object : Player.Listener {
                override fun onPlaybackStateChanged(state: Int) {
                    if (state == Player.STATE_ENDED) {
                        playing = false
                        onDone?.invoke()
                    }
                }
            })
            p.setMediaItem(MediaItem.fromUri(Uri.fromFile(File(path))))
            p.prepare()
            p.play()
            playing = true
        } catch (_: Exception) {
            playing = false
            onDone?.invoke()
        }
    }

    /** Движки синтеза, реально установленные в системе (через queries в манифесте).
     *  getPackageInfo тут врал бы на Android 11+ (невидимость чужих пакетов). */
    private fun installedEngines(): List<String> = try {
        @Suppress("DEPRECATION")
        val svcs = ctx.packageManager.queryIntentServices(
            android.content.Intent("android.intent.action.TTS_SERVICE"), 0)
        svcs.mapNotNull { it.serviceInfo?.packageName }.distinct()
    } catch (_: Exception) {
        emptyList()
    }

    /** Предпочтительный движок: Google TTS, иначе первый доступный, иначе дефолт */
    private fun preferredEngine(): String? {
        val found = installedEngines()
        return if ("com.google.android.tts" in found) "com.google.android.tts" else found.firstOrNull()
    }

    private fun newTts(engine: String?, listener: (Int) -> Unit): TextToSpeech =
        if (engine != null) TextToSpeech(ctx.applicationContext, listener, engine)
        else TextToSpeech(ctx.applicationContext, listener)

    /** Проверка синтеза: движок есть + голос хинди или санскрита скачан.
     *  engines — найденные движки, для диагностики в диалоге. */
    sealed interface TtsCheck {
        object Ready : TtsCheck
        class NoEngine(val engines: List<String>) : TtsCheck
        class NoVoice(val engines: List<String>) : TtsCheck
    }

    fun checkTts(cb: (TtsCheck) -> Unit) {
        try {
            val t = tts
            if (t != null && ttsReady) {
                cb(if (hasIndicVoice(t)) TtsCheck.Ready else TtsCheck.NoVoice(installedEngines()))
                return
            }
            val found = installedEngines()
            if (found.isEmpty()) {
                cb(TtsCheck.NoEngine(emptyList()))
                return
            }
            // Цепочка: Google -> остальные -> дефолт. Один падает — пробуем следующий.
            val chain = (listOf("com.google.android.tts").filter { it in found } + found)
                .distinct().map { it as String? } + listOf(null)
            tryEngine(chain, found, cb)
        } catch (_: Exception) {
            cb(TtsCheck.NoEngine(emptyList()))
        }
    }

    private fun tryEngine(chain: List<String?>, found: List<String>, cb: (TtsCheck) -> Unit) {
        if (chain.isEmpty()) {
            cb(TtsCheck.NoEngine(found))
            return
        }
        val eng = chain.first()
        try {
            val t = newTts(eng) { st ->
                if (st == TextToSpeech.SUCCESS) {
                    ttsReady = true
                    val cur = tts
                    cb(if (cur != null && hasIndicVoice(cur)) TtsCheck.Ready else TtsCheck.NoVoice(found))
                } else {
                    try { tts?.shutdown() } catch (_: Exception) { }
                    tts = null
                    ttsReady = false
                    tryEngine(chain.drop(1), found, cb)
                }
            }
            tts = t
        } catch (_: Exception) {
            tts = null
            tryEngine(chain.drop(1), found, cb)
        }
    }

    /** Голос хинди (лучше для санскрита) или санскрита; офлайн-предпочтительнее */
    private fun hasIndicVoice(t: TextToSpeech): Boolean = try {
        val vs = t.voices ?: return false
        vs.any { (it.locale.language == "hi" || it.locale.language == "sa") && !it.isNetworkConnectionRequired } ||
                vs.any { it.locale.language == "hi" || it.locale.language == "sa" }
    } catch (_: Exception) {
        false
    }

    /** Язык синтеза: хинди, запасной — санскрит */
    private fun pickLanguage(t: TextToSpeech) {
        try {
            val r = t.setLanguage(Locale("hi", "IN"))
            if (r == TextToSpeech.LANG_MISSING_DATA || r == TextToSpeech.LANG_NOT_SUPPORTED) {
                t.setLanguage(Locale("sa"))
            }
        } catch (_: Exception) { }
    }

    /** Синтез деванагари: хинди-голос (или санскрит, он есть в Google TTS) */
    fun speak(text: String) {
        stop()
        try {
            val t = tts ?: newTts(preferredEngine()) { st ->
                if (st == TextToSpeech.SUCCESS) {
                    ttsReady = true
                    try {
                        tts?.let { pickLanguage(it) }
                    } catch (_: Exception) { }
                    pending?.let { pending = null; doSpeak(it) }
                } else {
                    playing = false
                    onDone?.invoke()
                }
            }.also { tts = it }
            if (ttsReady) doSpeak(text) else pending = text
            playing = true
        } catch (_: Exception) {
            playing = false
            onDone?.invoke()
        }
    }

    private fun doSpeak(text: String) {
        try {
            tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(id: String?) {}
                override fun onDone(id: String?) {
                    playing = false
                    onDone?.invoke()
                }

                @Suppress("DEPRECATION")
                override fun onError(id: String?) {
                    playing = false
                    onDone?.invoke()
                }
            })
            tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "verse-audio")
        } catch (_: Exception) {
            playing = false
            onDone?.invoke()
        }
    }

    fun stop() {
        playing = false
        pending = null
        try {
            exo?.stop()
        } catch (_: Exception) { }
        try {
            exo?.release()
        } catch (_: Exception) { }
        exo = null
        try {
            tts?.stop()
        } catch (_: Exception) { }
    }

    fun release() {
        stop()
        try {
            tts?.shutdown()
        } catch (_: Exception) { }
        tts = null
        ttsReady = false
    }
}
