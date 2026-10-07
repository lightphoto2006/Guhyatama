package com.vedalibrary.app.data.update

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/** Мелкое состояние обновлений: когда проверяли, что пропустили, версии книг.
 *  Версия книги = версия файла из каталога (0 = через обновления не ставилась). */
@Singleton
class UpdatePrefs @Inject constructor(@ApplicationContext ctx: Context) {
    private val prefs = ctx.getSharedPreferences("updates", Context.MODE_PRIVATE)

    fun lastCheck(): Long = prefs.getLong("last_check", 0)
    fun markChecked() = prefs.edit().putLong("last_check", System.currentTimeMillis()).apply()
    fun skippedVersion(): Long = prefs.getLong("skip_vc", 0)
    fun skip(vc: Long) = prefs.edit().putLong("skip_vc", vc).apply()

    fun bookVersion(key: String): Int = prefs.getInt("book_ver_$key", 0)
    fun setBookVersion(key: String, v: Int) = prefs.edit().putInt("book_ver_$key", v).apply()
    /** Id книг, приехавших с этим файлом — если книгу удалили вручную, предложим скачать заново */
    fun bookIds(key: String): Set<String> =
        prefs.getStringSet("book_ids_$key", emptySet()) ?: emptySet()
    fun setBookIds(key: String, ids: Collection<String>) =
        prefs.edit().putStringSet("book_ids_$key", ids.toSet()).apply()
}
