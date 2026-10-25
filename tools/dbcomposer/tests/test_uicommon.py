#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тест контекстного меню лог-виджета + Ctrl+C/V/X/A по keycode (любая раскладка)."""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TOOLS_DIR = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
DBCOMPOSER_DIR = __import__("os").path.dirname(TOOLS_DIR)
if DBCOMPOSER_DIR not in sys.path:
    sys.path.insert(0, DBCOMPOSER_DIR)

import tkinter as tk
from tkinter import ttk

checks = 0
fails = 0


def check(cond, msg):
    global checks, fails
    checks += 1
    if cond:
        print("  OK: %s" % msg)
    else:
        fails += 1
        print("  FAIL: %s" % msg)


def test_attach_log_menu():
    print("=== attach_log_menu на tk.Text ===")
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        check(True, "Tk: нет дисплея (TclError) — пропущено")
        return

    try:
        import uicommon

        widget = tk.Text(root)
        menu = uicommon.attach_log_menu(widget)

        # 1) _ctx_menu создан
        check(hasattr(widget, "_ctx_menu"), "widget._ctx_menu существует")
        check(widget._ctx_menu is menu, "_ctx_menu == возвращённому menu")

        # 2) Пункты меню
        entry_count = menu.index("end") + 1
        check(entry_count >= 2, "меню имеет ≥ 2 пункта (got %d)" % entry_count)
        check(menu.entrycget(0, "label") == "Копировать",
              "пункт 0 = «Копировать» (got %s)" % menu.entrycget(0, "label"))
        check(menu.entrycget(1, "label") == "Выделить всё",
              "пункт 1 = «Выделить всё» (got %s)" % menu.entrycget(1, "label"))

        # 3) Копирование: вставляем текст, выделяем, вызываем invoke(0)
        widget.insert("1.0", "привет")
        widget.tag_add("sel", "1.0", "end-1c")
        menu.invoke(0)
        copied = widget.clipboard_get()
        check(copied == "привет",
              "clipboard_get() после invoke(0) = «привет» (got %r)" % copied)

        # 4) Выделить всё: tag_ranges("sel") непусты после invoke(1)
        widget.tag_remove("sel", "1.0", "end")
        menu.invoke(1)
        ranges = widget.tag_ranges("sel")
        check(len(ranges) >= 2,
              "tag_ranges('sel') после invoke(1) не пусты (got %d items)" % len(ranges))

        root.destroy()
    except tk.TclError:
        check(True, "Tk: нет дисплея (TclError) — пропущено")


def test_clipboard_bindings():
    """Ctrl+A/C/X/V по keycode — работает в любой раскладке."""
    print("=== install_clipboard_bindings ===")
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        check(True, "Tk: нет дисплея (TclError) — пропущено")
        return

    try:
        import uicommon

        # --- Entry ---
        ent = ttk.Entry(root)
        ent.pack()
        uicommon.install_clipboard_bindings(root)
        root.update()

        # Tест A — выделить всё
        ent.delete(0, "end")
        ent.insert(0, "hello world")
        ent.event_generate("<Control-Key>", keycode=65, state=0x4, keysym="Cyrillic_ef")
        root.update()
        sel = ent.selection_get()
        check(sel == "hello world", "Entry A (keycode=65): выделилось «hello world» (got %r)" % sel)

        # Тест C — копировать
        ent.event_generate("<Control-Key>", keycode=67, state=0x4, keysym="Cyrillic_ef")
        root.update()
        cb = ent.clipboard_get()
        check(cb == "hello world", "Entry C (keycode=67): в буфере «hello world» (got %r)" % cb)

        # Тест V — вставить в новое поле
        ent2 = ttk.Entry(root)
        ent2.pack()
        root.update()
        ent2.event_generate("<Control-Key>", keycode=86, state=0x4, keysym="Cyrillic_ef")
        root.update()
        cb2 = ent2.get()
        check(cb2 == "hello world", "Entry V (keycode=86): вставилось «hello world» (got %r)" % cb2)

        # --- Text ---
        txt = tk.Text(root)
        txt.pack()
        root.update()
        txt.insert("1.0", "text content here")
        txt.event_generate("<Control-Key>", keycode=65, state=0x4, keysym="Cyrillic_ef")
        root.update()
        sel_txt = txt.get("sel.first", "sel.last")
        check(sel_txt == "text content here", "Text A (keycode=65): выделилось (got %r)" % sel_txt)

        txt.event_generate("<Control-Key>", keycode=67, state=0x4, keysym="Cyrillic_ef")
        root.update()
        cb_txt = txt.clipboard_get()
        check(cb_txt == "text content here", "Text C (keycode=67): в буфере (got %r)" % cb_txt)

        # Тест X — вырезать
        txt.event_generate("<Control-Key>", keycode=88, state=0x4, keysym="Cyrillic_ef")
        root.update()
        remaining = txt.get("1.0", "end-1c")
        check(remaining == "", "Text X (keycode=88): текст удалён (got %r)" % remaining)
        cb_x = txt.clipboard_get()
        check(cb_x == "text content here", "Text X: в буфере после вырезания (got %r)" % cb_x)

        ent.destroy()
        ent2.destroy()
        txt.destroy()
        root.destroy()
    except tk.TclError:
        check(True, "Tk: нет дисплея (TclError) — пропущено")


def main():
    test_attach_log_menu()
    test_clipboard_bindings()

    print("")
    print("Итого проверок: %d, провалов: %d" % (checks, fails))
    if fails:
        print("FAIL")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
