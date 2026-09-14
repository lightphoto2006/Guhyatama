package com.vedalibrary.app.data.settings

import android.content.Context
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

private val Context.readerStore by preferencesDataStore("reader_settings")

/** Глобальные настройки читалки: какие разделы стиха показывать + размеры шрифта + выравнивание */
@Singleton
class ReaderSettings @Inject constructor(@ApplicationContext private val ctx: Context) {
    private val K_SAN = booleanPreferencesKey("show_sanskrit")
    private val K_TRA = booleanPreferencesKey("show_translit")
    private val K_SYN = booleanPreferencesKey("show_synonyms")
    private val K_TRL = booleanPreferencesKey("show_translation")
    private val K_PUR = booleanPreferencesKey("show_purport")
    private val K_FONT = floatPreferencesKey("font_size")
    private val K_FONT_V = floatPreferencesKey("font_verse")
    private val K_FONT_L = floatPreferencesKey("font_list")
    private val K_ALIGN = stringPreferencesKey("para_align")
    private val K_SECTIONS = stringPreferencesKey("book_sections")
    private val K_COLLAPSED = stringPreferencesKey("sections_collapsed")
    private val K_LANG = stringPreferencesKey("book_lang_filter")
    private val K_ORDER = stringPreferencesKey("book_order")

    val showSanskrit = ctx.readerStore.data.map { it[K_SAN] ?: true }
    val showTranslit = ctx.readerStore.data.map { it[K_TRA] ?: true }
    val showSynonyms = ctx.readerStore.data.map { it[K_SYN] ?: true }
    val showTranslation = ctx.readerStore.data.map { it[K_TRL] ?: true }
    val showPurport = ctx.readerStore.data.map { it[K_PUR] ?: true }
    /** Шрифт чтения стиха (наследует старый общий); шрифт списка главы — отдельно, не синхронизируются */
    val fontVerse = ctx.readerStore.data.map { it[K_FONT_V] ?: it[K_FONT] ?: 17f }
    val fontList = ctx.readerStore.data.map { it[K_FONT_L] ?: 15f }
    /** Выравнивание перевода/комментария/списков: left|justify|center */
    val paraAlign = ctx.readerStore.data.map { it[K_ALIGN] ?: "justify" }

    /** Разделы библиотеки (порядок фиксирован) */
    val sectionTitles = listOf(
        "Лекции Шьямакунды Прабху",
        "Основные книги и лекции Шрилы Прабхупады",
        "Письма и беседы Шрилы Прабхупады",
        "Книги Ачарий",
        "Остальное"
    )

    /** Ручная раскладка книга->секция ("id=2;id=0"); пусто = везде defaults */
    val bookSections: kotlinx.coroutines.flow.Flow<Map<String, Int>> =
        ctx.readerStore.data.map { prefs ->
            (prefs[K_SECTIONS] ?: "").split(";").mapNotNull {
                val kv = it.split("=", limit = 2)
                if (kv.size == 2) kv[0] to (kv[1].toIntOrNull() ?: -1) else null
            }.filter { it.second in sectionTitles.indices }.toMap()
        }

    /** Свёрнутые секции; по умолчанию все кроме первых двух */
    val collapsedSections: kotlinx.coroutines.flow.Flow<Set<Int>> =
        ctx.readerStore.data.map { prefs ->
            val raw = prefs[K_COLLAPSED]
            if (raw == null) setOf(2, 3, 4)
            else raw.split(",").mapNotNull { it.toIntOrNull() }.filter { it in sectionTitles.indices }.toSet()
        }

    /** Фильтр языка книг: all|rus|eng */
    val bookLang: kotlinx.coroutines.flow.Flow<String> =
        ctx.readerStore.data.map { prefs ->
            (prefs[K_LANG] ?: "all").takeIf { it == "rus" || it == "eng" } ?: "all"
        }

