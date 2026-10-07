#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вкладка «AI-импорт» dbcomposer: llama-server + три инструмента.

1. «Разное → привязка»: файлы лекций без парсящегося имени (уходят в «Разное»)
   LLM привязывает к (песня, глава, стихи) — ревью-таблица, применение с
   переименованием файла (точечно, через parse_lecture_filename).
2. «Текст → книга»: сырой txt/md → структура (главы/стихи) ПОД УПРАВЛЕНИЕМ
   ПОЛЬЗОВАТЕЛЯ (markdown-уровни / свой regex / автошаблоны / не делить;
   стихи: абзац / номер в строке / не делить) + опциональная подсказка LLM
   (точные подстроки-заголовки, позиции ищутся кодом) → ревью-дерево →
   source-.db в схеме исходников → кнопка «Открыть в Сборке».
3. «Метаданные»: LLM предлагает правки title/author/type загруженных книг
   (пресеты или свободный запрос) → ревью с галочками → правит строки Сборки.

Контракты ответов LLM — строгий JSON (см. llama_client.chat_json).
"""
import json
import os
import queue
import re
import sqlite3
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import llama_client
import recompose

HERE = os.path.dirname(os.path.abspath(__file__))
LECTURES_DIR = os.path.join(os.path.dirname(HERE), "lectures")
if LECTURES_DIR not in sys.path:
    sys.path.insert(0, LECTURES_DIR)
import lectures_build

AI_VERSION = 2

#: тело книги в приложении режется по bodyCap (LibraryDbImporter):
#: SCC/SSB/SBG/SBRS -> 120000, GC -> 60000, всё прочее -> 8000
BIG_TYPES = ("SCC", "SSB", "SBG", "SBRS")
META_FIELDS = ("title", "author", "type")
META_PRESETS = {
    "title": "Нормализуй названия книг: единообразие регистра, кавычек и пробелов, "
             "правильные названия произведений (Шримад-Бхагаватам, Бхагавад-гита, "
             "Чайтанья-чаритамрита и т.п.). Не меняй смысл и не сокращай.",
    "author": "Нормализуй имена авторов: единообразное написание "
              "(например «Б. Р. Шридхар Свами», «А. К. Бхактиведанта Свами Прабхупада»).",
    "type": "Определи тип книги по названию и автору. Значение поля type обязано быть "
            "ровно одним из разрешённых типов списка.",
}
SYSTEM_JSON = ("Ты — часть конвейера dbcomposer (сборка библиотечных .db для Android-приложения). "
               "Отвечай СТРОГО одним JSON-объектом: без markdown, без ```json, "
               "без пояснений и текста вокруг.")

#: автошаблоны границ глав (режим «Автошаблоны», пользовательский regex — выше)
PRESET_CHAPTER_RES = (
    r"^(?:Глава|ГЛАВА|CHAPTER|Chapter)\s+(?P<chapter>\d{1,4}|[IVXLCDM]{1,8})\s*[.:—–-]?\s*(?P<title>.*)$",
    r"^(?:Раздел|РАЗДЕЛ|SECTION|Section)\s+(?P<chapter>\d{1,4})\s*[.:—–-]?\s*(?P<title>.*)$",
    r"^===\s*(?P<chapter>\d{1,4})\s*===$",
    r"^(?P<chapter>\d{1,3})\s*\.\s+(?P<title>\S.*)$",
    r"^(?P<chapter>[IVXLCDM]{1,8})\s*[.)]\s+(?P<title>\S.*)$",
)
#: граница стиха по номеру в строке (режим «Номер в строке»)
DEFAULT_VERSE_RE = r"^\s*(?P<verse>\d{1,4})\s*[.)]\s*(?P<rest>.*)$"
RE_ROMAN = re.compile(r"^[IVXLCDM]+$")

#: схема source-.db — ровно как в рабочих источниках (Syamakunda_CC.db):
#: этого достаточно и для dbcomposer, и для импортёра приложения
SOURCE_DDL = (
    "CREATE TABLE books(_id INTEGER PRIMARY KEY, sort INTEGER, author TEXT, title TEXT, "
    "desc TEXT, type TEXT, levels INTEGER, hasSanskrit INTEGER, hasPurport INTEGER, "
    "hasColorStructure INTEGER, isSongBook INTEGER, text_size INTEGER, purport_size INTEGER, "
    "text_begin_raw TEXT, text_end_raw TEXT, web_abbrev TEXT, compare_code TEXT, "
    "issue TEXT, isSimple INTEGER)",
    "CREATE TABLE chapters(_id INTEGER PRIMARY KEY, book_id INTEGER, song TEXT, "
    "number INTEGER, title TEXT)",
    "CREATE TABLE songs(book_id INTEGER, song TEXT, songname TEXT, sort INTEGER)",
    "CREATE TABLE textnums(_id INTEGER PRIMARY KEY, book_id INTEGER, song TEXT, "
    "ch_no TEXT, txt_no TEXT, preview TEXT, url TEXT)",
    "CREATE TABLE texts(_id INTEGER PRIMARY KEY, sanskrit TEXT, translit TEXT, "
    "translit_srch TEXT, transl1 TEXT, transl2 TEXT, comment TEXT)",
    "CREATE TABLE covers(book_id INTEGER, image_id TEXT)",
    "CREATE TABLE images(image_id TEXT PRIMARY KEY, content BLOB)",
    "CREATE TABLE image_nums(bid INTEGER, sid TEXT, cid TEXT, tnum TEXT, text_id INTEGER, "
    "image_id TEXT, type TEXT, desc TEXT, kind TEXT)",
)


# ============================================================ нарезка текста
def text_to_paragraphs(text):
    """Абзацы = блоки через пустую строку. Внутренние переводы строк сохраняем
    (режим «номер в строке» их разбирает)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for chunk in re.split(r"\n[ \t]*\n+", text):
        s = chunk.strip("\n").strip()
        if s:
            out.append(s)
    return out


def _roman_to_int(s):
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    try:
        total = prev = 0
        for ch in s.upper():
            v = vals[ch]
            total += v - prev if v > prev else v
            prev = v
        return total
    except Exception:
        return None


def _num(v):
    v = (v or "").strip()
    if RE_ROMAN.match(v):
        n = _roman_to_int(v)
        if n:
            return n
    try:
        return int(v)
    except ValueError:
        return None


def _first_line(p):
    return p.split("\n")[0].strip()


