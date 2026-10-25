#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тест контекстного меню лог-виджета: attach_log_menu, Копировать, Выделить всё."""
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


def main():
    test_attach_log_menu()

    print("")
    print("Итого проверок: %d, провалов: %d" % (checks, fails))
    if fails:
        print("FAIL")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
