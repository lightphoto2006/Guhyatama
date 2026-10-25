# -*- coding: utf-8 -*-
"""Общие UI-утилиты для вкладок dbcomposer (stdlib, без tkinter-импорта сверх нужного)."""


def log_key(ev):
    """Лог только для чтения. Ctrl+A — выделить всё, Ctrl+C/Insert — копировать.
    Раскладка не важна (проверка по keycode)."""
    if ev.state & 0x4:  # Ctrl
        w = ev.widget
        if ev.keycode == 65:
            w.tag_add("sel", "1.0", "end-1c")
            return "break"
        if ev.keycode in (67, 45):
            try:
                sel = w.get("sel.first", "sel.last")
                w.clipboard_clear()
                w.clipboard_append(sel)
            except Exception:
                pass
            return "break"
        return "break"
    if ev.keysym in ("Up", "Down", "Left", "Right", "Home", "End",
                     "Prior", "Next", "Shift_L", "Shift_R",
                     "Control_L", "Control_R", "Caps_Lock"):
        return None
    return "break"


def say(log_widget, text):
    """Запись строки в лог-виджет с прокруткой."""
    log_widget.insert("end", str(text).rstrip() + "\n")
    log_widget.see("end")


def set_busy(owner, v, buttons=(), prog=None):
    """Блокировка/разблокировка кнопок и прогресс-бара."""
    owner.busy = v
    st = "disabled" if v else "normal"
    for b in buttons:
        b.configure(state=st)
    if prog is not None:
        if v:
            prog.start(12)
        else:
            prog.stop()
