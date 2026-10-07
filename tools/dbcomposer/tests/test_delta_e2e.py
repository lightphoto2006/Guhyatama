# -*- coding: utf-8 -*-
"""E2E дельты: make_delta -> make_catalog -> импорт-мердж.

Импорт-мердж повторяет семантику LibraryDbImporter.importFile(delta=true):
книга обязательна (иначе исключение), books/chapter-заголовки — точечный
UPDATE, стихи — upsert по координате (bookId/song/ch/txt, дубли ~2/~3 по
порядку _id), удалений НЕТ, счётчик «обновлено N стихов» = строк дельты.
Реальный прогон на настоящих базах библиотеки — e2e_real.py.
"""
import hashlib
import json
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
DBC = os.path.dirname(HERE)
MAKE_DELTA = os.path.join(DBC, "make_delta.py")
MAKE_CATALOG = os.path.join(DBC, "make_catalog.py")
sys.path.insert(0, HERE)
import test_delta as fx  # noqa: E402  (DDL и фикстуры)

FAILED = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (("  | " + str(extra)) if not cond else ""))
    if not cond:
        FAILED.append(name)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def run_tool(tool, args):
    r = subprocess.run([sys.executable, tool] + args, capture_output=True)
    return (r.returncode,
            r.stdout.decode("utf-8", "replace"),
            r.stderr.decode("utf-8", "replace"))


def is_gallery(preview):
    t = (preview or "").lstrip()
    return t.startswith("Иллюстрац") or t.startswith("Illustration")


# ------------------------------------------------- импортёр (семантика app) ---
class AppLib:
    """Мини-модель Room-библиотеки в объёме, который использует импортёр."""

    def __init__(self):
        self.books = {}     # bookId -> {title, author}
        self.chapters = {}  # chapterId -> {bookId, title}
        self.verses = {}    # verseId -> dict(preview, translation, purport, text, txtNo)

    def _book_rows(self, sq):
        out = []
        for _id, title, author, typ in sq.execute(
                "SELECT _id,title,author,type FROM books").fetchall():
            out.append(("gb-%s-%s-rus" % ((typ or "gb").lower(), _id),
                        _id, title, author, typ or "GB"))
        return out

    def _import_verses(self, sq, gb, book_id):
        """Чтение стихов книги как в app (ORDER BY song,ch_no,_id; дубли ~N).
        Возвращает число обработанных строк (для note «обновлено N стихов»)."""
        seen = {}
        done = 0
        cur = sq.execute(
            "SELECT n.song,n.ch_no,n.txt_no,n.preview,t.translit,"
            "t.transl1,t.transl2,t.comment FROM textnums n "
            "LEFT JOIN texts t ON t._id=n._id WHERE n.book_id=?"
            " ORDER BY n.song,n.ch_no,n._id", (gb,))
        for song, ch, txt, preview, translit, tr1, tr2, comment in cur.fetchall():
            if is_gallery(preview):
                continue
            base = "%s/%s/%s/%s" % (book_id, song, ch, txt)
            n = seen.get(base, 0)
            seen[base] = n + 1
            vid = base if n == 0 else "%s~%d" % (base, n + 1)
            # в приложении: text=translit||preview, translation=tr2||preview
            self.verses[vid] = {
                "preview": preview or "",
                "translation": tr2 or preview or "",
                "purport": comment,
                "synonyms": tr1 or None,
                "text": translit or preview or "",
                "txtNo": txt,
            }
            done += 1
        return done

    def install_full(self, path):
        """Полный импорт (replace=true): delete + вставка."""
        sq = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
        try:
            for book_id, gb, title, author, typ in self._book_rows(sq):
                self.books[book_id] = {"title": "%s [%s]" % (title, typ), "author": author}
                cur = sq.execute("SELECT song,number,title FROM chapters WHERE book_id=?"
                                 " ORDER BY song,number", (gb,))
                for song, num, ctitle in cur.fetchall():
                    cid = "%s/ch-%s-%s" % (book_id, song, num)
                    self.chapters[cid] = {"bookId": book_id, "title": ctitle}
                self._import_verses(sq, gb, book_id)
        finally:
            sq.close()

    def delta_import(self, path):
        """Импорт дельты: точечные UPDATE + вставки, без удалений."""
        sq = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
        try:
            updated = 0
            for book_id, gb, title, author, typ in self._book_rows(sq):
                if book_id not in self.books:
                    raise RuntimeError(
                        "Дельта для неустановленной книги %s — нужен полный файл" % book_id)
                # updateBookMeta(finalId, "title [type]", author)
                self.books[book_id] = {"title": "%s [%s]" % (title, typ), "author": author}
                # главы: установленные — только заголовок, новые — вставка
                cur = sq.execute("SELECT song,number,title FROM chapters WHERE book_id=?"
                                 " ORDER BY song,number", (gb,))
                for song, num, ctitle in cur.fetchall():
                    cid = "%s/ch-%s-%s" % (book_id, song, num)
                    if cid in self.chapters:
                        self.chapters[cid]["title"] = ctitle
                    else:
                        self.chapters[cid] = {"bookId": book_id, "title": ctitle}
                # стихи: upsert по id (суффиксы дублей — счётчик с нуля, как в app)
                updated += self._import_verses(sq, gb, book_id)
            return updated
        finally:
            sq.close()