    /** Ручной порядок книг (перетаскивание на главной): id через \n. Пусто = порядок по умолчанию. */
    val bookOrder: kotlinx.coroutines.flow.Flow<List<String>> =
        ctx.readerStore.data.map { prefs ->
            (prefs[K_ORDER] ?: "").split("\n").map { it.trim() }.filter { it.isNotEmpty() }.distinct()
        }

    suspend fun setBookOrder(ids: List<String>) = set(K_ORDER, ids.joinToString("\n"))

    suspend fun setShowSanskrit(v: Boolean) = set(K_SAN, v)
    suspend fun setShowTranslit(v: Boolean) = set(K_TRA, v)
    suspend fun setShowSynonyms(v: Boolean) = set(K_SYN, v)
    suspend fun setShowTranslation(v: Boolean) = set(K_TRL, v)
    suspend fun setShowPurport(v: Boolean) = set(K_PUR, v)
    suspend fun setFontSize(v: Float) = set(K_FONT_V, v)
    suspend fun setFontListSize(v: Float) = set(K_FONT_L, v)
    suspend fun setParaAlign(v: String) = set(K_ALIGN, v)

    /** Положить книгу в секцию вручную (перекрывает defaultSection) */
    suspend fun setBookSection(bookId: String, section: Int) {
        val cur = ctx.readerStore.data.map { it[K_SECTIONS] ?: "" }.first()
        val map = cur.split(";").mapNotNull {
            val kv = it.split("=", limit = 2)
            if (kv.size == 2) kv[0] to kv[1] else null
        }.toMutableList()
        map.removeAll { it.first == bookId }
        map += bookId to section.toString()
        set(K_SECTIONS, map.joinToString(";") { "${it.first}=${it.second}" })
    }

    suspend fun toggleSectionCollapsed(index: Int, collapsed: Boolean) {
        val cur = try {
            ctx.readerStore.data.map { it[K_COLLAPSED] }.first()
        } catch (_: Exception) { null }
        val set = (cur?.split(",")?.mapNotNull { it.toIntOrNull() }?.toMutableSet() ?: mutableSetOf(2, 3, 4))
        if (collapsed) set += index else set -= index
        set(K_COLLAPSED, set.sorted().joinToString(","))
    }

    /** Цикл фильтра языка: all -> rus -> eng -> all */
    suspend fun cycleBookLang() {
        val cur = try {
            ctx.readerStore.data.map { it[K_LANG] ?: "all" }.first()
        } catch (_: Exception) { "all" }
        set(K_LANG, when (cur) { "rus" -> "eng"; "eng" -> "all"; else -> "rus" })
    }

    companion object {
        /** Секция по умолчанию: свои загрузки (конспекты) — в 0; дальше по коду произведения */
        fun defaultSection(book: com.vedalibrary.app.data.local.Book): Int {
            if (book.sourceType != "GITABASE_DB") return 0
            return when (book.id.split("-").getOrNull(1)?.uppercase()) {
                "BG", "BG72", "SB", "CC", "ISO", "NOD", "NOI", "TLC", "KB", "TQK",
                "LBG", "LSB" -> 1
                "LTRS", "LTR", "TLKS" -> 2
                "BS", "MA", "DG", "GA", "LM" -> 3
                else -> 4
            }
        }
    }

    /** Кнопки громкости: шаг 1sp, пределы 12..30 */
    suspend fun bumpVerseFont(d: Int) {
        val cur = ctx.readerStore.data.map { it[K_FONT_V] ?: it[K_FONT] ?: 17f }.first()
        set(K_FONT_V, (cur + d).coerceIn(12f, 30f))
    }
    suspend fun bumpListFont(d: Int) {
        val cur = ctx.readerStore.data.map { it[K_FONT_L] ?: 15f }.first()
        set(K_FONT_L, (cur + d).coerceIn(12f, 30f))
    }

    private suspend fun <T> set(k: Preferences.Key<T>, v: T) {
        ctx.readerStore.updateData { it.toMutablePreferences().apply { this[k] = v } }
    }
}
