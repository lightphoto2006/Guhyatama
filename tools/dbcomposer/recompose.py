#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dbcomposer — чистка и пересборка Gitabase .db для Гухьятамы.
Только стандартная библиотека Python (sqlite3, json, os). Базы-источники не трогаем (только чтение).

  py recompose.py inspect SOURCE.db [--type BG] [--book 1]
      Инвентарь книги/файла + отчёт о мусоре.

  py recompose.py build SPEC.json OUT.db [--force]
      Пересборка по спеку (пример: spec.example.json).
      Копирует выбранные книги с ПЕРЕНУМЕРАЦИЕЙ _id, чистит мусор,
      перепривязывает chapters/songs/textnums/texts/image_nums/images/textrefs.
      Таблицы textindex*/meanings/eind/links/lettersbytopic приложению не нужны — пропускаем.

Что считается мусором (флаги спеки, по умолчанию ВКЛ):
  drop_error_rows   — textnums с '@ERROR' в song/ch_no/txt_no
  drop_empty_verses — пустой preview И все 5 текстовых полей пустые
  dedupe            — дубли (book,song,ch_no,txt_no), оставляем первый
  drop_empty_chapters (по умолч. ВЫКЛ) — главы без стихов после чистки
"""
import json
import os
import re
import sqlite3
import sys

TOOLS_VERSION = "2026-09-12e"

APP_TABLES = ('books', 'chapters', 'songs', 'textnums', 'texts',
              'textrefs', 'images', 'image_nums')
# lettersbytopic: связка «тема -> письма» (rec_id = txt_no писем); копируем целиком,
# если в сборку входит хотя бы одна книга писем (LTRS/LTR) — приложение сматчит позже
LINK_TABLES = ('lettersbytopic',)
SKIP_TABLES = ('textindex', 'textindex_content', 'textindex_segments',
               'textindex_segdir', 'meanings', 'eind', 'links')


def connect_ro(path):
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True)


def table_cols(con, table):
    return [c[1] for c in con.execute("PRAGMA table_info(%s)" % table).fetchall()]


def jpeg_size(data):
    """Габариты JPEG без Pillow (парсинг SOF-маркеров). None если не JPEG."""
    try:
        if not data or len(data) < 10 or data[0] != 0xFF or data[1] != 0xD8:
            return None
        i, n = 2, len(data)
        while i + 8 < n:
            if data[i] != 0xFF:
                return None
            m = data[i + 1]
            while m == 0xFF:
                i += 1
                m = data[i + 1]
            if m in (0xD8, 0xD9) or (0xD0 <= m <= 0xD7) or m == 0x01:
                i += 2
                continue
            if i + 3 >= n:
                return None
            ln = (data[i + 2] << 8) + data[i + 3]
            if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                     0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return ((data[i + 7] << 8) + data[i + 8],
                        (data[i + 5] << 8) + data[i + 6])
            i += 2 + ln
    except Exception:
        pass
    return None


def img_bytes(raw):
    """Контент images: base64-текст в BLOB или сырой JPEG -> байты JPEG (или None)."""
    if not raw:
        return None
    if isinstance(raw, str):
        raw = raw.encode('ascii', 'ignore')
    import base64 as _b64
    try:
        data = _b64.b64decode(raw, validate=False)
        if len(data) >= 100:
            return data
    except Exception:
        pass
    if len(raw) >= 100 and raw[:2] == b'\xff\xd8':
        return bytes(raw)
    return None


def image_info(src, book_id, limit=2000):
    """Картинки книги: [{'image_id','kb','dim','song','ch','txt','desc'}]."""
    con = connect_ro(src)
    try:
        cols = [c[1].lower() for c in con.execute("PRAGMA table_info(image_nums)").fetchall()]
        if not cols:
            return []
        if 'bid' in cols:
            where, args = "WHERE bid=?", (book_id,)
        else:
            where, args = "", ()
        sel = []
        for want in ('sid', 'cid', 'tnum', 'image_id', 'desc'):
            sel.append(want if want in cols else "NULL")
        rows = con.execute(
            "SELECT %s FROM image_nums %s LIMIT ?" % (",".join(sel), where),
            tuple(args) + (limit,)).fetchall()
    except Exception:
        con.close()
        return []
    out = []
    cache = {}
    for sid, cid, tnum, iid, desc in rows:
        if iid not in cache:
            r = con.execute("SELECT content FROM images WHERE image_id=?", (iid,)).fetchone()
            data = img_bytes(r[0]) if r else None
            if data is None:
                cache[iid] = (0, '')
            else:
                wh = jpeg_size(data)
                cache[iid] = (len(data) // 1024, '%dx%d' % wh if wh else '')
        kb, dim = cache[iid]
        out.append({'image_id': str(iid), 'kb': kb, 'dim': dim,
                    'song': str(sid), 'ch': str(cid), 'txt': str(tnum),
                    'desc': (desc or '')[:70]})
    con.close()
    return out


def has_table(con, table):
    r = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return r is not None


def chapter_verses(src, book_id, limit=5000):
    """Главы книги + число стихов в каждой (CAST — TEXT/INT не должны расходиться).
    Возвращает [{'song','number','title','verses'}]."""
    con = connect_ro(src)
    try:
        rows = con.execute(
            """SELECT c.song, c.number, c.title, COUNT(n._id) FROM chapters c
               LEFT JOIN textnums n ON n.book_id=c.book_id
               AND CAST(n.song AS TEXT)=CAST(c.song AS TEXT)
               AND CAST(n.ch_no AS TEXT)=CAST(c.number AS TEXT)
               WHERE c.book_id=? GROUP BY c.song, c.number
               ORDER BY c.song, c.number LIMIT ?""",
            (book_id, limit)).fetchall()
        return [{'song': str(r[0]), 'number': str(r[1]),
                 'title': (r[2] or '').strip(), 'verses': r[3]} for r in rows]
    finally:
        con.close()


def find_verses(src, book_id, kind='all', search='', limit=1000):
    """Строки textnums (+preview) для просмотра. kind: all|error|dup|empty|orphan.
    Возвращает [{'song','ch_no','txt_no','preview'}]."""
    con = connect_ro(src)
    try:
        if kind == 'error':
            q = ("SELECT song,ch_no,txt_no,preview FROM textnums WHERE book_id=? AND "
                 "(song LIKE '%@ERROR%' OR ch_no LIKE '%@ERROR%' OR txt_no LIKE '%@ERROR%') LIMIT ?")
            args = (book_id, limit)
        elif kind == 'dup':
            q = ("""SELECT n.song,n.ch_no,n.txt_no,n.preview FROM textnums n WHERE n.book_id=?
                    AND EXISTS (SELECT 1 FROM textnums m WHERE m.book_id=n.book_id
                    AND CAST(m.song AS TEXT)=CAST(n.song AS TEXT)
                    AND CAST(m.ch_no AS TEXT)=CAST(n.ch_no AS TEXT)
                    AND CAST(m.txt_no AS TEXT)=CAST(n.txt_no AS TEXT)
                    AND m._id<>n._id) LIMIT ?""")
            args = (book_id, limit)
        elif kind == 'empty':
            q = ("""SELECT n.song,n.ch_no,n.txt_no,n.preview FROM textnums n LEFT JOIN texts t ON t._id=n._id
                    WHERE n.book_id=? AND (n.preview IS NULL OR n.preview='')
                    AND (t.sanskrit IS NULL OR t.sanskrit='') AND (t.translit IS NULL OR t.translit='')
                    AND (t.transl1 IS NULL OR t.transl1='') AND (t.transl2 IS NULL OR t.transl2='')
                    AND (t.comment IS NULL OR t.comment='') LIMIT ?""")
            args = (book_id, limit)
        elif kind == 'orphan':
            q = ("""SELECT n.song,n.ch_no,n.txt_no,n.preview FROM textnums n WHERE n.book_id=?
                    AND NOT EXISTS (SELECT 1 FROM chapters c WHERE c.book_id=n.book_id
                    AND CAST(c.song AS TEXT)=CAST(n.song AS TEXT)
                    AND CAST(c.number AS TEXT)=CAST(n.ch_no AS TEXT)) LIMIT ?""")
            args = (book_id, limit)
        elif search:
            q = ("SELECT song,ch_no,txt_no,preview FROM textnums WHERE book_id=?"
                 " AND (CAST(song AS TEXT) LIKE ? OR CAST(ch_no AS TEXT) LIKE ?"
                 " OR CAST(txt_no AS TEXT) LIKE ? OR preview LIKE ?) LIMIT ?")
            like = '%' + search + '%'
            args = (book_id, like, like, like, like, limit)
        else:
            q = "SELECT song,ch_no,txt_no,preview FROM textnums WHERE book_id=? ORDER BY song,ch_no LIMIT ?"
            args = (book_id, limit)
        return [{'song': str(r[0]), 'ch_no': str(r[1]), 'txt_no': str(r[2]),
                 'preview': (r[3] or '')[:90]} for r in con.execute(q, args).fetchall()]
    finally:
        con.close()


def safe_int(v):
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return 0


def is_blank(v):
    return v is None or (isinstance(v, str) and v.strip() == '')


def books_row(con, old_bid):
    """Строка books с фолбэком на минимальный набор колонок (схемы плавают)."""
    try:
        return con.execute(
            "SELECT _id,sort,author,title,desc,type,levels,hasSanskrit,hasPurport,"
            "hasColorStructure,isSongBook,text_size,purport_size,text_begin_raw,"
            "text_end_raw,web_abbrev,compare_code,issue,isSimple FROM books WHERE _id=?",
            (old_bid,)).fetchone(), True
    except Exception:
        r = con.execute("SELECT _id,title,author,type FROM books WHERE _id=?", (old_bid,)).fetchone()
        return (r[0], None, r[2], r[1], None, r[3], None, None, None, None, None, None, None,
                None, None, None, None, None, None), False


# ---------------------------------------------------------------- inspect ---
def inspect_data(src):
    """Структура для GUI: [{'book_id','title','author','type','chapters','verses',
    'images','junk':[...]}]. Исключения — наружу (GUI покажет)."""
    con = connect_ro(src)
    try:
        books = con.execute("SELECT _id,title,author,type FROM books").fetchall()
        result = []
        for bid, title, author, btype in books:
            nch = con.execute("SELECT COUNT(*) FROM chapters WHERE book_id=?", (bid,)).fetchone()[0]
            ntn = con.execute("SELECT COUNT(*) FROM textnums WHERE book_id=?", (bid,)).fetchone()[0]
            nerr = con.execute(
                "SELECT COUNT(*) FROM textnums WHERE book_id=? AND (song LIKE '%@ERROR%' OR ch_no LIKE '%@ERROR%' OR txt_no LIKE '%@ERROR%')",
                (bid,)).fetchone()[0]
            nempty = con.execute(
                """SELECT COUNT(*) FROM textnums n LEFT JOIN texts t ON t._id=n._id
                   WHERE n.book_id=? AND (n.preview IS NULL OR n.preview='') AND
                   (t.sanskrit IS NULL OR t.sanskrit='') AND (t.translit IS NULL OR t.translit='')
                   AND (t.transl1 IS NULL OR t.transl1='') AND (t.transl2 IS NULL OR t.transl2='')
                   AND (t.comment IS NULL OR t.comment='')""", (bid,)).fetchone()[0]
            ndup = con.execute(
                """SELECT COUNT(*) FROM (SELECT song,ch_no,txt_no,COUNT(*) c FROM textnums
                   WHERE book_id=? GROUP BY song,ch_no,txt_no HAVING c>1)""", (bid,)).fetchone()[0]
            nch_orphan = con.execute(
                """SELECT COUNT(*) FROM chapters WHERE book_id=? AND song||'/'||number NOT IN
                   (SELECT song||'/'||ch_no FROM textnums WHERE book_id=?)""", (bid, bid)).fetchone()[0]
            ntn_orphan = con.execute(
                """SELECT COUNT(*) FROM (SELECT DISTINCT song,ch_no FROM textnums WHERE book_id=?)
                   WHERE song||'/'||ch_no NOT IN (SELECT song||'/'||number FROM chapters WHERE book_id=?)""",
                (bid, bid)).fetchone()[0]
            try:
                nimg = con.execute("SELECT COUNT(*) FROM image_nums WHERE bid=?", (bid,)).fetchone()[0]
            except Exception:
                nimg = 0
            junk = []
            if nerr:
                junk.append("@ERROR: %d" % nerr)
            if nempty:
                junk.append("пустых: %d" % nempty)
            if ndup:
                junk.append("дублей: %d" % ndup)
            if nch_orphan:
                junk.append("глав без стихов: %d" % nch_orphan)
            if ntn_orphan:
                junk.append("стихов без глав: %d" % ntn_orphan)
            result.append({
                'book_id': bid, 'title': title or '', 'author': author or '',
                'type': btype or '', 'chapters': nch, 'verses': ntn,
                'images': nimg, 'junk': junk,
            })
        return result
    finally:
        con.close()


def cmd_inspect(src, only_type=None, only_book=None):
    if not os.path.exists(src):
        return "Нет файла: %s" % src
    out = ["Файл: %s" % src, ""]
    for b in inspect_data(src):
        if only_type and b['type'] != only_type:
            continue
        if only_book and b['book_id'] != only_book:
            continue
        out.append("Книга %s: %s [%s] %s" % (b['book_id'], b['title'][:50], b['type'], b['author']))
        out.append("  глав=%d стихов=%d картинок=%d" % (b['chapters'], b['verses'], b['images']))
        out.append("  мусор: " + ("; ".join(b['junk']) if b['junk'] else "нет"))
        out.append("")
    return "\n".join(out)


# ------------------------------------------------------------------- build ---
def copy_table_schema(dst, src_con, table):
    """True, если DDL таблицы реально выполнен (в dst появилась таблица)."""
    row = src_con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if row and row[0]:
        dst.execute(row[0])
        return has_table(dst, table)
    return False


def resolve_book(con, spec):
    """Книга по {"file","book_id"} или {"file","type"} -> [(old_bid,title,author,type)]."""
    if 'book_id' in spec:
        rows = con.execute("SELECT _id,title,author,type FROM books WHERE _id=?",
                           (int(spec['book_id']),)).fetchall()
    elif 'type' in spec:
        rows = con.execute("SELECT _id,title,author,type FROM books WHERE type=?",
                           (spec['type'],)).fetchall()
    else:
        raise ValueError("Нужно book_id или type: %s" % spec)
    if not rows:
        raise ValueError("Книга не найдена: %s" % spec)
    return rows


def load_topic_map(src_cons, tspec):
    """Темы для merge: {txt_code: [(song, chapter)]}, [(song,number,title)], [(song,songname)].
    Возвращает (map, chapters, songs) или (None, None, None) при нулевом пересечении."""
    sf = tspec['file']
    if sf not in src_cons:
        if not os.path.exists(sf):
            raise ValueError("Нет файла тем: %s" % sf)
        src_cons[sf] = connect_ro(sf)
    con = src_cons[sf]
    trows = resolve_book(con, tspec)
    # главы/песни тем: берём из первой книги (обычно одна)
    chapters, songs = [], []
    for old_bid, _, _, _ in trows:
        chapters = [(str(s), str(n), t) for s, n, t in con.execute(
            "SELECT song,number,title FROM chapters WHERE book_id=? ORDER BY song,number",
            (old_bid,)).fetchall()]
        try:
            songs = [(str(s), n) for s, n in con.execute(
                "SELECT song,songname FROM songs WHERE book_id=? ORDER BY sort,song",
                (old_bid,)).fetchall()]
        except Exception:
            songs = []
        if chapters:
            break
    if not chapters:
        return None, None, None
    # связка rec_id -> [(song, chapter)]; таблица может лежать в файле тем или писем
    cmap = {}
    for _, lcon in list(src_cons.items()) + [(None, con)]:
        if lcon is None:
            continue
        try:
            rows = lcon.execute("SELECT rec_id,song,chapter FROM lettersbytopic").fetchall()
        except Exception:
            continue
        if not rows:
            continue
        for rec, s, c in rows:
            if rec:
                cmap.setdefault(str(rec), []).append((str(s), str(c)))
        if cmap:
            break
    if not cmap:
        return None, None, None
    return cmap, chapters, songs


def pattern_to_regex(pattern):
    """'BG{ch}.{txt}.mp3' -> regex с группами song/ch/txt."""
    out = []
    i = 0
    for m in re.finditer(r'\{(song|ch|txt)\}', pattern):
        out.append(re.escape(pattern[i:m.start()]))
        out.append('(?P<%s>.+?)' % m.group(1))
        i = m.end()
    out.append(re.escape(pattern[i:]))
    return re.compile(''.join(out) + '$')


def pack_audio(dst, spec, report):
    """Секция spec["audio_pack"]: {"dir": "...", "book_type": "BG",
    "pattern": "BG{ch}.{txt}.mp3"}. Кладёт MP3/OGG в таблицу verse_audio
    (book_type, song, ch_no, txt_no, content, mime). Приложение при импорте
    такого файла раскладывает их по книгам этого типа (rus+eng).
    OGG/Opus (Vagdhenu): магия OggS, mime audio/ogg."""
    ap = spec.get('audio_pack')
    if not ap:
        return
    d = ap.get('dir', '')
    btype = ap.get('book_type', 'BG')
    try:
        rx = pattern_to_regex(ap.get('pattern', 'BG{ch}.{txt}.mp3'))
    except Exception as e:
        report.append("audio: плохой pattern (%s)" % e)
        return
    if not os.path.isdir(d):
        report.append("audio: нет папки %s" % d)
        return
    dst.execute("CREATE TABLE IF NOT EXISTS verse_audio(book_type TEXT, song TEXT, ch_no TEXT, txt_no TEXT, content BLOB, mime TEXT)")
    dst.execute("DELETE FROM verse_audio")
    matched = skipped = total_kb = 0
    leftovers = []
    for f in sorted(os.listdir(d)):
        low = f.lower()
        if low.endswith('.mp3'):
            kind = 'mp3'
        elif low.endswith('.ogg') or low.endswith('.opus'):
            kind = 'ogg'
        else:
            continue
        m = rx.match(f)
        if not m:
            skipped += 1
            if len(leftovers) < 5:
                leftovers.append(f)
            continue
        p = os.path.join(d, f)
        try:
            if os.path.getsize(p) < 5 * 1024 or os.path.getsize(p) > 8 * 1024 * 1024:
                skipped += 1
                continue
            with open(p, 'rb') as fh:
                data = fh.read()
            if kind == 'mp3':
                ok = data[:3] == b'ID3' or (len(data) > 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0)
                mime = 'audio/mpeg'
            else:
                ok = data[:4] == b'OggS'
                mime = 'audio/ogg'
            if not ok:
                skipped += 1
                continue
            g = m.groupdict()
            dst.execute(
                "INSERT INTO verse_audio(book_type,song,ch_no,txt_no,content,mime)"
                " VALUES (?,?,?,?,?,?)",
                (btype, g.get('song') or '1', g.get('ch') or '', g.get('txt') or '',
                 data, mime))
            matched += 1
            total_kb += len(data) // 1024
        except Exception:
            skipped += 1
    report.append("audio %s: файлов %d, %d КБ, пропущено %d%s" % (
        btype, matched, total_kb, skipped,
        (" (напр. %s)" % ", ".join(leftovers)) if leftovers else ""))


def build(spec_path, out_path, force=False):
    with open(spec_path, encoding='utf-8') as f:
        spec = json.load(f)
    if os.path.exists(out_path) and not force:
        return "OUT уже есть: %s (добавь --force)" % out_path
    if os.path.exists(out_path):
        os.remove(out_path)

    drop_err = spec.get('drop_error_rows', True)
    drop_empty = spec.get('drop_empty_verses', True)
    dedupe = spec.get('dedupe', True)
    drop_empty_ch = spec.get('drop_empty_chapters', False)

    dst = sqlite3.connect(out_path)
    report = []
    # схема: копируем DDL нужных таблиц из первого источника, где они есть
    made = set()
    src_cons = {}
    result = None
    try:
        for bspec in spec.get('books', []):
            sf = bspec['file']
            if sf not in src_cons:
                if not os.path.exists(sf):
                    return "Нет файла-источника: %s" % sf
                src_cons[sf] = connect_ro(sf)
        for sf, con in src_cons.items():
            for t in APP_TABLES:
                if t not in made:
                    try:
                        # в помеченных «сделанными» только реально созданные таблицы;
                        # источники без таблицы пробуем дальше, а не «сжигаем» имя
                        if copy_table_schema(dst, con, t):
                            made.add(t)
                            report.append("схема %s: из %s" % (t, os.path.basename(sf)))
                    except Exception:
                        pass
        # схемы «плавают»: донор схемы может быть уже нужных колонок — досаживаем
        # столбцы, которые есть хотя бы в одном источнике (ALTER TABLE ADD COLUMN)
        for t in APP_TABLES:
            if t not in made:
                continue
            base = set(table_cols(dst, t))
            for sf, con in src_cons.items():
                try:
                    scols = table_cols(con, t)
                except Exception:
                    continue
                for c in scols:
                    if c not in base:
                        dst.execute('ALTER TABLE "%s" ADD COLUMN "%s"' % (t, c))
                        base.add(c)
        for t in made:
            dst.execute("DELETE FROM %s" % t)

        next_book = 0
        next_ch = 0
        next_tn = 0
        included_types = set()
        seen_src = set()
        cover_recs = []
        for bspec in spec.get('books', []):
            con = src_cons[bspec['file']]
            sel = "SELECT _id,title,author,type FROM books WHERE "
            if 'book_id' in bspec:
                sel += "_id=%d" % int(bspec['book_id'])
            elif 'type' in bspec:
                sel += "type='%s'" % bspec['type'].replace("'", "''")
            else:
                return "В спеке нужна book_id или type: %s" % bspec
            rows = con.execute(sel).fetchall()
            if not rows:
                return "Книга не найдена: %s" % bspec
            for old_bid, title, author, btype in rows:
                if (bspec['file'], old_bid) in seen_src:
                    continue
                seen_src.add((bspec['file'], old_bid))
                next_book += 1
                nb = next_book
                brow, full = books_row(con, old_bid)
                title = bspec.get('title', brow[3])
                author = bspec.get('author', brow[2])
                btype = bspec.get('type', brow[5])
                included_types.add(btype)
                if full:
                    (_, sort, _, _, desc, _, levels, hs, hp, hcs, isb, ts, ps,
                     tbr, ter, wa, cc, iss, issimple) = brow
                    dst.execute(
                        "INSERT INTO books(_id,sort,author,title,desc,type,levels,hasSanskrit,"
                        "hasPurport,hasColorStructure,isSongBook,text_size,purport_size,"
                        "text_begin_raw,text_end_raw,web_abbrev,compare_code,issue,isSimple)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (nb, sort, author, title, desc, btype, levels, hs, hp, hcs, isb,
                         ts, ps, tbr, ter, wa, cc, iss, issimple))
                else:
                    dst.execute("INSERT INTO books(_id,author,title,type) VALUES (?,?,?,?)",
                                (nb, author, title, btype))

                # главы (минус исключённые вручную; их стихи тоже уходят)
                # MERGE topics_from: главы/песни — из книги тем, стихи раскладываем по топикам.
                # Без merge: свои главы как есть.
                merge_map = None
                other_used = [False]
                OTHER_SONG, OTHER_NUM = '99', '1'
                tspec = bspec.get('topics_from')
                if tspec:
                    try:
                        tmap, tch, tsongs = load_topic_map(src_cons, tspec)
                    except Exception as e:
                        report.append("  topics %s: %s — обычный режим" % (btype, e))
                        tmap = None
                    if not tmap:
                        report.append("  topics %s: пересечений нет — обычный режим" % btype)
                    else:
                        merge_map = tmap
                        merge_other_title = bspec.get('untagged_title', 'Other')
                        ch_rows = [(s, n, t) for s, n, t in tch]
                if merge_map is None:
                    excl_ch = set(
                        (str(s), str(n)) for s, n in bspec.get('exclude_chapters', []))
                    ch_rows = [(s, n, t) for s, n, t in con.execute(
                        "SELECT song,number,title FROM chapters WHERE book_id=? ORDER BY song,number",
                        (old_bid,)).fetchall()
                        if (str(s), str(n)) not in excl_ch]
                else:
                    excl_ch = set(
                        (str(s), str(n)) for s, n in bspec.get('exclude_chapters', []))
                    ch_rows = [(s, n, t) for s, n, t in ch_rows
                               if (str(s), str(n)) not in excl_ch]
                for song, num, ctitle in ch_rows:
                    next_ch += 1
                    dst.execute(
                        "INSERT INTO chapters(_id,book_id,song,number,title) VALUES (?,?,?,?,?)",
                        (next_ch, nb, str(song), safe_int(num), ctitle))

                # песни (имена разделов-тем!)
                if merge_map is None:
                    try:
                        s_rows = con.execute(
                            "SELECT song,songname FROM songs WHERE book_id=? ORDER BY sort,song",
                            (old_bid,)).fetchall()
                        for s, sname in s_rows:
                            dst.execute(
                                "INSERT INTO songs(book_id,song,songname) VALUES (?,?,?)",
                                (nb, str(s), sname))
                    except Exception:
                        pass
                else:
                    for s, sname in tsongs:
                        dst.execute(
                            "INSERT INTO songs(book_id,song,songname) VALUES (?,?,?)",
                            (nb, str(s), sname))

                # стихи: фильтры + дедуп, свежие _id (texts._id = textnums._id!)
                # Ремонт: пустой song в textnums, когда у глав книги ровно один song (беседы TLKS)
                try:
                    ch_songs = [r[0] for r in con.execute(
                        "SELECT DISTINCT song FROM chapters WHERE book_id=?", (old_bid,)).fetchall()]
                    if len(ch_songs) == 1 and ch_songs[0] not in (None, ''):
                        only_song = str(ch_songs[0])
                    else:
                        only_song = None
                except Exception:
                    only_song = None
                tn_rows = con.execute(
                    "SELECT _id,song,ch_no,txt_no,preview FROM textnums WHERE book_id=? ORDER BY song,ch_no,_id",
                    (old_bid,)).fetchall()
                excl_v = set(
                    (str(s), str(c), str(t)) for s, c, t in bspec.get('exclude_verses', []))
                # стихи исключённых глав тоже уходят (иначе сироты)
                excl_ch = set(
                    (str(s), str(n)) for s, n in bspec.get('exclude_chapters', []))
                seen_keys = set()
                kept_new_keys = set()
                kept_full = set()
                kept_raw = set()
                kept = dropped_err = dropped_empty = dropped_dup = dropped_excl = fixed_song = merged = 0
                remap = {}
                for old_tid, song, ch, txt, preview in tn_rows:
                    if (str(song), str(ch), str(txt)) in excl_v or (str(song), str(ch)) in excl_ch:
                        dropped_excl += 1
                        continue
                    if drop_err and any('@ERROR' in str(x) for x in (song, ch, txt)):
                        dropped_err += 1
                        continue
                    t = con.execute(
                        "SELECT sanskrit,translit,translit_srch,transl1,transl2,comment FROM texts WHERE _id=?",
                        (old_tid,)).fetchone()
                    if t is None:
                        t = (None,) * 6
                    if drop_empty and is_blank(preview) and all(is_blank(x) for x in t):
                        dropped_empty += 1
                        continue
                    # координаты назначения: merge — топики письма (дубль под каждой темой),
                    # иначе свои (с ремонтом пустого song)
                    if merge_map is not None:
                        targets = merge_map.get(str(txt)) or []
                        if not targets:
                            targets = [(OTHER_SONG, '1')]
                            if not other_used[0]:
                                other_used[0] = True
                                next_ch += 1
                                dst.execute(
                                    "INSERT INTO chapters(_id,book_id,song,number,title) VALUES (?,?,?,?,?)",
                                    (next_ch, nb, OTHER_SONG, 1, merge_other_title))
                                dst.execute(
                                    "INSERT INTO songs(book_id,song,songname) VALUES (?,?,?)",
                                    (nb, OTHER_SONG, merge_other_title))
                    else:
                        ns, nc = str(song), str(ch)
                        if (ns == '') and only_song is not None:
                            ns = only_song
                            fixed_song += 1
                        targets = [(ns, nc)]
                    for ns, nc in targets:
                        key = (ns, nc, str(txt))
                        if dedupe and key in seen_keys:
                            dropped_dup += 1
                            continue
                        seen_keys.add(key)
                        kept_new_keys.add((ns, nc))
                        kept_full.add(key)
                        kept_raw.add((str(song), str(ch), str(txt)))
                        remap.setdefault((str(song), str(ch), str(txt)), []).append((ns, nc))
                        next_tn += 1
                        dst.execute(
                            "INSERT INTO textnums(_id,book_id,song,ch_no,txt_no,preview) VALUES (?,?,?,?,?,?)",
                            (next_tn, nb, ns, nc, str(txt), preview))
                        dst.execute(
                            "INSERT INTO texts(_id,sanskrit,translit,translit_srch,transl1,transl2,comment)"
                            " VALUES (?,?,?,?,?,?,?)", (next_tn,) + tuple(t))
                        kept += 1
                        if merge_map is not None and (ns, nc) != (str(song), str(ch)):
                            merged += 1

                # пустые главы — по флагу (по НОВЫМ координатам: работает и для merge)
                if drop_empty_ch:
                    dst.execute("DELETE FROM chapters WHERE book_id=?", (nb,))
                    for song, num, ctitle in ch_rows:
                        if (str(song), str(num)) in kept_new_keys:
                            next_ch += 1
                            dst.execute(
                                "INSERT INTO chapters(_id,book_id,song,number,title) VALUES (?,?,?,?,?)",
                                (next_ch, nb, str(song), safe_int(num), ctitle))
                    if other_used[0]:
                        next_ch += 1
                        dst.execute(
                            "INSERT INTO chapters(_id,book_id,song,number,title) VALUES (?,?,?,?,?)",
                            (next_ch, nb, OTHER_SONG, 1, merge_other_title))

                # картинки: привязка через remap (merge — к новым координатам),
                # drop_images — в мусор. Байты тянем только для kept-строк.
                # Обложка (cover_image) из drop исключается — иначе книга без обложки.
                cover_keep = bspec.get('cover_image')
                drop_img = set(bspec.get('drop_images', []))
                if cover_keep and cover_keep in drop_img:
                    drop_img.discard(cover_keep)
                    report.append("  обложка %s: убрана из удаляемых (%s)" % (btype, cover_keep))
                dropped_img = 0
                try:
                    img_rows = con.execute(
                        "SELECT sid,cid,tnum,text_id,image_id,type,desc,kind FROM image_nums WHERE bid=? LIMIT 5000",
                        (old_bid,)).fetchall()
                    want_images = set()
                    for sid, cid, tnum, text_id, image_id, itype, desc, kind in img_rows:
                        if not image_id or image_id in drop_img:
                            dropped_img += 1
                            continue
                        # строка без привязки (пустые sid/cid — обложечные) всегда остаётся;
                        # привязанная — только если её стих дожил
                        bound = bool(str(sid) or str(cid))
                        if bound and (str(sid), str(cid), str(tnum)) not in kept_full and \
                                (str(sid), str(cid), str(tnum)) not in kept_raw:
                            dropped_img += 1
                            continue
                        if merge_map is not None and bound:
                            newcoords = remap.get((str(sid), str(cid), str(tnum)), [])
                            if not newcoords:
                                dropped_img += 1
                                continue
                            for ns, nc in newcoords:
                                dst.execute(
                                    "INSERT INTO image_nums(bid,sid,cid,tnum,text_id,image_id,type,desc,kind)"
                                    " VALUES (?,?,?,?,?,?,?,?,?)",
                                    (nb, ns, nc, str(tnum), text_id, image_id, itype, desc, kind))
                        else:
                            dst.execute(
                                "INSERT INTO image_nums(bid,sid,cid,tnum,text_id,image_id,type,desc,kind)"
                                " VALUES (?,?,?,?,?,?,?,?,?)",
                                (nb, str(sid), str(cid), str(tnum), text_id, image_id, itype, desc, kind))
                        want_images.add(image_id)
                    for iid in want_images:
                        blob = con.execute("SELECT content FROM images WHERE image_id=?", (iid,)).fetchone()
                        if blob:
                            dst.execute("INSERT OR IGNORE INTO images(image_id,content) VALUES (?,?)",
                                        (iid, blob[0]))
                except Exception as e:
                    report.append("  картинки %s: пропуск (%s)" % (btype, e))

                # обложка книги: image_id из своих картинок или внешний JPEG
                cover_spec = bspec.get('cover_image') or bspec.get('cover_file')
                if cover_spec:
                    try:
                        if bspec.get('cover_file'):
                            with open(bspec['cover_file'], 'rb') as f:
                                cbytes = f.read()
                            ciid = 'COVER_' + re.sub(r'[^A-Za-z0-9_-]', '_', btype)[:20]
                            dst.execute("INSERT OR IGNORE INTO images(image_id,content) VALUES (?,?)",
                                        (ciid, cbytes))
                        else:
                            ciid = cover_spec
                            ok = dst.execute(
                                "SELECT 1 FROM images WHERE image_id=?", (ciid,)).fetchone()
                            if not ok:
                                raise ValueError("нет такой картинки в сборке: %s" % ciid)
                        cover_recs.append((nb, ciid))
                        report.append("  обложка %s: %s" % (btype, ciid))
                    except Exception as e:
                        report.append("  обложка %s: ОШИБКА %s" % (btype, e))

                report.append("Книга '%s' [%s]: стихов %d (song-починено: %d; мусор: err=%d empty=%d dup=%d excl=%d; картинок выкинуто: %d)" % (
                    (title or '')[:45], btype, kept, fixed_song, dropped_err, dropped_empty, dropped_dup, dropped_excl, dropped_img))

        # textrefs: только исходящие от включённых типов (входящие без книг-целей приложение покажет текстом)
        nrefs = 0
        seen_refs = set()
        for sf, con in src_cons.items():
            try:
                # columns can differ between files — map per source, not once
                ref_cols = table_cols(con, 'textrefs')
                if not ref_cols:
                    continue
                for r in con.execute("SELECT * FROM textrefs").fetchall():
                    key = tuple(r)
                    if key in seen_refs:
                        continue
                    seen_refs.add(key)
                    d = dict(zip(ref_cols, r))
                    if d.get('thisBook') in included_types:
                        dst.execute(
                            "INSERT INTO textrefs(thisBook,thisBookWeb,thisSong,thisChapter,thisTextNo,"
                            "thisFullTextNo,refbyBook,refbyBookWeb,refbySong,refbyChapter,refbyTextNo,"
                            "refbyText,refbyLevels,refbyScroll,refbyChapterName)"
                            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (d.get('thisBook'), d.get('thisBookWeb'), d.get('thisSong'), d.get('thisChapter'),
                             d.get('thisTextNo'), d.get('thisFullTextNo'), d.get('refbyBook'), d.get('refbyBookWeb'),
                             d.get('refbySong'), d.get('refbyChapter'), d.get('refbyTextNo'), d.get('refbyText'),
                             d.get('refbyLevels'), d.get('refbyScroll'), d.get('refbyChapterName')))
                        nrefs += 1
            except Exception:
                pass
        report.append("textrefs исходящих: %d" % nrefs)
        pack_audio(dst, spec, report)
        if cover_recs:
            dst.execute("CREATE TABLE IF NOT EXISTS covers(book_id INTEGER, image_id TEXT)")
            dst.execute("DELETE FROM covers")
            for nb_, ciid in cover_recs:
                dst.execute("INSERT INTO covers(book_id,image_id) VALUES (?,?)", (nb_, ciid))
            report.append("covers: %d" % len(cover_recs))
        if any(t in ('LTRS', 'LTR') for t in included_types):
            # донор — файл с самой широкой схемой; столбцы остальных досаживаем ALTER;
            # одинаковая таблица есть во многих базах — строки-дубли не размножаем
            donors = []
            for sf, con in src_cons.items():
                try:
                    cols = table_cols(con, 'lettersbytopic')
                except Exception:
                    cols = []
                if cols:
                    donors.append((sf, cols))
            if donors:
                donors.sort(key=lambda x: -len(x[1]))
                if not copy_table_schema(dst, src_cons[donors[0][0]], 'lettersbytopic'):
                    raise ValueError("не удалось создать таблицу lettersbytopic")
                made.add('lettersbytopic')
                base = set(table_cols(dst, 'lettersbytopic'))
                for sf, cols in donors:
                    for c in cols:
                        if c not in base:
                            dst.execute('ALTER TABLE "lettersbytopic" ADD COLUMN "%s"' % c)
                            base.add(c)
                seen_lbt = set()
                n0 = 0
                for sf, cols in donors:
                    con = src_cons[sf]
                    try:
                        rows = con.execute("SELECT * FROM lettersbytopic").fetchall()
                        for r in rows:
                            key = tuple(r)
                            if key in seen_lbt:
                                continue
                            seen_lbt.add(key)
                            dst.execute(
                                "INSERT INTO lettersbytopic(%s) VALUES (%s)" % (
                                    ",".join('"%s"' % c for c in cols),
                                    ",".join("?" * len(cols))), r)
                            n0 += 1
                    except Exception as e:
                        report.append("lettersbytopic %s: пропуск (%s)" % (os.path.basename(sf), e))
                report.append("lettersbytopic: %d (по %d файлам)" % (n0, len(donors)))
        dst.commit()
        try:
            report.append("integrity: %s" % dst.execute("PRAGMA integrity_check").fetchone()[0])
        except Exception as e:
            report.append("integrity: %s" % e)
        result = "\n".join(report)
    finally:
        for con in src_cons.values():
            try:
                con.close()
            except Exception:
                pass
        dst.close()
        if result is None and os.path.exists(out_path):
            # сборка провалилась — не оставляем битый/пустой огарзок OUT
            try:
                os.remove(out_path)
            except OSError:
                pass
    return result


SPEC_EXAMPLE = """{
  "_comment": "py recompose.py build spec.json clean.db",
  "out": "",
  "drop_error_rows": true,
  "drop_empty_verses": true,
  "dedupe": true,
  "drop_empty_chapters": false,
  "books": [
    {"file": "gitabase_texts_rus.db", "book_id": 1, "title": "Бхагавад Гита"},
    {"file": "gitabase_texts_rus.db", "type": "SB"},
    {"file": "gitabase_songs_rus.db", "book_id": 1}
  ]
}
"""


def main(argv):
    if len(argv) < 3 or argv[1] not in ('inspect', 'build', 'spec'):
        print(__doc__)
        print(SPEC_EXAMPLE)
        return 1
    if argv[1] == 'spec':
        print(SPEC_EXAMPLE)
        return 0
    if argv[1] == 'inspect':
        only_type = only_book = None
        rest = argv[3:]
        i = 0
        while i < len(rest):
            a = rest[i]
            if a.startswith('--type='):
                only_type = a.split('=', 1)[1]
            elif a == '--type' and i + 1 < len(rest):
                i += 1
                only_type = rest[i]
            elif a.startswith('--book='):
                only_book = int(a.split('=', 1)[1])
            elif a == '--book' and i + 1 < len(rest):
                i += 1
                only_book = int(rest[i])
            i += 1
        print(cmd_inspect(argv[2], only_type, only_book))
        return 0
    if argv[1] == 'build':
        force = '--force' in argv
        positionals = [a for a in argv[2:] if not a.startswith('--')]
        if len(positionals) < 1:
            print("Нужно: build SPEC.json [OUT.db] [--force]")
            return 1
        spec_path = positionals[0]
        if len(positionals) > 1:
            out_path = positionals[1]
        else:
            out_path = json.load(open(spec_path, encoding='utf-8')).get('out') or 'clean.db'
        if not out_path:
            print("Нет out: укажи OUT.db или поле out в спеке")
            return 1
        print(build(spec_path, out_path, force))
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
