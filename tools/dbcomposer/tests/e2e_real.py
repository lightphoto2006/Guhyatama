# -*- coding: utf-8 -*-
"""E2E на РЕАЛЬНЫХ базах библиотеки: Syamakunda_CC v2 -> v4.

Файлы ищутся в DBCMP_REAL_DIR или в tests/real/ (имена CC_v2_old.db,
CC_v4_new.db); при отсутствии — DBCMP_DOWNLOAD=1 качает их с GitHub release
(токен берётся из local.properties, githubFilesToken).

Проверяет:
  1. books._id между реальными версиями (стабильность под app-id);
  2. make_delta: независимый пересчёт ожидаемых строк + сверка с выданной
     дельтой (никаких ложных пропусков/ложных срабатываний);
  3. make_catalog: deltaSize/deltaSha/fp с реальных файлов.
"""
import hashlib
import io
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
ROOT = os.path.dirname(os.path.dirname(DBC))
MAKE_DELTA = os.path.join(DBC, "make_delta.py")
MAKE_CATALOG = os.path.join(DBC, "make_catalog.py")

OLD_NAME, NEW_NAME = "CC_v2_old.db", "CC_v4_new.db"
OLD_URL = ("https://api.github.com/repos/lightphoto2006/Guhyatama-files/"
           "releases/assets/605848620")
NEW_URL = ("https://api.github.com/repos/lightphoto2006/Guhyatama-files/"
           "releases/assets/606200632")

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


def find_files():
    dirs = []
    env = os.environ.get("DBCMP_REAL_DIR")
    if env:
        dirs.append(env)
    dirs.append(os.path.join(HERE, "real"))
    for d in dirs:
        a, b = os.path.join(d, OLD_NAME), os.path.join(d, NEW_NAME)
        if os.path.isfile(a) and os.path.isfile(b):
            return a, b
    if os.environ.get("DBCMP_DOWNLOAD") != "1":
        print("SKIP: нет реальных файлов (запусти с DBCMP_DOWNLOAD=1 "
              "или положи %s и %s в tests/real/)" % (OLD_NAME, NEW_NAME))
        return None, None
    d = os.path.join(HERE, "real")
    os.makedirs(d, exist_ok=True)
    tok = ""
    lp = os.path.join(ROOT, "local.properties")
    if os.path.isfile(lp):
        for line in io.open(lp, encoding="utf-8", errors="replace"):
            if line.startswith("githubFilesToken="):
                tok = line.split("=", 1)[1].strip()
    import urllib.request
    for url, name in ((OLD_URL, OLD_NAME), (NEW_URL, NEW_NAME)):
        out = os.path.join(d, name)
        print("скачиваю %s ..." % name)
        req = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + tok, "Accept": "application/octet-stream"})
        with urllib.request.urlopen(req, timeout=600) as r, open(out, "wb") as f:
            while True:
                chunk = r.read(1048576)
                if not chunk:
                    break
                f.write(chunk)
        print("  -> %d байт" % os.path.getsize(out))
    return os.path.join(d, OLD_NAME), os.path.join(d, NEW_NAME)


def load(path):
    """Строки таблицы texts+textnums книги (как читает make_delta)."""
    con = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    cols = [r[1] for r in con.execute("PRAGMA table_info(texts)")]
    common = [c for c in cols if c != "_id"]
    sel = ", ".join("t.%s" % c for c in common)
    rows = {}
    for song, ch, no, *vals in con.execute(
            "SELECT n.song,n.ch_no,n.txt_no,%s FROM textnums n "
            "LEFT JOIN texts t ON t._id=n._id ORDER BY n._id" % sel):
        rows.setdefault((str(song or ""), str(ch or ""), str(no or "")), []).append(
            tuple(vals))
    books = con.execute("SELECT _id,type FROM books").fetchall()
    con.close()
    return rows, books, common