def split_chapters(paras, opts):
    """Абзацы -> главы [{'song','number','title','paras'}] + song_names {song: имя}.

    opts['ch_mode']: md | regex | preset | none | llm(заголовки из llm_headings)
    opts['md_section'] (0=нет) / opts['md_chapter'] — уровни #;
    opts['chapter_re'] — свой regex (группы chapter/song/title);
    opts['llm_headings'] — [{'heading': точная подстрока, 'number', 'song', 'title'}].
    """
    mode = opts.get("ch_mode", "none")
    song_names = {}
    preface = []

    if mode == "llm":
        heads = opts.get("llm_headings") or []
        bounds = []  # (idx параграфа, заголовок)
        search = 0
        for h in heads:
            needle = h.get("heading") or ""
            if not needle:
                continue
            found = None
            for i in range(search, len(paras)):
                if needle in paras[i]:
                    found = i
                    break
            if found is None:
                continue
            bounds.append((found, h))
            search = found + 1
        if not bounds:
            return [], {}, ["LLM-заголовки не найдены в тексте (подстроки не совпали)"], []
        chapters = []
        notes = []
        for k, (idx, h) in enumerate(bounds):
            end = bounds[k + 1][0] if k + 1 < len(bounds) else len(paras)
            head_para = paras[idx]
            rest = head_para.replace(h["heading"], "", 1).strip()
            body = ([rest] if rest else []) + list(paras[idx + 1:end])
            song = _num(str(h.get("song") or "1")) or 1
            number = _num(str(h.get("number") or "")) or (k + 1)
            title = (h.get("title") or h["heading"]).strip()
            sname = str(h.get("song_name") or "").strip()
            if sname and not song_names.get(str(song)):
                song_names[str(song)] = sname[:80]
            chapters.append({"song": str(song), "number": int(number),
                             "title": title, "paras": body})
        if bounds[0][0] > 0:
            preface = list(paras[:bounds[0][0]])
        if preface and opts.get("prelude_intro", True):
            chapters.insert(0, {"song": chapters[0]["song"], "number": 0,
                                "title": "Введение", "paras": list(preface)})
            notes.append("шапка до первого заголовка -> глава 0 «Введение»")
            preface = []
        # preface без «Введения» возвращается — build_structure заметит выброс
        return chapters, song_names, notes, preface

    # --- обычные режимы: ищем абзацы-заголовки ---
    chapter_re = None
    if mode == "regex":
        try:
            chapter_re = re.compile(opts.get("chapter_re") or "")
        except re.error as e:
            return [], {}, ["плохой regex глав: %s" % e], []
        if "chapter" not in chapter_re.groupindex:
            return [], {}, ["regex глав должен содержать группу (?P<chapter>…)"], []

    md_section = int(opts.get("md_section", 0) or 0)
    md_chapter = int(opts.get("md_chapter", 2) or 2)

    chapters = []
    notes = []
    cur = None
    song_i = 0
    ch_i = 0
    first_song = None  # первая песня создаётся при первом заголовке — song=1
    prelude_intro = opts.get("prelude_intro", True)

    def new_song(name=""):
        nonlocal song_i, ch_i
        song_i += 1
        ch_i = 0  # нумерация глав начинается заново в каждой песне/разделе
        if name:
            song_names[str(song_i)] = name
        return song_i

    def cur_song():
        nonlocal first_song
        if first_song is None:
            first_song = new_song()
        return first_song

    def new_chapter(song, number, title):
        nonlocal cur
        cur = {"song": str(song), "number": number, "title": title, "paras": []}
        chapters.append(cur)

    for p in paras:
        line = _first_line(p)
        rest = p.split("\n", 1)[1].strip() if "\n" in p else ""
        if mode == "none":
            if cur is None:
                new_chapter(song_i or cur_song(), 1, opts.get("book_title") or "Текст")
            cur["paras"].append(p)
            continue
        if mode == "md":
            m = re.match(r"^(#{1,6})\s+(.*)$", line)
            if m:
                level = len(m.group(1))
                if md_section and level == md_section:
                    first_song = new_song(m.group(2).strip())
                    if rest:
                        (cur["paras"] if cur else preface).append(rest)
                    continue
                if level == md_chapter:
                    ch_i += 1
                    new_chapter(song_i or cur_song(), ch_i,
                                m.group(2).strip() or "Глава %d" % ch_i)
                    if rest:
                        cur["paras"].append(rest)
                    continue
            if cur is None:
                preface.append(p)
            else:
                cur["paras"].append(p)
            continue
        # regex / preset
        m = None
        g = None
        n = None
        if mode == "regex":
            m = chapter_re.match(line)
            if m:
                g = m.groupdict()
                n = _num(g.get("chapter") or "")
                if n is None:
                    notes.append("не число в regex-заголовке: %r" % line[:60])
                    m = None
        elif mode == "preset":
            for rx in PRESET_CHAPTER_RES:
                m = re.match(rx, line)
                if not m:
                    continue
                g = m.groupdict()
                n = _num(g.get("chapter") or "")
                if n is None:
                    m = None
                    continue
                break
        if m is not None and n is not None:
            s = _num(g.get("song")) if (g or {}).get("song") else None
            if s is not None and s != song_i:
                # явный номер песни из regex — это и есть текущий song
                ch_i = 0
                song_i = s
                if first_song is None:
                    first_song = s
            ch_i += 1
            new_chapter(s if s is not None else (song_i or cur_song()), n,
                        ((g.get("title") or "").strip() or "Глава %d" % n))
            if rest:
                cur["paras"].append(rest)
            continue
        if cur is None:
            preface.append(p)
        else:
            cur["paras"].append(p)

    chapters = [c for c in chapters if c["paras"]]
    if not chapters:
        if mode in ("regex", "preset"):
            return [], {}, notes or ["заголовки глав не найдены — попробуй другой режим/regex"], []
        # заголовков не было вообще (md/none): весь текст — одна глава
        chapters = [{"song": str(cur_song()), "number": 1,
                     "title": opts.get("book_title") or "Текст",
                     "paras": list(preface)}]
        preface = []
    if preface and prelude_intro and chapters:
        chapters.insert(0, {"song": chapters[0]["song"], "number": 0,
                            "title": "Введение", "paras": list(preface)})
        preface = []
        notes.append("шапка до первого заголовка -> глава 0 «Введение»")
    return chapters, song_names, notes, preface


def split_verses(paras, opts):
    """Абзацы главы -> стихи [(txt_no, text)].
    v_mode: para (абзац = стих) | number (номер в строке) | none (глава целиком)."""
    mode = opts.get("v_mode", "para")
    join_wraps = opts.get("join_wraps", True)
    strip_md = opts.get("strip_md", True)

    def finish(s):
        s = s.strip()
        if not s:
            return ""
        if join_wraps:
            s = re.sub(r"(\w)-\n", r"\1", s)
            s = re.sub(r"\s*\n\s*", " ", s)
        if strip_md:
            s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
            s = re.sub(r"^\s{0,3}#{1,6}\s+", "", s, flags=re.M)
            s = re.sub(r"^\s*>\s?", "", s, flags=re.M)
            s = re.sub(r"[*_`~]{1,3}", "", s)
        return re.sub(r"[ \t]+", " ", s).strip()

    if mode == "none":
        return [("1", finish("\n\n".join(paras)))] if any(p.strip() for p in paras) else []
    if mode == "para":
        out = []
        for i, p in enumerate(paras, 1):
            body = finish(p)
            if body:
                out.append((str(i), body))
        return out
    # number
    try:
        rx = re.compile(opts.get("verse_re") or DEFAULT_VERSE_RE)
    except re.error as e:
        return [("@ERROR", "плохой regex стихов: %s" % e)]
    if "verse" not in rx.groupindex:
        return [("@ERROR", "regex стихов должен содержать группу (?P<verse>…)")]
    verses = {}
    order = []
    cur = "0"
    verses[cur] = []
    for line in "\n".join(paras).split("\n"):
        m = rx.match(line)
        if m:
            g = m.groupdict()
            no = (g.get("verse") or "").strip() or (g.get("rest") or "").strip()
            if not no:
                continue
            cur = no
            if cur not in verses:
                verses[cur] = []
                order.append(cur)
            rest = (g.get("rest") or "").strip()
            if rest:
                verses[cur].append(rest)
        else:
            if line.strip():
                verses[cur].append(line.strip())
    out = []
    for no in ["0"] + order:
        body = finish("\n".join(verses.get(no, [])))
        if body and (no != "0" or len(order) > 0):
            out.append((no, body))
    if not out and verses.get("0"):
        out = [("1", finish("\n".join(verses["0"])))]
    return out


