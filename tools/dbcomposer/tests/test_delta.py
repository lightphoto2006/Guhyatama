#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тест make_delta.py (схема — как в ai_import.write_source_db, плюс lang в books)."""
import os
import sqlite3
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(os.path.dirname(HERE), "make_delta.py")

# DDL как в SOURCE_DDL (ai_import.py), в books добавлен lang TEXT (проверка сопоставления)
DDL = [
    "CREATE TABLE books(_id INTEGER PRIMARY KEY, sort INTEGER, author TEXT, title TEXT,"
    " desc TEXT, type TEXT, levels INTEGER, hasSanskrit INTEGER, hasPurport INTEGER,"
    " hasColorStructure INTEGER, isSongBook INTEGER, text_size INTEGER, purport_size INTEGER,"
    " text_begin_raw TEXT, text_end_raw TEXT, web_abbrev TEXT, compare_code TEXT,"
    " issue TEXT, isSimple INTEGER, lang TEXT)",
    "CREATE TABLE chapters(_id INTEGER PRIMARY KEY, book_id INTEGER, song TEXT,"
    " number INTEGER, title TEXT)",
    "CREATE TABLE songs(book_id INTEGER, song TEXT, songname TEXT, sort INTEGER)",
    "CREATE TABLE textnums(_id INTEGER PRIMARY KEY, book_id INTEGER, song TEXT,"
    " ch_no TEXT, txt_no TEXT, preview TEXT, url TEXT)",
    "CREATE TABLE texts(_id INTEGER PRIMARY KEY, sanskrit TEXT, translit TEXT,"
    " translit_srch TEXT, transl1 TEXT, transl2 TEXT, comment TEXT)",
    # таблицы, которые в дельту попадать НЕ должны:
    "CREATE TABLE covers(book_id INTEGER, image_id TEXT)",
    "CREATE TABLE images(image_id TEXT PRIMARY KEY, content BLOB)",
    "CREATE TABLE image_nums(bid INTEGER, sid TEXT, cid TEXT, tnum TEXT, text_id INTEGER,"
    " image_id TEXT, type TEXT, desc TEXT, kind TEXT)",
]


def create(path):
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    for d in DDL:
        con.execute(d)
    return con


def book(con, _id, typ, lang):
    con.execute("INSERT INTO books(_id,type,author,title,lang) VALUES (?,?,?,?,?)",
                (_id, typ, "автор", "титул " + typ, lang))


def chap(con, _id, bid, song, num, title):
    con.execute("INSERT INTO chapters(_id,book_id,song,number,title) VALUES (?,?,?,?,?)",
                (_id, bid, song, num, title))


def song(con, bid, s, name):
    con.execute("INSERT INTO songs(book_id,song,songname,sort) VALUES (?,?,?,?)",
                (bid, s, name, int(s)))


def verse(con, _id, bid, s, ch, no, prev, transl2, comment):
    con.execute("INSERT INTO textnums(_id,book_id,song,ch_no,txt_no,preview) VALUES (?,?,?,?,?,?)",
                (_id, bid, s, ch, no, prev))
    con.execute("INSERT INTO texts(_id,sanskrit,translit,translit_srch,transl1,transl2,comment)"
                " VALUES (?,?,?,?,?,?,?)", (_id, "а " + prev, "", "", "", transl2, comment))


def setup_common(con):
    book(con, 1, "BG", "rus")
    book(con, 2, "SCO", "rus")
    chap(con, 101, 1, "1", 1, "Глава 1")
    chap(con, 102, 2, "1", 1, "Chapter 1")
    song(con, 1, "1", "Песня 1")
    song(con, 2, "1", "Song 1")


