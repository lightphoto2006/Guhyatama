# -*- coding: utf-8 -*-
"""Общие UI-утилиты для вкладок dbcomposer (stdlib, без tkinter-импорта сверх нужного)."""

import tkinter as tk


def attach_log_menu(widget):
    """Контекстное меню правой кнопки для лог-виджета:
    «Копировать» (выделенный текст → буфер) и «Выделить всё».
    Возвращает объект tk.Menu, привязанный к widget._ctx_menu."""
    menu = tk.Menu(widget, tearoff=0)

    def _copy():
        try:
            sel = widget.get("sel.first", "sel.last")
            widget.clipboard_clear()
            widget.clipboard_append(sel)
        except Exception:
            pass

    def _select_all():
        widget.tag_add("sel", "1.0", "end-1c")

    menu.add_command(label="Копировать", command=_copy)
    menu.add_command(label="Выделить всё", command=_select_all)

    def _show_menu(ev):
        try:
            menu.tk_popup(ev.x_root, ev.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    widget._ctx_menu = menu
    widget.bind("<Button-3>", _show_menu)
    widget.bind("<Button-2>", _show_menu)
    widget.bind("<Control-Button-1>", _show_menu)
    return menu


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


def install_clipboard_bindings(root):
    """Ctrl+C/V/X/A по ФИЗИЧЕСКОМУ коду клавиши — работает и в русской раскладке."""
    def handler(ev):
        if not (ev.state & 0x4):  # Ctrl не нажат
            return None
        w = ev.widget
        try:
            key = int(ev.keycode)
        except Exception:
            return None
        seq = {65: "<<SelectAll>>", 67: "<<Copy>>", 86: "<<Paste>>", 88: "<<Cut>>"}.get(key)
        if seq is None:
            return None
        try:
            w.event_generate(seq)
        except Exception:
            return None
        return "break"
    for cls in ("Entry", "TEntry", "Text", "TCombobox", "Spinbox", "TSpinbox"):
        try:
            root.bind_class(cls, "<Key>", handler, add="+")
        except Exception:
            pass


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