def main():
    work = tempfile.mkdtemp(prefix="delta_e2e_")
    old_p = os.path.join(work, "old.db")
    new_p = os.path.join(work, "new.db")
    delta_p = os.path.join(work, "delta.db")

    # --- OLD (v1): BG 6 стихов; SCO/LEG — чужие для дельты
    old = fx.create(old_p)
    fx.setup_common(old)
    old.execute("UPDATE books SET title='Титул старый' WHERE _id=1")
    fx.book(old, 3, "LEG", "rus")
    fx.chap(old, 103, 3, "1", 1, "Old intro")
    fx.song(old, 3, "1", "Leg")
    fx.verse(old, 11, 1, "1", "1", "1", "one", "перевод один", None)
    fx.verse(old, 12, 1, "1", "1", "2", "two", "СТАРЫЙ перевод", "комм")
    fx.verse(old, 13, 1, "1", "1", "3", "three", "удаляемый", None)
    fx.verse(old, 10, 1, "1", "1", "5", "five", "тот же перевод", None)
    fx.verse(old, 501, 1, "1", "1", "6", "dup", "текст дубля", None)
    fx.verse(old, 502, 1, "1", "1", "6", "dup", "текст дубля", None)
    fx.verse(old, 21, 2, "1", "1", "1", "sco", "unchanged", None)
    fx.verse(old, 31, 3, "1", "1", "1", "leg", "old only", None)
    old.commit(); old.close()

    # --- NEW (v2): v2 изменён, v4 добавлен, v3 удалён, v5 тот же (другой _id),
    #     v6-дубль: первая строка изменена; глава 1 переименована; SCO не тронут
    new = fx.create(new_p)
    fx.setup_common(new)
    new.execute("UPDATE books SET title='Титул новый' WHERE _id=1")
    new.execute("UPDATE chapters SET title='Глава 1 (переименована)' WHERE _id=101")
    fx.chap(new, 105, 1, "2", 1, "Глава 2")
    fx.song(new, 1, "2", "Песня 2")
    fx.verse(new, 11, 1, "1", "1", "1", "one", "перевод один", None)
    fx.verse(new, 12, 1, "1", "1", "2", "two", "НОВЫЙ перевод", "комм")
    fx.verse(new, 14, 1, "1", "1", "4", "four", "добавленный", None)
    fx.verse(new, 7, 1, "1", "1", "5", "five", "тот же перевод", None)
    fx.verse(new, 501, 1, "1", "1", "6", "dup", "ИЗМЕНЁН дубль", None)
    fx.verse(new, 502, 1, "1", "1", "6", "dup", "текст дубля", None)
    fx.verse(new, 21, 2, "1", "1", "1", "sco", "unchanged", None)
    new.commit(); new.close()

    # --- 1) make_delta
    rc, so, se = run_tool(MAKE_DELTA, ["--old", old_p, "--new", new_p,
                                       "--out", delta_p, "--force"])
    check("make_delta: rc=0", rc == 0, se)
    check("make_delta: отчёт 4 стиха", "изменено 4 стихов" in so, so)

    # --- 2) make_catalog (NEW = полный файл, рядом — дельта)
    src = os.path.join(work, "src")
    os.makedirs(src)
    full = os.path.join(src, "BG_v2.db")
    with open(new_p, "rb") as a, open(full, "wb") as b:
        b.write(a.read())
    with open(delta_p, "rb") as a, open(os.path.join(src, "BG_delta.db"), "wb") as b:
        b.write(a.read())
    versions = {
        "apk": {},
        "books": {"BG": {"title": "Бхагавад Гита", "lang": "rus", "file": "BG_v2.db",
                         "version": 2, "url": "https://x/BG_v2.db",
                         "delta": {"file": "BG_delta.db", "url": "https://x/BG_delta.db",
                                   "from": 1},
                         "notes": ""}},
        "audio": {},
    }
    vpath = os.path.join(work, "versions.json")
    with open(vpath, "w", encoding="utf-8") as f:
        json.dump(versions, f, ensure_ascii=False)
    cat_p = os.path.join(work, "catalog.json")
    rc, so, se = run_tool(MAKE_CATALOG, ["--src", src, "--versions", vpath, "--out", cat_p])
    check("make_catalog: rc=0", rc == 0, se + so)
    cat = json.load(open(cat_p, encoding="utf-8"))
    e = next(x for x in cat["books"] if x["key"] == "BG")
    check("catalog: размер/sha полного файла",
          e["size"] == os.path.getsize(full) and e["sha256"] == sha256(full), e)
    check("catalog: deltaFrom=1, deltaSize/deltaSha с файла",
          e["deltaFrom"] == 1
          and e["deltaSize"] == os.path.getsize(os.path.join(src, "BG_delta.db"))
          and e["deltaSha"] == sha256(os.path.join(src, "BG_delta.db")), e)
    check("catalog: fp книги (t=bg,g=1)",
          any(f["t"] == "bg" and f["g"] == 1 for f in e.get("fp", [])), e.get("fp"))
    # дельта для несуществующего файла -> пустые поля (файл в каталоге не подставится)
    versions["books"]["BG"]["delta"]["file"] = "нет_такого.db"
    with open(vpath, "w", encoding="utf-8") as f:
        json.dump(versions, f, ensure_ascii=False)
    c2 = os.path.join(work, "c2.json")
    rc, so, se = run_tool(MAKE_CATALOG, ["--src", src, "--versions", vpath, "--out", c2])
    e2 = next(x for x in json.load(open(c2, encoding="utf-8"))["books"] if x["key"] == "BG")
    check("catalog: битая дельта -> deltaUrl пустой (fail-closed)",
          rc == 0 and e2["deltaUrl"] == "" and e2["deltaSize"] == 0
          and e2["deltaSha"] == "", e2)

    # --- 3) импорт-мердж: полный v1 -> дельта v2
    app = AppLib()
    app.install_full(old_p)
    bg = "gb-bg-1-rus"
    n_before = sum(1 for vid in app.verses if vid.startswith(bg + "/"))
    check("full: BG установлен (6 стихов)", n_before == 6, n_before)
    check("full: SCO и LEG тоже установлены",
          "gb-sco-2-rus" in app.books and "gb-leg-3-rus" in app.books, list(app.books))

    # дельта для неустановленной книги -> исключение (как в app)
    try:
        AppLib().delta_import(delta_p)
        check("delta: неустановленная книга -> исключение", False)
    except RuntimeError as ex:
        check("delta: неустановленная книга -> исключение", "неустановленной" in str(ex), ex)

    n_upd = app.delta_import(delta_p)
    n_after = sum(1 for vid in app.verses if vid.startswith(bg + "/"))
    check("delta: книга НЕ усохла (6 -> 7: +добавленный, удалённый оставлен)",
          n_after == n_before + 1, (n_before, n_after))
    check("delta: счётчик как в note app (4 стиха)", n_upd == 4, n_upd)
    g = lambda s: app.verses["%s/%s" % (bg, s)]  # noqa: E731
    check("delta: изменённый стих обновлён", g("1/1/2")["translation"] == "НОВЫЙ перевод",
          g("1/1/2"))
    check("delta: неизменённые не тронуты",
          g("1/1/1")["translation"] == "перевод один"
          and g("1/1/5")["translation"] == "тот же перевод"
          and app.verses["gb-sco-2-rus/1/1/1"]["translation"] == "unchanged",
          (g("1/1/1"), g("1/1/5"), app.verses.get("gb-sco-2-rus/1/1/1")))
    check("delta: удалённый стих остался (дизайн: дельта не удаляет)",
          g("1/1/3")["translation"] == "удаляемый", g("1/1/3"))
    check("delta: добавленный стих вставлен", g("1/1/4")["translation"] == "добавленный",
          g("1/1/4"))
    check("delta: дубль координаты — обе строки (~2), изменена первая",
          g("1/1/6")["translation"] == "ИЗМЕНЁН дубль"
          and g("1/1/6~2")["translation"] == "текст дубля",
          (g("1/1/6"), g("1/1/6~2")))
    check("delta: title/author обновлены из NEW",
          app.books[bg]["title"] == "Титул новый [BG]", app.books[bg])
    check("delta: глава переименована точечно",
          app.chapters["%s/ch-1-1" % bg]["title"] == "Глава 1 (переименована)",
          app.chapters["%s/ch-1-1" % bg])
    check("delta: чужая книга не тронута",
          app.books["gb-sco-2-rus"]["title"] == "титул SCO [SCO]",
          app.books["gb-sco-2-rus"])
    # глава «2» в дельту не попадала (нет изменённых стихов) — не должна появиться
    check("delta: посторонняя глава не вставлена", "%s/ch-2-1" % bg not in app.chapters,
          sorted(app.chapters))

    print()
    if FAILED:
        print("FAILED %d: %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