def build_structure(text, opts, llm_result=None):
    """Вся нарезка -> {'chapters': [...], 'song_names': {}, 'notes': [], 'stats': {}}."""
    if llm_result is not None:
        opts = dict(opts, ch_mode="llm", llm_headings=(llm_result or {}).get("chapters") or [])
    paras = text_to_paragraphs(text)
    if not paras:
        return {"chapters": [], "song_names": {}, "notes": ["пустой текст"],
                "stats": {"chapters": 0, "verses": 0, "chars": 0}}
    chapters, song_names, notes, preface = split_chapters(paras, opts)
    notes = list(notes)
    if preface:
        notes.append("шапка до первого заголовка выброшена (включи «Введение»)")
    # повтор (song, number) в тексте — сливаем в одну главу, иначе в .db будет дубль
    merged, seen = [], {}
    for c in chapters:
        k = (c["song"], c["number"])
        if k in seen:
            seen[k]["paras"] += c["paras"]
            notes.append("повтор главы %s.%s в тексте — объединил" % k)
        else:
            seen[k] = c
            merged.append(c)
    chapters = merged
    nverses = 0
    nchars = 0
    for c in chapters:
        c["verses"] = split_verses(c["paras"], opts)
        nverses += len(c["verses"])
        nchars += sum(len(t) for _, t in c["verses"])
    return {"chapters": chapters, "song_names": song_names, "notes": notes,
            "stats": {"chapters": len(chapters), "verses": nverses, "chars": nchars}}


