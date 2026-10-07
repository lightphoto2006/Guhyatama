#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_delta — строит delta.db для автообновлений: та же схема source-.db,
но содержит ТОЛЬКО изменённые стихи (OLD -> NEW). Приложение при
installed==deltaFrom качает дельту вместо полного файла и импортирует её
тем же LibraryDbImporter (upsert по координатам стихов), поэтому partial-файл
безопасен. Поля delta {file,url,from} в updates/versions.json, размер/хэш
для них считает make_catalog.py.

  py tools/dbcomposer/make_delta.py --old OLD.db --new NEW.db --out delta.db [--force]

Книга в OLD сопоставляется с книгой в NEW по lower(type); если колонка lang
есть в books обеих баз — тогда по type+lang. Книг, которых нет в NEW, дельта
не касается. Стих сопоставляется по координате (song, ch, txt_no) из textnums
в связке с texts. Стих считается изменённым, если координаты нет в OLD или
отличается любое общее значение колонок texts (NULL-safe: два NULL равны);
строки дублирующихся координат включаются целиком (id-суффиксы ~2/~3 при
импорте должны совпасть). В delta.db попадают только таблицы
books/chapters/songs/textnums/texts —
DDL копируется из NEW, images/image_nums/textrefs в дельту не пишутся.
recompose при пересборке нумерует книги по порядку спеки, поэтому _id в NEW
может не совпасть со старым: дельта пишется ПОД СТАРЫЙ _id (books._id и
book_id всех строк), иначе приложение не найдёт установленную книгу
(app-id = gb-<type>-<_id>-<lang>). В совпадающем случае код — no-op.
_id стихов (textnums/texts) остаются как в NEW.
"""
import argparse
import os
import sqlite3
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbcommon  # noqa: E402  (connect_ro / atomic_write_bytes живут рядом)

#: таблицы, которые попадают в дельту, в порядке создания
TABLES = ("books", "chapters", "songs", "textnums", "texts")


def die(msg):
    """Внятная ошибка в stderr и выход с кодом 1."""
    sys.stderr.write("make_delta: %s\n" % msg)
    sys.exit(1)


def cstr(v):
    """Координата как текст: None -> '', иначе str (0 -> '0', а не '')."""
    return str(v) if v is not None else ""


def open_ro(path, label):
    """Read-only соединение через dbcommon.connect_ro с проверкой, что файл
    реально читается как SQLite (mode=ro открывается лениво — проверяем
    первым запросом к sqlite_master)."""
    if not os.path.exists(path):
        die("%s: файл не найден: %s" % (label, path))
    try:
        con = dbcommon.connect_ro(path)
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error as e:
        die("%s: не открывается как база SQLite (%s): %s" % (label, e, path))
    return con


def pragma_cols(con, table, label):
    """Фактические колонки таблицы по PRAGMA table_info — схему не угадываем."""
    try:
        rows = con.execute("PRAGMA table_info(%s)" % table).fetchall()
    except sqlite3.Error as e:
        die("%s: не удалось прочитать колонки %s (%s)" % (label, table, e))
    return [r[1] for r in rows]


def book_key(d, use_lang):
    """Ключ сопоставления книг OLD<->NEW: lower(type); + lang, если колонка
    lang есть в books обеих баз (иначе — только type)."""
    k = (str(d.get("type") or "").strip().lower(), )
    if use_lang:
        v = d.get("lang")
        k += (str(v).strip() if v is not None else None, )
    return k


def verse_coord(song, ch, no):
    """Координата стиха (song, ch, txt_no) — текстовый кортеж для словарей."""
    return (cstr(song), cstr(ch), cstr(no))


def insert_table(wcon, table, cols, rows):
    """Вставка строк в дельту ровно теми колонками, что в NEW."""
    if not cols or not rows:
        return
    ph = ", ".join("?" for _ in cols)
    wcon.executemany("INSERT INTO %s (%s) VALUES (%s)"
                     % (table, ", ".join(cols), ph), rows)


def with_col(cols, row, name, value):
    """Копия строки row с колонкой name -> value; колонки нет — строка как была."""
    if name not in cols:
        return tuple(row)
    i = cols.index(name)
    out = list(row)
    out[i] = value
    return tuple(out)


def build(old, new, out):
    # --- фактические колонки (PRAGMA), сверяемся с реальной схемой
    o_cols = {t: pragma_cols(old, t, "old") for t in TABLES}
    n_cols = {t: pragma_cols(new, t, "new") for t in TABLES}
    for t in ("books", "textnums", "texts"):
        if not n_cols[t]:
            die("new: нет таблицы %s — это не база схемы source-.db" % t)
        if not o_cols[t]:
            die("old: нет таблицы %s — это не база схемы source-.db" % t)
    for t in ("textnums", "texts"):
        if "_id" not in n_cols[t]:
            die("new: в %s нет колонки _id — связка texts._id=textnums._id "
                "невозможна" % t)

    # сравнение стихов — по ПЕРЕСЕЧению колонок texts (NULL-safe); сам _id из
    # сравнения исключён: recompose при пересборке перенумеровывает _id — тогда
    # каждый стих «менялся» бы только из-за _id и дельта получилась бы ложной
    common_tx = [c for c in n_cols["texts"] if c in o_cols["texts"] and c != "_id"]

    # DDL берём из NEW — ровно 5 таблиц дельты, ничего лишнего
    ddl = {}
    for name, sql in new.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall():
        ln = (name or "").lower()
        if ln in TABLES and sql:
            ddl[ln] = sql

    use_lang = "lang" in o_cols["books"] and "lang" in n_cols["books"]
    old_books = {}  # book_key -> _id книги в OLD
    for row in old.execute("SELECT * FROM books").fetchall():
        d = dict(zip(o_cols["books"], row))
        old_books[book_key(d, use_lang)] = d.get("_id")
    new_books = []
    for row in new.execute("SELECT * FROM books").fetchall():
        d = dict(zip(n_cols["books"], row))
        new_books.append((book_key(d, use_lang), d))

    # запрос стихов: OLD — только общие колонки texts для сравнения;
    # NEW — полные строки textnums+texts (их и пишем в дельту)
    sel_old = ", ".join("t.%s" % c for c in common_tx) if common_tx else "NULL"
    q_old = ("SELECT n.song, n.ch_no, n.txt_no, %s FROM textnums n "
             "LEFT JOIN texts t ON t._id = n._id WHERE n.book_id = ?" % sel_old)
    sel_tn = ", ".join("n.%s" % c for c in n_cols["textnums"])
    sel_tx = ", ".join("t.%s" % c for c in n_cols["texts"])
    q_new = ("SELECT %s, %s FROM textnums n "
             "LEFT JOIN texts t ON t._id = n._id WHERE n.book_id = ?"
             % (sel_tn, sel_tx))
    # дубли координат книги: одна строка на книгу, не на стих
    q_dup = ("SELECT song, ch_no, txt_no FROM textnums WHERE book_id = ?"
             " GROUP BY song, ch_no, txt_no HAVING COUNT(*) > 1")
    ntn = len(n_cols["textnums"])

    counts = []          # (метка книги, число изменённых) — в отчёт
    remaps = []          # (метка книги, старый _id, новый _id) — перенумерация спеки
    rows_books = []
    rows_chapters = []
    rows_songs = []
    rows_textnums = []
    rows_texts = []

    try:
        for key, bd in new_books:
            bid = bd.get("_id")
            label = "%s#%s" % (bd.get("type"), bid)
            # старые стихи этой книги: координата -> значения общих колонок texts
            old_map = {}
            obid = old_books.get(key)
            # Дельта встаёт на УСТАНОВЛЕННУЮ книгу: её app-id (gb-type-_id-lang)
            # считается по books._id из файла, стоящего на устройстве (== OLD).
            # Перенумерация спеки в NEW не должна ломать поиск книги.
            tgt = obid if obid is not None else bid
            if tgt != bid:
                remaps.append((label, tgt, bid))
            if obid is not None:
                for row in old.execute(q_old, (obid, )).fetchall():
                    coord = verse_coord(row[0], row[1], row[2])
                    old_map[coord] = tuple(row[3:3 + len(common_tx)])
            # дубли координат: импорт даёт id base, base~2, base~3 по порядку строк,
            # поэтому дублирующуюся координату берём ЦЕЛИКОМ (иначе суффиксы поедут)
            dup_old = set()
            if obid is not None:
                for row in old.execute(q_dup, (obid, )).fetchall():
                    dup_old.add(verse_coord(row[0], row[1], row[2]))
            dup_new = set()
            for row in new.execute(q_dup, (bid, )).fetchall():
                dup_new.add(verse_coord(row[0], row[1], row[2]))
            need_ch = set()     # (song, ch) изменённых стихов
            need_songs = set()  # song изменённых стихов
            n_changed = 0
            for row in new.execute(q_new, (bid, )).fetchall():
                tn = dict(zip(n_cols["textnums"], row[:ntn]))
                tx = dict(zip(n_cols["texts"], row[ntn:]))
                coord = verse_coord(tn.get("song"), tn.get("ch_no"),
                                    tn.get("txt_no"))
                if (coord in old_map and coord not in dup_old
                        and coord not in dup_new):
                    # два NULL считаем равными: сравниваем кортежи как есть
                    if old_map[coord] == tuple(tx.get(c) for c in common_tx):
                        continue
                n_changed += 1
                rows_textnums.append(with_col(
                    n_cols["textnums"],
                    tuple(tn.get(c) for c in n_cols["textnums"]), "book_id", tgt))
                if tx.get("_id") is not None:
                    rows_texts.append(tuple(tx.get(c) for c in n_cols["texts"]))
                need_ch.add((cstr(tn.get("song")), cstr(tn.get("ch_no"))))
                need_songs.add(cstr(tn.get("song")))
            counts.append((label, n_changed))
            if not n_changed:
                continue
            # книга с изменениями — её строка books как в NEW, _id под установленную
            rows_books.append(tuple(
                tgt if c == "_id" else bd.get(c) for c in n_cols["books"]))
            # chapters/songs — только для изменённых стихов
            if n_cols["chapters"]:
                q = ("SELECT %s FROM chapters WHERE book_id = ?"
                     % ", ".join(n_cols["chapters"]))
                for row in new.execute(q, (bid, )).fetchall():
                    d = dict(zip(n_cols["chapters"], row))
                    if (cstr(d.get("song")), cstr(d.get("number"))) in need_ch:
                        rows_chapters.append(with_col(
                            n_cols["chapters"], row, "book_id", tgt))
            if n_cols["songs"]:
                q = ("SELECT %s FROM songs WHERE book_id = ?"
                     % ", ".join(n_cols["songs"]))
                for row in new.execute(q, (bid, )).fetchall():
                    d = dict(zip(n_cols["songs"], row))
                    if cstr(d.get("song")) in need_songs:
                        rows_songs.append(with_col(
                            n_cols["songs"], row, "book_id", tgt))
    except sqlite3.Error as e:
        die("не удалось прочитать стихи (%s)" % e)

    # --- собираем delta.db во временном файле рядом с --out и вставляем атомарно
    out_dir = os.path.dirname(out) or "."
    if not os.path.isdir(out_dir):
        die("нет папки для --out: %s" % out_dir)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_make_delta_", suffix=".db", dir=out_dir)
    os.close(fd)
    try:
        w = sqlite3.connect(tmp)
        try:
            for t in TABLES:
                if t in ddl:
                    w.execute(ddl[t])
            insert_table(w, "books", n_cols["books"], rows_books)
            insert_table(w, "chapters", n_cols["chapters"], rows_chapters)
            insert_table(w, "songs", n_cols["songs"], rows_songs)
            insert_table(w, "textnums", n_cols["textnums"], rows_textnums)
            insert_table(w, "texts", n_cols["texts"], rows_texts)
            w.commit()
        except sqlite3.Error as e:
            die("не удалось собрать дельту (%s)" % e)
        finally:
            w.close()
        with open(tmp, "rb") as f:
            data = f.read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    err = dbcommon.atomic_write_bytes(out, data)
    if err:
        die("не записано атомарно (%s): %s" % (out, err))

    # --- отчёт
    for label, n in counts:
        print("%s: изменено %d стихов" % (label, n))
    for label, old_id, new_id in remaps:
        print("ВНИМАНИЕ: %s перенумерована (OLD _id=%s, NEW _id=%s) — "
              "дельта записана под старый _id" % (label, old_id, new_id))
    print("Итого строк: books=%d chapters=%d songs=%d textnums=%d texts=%d" % (
        len(rows_books), len(rows_chapters), len(rows_songs),
        len(rows_textnums), len(rows_texts)))
    print("Записан: %s" % out)


def main(argv):
    ap = argparse.ArgumentParser(
        description="Дельта изменённых стихов OLD->NEW для автообновлений "
                    "(catalog.json)")
    ap.add_argument("--old", required=True, help="база предыдущей версии")
    ap.add_argument("--new", required=True, help="база новой версии")
    ap.add_argument("--out", required=True, help="куда положить delta.db")
    ap.add_argument("--force", action="store_true",
                    help="перезаписать существующий --out")
    a = ap.parse_args(argv[1:])
    out = os.path.abspath(a.out)
    # без --force существующий файл не трогаем никогда
    if os.path.exists(out) and not a.force:
        die("--out уже существует: %s (перезапись — с --force)" % out)
    old = open_ro(a.old, "old")
    new = open_ro(a.new, "new")
    try:
        build(old, new, out)
    finally:
        for con in (old, new):
            try:
                con.close()
            except sqlite3.Error:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
