package com.vedalibrary.app.ui.util

/**
 * Кнопки громкости меняют шрифт — но только на экранах чтения.
 * Экран регистрирует обработчик при показе и снимает при уходе.
 * Стек владельцев вместо единственного слота: вложенные/параллельно
 * составленные экраны не гасят друг другу — сверху всегда последний
 * зарегистрированный, а чужой clear снимает только свою запись
 * (у синглтона при быстрой навигации старый экран снимал ПОСЛЕ нового —
 * чужой clear гасил новый handler, «громкость работала раз через раз»,
 * а при возврате «назад» обработчик терялся совсем).
 */
object VolumeFont {
    private val stack = ArrayList<Pair<Any, (Int) -> Unit>>()
    val handler: ((Int) -> Unit)? get() = stack.lastOrNull()?.second

    fun set(owner: Any, h: (Int) -> Unit) {
        stack.removeAll { it.first === owner }
        stack.add(owner to h)
    }

    fun clear(owner: Any) {
        stack.removeAll { it.first === owner }
    }
}
