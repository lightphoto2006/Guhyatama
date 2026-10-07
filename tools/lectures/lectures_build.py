#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lectures_build — балк-конвертация Word-транскрипций лекций в clean.db для Гухьятамы.
Только стандартная библиотека (zipfile, xml, sqlite3, json, re). Исходные .docx не трогаем.

ОСНОВНОЙ режим «папка = одна книга»: каждый .docx = ОДНА лекция,
иерархия — в имени файла: 001 (2.3.1-36) / 338 (1.6.82-120) Величие Адвайты Ачарьи.
Сортировка — по (песнь, глава, текст), не по номеру файла.
  py lectures_build.py scan "папка"
  py lectures_build.py build lectures.json [OUT.db] [--force]   (спека с ключом "book")

Старый режим «файл = книга» (маркера КНИГА/РАЗДЕЛ/ГЛАВА/ЛЕКЦИЯ внутри) оставлен
для совместимости: спека без ключа "book".

Идея: одна лекция = одна строка textnums/texts (как стих в исходном формате).
Приложение уже умеет такое без правок схемы:
  Book (произведение) -> songs (разделы: лилы/песни) -> chapters (главы) -> verses (лекции).
  Reader: песни плитками -> главы плитками -> список лекций -> экран лекции.
  Для БГ раздел один (song=1) — приложение сразу показывает главы.

Word-шаблон (4 уровня; работают и стили Heading 1-4, и plain-префиксы):
  H1 / КНИГА: <название> | TYPE=<SCC|SSB|SBG>
  H2 / РАЗДЕЛ: <название> | SONG=<n>        (для БГ можно опустить — будет song=1)
  H3 / ГЛАВА <n>[: название]                  (для БГ = глава БГ 1..18)
  H4 / ЛЕКЦИЯ <num>[: заголовок] [| REF=<привязка к стиху>] [| ДАТА=<дата>]
  тело: обычные абзацы до следующего маркера. Пустая строка = граница абзаца.

Примеры заголовков:
  КНИГА: Чайтанья Чаритамрита | TYPE=SCC
  РАЗДЕЛ: Мадхья-лила | SONG=2
  ГЛАВА 5: Слушание ...
  ЛЕКЦИЯ 000: Экстазы Господа Чайтаньи | REF=ЧЧ Мадхья 5.12 | ДАТА=01.01.2025

Использование:
  py lectures_build.py inspect "лекция.docx"
  py lectures_build.py build lectures.json [OUT.db] [--force]

Спека lectures.json:
  {
    "out": "lectures_clean.db",
    "defaults": {"author": "Шьямакунда прабху", "type": "SCC"},
    "files": [
      {"docx": "000 Чайтанья Чаритамрита.docx", "title": "Чайтанья Чаритамрита. Лекции",
       "type": "SCC", "author": "Шьямакунда прабху"},
      {"docx": "БГ лекции.docx", "title": "Бхагавад-гита. Лекции", "type": "SBG"}
    ]
  }
  Поля файла перекрывают defaults. title/type можно также задать маркером КНИГА: внутри.