def main():
    work = tempfile.mkdtemp(prefix="mkdelta_")
    old_p = os.path.join(work, "old.db")
    new_p = os.path.join(work, "new.db")
    out_p = os.path.join(work, "delta.db")

    # OLD: BG 6 стихов (v1 — NULL comment, v2 — старый перевод, v3 — будет удалён,
    #      v5 — такой же в NEW, но с ДРУГИМ _id: recompose перенумеровывает,
    #      v6 — дубль координаты, обе строки одинаковые),
    #      SCO 1 стих, LEG только в OLD (игнор).
    old = create(old_p)
    setup_common(old)
    book(old, 3, "LEG", "rus")
    chap(old, 103, 3, "1", 1, "Old intro")
    song(old, 3, "1", "Leg")
    verse(old, 11, 1, "1", "1", "1", "one", "перевод один", None)   # comment NULL
    verse(old, 12, 1, "1", "1", "2", "two", "СТАРЫЙ перевод", "комм")
    verse(old, 13, 1, "1", "1", "3", "three", "удаляемый", None)
    verse(old, 10, 1, "1", "1", "5", "five", "тот же перевод", None)  # _id=10, тот же texts
    verse(old, 501, 1, "1", "1", "6", "dup", "текст дубля", None)     # дубль координаты
    verse(old, 502, 1, "1", "1", "6", "dup", "текст дубля", None)     # (обе одинаковые)
    verse(old, 21, 2, "1", "1", "1", "sco", "unchanged", None)
    verse(old, 31, 3, "1", "1", "1", "leg", "old only", None)
    old.commit(); old.close()

    # NEW: BG — v1 без изменений (NULL comment), v2 изменён, v4 добавлен,
    #      v5 — то же содержимое texts, но _id=7 вместо 10 (НЕ должен считаться
    #      изменённым: _id в сравнении не участвует),
    #      v6 — дубль координаты: первая строка изменена, вторая та же (в дельту
    #      должны ехать ОБЕ — суффиксы id ~2/~3 при импорте не должны ездить);
    #      SCO тот же.
    new = create(new_p)
    setup_common(new)
    chap(new, 105, 1, "2", 1, "Глава 2 (без изменённых стихов)")
    song(new, 1, "2", "Песня 2")
    verse(new, 11, 1, "1", "1", "1", "one", "перевод один", None)   # тот же, comment NULL
    verse(new, 12, 1, "1", "1", "2", "two", "НОВЫЙ перевод", "комм")
    verse(new, 14, 1, "1", "1", "4", "four", "добавленный", None)
    verse(new, 7, 1, "1", "1", "5", "five", "тот же перевод", None)  # _id=7 (в OLD был 10)
    verse(new, 501, 1, "1", "1", "6", "dup", "ИЗМЕНЁН дубль", None)  # первая из дубля
    verse(new, 502, 1, "1", "1", "6", "dup", "текст дубля", None)    # вторая та же
    verse(new, 21, 2, "1", "1", "1", "sco", "unchanged", None)
    new.commit(); new.close()

    if os.path.exists(out_p):
        os.remove(out_p)

    def run(extra):
        r = subprocess.run([sys.executable, TOOL, "--old", old_p, "--new", new_p,
                            "--out", out_p] + extra,
                           capture_output=True)
        return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")

    rc, so, se = run([])
    print("--- запуск 1: rc=%s" % rc)
    print(so, end="")
    if se:
        print("STDERR:", se, end="")
    assert rc == 0, "первый запуск должен быть успешен"
    assert "Записан:" in so
    assert "BG#1: изменено 4 стихов" in so
    assert "SCO#2: изменено 0 стихов" in so
    assert "Итого строк: books=1 chapters=1 songs=1 textnums=4 texts=4" in so

    # сверка delta.db
    con = sqlite3.connect(out_p)
    names = sorted(r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"))
    assert names == ["books", "chapters", "songs", "textnums", "texts"], names
    books = con.execute("SELECT _id,type FROM books").fetchall()
    assert books == [(1, "BG")], books
    tnums = sorted(con.execute("SELECT _id,song,ch_no,txt_no FROM textnums").fetchall())
    assert tnums == [(12, "1", "1", "2"), (14, "1", "1", "4"),
                     (501, "1", "1", "6"), (502, "1", "1", "6")], tnums
    texts = con.execute("SELECT _id,transl2,comment FROM texts ORDER BY _id").fetchall()
    assert texts == [(12, "НОВЫЙ перевод", "комм"), (14, "добавленный", None),
                     (501, "ИЗМЕНЁН дубль", None), (502, "текст дубля", None)], texts
    chs = con.execute("SELECT _id FROM chapters ORDER BY _id").fetchall()
    assert chs == [(101,)], chs          # глава 105 (song 2) не нужна — нет изменённых стихов в ней
    sgs = con.execute("SELECT book_id,song FROM songs ORDER BY song").fetchall()
    assert sgs == [(1, "1")], sgs
    n = con.execute("SELECT COUNT(*) FROM textnums WHERE book_id=2").fetchone()[0]
    assert n == 0, "стихов SCO в дельте быть не должно"
    n = con.execute("SELECT COUNT(*) FROM textnums WHERE txt_no='3'").fetchone()[0]
    assert n == 0, "удалённый стих не должен попасть в дельту"
    n = con.execute("SELECT COUNT(*) FROM textnums WHERE txt_no='5'").fetchone()[0]
    assert n == 0, "стих texts с тем же содержимым, но другим _id (10->7), — не дельта"
    n = con.execute("SELECT COUNT(*) FROM texts WHERE _id IN (7, 10)").fetchone()[0]
    assert n == 0, "перенумерованный texts (_id 10/7) не должен попасть в дельту"
    con.close()

    # повторный запуск без --force -> код 1
    rc2, so2, se2 = run([])
    print("--- запуск без --force: rc=%s" % rc2)
    assert rc2 == 1, "ожидался код 1"
    assert se2.strip(), "сообщение об ошибке в stderr"
    # с --force -> код 0
    rc3, so3, se3 = run(["--force"])
    print("--- запуск с --force: rc=%s" % rc3)
    print(so3, end="")
    assert rc3 == 0

    # битая база -> внятная ошибка и код 1
    bad_p = os.path.join(work, "bad.db")
    with open(bad_p, "wb") as f:
        f.write(b"this is not sqlite" * 64)
    r = subprocess.run([sys.executable, TOOL, "--old", bad_p, "--new", new_p,
                        "--out", os.path.join(work, "delta_bad.db")],
                       capture_output=True)
    print("--- битая old: rc=%s" % r.returncode)
    assert r.returncode == 1
    assert r.stderr.decode("utf-8", "replace").strip()

    # --- перенумерация книг в NEW (recompose нумерует по порядку спеки):
    # дельта обязана встать под СТАРЫЙ _id, иначе app-id (gb-type-_id-lang)
    # установленной книги не совпадёт и импорт откажется
    old2_p = os.path.join(work, "old2.db")
    new2_p = os.path.join(work, "new2.db")
    out2_p = os.path.join(work, "delta2.db")
    o2 = create(old2_p)
    book(o2, 5, "XY", "rus")
    chap(o2, 201, 5, "1", 1, "Глава 1")
    song(o2, 5, "1", "Песня 1")
    verse(o2, 31, 5, "1", "1", "1", "a", "старый", None)
    verse(o2, 32, 5, "1", "1", "2", "b", "без изменений", None)
    o2.commit(); o2.close()
    n2 = create(new2_p)
    book(n2, 9, "XY", "rus")            # тот же type+lang, другой _id
    chap(n2, 201, 9, "1", 1, "Глава 1")
    song(n2, 9, "1", "Песня 1")
    verse(n2, 31, 9, "1", "1", "1", "a", "НОВЫЙ", None)
    verse(n2, 32, 9, "1", "1", "2", "b", "без изменений", None)
    n2.commit(); n2.close()
    r2 = subprocess.run([sys.executable, TOOL, "--old", old2_p, "--new", new2_p,
                         "--out", out2_p, "--force"], capture_output=True)
    so_r = r2.stdout.decode("utf-8", "replace")
    print("--- перенумерация _id: rc=%s" % r2.returncode)
    print(so_r, end="")
    assert r2.returncode == 0, r2.stderr.decode("utf-8", "replace")
    assert "перенумерована" in so_r and "OLD _id=5, NEW _id=9" in so_r, so_r
    c2 = sqlite3.connect(out2_p)
    assert c2.execute("SELECT _id FROM books").fetchall() == [(5,)], "books._id — СТАРАЯ"
    assert c2.execute("SELECT DISTINCT book_id FROM textnums").fetchall() == [(5,)]
    assert c2.execute("SELECT DISTINCT book_id FROM chapters").fetchall() == [(5,)]
    assert c2.execute("SELECT DISTINCT book_id FROM songs").fetchall() == [(5,)]
    rows = c2.execute("SELECT _id, transl2 FROM texts").fetchall()
    assert rows == [(31, "НОВЫЙ")], rows
    c2.close()

    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