def main():
    old_p, new_p = find_files()
    if old_p is None:
        return 0

    # --- 1) стабильность books._id между реальными версиями
    old_rows, old_books, old_common = load(old_p)
    new_rows, new_books, new_common = load(new_p)
    print("OLD books:", old_books, " NEW books:", new_books)
    check("реальные версии: книги совпадают по (type,_id)",
          [(t, i) for i, t in old_books] == [(t, i) for i, t in new_books],
          (old_books, new_books))
    common = [c for c in new_common if c in old_common]
    check("общие колонки texts есть", bool(common), common)

    # --- 2) независимый пересчёт ожидаемых строк дельты (правила make_delta)
    dup_old = {c for c, v in old_rows.items() if len(v) > 1}
    dup_new = {c for c, v in new_rows.items() if len(v) > 1}
    expected = set()   # координаты, которые ДОЛЖНЫ быть в дельте
    for coord, new_vals in new_rows.items():
        old_vals = old_rows.get(coord)
        if old_vals is None or coord in dup_old or coord in dup_new:
            expected.add(coord)
            continue
        # последняя строка OLD против каждой NEW (dict-перезапись как в make_delta)
        if any(v != old_vals[-1] for v in new_vals):
            expected.add(coord)
    check("в файлах есть изменения (не пустая дельта)", bool(expected),
          "%d из %d координат" % (len(expected), len(new_rows)))

    work = tempfile.mkdtemp(prefix="e2e_real_")
    delta_p = os.path.join(work, "delta.db")
    r = subprocess.run([sys.executable, MAKE_DELTA, "--old", old_p, "--new", new_p,
                        "--out", delta_p, "--force"], capture_output=True)
    so = r.stdout.decode("utf-8", "replace")
    print(so, end="")
    check("make_delta: rc=0", r.returncode == 0, r.stderr.decode("utf-8", "replace"))

    # сверка выданной дельты с независимым пересчётом
    con = sqlite3.connect("file:%s?mode=ro" % delta_p.replace("\\", "/"), uri=True)
    got = set()
    for song, ch, no in con.execute("SELECT song,ch_no,txt_no FROM textnums"):
        got.add((str(song or ""), str(ch or ""), str(no or "")))
    n_rows = con.execute("SELECT COUNT(*) FROM textnums").fetchone()[0]
    books_d = con.execute("SELECT _id,type FROM books").fetchall()
    names = sorted(x[0] for x in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"))
    # содержимое дельты == NEW для её строк (одинаковый SELECT к обеим базам)
    SEL5 = ("SELECT t.sanskrit,t.translit,t.transl1,t.transl2,t.comment "
            "FROM textnums n LEFT JOIN texts t ON t._id=n._id "
            "WHERE n.song=? AND n.ch_no=? AND n.txt_no=?")
    ncon = sqlite3.connect("file:%s?mode=ro" % new_p.replace("\\", "/"), uri=True)
    bad_content = 0
    for song, ch, no in got:
        cur = con.execute(SEL5, (song, ch, no))
        got_vals = sorted(tuple(r) for r in cur.fetchall())
        cur = ncon.execute(SEL5, (song, ch, no))
        want_vals = sorted(tuple(r) for r in cur.fetchall())
        if got_vals != want_vals or not got_vals:
            bad_content += 1
    ncon.close()
    con.close()
    check("дельта: координаты == независимому пересчёту", got == expected,
          "лишние %s, пропущенные %s" % (sorted(got - expected)[:5],
                                         sorted(expected - got)[:5]))
    check("дельта: строк == ВСЕМ строкам NEW этих координат (дубли целиком)",
          n_rows == sum(len(new_rows[c]) for c in got),
          (n_rows, sum(len(new_rows[c]) for c in got)))
    check("дельта: содержимое == NEW", bad_content == 0, bad_content)
    check("дельта: только 5 таблиц", names == ["books", "chapters", "songs",
                                               "textnums", "texts"], names)
    check("дельта: books._id == OLD (app-id установленной книги)",
          books_d == old_books, (books_d, old_books))

    # --- 3) make_catalog на реальных файлах
    src = work
    import shutil
    shutil.copyfile(new_p, os.path.join(src, "CC_v4.db"))
    shutil.copyfile(delta_p, os.path.join(src, "CC_delta_v4.db"))
    vpath = os.path.join(src, "versions.json")
    with open(vpath, "w", encoding="utf-8") as f:
        json.dump({"apk": {}, "audio": {},
                   "books": {"CC": {"title": "Чайтанья Чаритамрита", "lang": "rus",
                                    "file": "CC_v4.db", "version": 4,
                                    "url": "https://x/CC_v4.db",
                                    "delta": {"file": "CC_delta_v4.db",
                                              "url": "https://x/CC_delta_v4.db",
                                              "from": 2},
                                    "notes": ""}}},
                  f, ensure_ascii=False)
    cat_p = os.path.join(src, "catalog.json")
    r = subprocess.run([sys.executable, MAKE_CATALOG, "--src", src,
                        "--versions", vpath, "--out", cat_p], capture_output=True)
    print(r.stdout.decode("utf-8", "replace"), end="")
    check("make_catalog: rc=0", r.returncode == 0,
          r.stderr.decode("utf-8", "replace"))
    if r.returncode == 0:
        e = next(x for x in json.load(open(cat_p, encoding="utf-8"))["books"]
                 if x["key"] == "CC")
        check("catalog: deltaFrom=2, deltaSize/deltaSha с реального файла",
              e["deltaFrom"] == 2
              and e["deltaSize"] == os.path.getsize(os.path.join(src, "CC_delta_v4.db"))
              and e["deltaSha"] == sha256(os.path.join(src, "CC_delta_v4.db")), e)
        check("catalog: sha полного файла совпал",
              e["sha256"] == sha256(new_p) and e["size"] == os.path.getsize(new_p), e)
        check("catalog: fp (t=scc,g=1,v=180)", any(f["t"] == "scc" and f["g"] == 1
                                                  for f in e.get("fp", [])), e.get("fp"))

    print()
    if FAILED:
        print("FAILED %d: %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
