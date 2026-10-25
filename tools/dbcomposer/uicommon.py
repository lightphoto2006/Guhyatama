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
    TAG = "ClipFix"
    def _sel(w):
        try:
            return w.get("sel.first", "sel.last")
        except Exception:
            try:
                return w.selection_get()
            except Exception:
                return ""
    def handler(ev):
        if not (ev.state & 0x4):
            return None
        w = ev.widget
        k = int(getattr(ev, "keycode", 0) or 0)
        try:
            if k == 65:                      # A — выделить всё
                if isinstance(w, tk.Text):
                    w.tag_add("sel", "1.0", "end-1c")
                else:
                    w.selection_range(0, "end")
            elif k == 67:                    # C — копировать
                s = _sel(w)
                if s:
                    w.clipboard_clear()
                    w.clipboard_append(s)
            elif k == 88:                    # X — вырезать
                s = _sel(w)
                if s:
                    w.clipboard_clear()
                    w.clipboard_append(s)
                    if isinstance(w, tk.Text):
                        w.delete("sel.first", "sel.last")
                    else:
                        w.delete("sel.first", "sel.last")
            elif k == 86:                    # V — вставить
                try:
                    data = w.clipboard_get()
                except Exception:
                    data = ""
                if data:
                    if isinstance(w, tk.Text):
                        try:
                            w.delete("sel.first", "sel.last")
                        except Exception:
                            pass
                        w.insert("insert", data)
                    else:
                        try:
                            w.delete("sel.first", "sel.last")
                        except Exception:
                            pass
                        w.insert("insert", data)
            else:
                return None
        except Exception:
            return None
        return "break"
    def ensure(w):
        try:
            tags = w.bindtags()
            if TAG not in tags:
                w.bindtags((TAG,) + tuple(tags))
        except Exception:
            pass
    def scan(w):
        ensure(w)
        try:
            for ch in w.winfo_children():
                scan(ch)
        except Exception:
            pass
    root.bind_class(TAG, "<Control-Key>", handler)
    root.bind_all("<FocusIn>", lambda e: ensure(e.widget), add="+")
    scan(root)
    # периодически досканировать новые окна (диалоги создаются позже)
    def tick():
        try:
            scan(root)
        except Exception:
            pass
        root.after(1500, tick)
    tick()


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
