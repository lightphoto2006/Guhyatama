#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Офлайн-тест публикации релизов: gh_release.next_db_tag, release_gui._resolve_file,
_patch_catalog_worker, Tk-инициализация. БЕЗ сетевых запросов и git-push."""
import json
import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# dbcomposer packages are in the sibling directory
TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

import gh_release
import release_gui

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


# ======================================================================
# a) gh_release.next_db_tag — подмена list_releases
# ======================================================================
def test_next_db_tag():
    print("=== a) gh_release.next_db_tag ===")
    orig = gh_release.list_releases
    gh_release.list_releases = lambda tok, repo, per_page=50: [
        {"tag_name": "db-v13"},
        {"tag_name": "db-v2"},
        {"tag_name": "zz-probe"},
    ]
    try:
        tag = gh_release.next_db_tag("fake")
        check(tag == "db-v14", 'next_db_tag вернул "db-v14" (got %s)' % tag)
    finally:
        gh_release.list_releases = orig


# ======================================================================
# b) release_gui.ReleaseTab._resolve_file
# ======================================================================
def test_resolve_file():
    print("=== b) release_gui.ReleaseTab._resolve_file ===")
    tmpdir = tempfile.mkdtemp(prefix="resolvefile_")

    # подменяем release_gui.DB_DIR / RELEASES_DIR / UPDATES_DIR на tmpdir
    old_db_dir = release_gui.DB_DIR
    old_rel_dir = release_gui.RELEASES_DIR
    old_upd_dir = release_gui.UPDATES_DIR

    release_gui.DB_DIR = tmpdir
    release_gui.RELEASES_DIR = tmpdir
    release_gui.UPDATES_DIR = tmpdir

    try:
        tab = object.__new__(release_gui.ReleaseTab)

        # 1) Существующий абсолютный путь
        fp = os.path.join(tmpdir, "probe.db")
        with open(fp, "wb") as f:
            f.write(b"")
        result = tab._resolve_file(fp)
        check(result == fp, "существующий абс. путь возвращён как есть (got %s)" % result)

        # 2) Несуществующий абсолютный путь
        try:
            tab._resolve_file(os.path.join(tmpdir, "nope.db"))
            check(False, "несуществующий абс. путь должен бросить RuntimeError")
        except RuntimeError as e:
            check("nope.db" in str(e), "несуществующий абс. путь бросил RuntimeError (%s)" % e)

        # 3) Относительное имя, лежащее в подменённой DB_DIR
        fp2 = os.path.join(tmpdir, "in_db_dir.db")
        with open(fp2, "wb") as f:
            f.write(b"")
        result2 = tab._resolve_file("in_db_dir.db")
        check(result2 == fp2, "относительное имя нашлось в подменённой DB_DIR (got %s)" % result2)

        # 4) Относительное имя, которого нет нигде
        try:
            tab._resolve_file("nowhere.db")
            check(False, "несуществующее относительное имя должно бросить RuntimeError")
        except RuntimeError as e:
            check("nowhere.db" in str(e), "несуществующее относительное имя бросил RuntimeError (%s)" % e)

        # 5) Пустая строка
        try:
            tab._resolve_file("")
            check(False, "пустая строка должна бросить RuntimeError")
        except RuntimeError as e:
            check("пустой путь" in str(e), "пустая строка бросил RuntimeError (%s)" % e)
    finally:
        release_gui.DB_DIR = old_db_dir
        release_gui.RELEASES_DIR = old_rel_dir
        release_gui.UPDATES_DIR = old_upd_dir


# ======================================================================
# c) _patch_catalog_worker
# ======================================================================
def test_patch_catalog_worker():
    print("=== c) _patch_catalog_worker ===")
    tmpdir = tempfile.mkdtemp(prefix="patchcat_")

    old_catalog = release_gui.CATALOG_JSON
    old_root = release_gui.ROOT

    release_gui.CATALOG_JSON = os.path.join(tmpdir, "catalog.json")
    release_gui.ROOT = tmpdir

    # Мокаем atomic_write_bytes: пишем напрямую, чтобы избежать
    # Windows-баги os.replace в tempfile.mkstemp на некоторых системах
    old_aws = release_gui.dbcommon.atomic_write_bytes
    written_files = {}

    def mock_atomic_write_bytes(path, data):
        written_files[path] = data
        # также пишем реально для чтения
        d = os.path.dirname(os.path.abspath(path))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return None

    release_gui.dbcommon.atomic_write_bytes = mock_atomic_write_bytes

    try:
        # создаём updates/ и catalog.json
        updates_dir = os.path.join(tmpdir, "updates")
        os.makedirs(updates_dir, exist_ok=True)

        # catalog.json с одной книгой, size=0 (как будто make_catalog не нашёл .db)
        cdata = {"books": [{"key": "TestBook", "size": 0, "sha256": ""}], "audio": [], "apk": {}}
        cat_path = release_gui.CATALOG_JSON
        with open(cat_path, "w", encoding="utf-8") as f:
            json.dump(cdata, f)

        # Создаём ReleaseTab-объект через object.__new__
        tab = object.__new__(release_gui.ReleaseTab)

        def say_mock(t):
            pass

        tab._patch_catalog_worker(say_mock, "books", "TestBook",
                                  size=123, sha="abc", dsize=45, dsha="def")

        # Проверка updates/catalog.json
        with open(cat_path, "r", encoding="utf-8") as f:
            patched = json.load(f)
        entry = patched["books"][0]
        check(entry["size"] == 123, "size=123 в updates/catalog.json (got %s)" % entry.get("size"))
        check(entry["sha256"] == "abc", "sha256=abc (got %s)" % entry.get("sha256"))
        check(entry.get("deltaSize") == 45, "deltaSize=45 (got %s)" % entry.get("deltaSize"))
        check(entry.get("deltaSha") == "def", "deltaSha=def (got %s)" % entry.get("deltaSha"))

        # Проверка корня: catalog.json должен быть копией
        root_cat = os.path.join(tmpdir, "catalog.json")
        check(os.path.exists(root_cat), "catalog.json скопирован в корень tmpdir")
        if os.path.exists(root_cat):
            with open(root_cat, "r", encoding="utf-8") as f:
                root_data = json.load(f)
            check(root_data["books"][0]["size"] == 123, "корневой catalog.json size=123")
            check(root_data["books"][0]["sha256"] == "abc", "корневой catalog.json sha256=abc")
    finally:
        release_gui.CATALOG_JSON = old_catalog
        release_gui.ROOT = old_root
        release_gui.dbcommon.atomic_write_bytes = old_aws


# ======================================================================
# d) delta_is_useless
# ======================================================================
def test_delta_is_useless():
    print("=== d) delta_is_useless ===")
    tmpdir = tempfile.mkdtemp(prefix="deltauseless_")

    # 1) 1000 байт полный, 980 байт дельта, max_ratio=0.98 → True
    fp_full = os.path.join(tmpdir, "full.bin")
    fp_delta = os.path.join(tmpdir, "delta.bin")
    with open(fp_full, "wb") as f:
        f.write(b"x" * 1000)
    with open(fp_delta, "wb") as f:
        f.write(b"d" * 980)
    check(release_gui.delta_is_useless(fp_delta, fp_full, max_ratio=0.98),
          "1000/980 при max_ratio=0.98 → True")

    # 2) 1000 байт полный, 500 байт дельта → False
    with open(fp_delta, "wb") as f:
        f.write(b"d" * 500)
    check(not release_gui.delta_is_useless(fp_delta, fp_full, max_ratio=0.98),
          "1000/500 при max_ratio=0.98 → False")

    # 3) Файла нет → False
    check(not release_gui.delta_is_useless("/nonexistent/delta.bin", fp_full),
          "файла нет → False")

    # 4) 1000/920 при max_ratio=0.9 → True
    with open(fp_delta, "wb") as f:
        f.write(b"d" * 920)
    check(release_gui.delta_is_useless(fp_delta, fp_full, max_ratio=0.9),
          "1000/920 при max_ratio=0.9 → True")


# ======================================================================
# e) Tk-тест (пропуск без дисплея)
# ======================================================================
def test_tk():
    print("=== d) Tk-тест ===")
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        check(False, "tkinter недоступен")
        return

    try:
        root = tk.Tk()
        root.withdraw()  # скрыть окно

        tab = release_gui.ReleaseTab(root)

        # 5 вкладок Notebook
        child_count = len(list(tab.nb.children))
        check(child_count == 5, "Notebook имеет 5 вкладок (got %d)" % child_count)

        # Атрибуты
        check(hasattr(tab, "nb"), "есть атрибут nb")
        check(hasattr(tab, "b_publish"), "есть атрибут b_publish")
        check(hasattr(tab, "v_cat_versions"), "есть атрибут v_cat_versions")
        check(hasattr(tab, "l_publish_hint"), "есть атрибут l_publish_hint")

        # _refresh_publish_hint: текст содержит «Токен»
        tab._refresh_publish_hint()
        hint_text = tab.l_publish_hint.cget("text")
        check("Токен" in hint_text, "l_publish_hint содержит «Токен» (got %s)" % hint_text[:80])

        root.destroy()
    except tk.TclError:
        check(True, "Tk: нет дисплея (TclError) — пропущено")


# ======================================================================
# f) step3_differs и delta_file_problem
# ======================================================================
def test_step3_differs_and_delta():
    print("=== f) step3_differs и delta_file_problem ===")

    # step3_differs: books, одинаковые → False
    check(release_gui.step3_differs("books",
                                    {"version": 5, "file": "a.db", "url": "u"},
                                    {"version": 5, "file": "a.db", "url": "u"}) is False,
          "books одинаковые → False")

    # step3_differs: books, изменённый url → True
    check(release_gui.step3_differs("books",
                                    {"version": 5, "file": "a.db", "url": "u2"},
                                    {"version": 5, "file": "a.db", "url": "u"}) is True,
          "books url изменён → True")

    # step3_differs: books, saved=None → True
    check(release_gui.step3_differs("books",
                                    {"version": 5, "file": "a.db", "url": "u"},
                                    None) is True,
          "books saved=None → True")

    # step3_differs: apk, одинаковые → False
    check(release_gui.step3_differs("apk",
                                    {"versionCode": 57, "versionName": "1.3.9", "file": "x.apk"},
                                    {"versionCode": 57, "versionName": "1.3.9", "file": "x.apk"}) is False,
          "apk одинаковые → False")

    # step3_differs: apk, versionCode изменён → True
    check(release_gui.step3_differs("apk",
                                    {"versionCode": 56, "versionName": "1.3.9", "file": "x.apk"},
                                    {"versionCode": 57, "versionName": "1.3.9", "file": "x.apk"}) is True,
          "apk versionCode изменён → True")

    # delta_file_problem: пустая строка → ""
    check(release_gui.delta_file_problem("") == "",
          "delta_file_problem(\"\") → \"\"")

    # delta_file_problem: существующий временный файл → ""
    tmpf = tempfile.NamedTemporaryFile(delete=False, prefix="delta_ok_")
    tmpf.close()
    try:
        check(release_gui.delta_file_problem(tmpf.name) == "",
              "delta_file_problem(существующий файл) → \"\"")
    finally:
        os.unlink(tmpf.name)

    # delta_file_problem: несуществующий → содержит «не найден»
    res = release_gui.delta_file_problem("/nonexistent/path/delta.db")
    check("не найден" in res,
          "delta_file_problem(несуществующий) содержит «не найден» (got %s)" % res)


# ======================================================================
# main
# ======================================================================
def main():
    test_next_db_tag()
    test_resolve_file()
    test_patch_catalog_worker()
    test_delta_is_useless()
    test_tk()
    test_step3_differs_and_delta()

    print("")
    print("Итого проверок: %d, провалов: %d" % (checks, fails))
    if fails:
        print("FAIL")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
