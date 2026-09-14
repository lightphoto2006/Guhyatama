package com.vedalibrary.app.ui.util

/**
 * Кнопки громкости меняют шрифт — но только на экранах чтения.
 * Экран регистрирует обработчик при показе и снимает при уходе.
 * Владелец-токен: при быстрой навигации старый экран снимается ПОСЛЕ того,
 * как новый зарегистрировался — чужой clear тогда не гасит новый handler
 * (иначе громкость работает раз через раз).
 */
object VolumeFont {
    private var owner: Any? = null
    var handler: ((Int) -> Unit)? = null
        private set

    fun set(owner: Any, h: (Int) -> Unit) {
        this.owner = owner
        handler = h
    }

    fun clear(owner: Any) {
        if (this.owner === owner) {
            this.owner = null
            handler = null
        }
    }
}