"""
import html
import json
import os
import re
import sqlite3
import sys
import zipfile
import xml.etree.ElementTree as ET

VERSION = "2026-09-15a"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Тип -> человеческий код произведения для подписей (VerseShare.RU расширь теми же ключами)
WORK_CODE = {"SCC": "CC", "SSB": "SB", "SBG": "BG", "SBRS": "BRS"}
# Дефолтные разделы, если в файле нет маркеров РАЗДЕЛ:
DEFAULT_SONGS = {
    "SCC": [(1, "Ади-лила"), (2, "Мадхья-лила"), (3, "Антья-лила")],
    "SSB": [(i, "Песнь %d" % i) for i in range(1, 13)],
    "SBG": [(1, "Бхагавад-гита")],
    "SBRS": [(1, "Восточный"), (2, "Южный"), (3, "Западный"), (4, "Северный")],
}

RE_BOOK = re.compile(r"^\s*КНИГА\s*:\s*(.+?)\s*$", re.I)
RE_SONG = re.compile(r"^\s*РАЗДЕЛ\s*:\s*(.+?)\s*$", re.I)
RE_CH = re.compile(r"^\s*ГЛАВА\s+(\d+)\s*[:.\-–—]?\s*(.*)$", re.I)
RE_LEC = re.compile(r"^\s*ЛЕКЦИЯ\s*[№#]?\s*([\w\-–.]+)\s*[:.\-–—]?\s*(.*)$", re.I | re.U)
RE_PIPE = re.compile(r"\|")
RE_META = re.compile(r"^\s*(TYPE|SONG|REF|ДАТА|DATE|AUTHOR|АВТОР)\s*=\s*(.+?)\s*$", re.I)


def split_title_meta(text):
    """'Мадхья-лила | SONG=2' -> ('Мадхья-лила', {'SONG': '2'})."""
    parts = RE_PIPE.split(text)
    title = parts[0].strip()
    meta = {}
    for p in parts[1:]:
        m = RE_META.match(p.strip())
        if m:
            meta[m.group(1).upper()] = m.group(2).strip()
    # русские ключи -> канон
    if "АВТОР" in meta and "AUTHOR" not in meta:
        meta["AUTHOR"] = meta.pop("АВТОР")
    if "ДАТА" in meta and "DATE" not in meta:
        meta["DATE"] = meta.pop("ДАТА")
    return title, meta


def read_ole_stream(path, stream_name):
    """Чтение потока из OLE-контейнера (.doc) только на struct — без olefile.
    FAT-цепочки + chained DIFAT; mini-потоки не нужны (WordDocument всегда большой)."""
    import struct
    with open(path, "rb") as f:
        hdr = f.read(512)
        if len(hdr) < 512 or hdr[0:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise ValueError("не OLE-контейнер (не .doc?)")
        sec_size = 1 << struct.unpack_from("<H", hdr, 30)[0]
        first_dir = struct.unpack_from("<i", hdr, 48)[0]
        cutoff = struct.unpack_from("<I", hdr, 56)[0]
        first_difat = struct.unpack_from("<i", hdr, 68)[0]
        ndifat = struct.unpack_from("<i", hdr, 72)[0]
        difat = list(struct.unpack_from("<109i", hdr, 76))
        if ndifat > 0 and first_difat >= 0:
            sec = first_difat
            for _ in range(ndifat):
                f.seek(512 + sec * sec_size)
                blk = f.read(sec_size)
                if len(blk) < sec_size:
                    break
                difat.extend(struct.unpack_from("<%di" % (sec_size // 4 - 1), blk, 0))
                sec = struct.unpack_from("<i", blk, sec_size - 4)[0]
                if sec < 0:
                    break
        fat = []
        for s in difat:
            if s < 0:
                continue
            f.seek(512 + s * sec_size)
            blk = f.read(sec_size)
            if len(blk) < sec_size:
                break
            fat.extend(struct.unpack_from("<%di" % (sec_size // 4), blk))

        def chain(start):
            out = bytearray()
            s = start
            guard = len(fat) + 2
            while 0 <= s < len(fat) and guard > 0:
                guard -= 1
                f.seek(512 + s * sec_size)
                blk = f.read(sec_size)
                if not blk:
                    break
                out += blk
                nxt = fat[s]
                if nxt < 0:
                    break
                s = nxt
            return bytes(out)

        raw_dir = chain(first_dir)
        want = stream_name.lower()
        found = None
        for i in range(0, len(raw_dir) - 128 + 1, 128):
            e = raw_dir[i:i + 128]
            nlen = struct.unpack_from("<H", e, 64)[0]
            if nlen < 4 or nlen > 66:
                continue
            nm = e[:nlen - 2].decode("utf-16le", errors="ignore")
            if nm.lower() == want:
                found = (struct.unpack_from("<i", e, 116)[0],
                         struct.unpack_from("<I", e, 120)[0])
                break
        if found is None:
            raise ValueError("внутри нет потока %s" % stream_name)
        start, size = found
        if size < cutoff:
            raise ValueError("поток слишком мал — сохрани как .docx")
        return chain(start)[:size]


def read_doc_paragraphs(path):
    """Старый бинарный .doc (OLE): best-effort извлечение русского текста, только stdlib.
    Мусор binary отсекается фильтром (доля кириллицы + CJK/PUA); итог виден в scan."""
    try:
        data = read_ole_stream(path, "WordDocument")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError("не читается как .doc (%s) — сохрани как .docx" % e)
    text = data.decode("utf-16le", errors="ignore")
    # Поля Word: \x13 HYPERLINK "url" \o "tip" \x14ТЕКСТ\x15 — код выкидываем, текст оставляем.
    # Иначе в лекцию едет мусор вида HYPERLINK "http://vedadev.ru/..." (файл 031 и др.)
    text = re.sub(r"\x13\s*HYPERLINK\s+\"[^\"]*\"(?:\s*\\[a-zA-Z]\s*(?:\"[^\"]*\")?)*\s*\x14",
                  "", text)
    out = []
    foreign_re = re.compile("[\u0B80-\u0BFF\u0600-\u06FF\u0590-\u05FF\u0E00-\u0E7F\uAC00-\uD7AF]")
    for raw in re.split(r"[\r\n]+", text):
        line = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
        line = re.sub(r"\s+", " ", line).strip()
        # след вырезанных полей: «слово — — перевод» -> «слово — перевод»
        line = re.sub(r"—\s*—", "—", line)
        if len(line) < 2:
            continue
        cyr = len(re.findall(r"[А-Яа-яЁё]", line))
        # мусор binary: кириллицы мало относительно длины + CJK/PUA-символы
        if cyr < 3 or cyr / len(line) < 0.2:
            continue
        if len(re.findall(r"[ⴀ-鿿-]", line)) > 2:
            continue
        # колонтитул с бинарным мусором (тамил/арабский + хвост кириллицы): чужих письмен
        # много, кириллицы меньше 60% — выкидываем (деванагари не трогаем: вдруг шлока)
        if len(foreign_re.findall(line)) > 2 and cyr / len(line) < 0.6:
            continue
        out.append(("Normal", line))
    if len(out) < 3:
        raise ValueError("не смог извлечь текст из .doc — сохрани как .docx")
    return out


def read_docx_paragraphs(path):
    """[(style, text)]; style = 'Heading1'..'Heading4' / 'Normal'. Без внешних зависимостей."""
    if path.lower().endswith(".doc") and not path.lower().endswith(".docx"):
        try:
            return read_doc_paragraphs(path)
        except ValueError as e:
            # .docx с неверным расширением .doc (встречается в архиве) — пробуем как zip
            if "не OLE" not in str(e):
                raise
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        raise ValueError("не открывается как .docx (старый .doc сохрани как .docx): %s" % e)
    try:
        xml = z.read("word/document.xml")
    except KeyError:
        raise ValueError("внутри нет word/document.xml — это не .docx")
    finally:
        z.close()
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    root = ET.fromstring(xml)
    out = []
    for p in root.findall(".//w:p", ns):
        style = "Normal"
        ps = p.find("w:pPr/w:pStyle", ns)
        if ps is not None:
            v = ps.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", "")
            if v.lower().startswith("heading"):
                style = "Heading" + v[len("heading"):]
        texts = []
        for t in p.findall(".//w:t", ns):
            texts.append(t.text or "")
        # разрывы строк внутри абзаца
        for br in p.findall(".//w:br", ns):
            texts.append("\n")
        text = "".join(texts).replace("\r", "").strip()
        # пустой абзац — граница (храним как пустой Normal для деления на абзацы)
        if not text:
            out.append(("Normal", ""))
            continue
        out.append((style, text))
    return out


def parse_docx(path, defaults=None):
    """Полный разбор файла -> dict(book, songs, chapters, lectures). Исключения — наружу."""
    defaults = defaults or {}
    paras = read_docx_paragraphs(path)
    book_title = defaults.get("title")
    book_type = (defaults.get("type") or "").upper()
    book_author = defaults.get("author", "Шьямакунда прабху")
    songs = {}       # song_no -> songname
    chapters = {}    # (song, num) -> title
    lectures = []    # (song, ch, num, heading, ref, date, body_paras)
    cur_song = None
    cur_ch = None
    cur_lec = None  # [song, ch, num, heading, ref, date, paras]

    def flush_lec():
        nonlocal cur_lec
        if cur_lec is not None:
            lectures.append(tuple(cur_lec[:6]) + (cur_lec[6],))
            cur_lec = None

    def ensure_chapter(song, ch):
        if (song, ch) not in chapters:
            chapters[(song, ch)] = "Глава %s" % ch

    for style, text in paras:
        if not text:
            if cur_lec is not None:
                cur_lec[6].append("")  # граница абзаца
            continue
        is_h1 = style == "Heading1" or RE_BOOK.match(text)
        is_h2 = style == "Heading2" or RE_SONG.match(text)
        is_h3 = style == "Heading3" or RE_CH.match(text)
        is_h4 = style == "Heading4" or RE_LEC.match(text)
        if is_h1:
            m = RE_BOOK.match(text)
            raw = m.group(1) if m else text
            title, meta = split_title_meta(raw)
            if title:
                book_title = title
            if meta.get("TYPE"):
                book_type = meta["TYPE"].upper()
            if meta.get("AUTHOR"):
                book_author = meta["AUTHOR"]
            continue
        if is_h2:
            m = RE_SONG.match(text)
            raw = m.group(1) if m else text
            title, meta = split_title_meta(raw)
            no = meta.get("SONG")
            if no is None:
                no = str(max([int(k) for k in songs.keys()], default=0) + 1)
            no = str(no)
            songs[no] = title or ("Раздел %s" % no)
            cur_song = no
            cur_ch = None
            flush_lec()
            continue
        if is_h3:
            m = RE_CH.match(text)
            if m:
                num, rest = m.group(1), m.group(2).strip()
            else:
                num, rest = str(len(chapters) + 1), text
            if cur_song is None:
                cur_song = "1"
                songs.setdefault("1", DEFAULT_SONGS.get(book_type, [(1, "")])[0][1]
                                 if book_type in DEFAULT_SONGS else "Раздел 1")
            cur_ch = str(num)
            chapters[(cur_song, cur_ch)] = rest or ("Глава %s" % cur_ch)
            flush_lec()
            continue
        if is_h4:
            m = RE_LEC.match(text)
            if m:
                num, rest = m.group(1), m.group(2).strip()
            else:
                num, rest = str(len(lectures) + 1).zfill(3), text
            heading, meta = split_title_meta(rest)
            if cur_song is None:
                cur_song = "1"
                songs.setdefault("1", "Раздел 1")
            if cur_ch is None:
                cur_ch = "1"
                ensure_chapter(cur_song, cur_ch)
            flush_lec()
            cur_lec = [cur_song, cur_ch, str(num), heading or ("Лекция %s" % num),
                       meta.get("REF", ""), meta.get("DATE", ""), []]
            continue
        # обычный текст тела
        if cur_lec is None:
            # текст до первой ЛЕКЦИИ: заводим лекцию-автозаглушку, чтобы ничего не потерять
            if cur_song is None:
                cur_song = "1"
                songs.setdefault("1", "Раздел 1")
            if cur_ch is None:
                cur_ch = "1"
                ensure_chapter(cur_song, cur_ch)
            n = str(len([l for l in lectures if l[0] == cur_song and l[1] == cur_ch]) + 1).zfill(3)
            cur_lec = [cur_song, cur_ch, n, "", "", "", []]
            if len(lectures) == 0 and not book_title:
                pass
        # склейка: новый абзац
        if cur_lec[6] and cur_lec[6][-1] != "":
            cur_lec[6].append(text)
        else:
            if cur_lec[6] and cur_lec[6][-1] == "":
                cur_lec[6][-1] = text
            else:
                cur_lec[6].append(text)
    flush_lec()

    if not book_title:
        book_title = os.path.splitext(os.path.basename(path))[0]
    if not book_type:
        book_type = "SCC"
    book_type = book_type.upper()
    if not songs:
        for no, name in DEFAULT_SONGS.get(book_type, [(1, "Раздел 1")]):
            songs.setdefault(str(no), name)
        if len(songs) == 1:
            only = list(songs.keys())[0]
            cur_song = only
    # принудительные значения (GUI: правки пользователя важнее маркеров документа)
    if defaults.get("force_title"):
        book_title = defaults["force_title"]
    if defaults.get("force_type"):
        book_type = str(defaults["force_type"]).upper()
    if defaults.get("force_author"):
        book_author = defaults["force_author"]
    # пустые главы без лекций — оставляем (плитка с 0 лекций видна как диагностика),
    # что чистить — решает флаг спеки drop_empty_chapters
    return {"title": book_title, "type": book_type, "author": book_author,
            "songs": songs, "chapters": chapters, "lectures": lectures, "src": path}


def paras_to_html(paras):
    """Абзацы -> HTML для texts.transl2 (экранируем, пустые строки схлопываем)."""
    cleaned = []
    for p in paras:
        p = re.sub(r"\s+", " ", p).strip()
        if p:
            cleaned.append("<p>%s</p>" % html.escape(p))
    return "\n".join(cleaned)


def read_cover_file(path):
    """Байты обложки (JPEG) + пометка. JPEG/PNG едут как есть; остальное (WEBP/HEIC/BMP)
    конвертируется через Pillow (если стоит) с ужатием до 1024px. Приложение ест только JPEG/PNG."""
    if not os.path.exists(path):
        raise ValueError("нет файла %s" % path)
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 100 or len(data) > 12 * 1024 * 1024:
        raise ValueError("подозрительный размер %d" % len(data))
    if len(data) > 2 and data[0] == 0xFF and data[1] == 0xD8:
        return data, "JPEG"
    if len(data) > 4 and data[:4] == b"\x89PNG":
        return data, "PNG"
    kind = "WEBP" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else "не-JPEG/PNG"
    try:
        from PIL import Image
        import io
    except ImportError:
        raise ValueError("%s, а Pillow нет (py -m pip install pillow) — дай JPEG" % kind)
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((1024, 1024))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        return buf.getvalue(), "%s->JPEG" % kind
    except Exception as e:
        raise ValueError("не сконвертировать в JPEG (%s)" % e)


def build_db(spec_path, out_path, force=False):
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    if os.path.exists(out_path) and not force:
        return "OUT уже есть: %s (добавь --force)" % out_path
    if os.path.exists(out_path):
        os.remove(out_path)
    defaults = spec.get("defaults", {})
    drop_empty_ch = spec.get("drop_empty_chapters", False)
    base = os.path.dirname(os.path.abspath(spec_path))

    books = []
    for fspec in spec.get("files", []):
        docx = fspec["docx"]
        if not os.path.isabs(docx):
            docx = os.path.join(base, docx)
        if not os.path.exists(docx):
            return "Нет файла: %s" % docx
        d = dict(defaults)
        d.update({k: v for k, v in fspec.items() if k != "docx"})
        b = parse_docx(docx, d)
        # обложка — относительный путь считаем от спеки
        cov = fspec.get("cover_file") or defaults.get("cover_file")
        if cov:
            if not os.path.isabs(cov):
                cov = os.path.join(base, cov)
            b["cover_file"] = cov
        books.append(b)

    dst = sqlite3.connect(out_path)
    report = []
    try:
        # Схема — минимальный набор исходного формата, который понимает LibraryDbImporter.
        dst.execute("CREATE TABLE books(_id INTEGER PRIMARY KEY, sort INTEGER, author TEXT,"
                    " title TEXT, desc TEXT, type TEXT, levels INTEGER, hasSanskrit INTEGER,"
                    " hasPurport INTEGER, hasColorStructure INTEGER, isSongBook INTEGER,"
                    " text_size INTEGER, purport_size INTEGER, text_begin_raw TEXT,"
                    " text_end_raw TEXT, web_abbrev TEXT, compare_code TEXT, issue TEXT, isSimple INTEGER)")
        dst.execute("CREATE TABLE chapters(_id INTEGER PRIMARY KEY, book_id INTEGER,"
                    " song TEXT, number INTEGER, title TEXT)")
        dst.execute("CREATE TABLE songs(book_id INTEGER, song TEXT, songname TEXT, sort INTEGER)")
        dst.execute("CREATE TABLE textnums(_id INTEGER PRIMARY KEY, book_id INTEGER, song TEXT,"
                    " ch_no TEXT, txt_no TEXT, preview TEXT, url TEXT)")
        dst.execute("CREATE TABLE texts(_id INTEGER PRIMARY KEY, sanskrit TEXT, translit TEXT,"
                    " translit_srch TEXT, transl1 TEXT, transl2 TEXT, comment TEXT)")
        # пустая image_nums: старые версии приложения рано выходили без неё и не доходили до covers
        dst.execute("CREATE TABLE IF NOT EXISTS image_nums(bid INTEGER, sid TEXT, cid TEXT,"
                    " tnum TEXT, text_id INTEGER, image_id TEXT, type TEXT, desc TEXT, kind TEXT)")
        nb = nch = ntn = 0
        for b in books:
            nb += 1
            dst.execute("INSERT INTO books(_id, author, title, type) VALUES (?,?,?,?)",
                        (nb, b["author"], b["title"], b["type"]))
            for song_no in sorted(b["songs"], key=lambda s: (int(s) if s.isdigit() else 999, s)):
                dst.execute("INSERT INTO songs(book_id, song, songname) VALUES (?,?,?)",
                            (nb, str(song_no), b["songs"][song_no]))
            # главы: сортировка song,num как числа где возможно
            def ch_key(k):
                s, n = k
                try:
                    return (int(s), int(n))
                except Exception:
                    return (999, 999)
            kept_ch = 0
            for (song, num) in sorted(b["chapters"], key=ch_key):
                has_lec = any(l[0] == song and l[1] == num for l in b["lectures"])
                if drop_empty_ch and not has_lec:
                    continue
                nch += 1
                try:
                    inum = int(num)
                except Exception:
                    inum = 0
                dst.execute("INSERT INTO chapters(_id, book_id, song, number, title)"
                            " VALUES (?,?,?,?,?)", (nch, nb, str(song), inum, b["chapters"][(song, num)]))
                kept_ch += 1
            for (song, ch, num, heading, ref, date, paras) in b["lectures"]:
                ntn += 1
                preview = heading or ("Лекция %s" % num)
                body = paras_to_html(paras)
                meta_bits = [x for x in
                             (("Привязка: %s" % ref) if ref else "",
                              ("Дата: %s" % date) if date else "") if x]
                comment = ("<p><i>%s</i></p>" % html.escape(" · ".join(meta_bits))) if meta_bits else None
                # transl1 = привязка к стиху (идет в FTS/synonyms -> поиск "ЧЧ 5.12" находит лекцию)
                dst.execute("INSERT INTO textnums(_id, book_id, song, ch_no, txt_no, preview)"
                            " VALUES (?,?,?,?,?,?)", (ntn, nb, str(song), str(ch), str(num), preview[:500]))
                dst.execute("INSERT INTO texts(_id, translit, transl1, transl2, comment)"
                            " VALUES (?,?,?,?,?)",
                            (ntn, preview[:2000], (ref or None), body[:30000], comment))
            report.append("Книга '%s' [%s]: разделов %d, глав %d, лекций %d"
                          % (b["title"][:45], b["type"], len(b["songs"]), kept_ch,
                             len(b["lectures"])))
            # обложка: JPEG/PNG файлом -> images + covers (как у recompose).
            # Приложение покажет её на карточке книги (Book.coverPath).
            cov = b.get("cover_file")
            if cov:
                try:
                    cbytes, fmt = read_cover_file(cov)
                    ciid = "COVER_" + re.sub(r"[^A-Za-z0-9_-]", "_", b["type"])[:20]
                    dst.execute("CREATE TABLE IF NOT EXISTS images(image_id TEXT PRIMARY KEY, content BLOB)")
                    dst.execute("CREATE TABLE IF NOT EXISTS covers(book_id INTEGER, image_id TEXT)")
                    dst.execute("INSERT OR IGNORE INTO images(image_id, content) VALUES (?,?)",
                                (ciid, cbytes))
                    dst.execute("INSERT INTO covers(book_id, image_id) VALUES (?,?)", (nb, ciid))
                    report.append("  обложка %s: %s (%s, %d КБ)" % (b["type"], os.path.basename(cov),
                                                                    fmt, len(cbytes) // 1024))
                except Exception as e:
                    report.append("  обложка %s: ОШИБКА %s" % (b["type"], e))
        dst.commit()
        try:
            report.append("integrity: %s" % dst.execute("PRAGMA integrity_check").fetchone()[0])
        except Exception as e:
            report.append("integrity: %s" % e)
        result = "\n".join(report)
    finally:
        dst.close()
        if not report or (out_path and not os.path.exists(out_path)):
            pass
    return result


def cmd_inspect(path):
    try:
        b = parse_docx(path, {})
    except Exception as e:
        return "ОШИБКА: %s" % e
    out = ["Файл: %s" % path,
           "Книга: %s [%s] — %s" % (b["title"], b["type"], b["author"]),
           "Разделы (%d): %s" % (len(b["songs"]),
                                 ", ".join("%s=%s" % (k, v) for k, v in sorted(b["songs"].items()))),
           "Глав: %d, лекций: %d" % (len(b["chapters"]), len(b["lectures"])), ""]
    for (s, c, n, h, ref, date, paras) in b["lectures"][:30]:
        words = sum(len(p.split()) for p in paras)
        out.append("  разд.%s гл.%s лекция %s: %s%s%s (%d слов)" % (
            s, c, n, h[:60], (" | " + ref) if ref else "", (" | " + date) if date else "", words))
    if len(b["lectures"]) > 30:
        out.append("  ... ещё %d" % (len(b["lectures"]) - 30))
    # диагностика: лекции без тела, главы без лекций
    empty = [n for (s, c, n, h, r, d, p) in b["lectures"] if not any(x.strip() for x in p)]
    if empty:
        out.append("ПУСТЫЕ лекции (нет тела): %s" % ", ".join(empty[:10]))
    nolec = [(s, c) for (s, c) in b["chapters"]
             if not any(l[0] == s and l[1] == c for l in b["lectures"])]
    if nolec:
        out.append("Главы без лекций: %s" % ", ".join("%s/%s" % x for x in nolec[:10]))
    return "\n".join(out)


# ------------------------------------------------- режим «папка = одна книга» ---
# Реальные файлы: ОДИН .docx = ОДНА лекция, иерархия — в имени файла:
#   001 (2.3.1-36)            -> песнь 2 (Мадхья-лила), глава 3, тексты 1-36
#   338 (1.6.82-120) Величие Адвайты Ачарьи -> песнь 1 (Ади-лила), глава 6, тексты 82-120
# Сортировка — по (песнь, глава, первый текст), НЕ по номеру файла.
WORK_SHORT = {"SCC": "ЧЧ", "SSB": "ШБ", "SBG": "БГ", "SBRS": "БРС"}
WORK_SONG_NAMES = {
    "SCC": {"1": "Ади-лила", "2": "Мадхья-лила", "3": "Антья-лила"},
    "SSB": {},
    "SBG": {"1": "Бхагавад-гита"},
    "SBRS": {"1": "Восточный", "2": "Южный", "3": "Западный", "4": "Северный"},
}
#: Полный ростер глав (волн) — создаются все, даже пустые (под будущие лекции).
#: Без ростера главы заводятся только по факту лекций.
CHAPTER_ROSTER = {
    "SBRS": {
        ("1", "1"): "Саманья бхакти", ("1", "2"): "Садхана бхакти",
        ("1", "3"): "Бхава бхакти", ("1", "4"): "Према бхакти",
        ("2", "1"): "Вибхава", ("2", "2"): "Анубхава",
        ("2", "3"): "Саттвика бхава", ("2", "4"): "Вьябхичари бхава",
        ("2", "5"): "Стхаи бхава",
        ("3", "1"): "Шанта раса", ("3", "2"): "Прити раса",
        ("3", "3"): "Преё раса", ("3", "4"): "Ватсалья раса",
        ("3", "5"): "Мадхурья раса",
        ("4", "1"): "Хасья раса", ("4", "2"): "Адбхута раса",
        ("4", "3"): "Вира раса", ("4", "4"): "Каруна раса",
        ("4", "5"): "Раудра раса", ("4", "6"): "Бхайанака раса",
        ("4", "7"): "Бибхатса раса",
        ("4", "8"): "Совместимые и несовместимые расы",
        ("4", "9"): "Расабхаса",
    },
}
#: файлы без привязки в имени едут в этот раздел (songname «Разное» — подпись группы)
MISC_SONG = "99"
#: кросс-главный диапазон: 229 (3.4206-3.5.20) = песнь 3, гл.4 ст.206 — гл.5 ст.20
RE_FNAME_XCH = re.compile(
    r"^\s*(.*?)\(\s*(\d+)\s*\.\s*(\d)(\d{1,3})\s*[–—\-]\s*"
    r"(?:(\d+)\s*\.\s*)?(\d+)\s*\.\s*(\d+)\s*\)?\s*(.*)$")
#: обычный: 338 (1.6.82-120) Title / ОЯ (2.11.196-211 / 4236 079 (2.14.90-141
#: (скобка может быть не закрыта, префикс — любым)
RE_FNAME = re.compile(
    r"^\s*(.*?)\(\s*(\d+)\s*\.\s*(\d+)\s*\.\s*([^)]+)\)?\s*(.*)$")
RE_LEADNUM = re.compile(r"^\s*(\d+)")
#: главы больше сотни не бывает — такое «ch» признак слипшейся записи без точки
MAX_CHAPTER = 60


def leading_num(s):
    m = RE_LEADNUM.match(s or "")
    return m.group(1) if m else ""


def stem_num(stem):
    """Номер из имени, когда он не ведущий ("БРС 025" -> 025, "К 001 ..." -> 001).
    Имена вида "2.5.1-118 ..." (голая ссылка на стих, не номер лекции) пропускаем."""
    if leading_num(stem):
        return leading_num(stem)
    if re.match(r"^\s*\d+\s*\.\s*\d+", stem or ""):
        return ""
    m = re.search(r"(\d+)", stem or "")
    return m.group(1) if m else ""


def normalize_txts(s):
    s = re.sub(r"\s+", " ", (s or "").strip()).strip(" .,;")
    s = re.sub(r"\s*[–—]\s*", "-", s)
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    return s.strip(" .,;")


def parse_lecture_filename(basename):
    """Имя файла -> dict(num, song, ch, txts, title) или None (нет привязки).

    Терпит: незакрытую скобку, любой префикс (ОЯ, 4236 079),
    диапазоны через запятую (1-74, 82-115), кросс-главы (3.4206-3.5.20).
    """
    name = basename
    low = name.lower()
    if low.endswith(".docx"):
        name = name[:-5]
    elif low.endswith(".doc"):
        name = name[:-4]
    stem = name.strip()
    m = RE_FNAME_XCH.match(stem)
    if m:
        prefix, song, c1, t1, _s2, c2, t2, title = m.groups()
        # защита от ложного срабатывания на обычных диапазонах
        if int(c2) <= MAX_CHAPTER and int(t1) >= 1:
            return {"num": leading_num(prefix), "song": str(int(song)), "ch": str(int(c1)),
                    "txts": normalize_txts("%s-%s.%s" % (t1, c2, t2)),
                    "title": title.strip()}
    m = RE_FNAME.match(stem)
    if not m:
        return None
    prefix, song, ch, raw, title = m.groups()
    if int(ch) > MAX_CHAPTER:
        return None
    return {"num": leading_num(prefix), "song": str(int(song)), "ch": str(int(ch)),
            "txts": normalize_txts(raw), "title": title.strip()}


def txt_start(txts):
    try:
        return int(re.split(r"[-–—,]", txts or "")[0].strip() or 0)
    except Exception:
        return 0


#: Шапка привязки в теле лекции: "6 (1.1.2-3)", "1 (1.1.1. Мангала текст)".
#: Спасает файлы, в чьих именах номеров нет ("БРС 001", "БРС 209(2.вишада...)").
RE_BODY_BIND = re.compile(
    r"\(\s*(\d+)\s*\.\s*(\d+)\s*\.\s*(\d+(?:\s*[-–—]\s*\d+)?)\s*[.)]")

#: Слова титулов произведений: ведущий абзац только из них — мусор шапки,
#: а не текст (плюс декоративные шрифты-символы). Такое выкидываем целиком.
TITLE_WORDS = frozenset(
    "шри шрила sri чайтанья чайтанйа чаритамрита бхакти расамрита расамрта синдху "
    "бхагавад гита бхагаватам шримад рупа госвами лекции шьямакунда шйамакунда "
    "шьямакунды шйамакунды прабху".split())
#: Письменности, которым в наших текстах делать нечего (символьные шрифты DOC):
#: лао, армянский, эфиопский, гуджарати, гурмукхи, каннада, канадские слоговые,
#: радикалы Канси/CJK, спецсимволы, мусорные юникод-хвосты
RE_DECOR = re.compile(
    "[\u0e80-\u0eff\u0530-\u058f\u1200-\u137f\u0a80-\u0aff\u0a00-\u0a7f"
    "\u0c80-\u0cff\u1400-\u167f\u2f00-\u2fdf\u2e80-\u2eff\uffff\u26a5]")


def strip_decor_headers(paras):
    """Убрать ведущие титульные абзацы: пустые + символьный мусор + голый титул
    («SSS… Чайтанья Чаритамрита», «Бхакти расамрита синдху»). Возвращает новый список."""
    out = list(paras)
    while out:
        t = (out[0] or "").strip()
        if not t:
            out.pop(0)
            continue
        if RE_DECOR.search(t):
            out.pop(0)
            continue
        words = re.findall(r"[А-Яа-яЁёA-Za-z]+", t.lower())
        if words and all(w in TITLE_WORDS for w in words):
            out.pop(0)
            continue
        break
    return out


def parse_body_binding(paras):
    """Привязка из тела лекции. Ступень 1 — шапка: номер + (песнь.глава.стихи[-]).
    Ступень 2 — первая inline-ссылка вида «БРС 2.1.313:» / «Второй текст 1.1.2»
    в первых 30 абзацах (тема раскрывает именно этот стих; чисто тематические
    без ссылок честно едут в «Разное»).
    Возвращает (song, ch, txts, num, title) или None."""
    body = [p for p in (paras or []) if (p or "").strip()]
    for p in body[:12]:
        t = p.strip()
        m = RE_BODY_BIND.search(t)
        if not m:
            continue
        song, ch, txts = m.group(1), m.group(2), normalize_txts(m.group(3))
        try:
            if int(ch) > MAX_CHAPTER or int(ch) < 1:
                continue
        except Exception:
            continue
        rest = t[m.end():].strip(" \t.)—-–")
        num = leading_num(t[:m.start()])
        return str(int(song)), str(int(ch)), txts, num, rest
    for p in body[:30]:
        t = p.strip()
        m = (re.search(r"БРС\s*(\d+)\s*\.\s*(\d+)\s*\.\s*(\d+)", t) or
             re.search(r"(?:текст[а-я]*|стих[а-я]*)\s+(\d+)\s*\.\s*(\d+)\s*\.\s*(\d+)",
                       t, re.I))
        if not m:
            continue
        song, ch, txt = m.group(1), m.group(2), m.group(3)
        try:
            if int(ch) > MAX_CHAPTER or int(ch) < 1 or int(song) < 1:
                continue
        except Exception:
            continue
        return str(int(song)), str(int(ch)), normalize_txts(txt), "", ""
    return None


def build_display(num, txts, name, intro=False):
    """Название лекции для списка (как у лекций Прабхупады — только имя, без тела):
    029 (2.8.134-149) Сварупа Кришны -> «Лекция №29 по стихам 134-149 — Сварупа Кришны»;
    028 (2.8.117-133) -> «Лекция №28 по стихам 117-133»."""
    if intro:
        return "Введение"
    n = str(int(num)) if (num or "").isdigit() else (num or "")
    if txts:
        head = ("Лекция №%s по стихам %s" % (n, txts)) if n else ("По стихам %s" % txts)
    else:
        head = ("Лекция №%s" % n) if n else ""
    if name:
        return (head + " — " + name) if head else name
    return head


def parse_single_lecture(path, book_type):
    """Один файл = одна лекция. Возвращает dict(song, ch, txts, name, title, ref, paras, catnum)."""
    base = os.path.basename(path)
    info = parse_lecture_filename(base)
    paras = [t for _, t in read_docx_paragraphs(path)]
    # Мусорные титулы DOC-шрифтов в начале (SSS… + название) — не текст лекции
    paras = strip_decor_headers(paras)
    body = [p for p in paras if p.strip()]
    if not body:
        raise ValueError("пустой документ (нет текста)")
    stem = os.path.splitext(base)[0]
    # 000 <Произведение> без скобок (000 Чайтанья Чаритамрита) — вводная лекция;
    # раздел/глава назначаются позже в assign_intro_song (первый настоящий раздел, глава «0»)
    intro = info is None and leading_num(stem) == "000"
    if intro:
        song, ch, txts, name, num = "0", "0", "", "", "000"
    elif info is None:
        # Имя без номеров ("БРС 001", "БРС 209(2.вишада...)"): привязку ищем
        # в шапке тела ("6 (1.1.2-3)", "1 (1.1.1. Мангала текст)"). Имя файла
        # в привязке не участвует и тело не трогаем, кроме титульного мусора.
        bind = parse_body_binding(body)
        if bind is not None:
            song, ch, txts = bind[0], bind[1], bind[2]
            num = stem_num(stem) or bind[3]
            # имя: титул из шапки; иначе остаток имени после "КОД NNN"
            # ("БРС 209(2.вишада...)" -> тема из скобок); осмысленные имена без цифр не трогаем
            name = bind[4]
            if not name:
                mpre = re.match(r"^[A-Za-zА-Яа-яЁё]+\s*\d+\s*", stem)
                if mpre:
                    rest = stem[mpre.end():].strip(" \t-–—")
                    if rest.startswith("(") and rest.endswith(")"):
                        rest = rest[1:-1].strip()
                    name = rest
                else:
                    name = stem.strip()
        else:
            # имя — ТОЛЬКО из названия файла (остаток после номера); номер умеет
            # быть не ведущим ("БРС 025" -> 025) — иначе интерполяция его не видит
            song, ch, txts = MISC_SONG, "1", ""
            num = stem_num(stem)
            name = stem[len(num):].strip(" \t-–—") if num else stem.strip()
    else:
        song, ch, txts = info["song"], info["ch"], info["txts"]
        name, num = info["title"], info["num"]
    title = build_display(num, txts, name, intro) or stem
    # имя уже с готовой шапкой «Лекция №..» (ручная правка файла) — не оборачиваем второй раз
    if name and re.match(r"(?i)^\s*лекция\s*№", name):
        title = name.strip().replace(" - ", " — ")
    catnum = -1 if intro else (txt_start(txts) if txts else (int(num) if (num or "").isdigit() else 0))
    short = WORK_SHORT.get(book_type, book_type)
    if intro or not txts:
        ref = ""
    elif book_type == "SBG":
        ref = "%s %s.%s" % (short, ch, txts or "?")
    else:
        ref = "%s %s.%s.%s" % (short, song, ch, txts)
    return {"song": song, "ch": ch, "txts": txts, "name": name, "title": title,
            "num": num, "ref": ref, "paras": paras, "src": path, "catnum": catnum,
            "intro": intro, "unparsed": not txts and not intro}


def interpolate_misc(lectures):
    """Без привязки с числовым номером -> в (song, ch) ближайшей привязанной
    по номеру лекции (на стыке разделов — к ближайшей, при равенстве — к предыдущей).
    Стихам не приписываем (txts пустые) — только полка. Возвращает число устроенных."""
    def num_of(l):
        try:
            return int(l.get("num") or "")
        except Exception:
            return None

    bound = [(num_of(l), l["song"], l["ch"]) for l in lectures
             if l["song"] != MISC_SONG and num_of(l) is not None]
    if not bound:
        return 0
    n = 0
    for l in lectures:
        if l["song"] != MISC_SONG or l.get("intro"):
            continue
        me = num_of(l)
        if me is None:
            continue
        best = min(bound, key=lambda b: (abs(b[0] - me), b[0] > me, -b[0]))
        l["song"], l["ch"] = best[1], best[2]
        l["interp"] = True
        l["unparsed"] = False
        n += 1
    return n


def assign_intro_song(lectures):
    """Введение — главой «Введение» в ПЕРВОМ настоящем разделе (без лишней плитки):
    книга -> Ади-лила -> [Введение, Глава 1, ..] -> лекция. Без разделов — в «Разное»."""
    def skey(s):
        try:
            return int(s)
        except Exception:
            return 999
    real = sorted({l["song"] for l in lectures
                   if not l.get("intro") and l["song"] != MISC_SONG}, key=skey)
    first = real[0] if real else MISC_SONG
    for l in lectures:
        if l.get("intro"):
            l["song"], l["ch"] = first, "0"


def scan_lectures(paths, book_type):
    """Разбор списка файлов -> (lectures_sorted, errors). Сортировка по (песнь, глава, текст)."""
    lectures, errors = [], []
    for p in paths:
        try:
            lectures.append(parse_single_lecture(p, book_type))
        except Exception as e:
            errors.append((p, str(e)))
    def key(l):
        try:
            s = int(l["song"])
        except Exception:
            s = 999
        try:
            c = int(l["ch"])
        except Exception:
            c = 999
        n = txt_start(l["txts"]) if l["txts"] else l.get("catnum", 0)
        return (s, c, n, os.path.basename(l["src"]))
    lectures.sort(key=key)
    assign_intro_song(lectures)
    n_interp = interpolate_misc(lectures)
    # Введение должно быть первым и в общем порядке (глава «0» сортируется как -1)
    lectures.sort(key=lambda l: (0,) if l.get("intro") else (1,))
    return lectures, errors, n_interp


def build_lectures_book(spec_path, out_path, force=False):
    """Спека: {"book": {title, type, author, cover_file}, "files": [{"docx":...}, ...]}."""
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    if os.path.exists(out_path) and not force:
        return "OUT уже есть: %s (добавь --force)" % out_path
    if os.path.exists(out_path):
        os.remove(out_path)
    base = os.path.dirname(os.path.abspath(spec_path))
    bspec = spec.get("book", {})
    book_title = bspec.get("title") or "Лекции"
    book_type = str(bspec.get("type") or "SCC").upper()
    book_author = bspec.get("author") or "Шьямакунда прабху"
    paths = []
    force_titles = {}
    for fspec in spec.get("files", []):
        d = fspec["docx"]
        if not os.path.isabs(d):
            d = os.path.join(base, d)
        if not os.path.exists(d):
            return "Нет файла: %s" % d
        paths.append(d)
        if fspec.get("force_title"):
            force_titles[d] = fspec["force_title"]
    if not paths:
        return "Нет файлов: пустой список files"
    lectures, errors, n_interp = scan_lectures(paths, book_type)
    for l in lectures:
        if l["src"] in force_titles:
            # правка из GUI — это ИМЯ (часть после «Лекция №.. по стихам .. — »), каркас пересобираем;
            # уже готовая шапка «Лекция №..» используется как есть (защита от дабл-обёртки)
            nm = force_titles[l["src"]].strip()
            if re.match(r"(?i)^\s*лекция\s*№", nm):
                l["name"] = ""
                l["title"] = nm.replace(" - ", " — ")
            else:
                l["name"] = nm
                l["title"] = build_display(l["num"], l["txts"], l["name"], l["intro"]) or l["title"]
    if not lectures:
        return "Ни одна лекция не разобрана:\n" + "\n".join(
            "%s: %s" % (os.path.basename(p), e) for p, e in errors)

    dst = sqlite3.connect(out_path)
    report = []
    try:
        dst.execute("CREATE TABLE books(_id INTEGER PRIMARY KEY, sort INTEGER, author TEXT,"
                    " title TEXT, desc TEXT, type TEXT, levels INTEGER, hasSanskrit INTEGER,"
                    " hasPurport INTEGER, hasColorStructure INTEGER, isSongBook INTEGER,"
                    " text_size INTEGER, purport_size INTEGER, text_begin_raw TEXT,"
                    " text_end_raw TEXT, web_abbrev TEXT, compare_code TEXT, issue TEXT, isSimple INTEGER)")
        dst.execute("CREATE TABLE chapters(_id INTEGER PRIMARY KEY, book_id INTEGER,"
                    " song TEXT, number INTEGER, title TEXT)")
        dst.execute("CREATE TABLE songs(book_id INTEGER, song TEXT, songname TEXT, sort INTEGER)")
        dst.execute("CREATE TABLE textnums(_id INTEGER PRIMARY KEY, book_id INTEGER, song TEXT,"
                    " ch_no TEXT, txt_no TEXT, preview TEXT, url TEXT)")
        dst.execute("CREATE TABLE texts(_id INTEGER PRIMARY KEY, sanskrit TEXT, translit TEXT,"
                    " translit_srch TEXT, transl1 TEXT, transl2 TEXT, comment TEXT)")
        # пустая image_nums: старые версии приложения рано выходили без неё и не доходили до covers
        dst.execute("CREATE TABLE IF NOT EXISTS image_nums(bid INTEGER, sid TEXT, cid TEXT,"
                    " tnum TEXT, text_id INTEGER, image_id TEXT, type TEXT, desc TEXT, kind TEXT)")
        dst.execute("INSERT INTO books(_id, author, title, type) VALUES (1,?,?,?)",
                    (book_author, book_title, book_type))
        # разделы: имена лил/песен; «Разное» — для файлов без привязки.
        # У типов с ростером (SBRS) — все разделы/главы из ростера, даже пустые.
        roster = CHAPTER_ROSTER.get(book_type, {})
        song_names = dict(WORK_SONG_NAMES.get(book_type, {}))
        if book_type == "SSB":
            for i in range(1, 13):
                song_names.setdefault(str(i), "Песнь %d" % i)
        songs_present = sorted({l["song"] for l in lectures} |
                               ({s for (s, _c) in roster} if roster else set()),
                               key=lambda s: (int(s) if s.isdigit() else 999, s))
        for s in songs_present:
            name = song_names.get(s, "Разное" if s == MISC_SONG else "Раздел %s" % s)
            dst.execute("INSERT INTO songs(book_id, song, songname) VALUES (1,?,?)", (s, name))
        # главы по (song, ch)
        ch_pairs = sorted({(l["song"], l["ch"]) for l in lectures} | set(roster),
                          key=lambda k: ((int(k[0]) if k[0].isdigit() else 999),
                                         (int(k[1]) if k[1].isdigit() else 999)))
        ch_id = {}
        nch = 0
        for (s, c) in ch_pairs:
            nch += 1
            try:
                inum = int(c)
            except Exception:
                inum = 0
            if c == "0":
                title = "Введение"
            elif (s, c) in roster:
                title = roster[(s, c)]
            else:
                title = "Без привязки" if s == MISC_SONG else "Глава %s" % c
            dst.execute("INSERT INTO chapters(_id, book_id, song, number, title)"
                        " VALUES (?,?,?,?,?)", (nch, 1, s, inum, title))
            ch_id[(s, c)] = nch
        ntn = 0
        for i, l in enumerate(lectures):
            ntn += 1
            body = paras_to_html(l["paras"])
            comment = ("<p><i>Файл: %s</i></p>" % html.escape(os.path.basename(l["src"])))
            dst.execute("INSERT INTO textnums(_id, book_id, song, ch_no, txt_no, preview)"
                        " VALUES (?,?,?,?,?,?)",
                        (ntn, 1, l["song"], l["ch"],
                         l["txts"] or ("000" if l.get("intro") else
                                       (str(l.get("catnum")) if l.get("catnum") else ("%03d" % (i + 1)))),
                         l["title"][:500]))
            dst.execute("INSERT INTO texts(_id, translit, transl1, transl2, comment)"
                        " VALUES (?,?,?,?,?)",
                        # тело целиком (до 120К — столько же берёт приложение для лекций)
                        (ntn, l["title"][:2000], (l["ref"] or None), body[:120000], comment))
        cov = bspec.get("cover_file")
        if cov:
            if not os.path.isabs(cov):
                cov = os.path.join(base, cov)
            try:
                cbytes, fmt = read_cover_file(cov)
                ciid = "COVER_" + re.sub(r"[^A-Za-z0-9_-]", "_", book_type)[:20]
                dst.execute("CREATE TABLE IF NOT EXISTS images(image_id TEXT PRIMARY KEY, content BLOB)")
                dst.execute("CREATE TABLE IF NOT EXISTS covers(book_id INTEGER, image_id TEXT)")
                dst.execute("INSERT OR IGNORE INTO images(image_id, content) VALUES (?,?)",
                            (ciid, cbytes))
                dst.execute("INSERT INTO covers(book_id, image_id) VALUES (1,?)", (ciid,))
                report.append("обложка: %s (%s, %d КБ)" % (os.path.basename(cov), fmt, len(cbytes) // 1024))
            except Exception as e:
                report.append("обложка: ОШИБКА %s" % e)
        misc = sum(1 for l in lectures if l["unparsed"])
        n_inter = sum(1 for l in lectures if l.get("interp"))
        report.insert(0, "Книга '%s' [%s]: ОДНА книга, разделов %d, глав %d, лекций %d%s" % (
            book_title[:45], book_type, len(songs_present), len(ch_pairs), len(lectures),
            (" (без привязки: %d%s)" % (
                misc, ("; по номерам в главы: %d" % n_inter) if n_inter else ""))
            if (misc or n_inter) else ""))
        for p, e in errors:
            report.append("ОШИБКА файла %s: %s" % (os.path.basename(p), e))
        dst.commit()
        try:
            has_cov = dst.execute("SELECT 1 FROM sqlite_master WHERE name='covers'").fetchone()
            if has_cov:
                report.append("проверка: обложек в файле %d" %
                              dst.execute("SELECT COUNT(*) FROM covers").fetchone()[0])
            else:
                report.append("проверка: обложек в файле НЕТ (сборка без cover_file)")
        except Exception as e:
            report.append("проверка обложек: %s" % e)
        try:
            report.append("integrity: %s" % dst.execute("PRAGMA integrity_check").fetchone()[0])
        except Exception as e:
            report.append("integrity: %s" % e)
        return "\n".join(report)
    finally:
        dst.close()


def cmd_scan(d):
    """Папка/файл -> как лекции разложатся (песнь/глава/тексты), сортировка как в сборке."""
    if os.path.isdir(d):
        paths = [os.path.join(d, f) for f in sorted(os.listdir(d))
                 if f.lower().endswith((".docx", ".doc")) and not f.startswith("~")]
    else:
        paths = [d]
    lectures, errors, _ = scan_lectures(paths, "SCC")
    out = ["Файлов: %d, лекций: %d" % (len(paths), len(lectures)), ""]
    for l in lectures[:50]:
        words = sum(len(p.split()) for p in l["paras"] if p.strip())
        out.append("  %s.%s.%s | %s | %s (%d слов)" % (
            l["song"], l["ch"], l["txts"] or "?",
            l["title"][:55], os.path.basename(l["src"]), words))
    if len(lectures) > 50:
        out.append("  ... ещё %d" % (len(lectures) - 50))
    for p, e in errors:
        out.append("ОШИБКА %s: %s" % (os.path.basename(p), e))
    return "\n".join(out)


SPEC_EXAMPLE = """{
  "_comment": "py lectures_build.py build lectures.json lectures_clean.db --force. Папка = ОДНА книга, файл = ОДНА лекция",
  "out": "lectures_clean.db",
  "book": {"title": "Чайтанья Чаритамрита. Лекции", "type": "SCC",
           "author": "Шьямакунда прабху", "cover_file": "cover.jpg"},
  "files": [
    {"docx": "001 (2.3.1-36).docx"},
    {"docx": "338 (1.6.82-120) Величие Адвайты Ачарьи.docx"}
  ]
}
"""


def main(argv):
    if len(argv) < 3 or argv[1] not in ("inspect", "scan", "build", "spec"):
        print(__doc__)
        print(SPEC_EXAMPLE)
        return 1
    if argv[1] == "spec":
        print(SPEC_EXAMPLE)
        return 0
    if argv[1] == "inspect":
        print(cmd_inspect(argv[2]))
        return 0
    if argv[1] == "scan":
        print(cmd_scan(argv[2]))
        return 0
    if argv[1] == "build":
        force = "--force" in argv
        pos = [a for a in argv[2:] if not a.startswith("--")]
        if not pos:
            print("Нужно: build SPEC.json [OUT.db] [--force]")
            return 1
        spec_path = pos[0]
        if len(pos) > 1:
            out_path = pos[1]
        else:
            out_path = json.load(open(spec_path, encoding="utf-8")).get("out") or "lectures_clean.db"
        if not out_path:
            print("Нет out: укажи OUT.db или поле out в спеке")
            return 1
        # спека с ключом "book" = режим «папка = одна книга»; иначе старый режим «файл = книга»
        has_book = "book" in json.load(open(spec_path, encoding="utf-8"))
        print((build_lectures_book if has_book else build_db)(spec_path, out_path, force))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