# ============================================================ source-.db
def _html(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def write_source_db(struct, meta, out_path):
    """Структура -> source-.db (схема источников dbcomposer). Возвращает счётчики."""
    if os.path.exists(out_path):
        os.remove(out_path)
    con = sqlite3.connect(out_path)
    try:
        for ddl in SOURCE_DDL:
            con.execute(ddl)
        con.execute(
            "INSERT INTO books(_id,author,title,type,hasSanskrit,hasPurport) "
            "VALUES (?,?,?,?,?,?)",
            (1, meta.get("author", ""), meta.get("title", ""), meta.get("type", ""),
             0, 1 if meta.get("with_purport") else 0))
        songs_done = set()
        for song, name in sorted(struct.get("song_names", {}).items(), key=lambda kv: int(kv[0])):
            if song not in songs_done:
                con.execute("INSERT INTO songs(book_id,song,songname,sort) VALUES (?,?,?,?)",
                            (1, str(song), name, int(song)))
                songs_done.add(song)
        nid = 0
        nch = ntn = 0
        for c in struct["chapters"]:
            con.execute("INSERT INTO chapters(book_id,song,number,title) VALUES (?,?,?,?)",
                        (1, c["song"], int(c["number"]), c["title"]))
            nch += 1
            seen = set()
            for txt_no, body in c["verses"]:
                if txt_no == "@ERROR":
                    raise ValueError(body)
                if (c["song"], c["number"], txt_no) in seen:
                    txt_no = "%s-2" % txt_no
                seen.add((c["song"], c["number"], txt_no))
                nid += 1
                plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
                preview = plain[:200]
                con.execute(
                    "INSERT INTO textnums(_id,book_id,song,ch_no,txt_no,preview) "
                    "VALUES (?,?,?,?,?,?)",
                    (nid, 1, c["song"], str(c["number"]), str(txt_no), preview))
                # абзацы — по пустой строке; одиночный перенос внутри абзаца
                # в HTML рендерится как пробел (стандартная свёртка пробелов)
                blocks = re.split(r"\n[ \t]*\n", body)
                html = "".join(
                    "<p>%s</p>" % _html(re.sub(r"\s*\n\s*", " ", b).strip())
                    for b in blocks if b.strip())
                con.execute(
                    "INSERT INTO texts(_id,sanskrit,translit,translit_srch,transl1,"
                    "transl2,comment) VALUES (?,?,?,?,?,?,?)",
                    (nid, "", "", "", "", html, ""))
                ntn += 1
        con.commit()
    finally:
        con.close()
    # мгновенная приёмка: то, что увидит «Сборка»
    recompose.inspect_data(out_path)
    return {"chapters": nch, "texts": ntn, "ids": nid}


# ============================================================ промпты
def _song_desc(book_type):
    names = dict(lectures_build.WORK_SONG_NAMES.get(book_type, {}))
    if names:
        return "song: " + ", ".join("%s=%s" % kv for kv in sorted(names.items()))
    if book_type == "SSB":
        return "song: номер песни Шримад-Бхагаватам 1..12"
    return "song: целое число, обычно 1"


def binding_messages(book_type, basename, paras):
    body = "\n".join(p.strip() for p in paras[:12] if p.strip())[:3500]
    return [
        {"role": "system", "content": SYSTEM_JSON},
        {"role": "user", "content":
         "Определи привязку лекции в книге.\n"
         "Тип книги: %s. Разделы: %s.\n"
         "Файл: %s\nНачало текста лекции:\n---\n%s\n---\n"
         "Верни JSON:\n"
         '{"song": <целое, раздел>,"ch": <целое, глава; 0 = введение>,'
         '"txts": "<стих или диапазон, напр. 1-36; пусто, если неизвестен>",'
         '"title": "<3-6 слов по теме лекции>",'
         '"confidence": "high|medium|low", "reason": "<одна строка>"}\n'
         "Санскрит и цитаты не выдумывай. Если привязка неясна — txts=\"\" "
         "и confidence=low." % (book_type, _song_desc(book_type), basename, body)},
    ]


def structure_messages(book_title, text):
    # 30000 симв. ~ до 20k токенов — влезает в контекст 32k даже под русским текстом
    body = text[:30000]
    if len(text) > len(body):
        body += "\n\n[...текст обрезан до 30000 символов...]"
    return [
        {"role": "system", "content": SYSTEM_JSON},
        {"role": "user", "content":
         "Найди в тексте границы ГЛАВ (и разделов, если есть).\n"
         "Название книги (подсказка): %s\n"
         "Верни JSON:\n"
         '{"book_title": "<название по тексту или подсказке>",'
         '"chapters": [{"heading": "<ТОЧНАЯ строка-заголовок, скопированная из '
         'текста БЕЗ изменений>", "number": <порядковый номер с 1>, '
         '"song": <раздел с 1, если есть>, '
         '"song_name": "<название раздела, только когда song новый>", '
         '"title": "<короткий титул>"}]}\n'
         "Строго: heading — точная подстрока текста (регистр и пунктуация как в "
         "тексте); chapters — по порядку следования; заголовков нет — "
         '{"book_title": "...", "chapters": []}.\n---\n%s\n---' % (book_title or "—", body)},
    ]


def meta_messages(instruction, field, books, allowed_types):
    return [
        {"role": "system", "content": SYSTEM_JSON},
        {"role": "user", "content":
         "Задача: %s\nПоле для правки по умолчанию: %s. Разрешённые типы книг: %s\n"
         "Книги (idx — номер, он же ключ ответа):\n%s\n"
         "Верни JSON:\n"
         '{"proposals": [{"idx": <число>, "field": "title|author|type", '
         '"value": "<полное новое значение>", "confidence": "high|medium|low", '
         '"reason": "<одна строка>"}]}\n'
         "Правила: правь только те книги, где правка реально нужна; value — полное "
         "новое значение поля; для field=type значение строго из разрешённых типов; "
         "если правок нет — {\"proposals\": []}."
         % (instruction, field, ", ".join(allowed_types) or "—",
            json.dumps(books, ensure_ascii=False))},
    ]


def validate_binding(prop, book_type, row):
    """Ответ LLM -> (filename_stem | None, замечания). None = привязка негодна."""
    notes = []
    song = _num(str(prop.get("song", "")))
    ch = _num(str(prop.get("ch", "")))
    limits = {"SCC": (1, 3), "SBG": (1, 1), "SBRS": (1, 4), "SSB": (1, 12)}
    lo, hi = limits.get(book_type, (1, 99))
    if song is None or not (lo <= song <= hi):
        notes.append("песня %r вне диапазона %d..%d" % (prop.get("song"), lo, hi))
        return None, notes
    if ch is None or not (0 <= ch <= lectures_build.MAX_CHAPTER):
        notes.append("глава %r не число или > %d" % (prop.get("ch"), lectures_build.MAX_CHAPTER))
        return None, notes
    txts = lectures_build.normalize_txts(str(prop.get("txts") or ""))
    if not txts or not re.match(r"^\d+([-,.\s]*\d+)*$", txts):
        if not txts:
            notes.append("стихи не указаны (txts пусто)")
        else:
            notes.append("стихи %r не похожи на номера/диапазоны" % txts)
        return None, notes
    num = str(row.get("num") or "").strip()
    title = re.sub(r"\s+", " ", str(prop.get("title") or "")).strip()[:60]
    core = "(%d.%d.%s)" % (song, ch, txts)
    tail = (" " + title) if title else ""
    stem = ("%s %s%s" % (num, core, tail)).strip() if num else (core + tail).strip()
    check = lectures_build.parse_lecture_filename(stem + ".docx")
    if check is None:
        notes.append("имя %r не проходит парсер имён" % stem)
        return None, notes
    return stem, notes


# ============================================================ вкладка
class AIImportTab(ttk.Frame):
    def __init__(self, parent, app=None):
        super().__init__(parent)
        self.app = app
        self.q = queue.Queue()
        self.busy = False
        self.cfg = llama_client.load_cfg()
        self.server = llama_client.LlamaServer(self.cfg)
        self._activated = False
        self._struct = None
        self._t1 = {}        # path -> {row, prop}
        self._t3 = []        # книги из Сборки (payload запроса)
        self._t3props = {}   # iid строки ревью -> {base_iid, field, value, ...}
        self._t3n = 0
        self._last_out = None
        self._btns = []

        self._build_server_bar()
        self._build_tools()
        logf = ttk.Frame(self, padding=(6, 0, 6, 6))
        logf.pack(fill="x")
        self.prog = ttk.Progressbar(logf, mode="indeterminate", length=100)
        self.prog.pack(side="left", padx=(0, 6))
        self.log = tk.Text(logf, height=6, wrap="word")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.bind("<Key>", self._log_key)
        self.after(150, self.poll)

    # ------------------------------------------------------- сервер --------
    def _build_server_bar(self):
        srv = ttk.LabelFrame(self, text="llama-server (HTTP API)", padding=6)
        srv.pack(fill="x")

        r0 = ttk.Frame(srv)
        r0.pack(fill="x")
        self.lbl_srv = ttk.Label(r0, text="● статус: не проверялся", foreground="gray")
        self.lbl_srv.pack(side="left")
        self.b_start = ttk.Button(r0, text="Запустить сервер", command=self.do_start_srv)
        self.b_start.pack(side="left", padx=6)
        self.b_stop = ttk.Button(r0, text="Стоп", command=self.do_stop_srv, state="disabled")
        self.b_stop.pack(side="left")
        self.b_health = ttk.Button(r0, text="Проверить", command=self.do_health)
        self.b_health.pack(side="left", padx=4)
        ttk.Label(r0, text="v%d" % AI_VERSION, foreground="gray").pack(side="right")
        self._btns += [self.b_start]

        r1 = ttk.Frame(srv)
        r1.pack(fill="x", pady=(4, 0))
        ttk.Label(r1, text="Модель:").pack(side="left")
        self.v_model = tk.StringVar(value=self.cfg.get("model", ""))
        ttk.Entry(r1, textvariable=self.v_model).pack(
            side="left", fill="x", expand=True, padx=4)
        ttk.Button(r1, text="…", width=3, command=self._pick_model).pack(side="left")
        ttk.Label(r1, text="Порт:").pack(side="left", padx=(8, 2))
        self.v_port = tk.StringVar(value=str(self.cfg.get("port", 8080)))
        ttk.Entry(r1, textvariable=self.v_port, width=6).pack(side="left")

        r2 = ttk.Frame(srv)
        r2.pack(fill="x", pady=(4, 0))
        ttk.Label(r2, text="Контекст:").pack(side="left")
        self.v_ctx = tk.StringVar(value=str(self.cfg.get("ctx", 32768)))
        ttk.Entry(r2, textvariable=self.v_ctx, width=8).pack(side="left", padx=(2, 6))
        ttk.Label(r2, text="Аргументы:").pack(side="left")
        self.v_extra = tk.StringVar(value=self.cfg.get("extra", ""))
        ttk.Entry(r2, textvariable=self.v_extra).pack(
            side="left", fill="x", expand=True, padx=4)
        ttk.Label(r2, text="exe/путь к модели — в полях выше, сохраняется при Запустить",
                  foreground="gray").pack(side="left", padx=4)

    def _pick_model(self):
        p = filedialog.askopenfilename(
            title="Модель GGUF", parent=self,
            filetypes=[("GGUF", "*.gguf"), ("Все", "*.*")])
        if p:
            self.v_model.set(p)

    def _srv_patch(self):
        patch = {"model": self.v_model.get().strip(), "port": self.v_port.get().strip(),
                 "ctx": self.v_ctx.get().strip(), "extra": self.v_extra.get().strip()}
        try:
            patch["port"] = int(patch["port"])
            patch["ctx"] = int(patch["ctx"])
        except ValueError:
            pass
        llama_client.save_cfg(patch)
        if self.server.alive():
            # сервер уже работает на старых настройках: не подменяем объект
            # (потеряли бы proc — «Стоп» стал бы бесполезен), чат ходит на тот же порт
            self.say("сервер запущен — настройки сохранены, применятся после перезапуска")
            return self.cfg
        self.cfg = llama_client.load_cfg()
        self.server = llama_client.LlamaServer(self.cfg)
        return self.cfg

    def do_health(self):
        self._srv_patch()
        threading.Thread(target=self._health_bg, daemon=True).start()

    def _health_bg(self):
        st = self.server.health(timeout=1.5)
        self.q.put(("status", st))

    def do_start_srv(self):
        self._srv_patch()
        if self.server.health(timeout=1.2) == "ready":
            self.q.put(("status", "ready"))
            self.say("сервер уже отвечает на %s" % self.server.base_url)
            return
        self.say("сервер: подготовка…")
        self.set_busy(True)
        threading.Thread(target=self._start_bg, daemon=True).start()

    def _start_bg(self):
        put = self.q.put
        err = self.server.start(log=lambda s: put(("log", s)))
        if err:
            put(("log", "ЗАПУСК НЕ УДАЛСЯ: %s" % err))
            put(("status", "down"))
            put(("busy", False))
            return
        put(("status", "loading"))
        if self.server.wait_ready(timeout=600, log=lambda s: put(("log", s))):
            put(("status", "ready"))
        else:
            put(("status", "down"))
        put(("busy", False))

    def do_stop_srv(self):
        self.server.stop()
        self.q.put(("status", "down"))
        self.say("сервер остановлен")

    def _set_status(self, st):
        colors = {"ready": "#0a7d2c", "loading": "#b58900", "down": "#c0392b"}
        texts = {"ready": "● статус: готов (%s)" % self.server.base_url,
                 "loading": "● статус: загрузка модели…",
                 "down": "● статус: не запущен"}
        self.lbl_srv.configure(text=texts.get(st, "● статус: %s" % st),
                               foreground=colors.get(st, "gray"))
        running = self.server.alive()
        self.b_stop.configure(state="normal" if running else "disabled")
        self.b_start.configure(state="disabled" if running else "normal")

    def on_activate(self):
        if self._activated:
            return
        self._activated = True
        self.say("AI-импорт v%d. Модель: %s" % (AI_VERSION,
                                                os.path.basename(self.cfg.get("model", "?"))))
        threading.Thread(target=self._health_bg, daemon=True).start()

    # ------------------------------------------------------- общее ---------
    def set_busy(self, v):
        self.busy = v
        st = "disabled" if v else "normal"
        for b in self._btns:
            try:
                b.configure(state=st)
            except Exception:
                pass
        if v:
            self.prog.start(12)
        else:
            self.prog.stop()
            running = self.server.alive()
            self.b_start.configure(state="disabled" if running else "normal")
            self.b_stop.configure(state="normal" if running else "disabled")

    def say(self, text):
        self.log.insert("end", str(text).rstrip() + "\n")
        self.log.see("end")
        if len(self.log.get("1.0", "end")) > 60000:
            self.log.delete("1.0", "20.0")

    def _log_key(self, ev):
        if ev.state & 0x4:
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

    def poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                try:
                    if kind == "log":
                        self.say(item[1])
                    elif kind == "status":
                        self._set_status(item[1])
                    elif kind == "busy":
                        self.set_busy(item[1])
                    elif kind == "t1_fill":
                        self._t1_fill(item[1])
                    elif kind == "t1_row":
                        self._t1_row(item[1], item[2])
                    elif kind == "t1_done":
                        self.say("привязка: готово запросов %d%s" % (
                            item[1], ("; ошибок %d" % item[2]) if item[2] else ""))
                        self.set_busy(False)
                    elif kind == "t3_row":
                        self._t3_row(item[1], item[2])
                    elif kind == "t3_done":
                        self.say("метаданные: предложений %d%s" % (
                            item[1], ("; ошибок %d" % item[2]) if item[2] else ""))
                        self.set_busy(False)
                    elif kind == "t2_struct":
                        self._show_struct(item[1], item[2])
                except Exception as e:
                    # поломка одного сообщения не должна убить диспетчер
                    self.say("ошибка обработки: %s" % e)
        except queue.Empty:
            pass
        try:
            self.after(150, self.poll)
        except Exception:
            pass

    def _need_server(self):
        if self.server.health(timeout=1.2) != "ready":
            messagebox.showwarning("Сервер не готов",
                                   "llama-server не отвечает на /health.\n"
                                   "Нажми «Запустить сервер» и дождись зелёного статуса.")
            return False
        return True

    # ------------------------------------------------- 1. Разное -> привязка
    def _build_tab1(self, nb):
        t = ttk.Frame(nb, padding=6)
        nb.add(t, text="1 · Разное → привязка")
        bar = ttk.Frame(t)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Button(bar, text="Загрузить без привязки (из Лекций)",
                   command=self.t1_load).pack(side="left")
        ttk.Button(bar, text="Все / снять", command=self.t1_flip).pack(side="left", padx=4)
        self.b_t1llm = ttk.Button(bar, text="Привязать через LLM", command=self.t1_run)
        self.b_t1llm.pack(side="left", padx=4)
        self.b_t1apply = ttk.Button(bar, text="Применить отмеченные",
                                    command=self.t1_apply)
        self.b_t1apply.pack(side="left")
        self.v_ren = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="переименовать файлы на диске",
                        variable=self.v_ren).pack(side="left", padx=8)
        self._btns += [self.b_t1llm, self.b_t1apply]

        cols = ("file", "prop", "conf", "why")
        self.tv1 = ttk.Treeview(t, columns=cols, show="tree headings", selectmode="browse")
        self.tv1.heading("#0", text="✓")
        self.tv1.column("#0", width=30, stretch=False, anchor="center")
        for c, label, w in (("file", "Файл без привязки", 300),
                            ("prop", "Предложение", 220),
                            ("conf", "Увер.", 70),
                            ("why", "Почему", 300)):
            self.tv1.heading(c, text=label)
            self.tv1.column(c, width=w, anchor="w", stretch=c in ("file", "why"))
        self.tv1.pack(fill="both", expand=True)
        self.tv1.bind("<ButtonRelease-1>", self._t1_click)
        ttk.Label(t, text="Лекция привязывается именем «NNN (песнь.глава.стихи) Заголовок» — "
                          "те же правила, что у парсера имён (TEMPLATE.md).",
                  foreground="gray").pack(fill="x", pady=(4, 0))

    def _t1_click(self, ev):
        iid = self.tv1.identify_row(ev.y)
        if iid and self.tv1.identify_column(ev.x) == "#0" and iid in self._t1:
            self.tv1.item(iid, text="" if self.tv1.item(iid, "text") == "☑" else "☑")

    def t1_flip(self):
        any_off = any(self.tv1.item(i, "text") != "☑" for i in self.tv1.get_children())
        for i in self.tv1.get_children():
            self.tv1.item(i, text="☑" if any_off else "")

    def t1_load(self):
        lect = getattr(self.app, "tab_lectures", None) if self.app else None
        if lect is None:
            messagebox.showinfo("Нет лекций", "Открой приложение с вкладкой Лекции.")
            return
        if lect.building:
            messagebox.showwarning("Занято", "Идёт сборка лекций — дождись конца.")
            return
        if not lect._activated:
            self.say("чту папку лекций…")
            self.update_idletasks()
            self.app.nb.select(lect)
            lect.on_activate()
        items = [(p, l) for p, l in lect.rows.items() if l.get("unparsed")]
        if not items:
            self.say("файлов без привязки нет")
            return
        self.q.put(("t1_fill", [p for p, _ in items]))
        self.say("без привязки: %d" % len(items))

    def _t1_fill(self, paths):
        for i in self.tv1.get_children():
            self.tv1.delete(i)
        self._t1 = {}
        lect = self.app.tab_lectures
        for p in paths:
            self.tv1.insert("", "end", iid=p, text="☑",
                            values=(os.path.basename(p), "", "", ""))
            self._t1[p] = {"row": lect.rows.get(p), "prop": None}

    def t1_run(self):
        if not self._t1:
            self.say("сначала «Загрузить без привязки»")
            return
        if not self._need_server():
            return
        cfg = self.cfg
        jobs = [p for p, d in self._t1.items() if self.tv1.item(p, "text") == "☑"
                and d["row"] is not None]
        if not jobs:
            self.say("не отмечено ни одного файла")
            return
        lect = self.app.tab_lectures
        book_type = lect.e_btype.get() or "SCC"
        payload = [(p, self._t1[p]["row"], book_type) for p in jobs]
        self.set_busy(True)
        self.say("привязка через LLM: %d файлов, тип %s" % (len(payload), book_type))
        threading.Thread(target=self._t1_bg, args=(cfg, payload), daemon=True).start()

    def _t1_bg(self, cfg, payload):
        ok = err = 0
        for path, row, book_type in payload:
            try:
                prop = llama_client.chat_json(
                    cfg, binding_messages(book_type, os.path.basename(path), row.get("paras") or []),
                    max_tokens=1500, temperature=0.1)
                stem, notes = validate_binding(prop, book_type, row)
                out = {"stem": stem, "notes": notes,
                       "conf": str(prop.get("confidence") or ""),
                       "why": str(prop.get("reason") or "")[:200],
                       "title": str(prop.get("title") or "")[:60]}
                if stem:
                    ok += 1
                else:
                    err += 1
                self.q.put(("t1_row", path, out))
            except Exception as e:
                err += 1
                self.q.put(("t1_row", path, {"stem": None, "notes": [str(e)[:200]],
                                             "conf": "", "why": "", "title": ""}))
        self.q.put(("t1_done", ok, err))

    def _t1_row(self, path, out):
        if not self.tv1.exists(path):
            return
        self._t1[path]["prop"] = out
        stem = out["stem"]
        prop = (stem + os.path.splitext(path)[1]) if stem else "—"
        why = "; ".join(out["notes"]) or out["why"]
        self.tv1.set(path, "prop", prop)
        self.tv1.set(path, "conf", out["conf"])
        self.tv1.set(path, "why", why)
        if not stem:
            self.tv1.item(path, text="")

    def t1_apply(self):
        lect = self.app.tab_lectures
        if lect.building:
            messagebox.showwarning("Занято", "Идёт сборка лекций.")
            return
        todo = [(p, d) for p, d in self._t1.items()
                if self.tv1.exists(p) and self.tv1.item(p, "text") == "☑"
                and d.get("prop") and d["prop"].get("stem")]
        if not todo:
            self.say("нет отмеченных с валидной привязкой")
            return
        rename = bool(self.v_ren.get())
        done = skipped = 0
        for path, d in todo:
            stem = d["prop"]["stem"]
            ext = os.path.splitext(path)[1]
            new_path = os.path.join(os.path.dirname(path), stem + ext)
            target = path
            if rename and new_path != path:
                if os.path.exists(new_path):
                    self.say("пропуск: уже есть %s" % os.path.basename(new_path))
                    skipped += 1
                    continue
                try:
                    os.rename(path, new_path)
                    target = new_path
                except OSError as e:
                    self.say("переименование не удалось (%s): %s" % (os.path.basename(path), e))
                    skipped += 1
                    continue
            try:
                l2 = lectures_build.parse_single_lecture(target, lect.e_btype.get() or "SCC")
            except Exception as e:
                if target != path and os.path.exists(target):
                    os.rename(target, path)
                self.say("разбор не удался (%s): %s" % (os.path.basename(target), e))
                skipped += 1
                continue
            if l2.get("unparsed"):
                self.say("парсер всё равно не принял привязку: %s" % os.path.basename(target))
                skipped += 1
                continue
            l2["checked"] = True
            if path in lect.rows:
                del lect.rows[path]
            lect.rows[target] = l2
            done += 1
        lectures_build.assign_intro_song(list(lect.rows.values()))
        lect.refresh_table()
        for p in [p for p in list(self._t1) if p not in lect.rows
                  and self.tv1.exists(p)]:
            self.tv1.delete(p)
            del self._t1[p]
        for p, d in self._t1.items():
            if self.tv1.exists(p):
                self.tv1.item(p, text="")
                self.tv1.set(p, "prop", "")
                d["prop"] = None
        self.say("привязано: %d, пропущено: %d" % (done, skipped))

    # ------------------------------------------------- 2. Текст -> книга
    def _build_tab2(self, nb):
        t = ttk.Frame(nb)
        nb.add(t, text="2 · Текст → книга")
        left = ttk.Frame(t, padding=6)
        left.pack(side="left", fill="y")

        book = ttk.LabelFrame(left, text="Книга", padding=4)
        book.pack(fill="x")
        ttk.Label(book, text="Название:").grid(row=0, column=0, sticky="w")
        self.v_btitle = tk.StringVar(value=self.cfg.get("t2_title", ""))
        ttk.Entry(book, textvariable=self.v_btitle, width=26).grid(row=0, column=1, sticky="ew")
        ttk.Label(book, text="Тип:").grid(row=1, column=0, sticky="w")
        self.v_btype = tk.StringVar(value=self.cfg.get("t2_type", "SCC"))
        self.cmb_type = ttk.Combobox(book, textvariable=self.v_btype, width=10,
                                     values=self._type_values())
        self.cmb_type.grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(book, text="Автор:").grid(row=2, column=0, sticky="w")
        self.v_bauthor = tk.StringVar(value=self.cfg.get("t2_author", ""))
        ttk.Entry(book, textvariable=self.v_bauthor, width=26).grid(row=2, column=1, sticky="ew")
        self.lbl_cap = ttk.Label(book, text="", foreground="#b58900")
        self.lbl_cap.grid(row=3, column=0, columnspan=2, sticky="w")
        self.v_btype.trace_add("write", lambda *a: self._cap_hint())
        self._cap_hint()
        book.columnconfigure(1, weight=1)

        chf = ttk.LabelFrame(left, text="Нарезка ГЛАВ", padding=4)
        chf.pack(fill="x", pady=(6, 0))
        self.v_chmode = tk.StringVar(value=self.cfg.get("t2_chmode", "md"))
        for val, label in (("md", "Markdown #"), ("regex", "Свой regex"),
                           ("preset", "Автошаблоны"), ("none", "Не делить")):
            ttk.Radiobutton(chf, text=label, value=val, variable=self.v_chmode,
                            command=self._chmode_ui).pack(anchor="w")
        md = ttk.Frame(chf)
        md.pack(fill="x")
        ttk.Label(md, text="раздел — уровень #").pack(side="left")
        self.v_mdsec = tk.StringVar(value=str(self.cfg.get("t2_mdsec", 1)))
        ttk.Combobox(md, textvariable=self.v_mdsec, width=3, state="readonly",
                     values=("0", "1", "2", "3", "4", "5", "6")).pack(side="left", padx=2)
        ttk.Label(md, text="глава — ").pack(side="left", padx=(6, 0))
        self.v_mdch = tk.StringVar(value=str(self.cfg.get("t2_mdch", 2)))
        ttk.Combobox(md, textvariable=self.v_mdch, width=3, state="readonly",
                     values=("1", "2", "3", "4", "5", "6")).pack(side="left", padx=2)
        ttk.Label(chf, text="Regex (группа chapter, можно song/title):",
                  foreground="gray").pack(anchor="w")
        self.v_chre = tk.StringVar(value=self.cfg.get("t2_chre", ""))
        ttk.Entry(chf, textvariable=self.v_chre).pack(fill="x", pady=2)
        self.v_intro = tk.BooleanVar(value=self.cfg.get("t2_intro", True))
        ttk.Checkbutton(chf, text="шапка до первого заголовка → «Введение»",
                        variable=self.v_intro).pack(anchor="w")

        vf = ttk.LabelFrame(left, text="Нарезка СТИХОВ", padding=4)
        vf.pack(fill="x", pady=(6, 0))
        self.v_vmode = tk.StringVar(value=self.cfg.get("t2_vmode", "para"))
        for val, label in (("para", "Абзац = стих"), ("number", "Номер в строке"),
                           ("none", "Не делить (глава целиком)")):
            ttk.Radiobutton(vf, text=label, value=val, variable=self.v_vmode).pack(anchor="w")
        ttk.Label(vf, text="Regex номера (группа verse):", foreground="gray").pack(anchor="w")
        self.v_vre = tk.StringVar(value=self.cfg.get("t2_vre", DEFAULT_VERSE_RE))
        ttk.Entry(vf, textvariable=self.v_vre).pack(fill="x", pady=2)

        pf = ttk.LabelFrame(left, text="Обработка текста", padding=4)
        pf.pack(fill="x", pady=(6, 0))
        self.v_join = tk.BooleanVar(value=self.cfg.get("t2_join", True))
        self.v_md = tk.BooleanVar(value=self.cfg.get("t2_stripmd", True))
        ttk.Checkbutton(pf, text="склеивать переносы строк",
                        variable=self.v_join).pack(anchor="w")
        ttk.Checkbutton(pf, text="убрать markdown-разметку (*, [], >)",
                        variable=self.v_md).pack(anchor="w")

        self.b_llmstruct = ttk.Button(
            left, text="LLM: предложить структуру",
            command=self.t2_llm_structure)
        self.b_llmstruct.pack(fill="x", pady=(8, 0))
        ttk.Label(left, text="LLM ищет только точные заголовки-подстроки — "
                             "границы ставит код по ним.",
                  foreground="gray", wraplength=280).pack(fill="x")

        right = ttk.Frame(t, padding=(0, 6, 6, 6))
        right.pack(side="left", fill="both", expand=True)
        sb = ttk.Frame(right)
        sb.pack(fill="x")
        ttk.Button(sb, text="Загрузить .txt/.md", command=self.t2_load).pack(side="left")
        ttk.Button(sb, text="Очистить", command=self.t2_clear).pack(side="left", padx=4)
        self.v_srcfile = tk.StringVar(value="")
        ttk.Label(sb, textvariable=self.v_srcfile, foreground="gray").pack(
            side="left", padx=8)
        self.txt2 = tk.Text(right, height=9, wrap="word")
        self.txt2.pack(fill="x", pady=4)
        self.tv2 = ttk.Treeview(right, columns=("words",), show="tree headings")
        self.tv2.heading("#0", text="Структура (предпросмотр)")
        self.tv2.column("#0", width=560, anchor="w")
        self.tv2.heading("words", text="Симв.")
        self.tv2.column("words", width=70, anchor="e", stretch=False)
        self.tv2.pack(fill="both", expand=True)
        pb = ttk.Frame(right)
        pb.pack(fill="x", pady=(4, 0))
        self.b_parse = ttk.Button(pb, text="Разобрать", command=self.t2_parse)
        self.b_parse.pack(side="left")
        self.b_save = ttk.Button(pb, text="Собрать .db…", command=self.t2_save)
        self.b_save.pack(side="left", padx=4)
        self.b_open = ttk.Button(pb, text="Открыть в Сборке", command=self.t2_open,
                                 state="disabled")
        self.b_open.pack(side="left")
        self.lbl_stat = ttk.Label(pb, text="глав: 0, стихов: 0")
        self.lbl_stat.pack(side="left", padx=10)
        self._btns += [self.b_llmstruct]
        self._chmode_ui()

    def _type_values(self):
        return ("SCC SSB SBG SBRS GC LTRS LBG LSB TLKS BG SB CC TLC NOD NOI BS ISO KB "
                "TQK GT").split()

    def _cap_hint(self):
        t = (self.v_btype.get() or "").strip().upper().split("-")[0]
        if t in BIG_TYPES:
            self.lbl_cap.configure(text="лимит тела в приложении: 120 000 симв.")
        elif t == "GC":
            self.lbl_cap.configure(text="лимит тела в приложении: 60 000 симв.")
        else:
            self.lbl_cap.configure(
                text="⚠ для типа %s в приложении лимит тела 8 000 символов "
                     "( длинный текст обрежется )" % (t or "?"),
                foreground="#c0392b")

    def _chmode_ui(self):
        mode = self.v_chmode.get()
        self.v_mdch.set(self.v_mdch.get() or "2")

    def _split_opts(self):
        return {
            "ch_mode": self.v_chmode.get(),
            "md_section": int(self.v_mdsec.get() or 0),
            "md_chapter": int(self.v_mdch.get() or 2),
            "chapter_re": self.v_chre.get(),
            "prelude_intro": bool(self.v_intro.get()),
            "v_mode": self.v_vmode.get(),
            "verse_re": self.v_vre.get(),
            "join_wraps": bool(self.v_join.get()),
            "strip_md": bool(self.v_md.get()),
            "book_title": self.v_btitle.get().strip(),
        }

    def _save_t2(self):
        o = self._split_opts()
        llama_client.save_cfg({
            "t2_title": self.v_btitle.get(), "t2_type": self.v_btype.get(),
            "t2_author": self.v_bauthor.get(),
            "t2_chmode": o["ch_mode"], "t2_mdsec": o["md_section"],
            "t2_mdch": o["md_chapter"], "t2_chre": o["chapter_re"],
            "t2_intro": o["prelude_intro"], "t2_vmode": o["v_mode"],
            "t2_vre": o["verse_re"], "t2_join": o["join_wraps"],
            "t2_stripmd": o["strip_md"],
        })
        self.cfg = llama_client.load_cfg()

    def t2_load(self):
        p = filedialog.askopenfilename(
            title="Текст лекции/книги", parent=self,
            filetypes=[("Текст", "*.txt *.md"), ("Все", "*.*")])
        if not p:
            return
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            messagebox.showerror("Не читается", str(e))
            return
        self.txt2.delete("1.0", "end")
        self.txt2.insert("1.0", text)
        self.v_srcfile.set(os.path.basename(p))
        self.say("загружено: %s (%d симв.)" % (os.path.basename(p), len(text)))

    def t2_clear(self):
        self.txt2.delete("1.0", "end")
        self.v_srcfile.set("")
        self._struct = None
        for i in self.tv2.get_children():
            self.tv2.delete(i)

    def t2_parse(self):
        text = self.txt2.get("1.0", "end")
        if not text.strip():
            self.say("пусто — вставь или загрузи текст")
            return
        self._save_t2()
        struct = build_structure(text, self._split_opts())
        self._show_struct(struct, "правила")

    def t2_llm_structure(self):
        text = self.txt2.get("1.0", "end")
        if not text.strip():
            self.say("пусто — вставь или загрузи текст")
            return
        if not self._need_server():
            return
        self._save_t2()
        cfg = self.cfg
        opts = self._split_opts()
        title = self.v_btitle.get().strip()
        self.set_busy(True)
        self.say("LLM ищет структуру (заголовки-подстроки)…")
        threading.Thread(target=self._t2_llm_bg, args=(cfg, title, text, opts),
                         daemon=True).start()

    def _t2_llm_bg(self, cfg, title, text, opts):
        try:
            res = llama_client.chat_json(
                cfg, structure_messages(title, text),
                max_tokens=2048, temperature=0.1, timeout=900)
            heads = (res or {}).get("chapters") or []
            self.q.put(("log", "LLM: заголовков %d" % len(heads)))
            struct = build_structure(text, opts, llm_result=res)
            self.q.put(("t2_struct", struct, "LLM + правила стихов"))
        except Exception as e:
            self.q.put(("log", "LLM ОШИБКА: %s" % e))
            self.q.put(("busy", False))

    def _show_struct(self, struct, how):
        self._struct = struct
        for i in self.tv2.get_children():
            self.tv2.delete(i)
        st = struct["stats"]
        if not st["chapters"]:
            self.lbl_stat.configure(text="глав: 0, стихов: 0")
            self.say("структура пуста%s" % (
                (": " + "; ".join(struct["notes"])) if struct["notes"] else ""))
            self.set_busy(False)
            return
        for ci, c in enumerate(struct["chapters"]):
            cid = self.tv2.insert("", "end", text="Глава %s — %s" % (c["number"], c["title"]),
                                  values=(sum(len(t) for _, t in c["verses"]),))
            for no, body in c["verses"]:
                self.tv2.insert(cid, "end",
                                text="стих %s: %s" % (no, body[:90].replace("\n", " ")),
                                values=(len(body),))
            self.tv2.item(cid, open=True)
        names = struct.get("song_names") or {}
        if names:
            self.say("разделы: " + ", ".join("%s=%s" % kv for kv in sorted(names.items())))
        for n in struct["notes"]:
            self.say("примечание: %s" % n)
        self.lbl_stat.configure(text="глав: %d, стихов: %d, символов: %d (%s)" % (
            st["chapters"], st["verses"], st["chars"], how))
        self.say("разобрано (%s): глав %d, стихов %d" % (how, st["chapters"], st["verses"]))
        self.set_busy(False)

    def t2_save(self):
        if not self._struct or not self._struct["chapters"]:
            self.say("сначала «Разобрать»")
            return
        if not (self.v_btitle.get().strip() and self.v_btype.get().strip()):
            messagebox.showwarning("Нужны поля", "Укажи название и тип книги.")
            return
        out = filedialog.asksaveasfilename(
            title="Сохранить source-.db", defaultextension=".db",
            filetypes=[("SQLite", "*.db")], parent=self,
            initialfile="%s.db" % re.sub(r"[^\w\- ]+", "", self.v_btitle.get().strip())[:40])
        if not out:
            return
        if os.path.exists(out) and not messagebox.askyesno(
                "Перезапись", "Файл есть. Перезаписать?\n%s" % out):
            return
        meta = {"title": self.v_btitle.get().strip(),
                "author": self.v_bauthor.get().strip(),
                "type": self.v_btype.get().strip().upper()}
        try:
            stat = write_source_db(self._struct, meta, out)
        except Exception as e:
            messagebox.showerror("Не собралось", str(e))
            return
        self._last_out = out
        self.b_open.configure(state="normal")
        self.say("source-.db: %s (глав %d, стихов %d)" % (
            out, stat["chapters"], stat["texts"]))

    def t2_open(self):
        if not self._last_out or not self.app:
            return
        r = self.app.load_file(self._last_out, quiet=False)
        if r == "ok":
            self.app.nb.select(0)
            self.say("открыто в «Сборке»: %s" % os.path.basename(self._last_out))

    # ------------------------------------------------- 3. Метаданные
    def _build_tab3(self, nb):
        t = ttk.Frame(nb, padding=6)
        nb.add(t, text="3 · Метаданные")
        bar = ttk.Frame(t)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Button(bar, text="Взять книги из Сборки", command=self.t3_load).pack(side="left")
        self.v_field = tk.StringVar(value="title")
        for val, label in (("title", "Названия"), ("author", "Авторы"),
                           ("type", "Типы"), ("free", "Свой запрос")):
            ttk.Radiobutton(bar, text=label, value=val, variable=self.v_field).pack(
                side="left", padx=2)
        self.v_free = tk.StringVar(value="")
        self.e_free = ttk.Entry(bar, textvariable=self.v_free, width=44)
        self.e_free.pack(side="left", padx=6, fill="x", expand=True)
        self.b_t3llm = ttk.Button(bar, text="Запрос к LLM", command=self.t3_run)
        self.b_t3llm.pack(side="left", padx=4)
        self.b_t3apply = ttk.Button(bar, text="Применить отмеченные",
                                    command=self.t3_apply)
        self.b_t3apply.pack(side="left")
        self._btns += [self.b_t3llm, self.b_t3apply]

        cols = ("book", "field", "value", "conf", "why")
        self.tv3 = ttk.Treeview(t, columns=cols, show="tree headings", selectmode="browse")
        self.tv3.heading("#0", text="✓")
        self.tv3.column("#0", width=30, stretch=False, anchor="center")
        for c, label, w in (("book", "Книга", 240), ("field", "Поле", 70),
                            ("value", "Станет", 260), ("conf", "Увер.", 70),
                            ("why", "Почему", 240)):
            self.tv3.heading(c, text=label)
            self.tv3.column(c, width=w, anchor="w",
                            stretch=c in ("book", "value", "why"))
        self.tv3.pack(fill="both", expand=True)
        self.tv3.bind("<ButtonRelease-1>", self._t3_click)
        ttk.Label(t, text="Правки меняют только то, что уйдёт в сборку (переименование "
                          "при сборке), исходные .db не трогаются.",
                  foreground="gray").pack(fill="x", pady=(4, 0))

    def _t3_click(self, ev):
        iid = self.tv3.identify_row(ev.y)
        if iid and self.tv3.identify_column(ev.x) == "#0":
            self.tv3.item(iid, text="" if self.tv3.item(iid, "text") == "☑" else "☑")

    def t3_load(self):
        if not self.app or not self.app.rows:
            self.say("в «Сборке» пусто — добавь .db")
            return
        for i in self.tv3.get_children():
            self.tv3.delete(i)
        self._t3 = []
        self._t3props = {}
        self._t3n = 0
        for iid, r in sorted(self.app.rows.items(),
                             key=lambda kv: (kv[1]["file"], kv[1]["title"] or "")):
            self._t3.append({
                "iid": iid, "file": os.path.basename(r["file"]),
                "title": r.get("new_title") or r.get("title") or "",
                "author": r.get("new_author") or r.get("author") or "",
                "type": r.get("new_type") or r.get("type") or ""})
        for i, b in enumerate(self._t3):
            self.tv3.insert("", "end", iid="b%d" % i, text="",
                            values=(b["title"][:60], "", "", "", ""))
        self.say("книг из Сборки: %d" % len(self._t3))

    def t3_run(self):
        if not self._t3:
            self.say("сначала «Взять книги из Сборки»")
            return
        if not self._need_server():
            return
        field = self.v_field.get()
        if field == "free":
            instruction = self.v_free.get().strip()
            if not instruction:
                messagebox.showwarning("Пустой запрос", "Напиши, что поправить.")
                return
            fields = list(META_FIELDS)
        else:
            instruction = META_PRESETS[field]
            fields = [field]
        types = sorted({t for t in (b["type"] for b in self._t3) if t}
                       | set(self._type_values()))
        books = [{"idx": i, "title": b["title"], "author": b["author"], "type": b["type"]}
                 for i, b in enumerate(self._t3)]
        ids = {i: b["iid"] for i, b in enumerate(self._t3)}  # внутренний ключ — в промпт не идёт
        for i in self.tv3.get_children():
            self.tv3.delete(i)
        self._t3props = {}
        self._t3n = 0
        cfg = self.cfg
        self.set_busy(True)
        self.say("метаданные: книг %d, поле %s" % (len(books), field))
        threading.Thread(target=self._t3_bg,
                         args=(cfg, instruction, fields, types, books, ids),
                         daemon=True).start()

    def _t3_bg(self, cfg, instruction, fields, types, books, ids):
        ok = err = 0
        # книги по 60 за запрос — иначе промпт + ответ не влезают в контекст
        try:
            for i in range(0, len(books), 60):
                chunk = books[i:i + 60]
                res = llama_client.chat_json(
                    cfg, meta_messages(instruction, ",".join(fields), chunk, types),
                    max_tokens=4096, temperature=0.1, timeout=900)
                for p in (res or {}).get("proposals") or []:
                    try:
                        base = ids[int(p.get("idx"))]
                    except Exception:
                        err += 1
                        continue
                    fld = str(p.get("field") or "")
                    val = str(p.get("value") or "").strip()
                    if fld not in META_FIELDS or not val or fld not in fields:
                        continue
                    if fld == "type" and val.upper() not in types:
                        err += 1
                        continue
                    self.q.put(("t3_row", base, {
                        "field": fld,
                        "value": val.upper() if fld == "type" else val,
                        "conf": str(p.get("confidence") or ""),
                        "why": str(p.get("reason") or "")[:200],
                        "book": books[int(p.get("idx"))]["title"][:60]}))
                    ok += 1
        except Exception as e:
            self.q.put(("log", "метаданные ОШИБКА: %s" % e))
            err += 1
        self.q.put(("t3_done", ok, err))

    def _t3_row(self, base_iid, prop):
        prop = dict(prop, base_iid=base_iid)
        iid = "p%d" % self._t3n
        self._t3n += 1
        self._t3props[iid] = prop
        self.tv3.insert("", "end", iid=iid, text="☑",
                        values=(prop["book"], prop["field"], prop["value"][:80],
                                prop["conf"], prop["why"]))

    def t3_apply(self):
        if not self.app:
            return
        n = 0
        for iid in self.tv3.get_children():
            if self.tv3.item(iid, "text") != "☑":
                continue
            prop = self._t3props.get(iid)
            if not prop:
                continue
            row = self.app.rows.get(prop["base_iid"])
            if row is None:
                continue
            row["new_" + prop["field"]] = prop["value"]
            if prop["field"] == "title":
                self.app.tv.set(prop["base_iid"], "title", prop["value"][:60])
            elif prop["field"] == "type":
                self.app.tv.set(prop["base_iid"], "type", prop["value"])
            self.tv3.item(iid, text="")
            n += 1
        self.say("применено правок: %d" % n)

    # ------------------------------------------------------- сборка UI ------
    def _build_tools(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        self._build_tab1(self.nb)
        self._build_tab2(self.nb)
        self._build_tab3(self.nb)
