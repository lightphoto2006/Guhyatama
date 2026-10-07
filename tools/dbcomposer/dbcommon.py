#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Общие помощники dbcomposer: конфиги, галереи, картинки, пути, ключи.

Всё, что раньше было продублировано в gui.py / lectures_gui.py / audio_gui.py /
recompose.py / make_catalog.py и местами расходилось — здесь, в одном месте.
"""
import base64
import json
import os
import sqlite3
import tempfile
from urllib.parse import quote

# ------------------------------------------------------------ конфиги / JSON ---


def atomic_write_bytes(path, data):
    """Запись файла атомарно: tmp в той же папке + os.replace.
    Возвращает None при успехе, текст ошибки при неудаче (вызывающий решает,
    что делать — молча глотать больше нельзя)."""
    try:
        d = os.path.dirname(os.path.abspath(path)) or "."
        fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=d)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
            return None
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        return str(e)


def atomic_json(path, obj, indent=1):
    """JSON-конфиг атомарно. Возвращает None при успехе, текст ошибки при неудаче."""
    try:
        data = json.dumps(obj, ensure_ascii=False, indent=indent).encode("utf-8")
    except Exception as e:
        return "json: %s" % e
    return atomic_write_bytes(path, data)


def load_cfg(path):
    """Конфиг без исключений наружу: битый/отсутствующий -> {}."""
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def save_cfg(path, cfg):
    """Сохранение конфига атомарно; при ошибке — текст в stderr, не молчим."""
    err = atomic_json(path, cfg, indent=1)
    if err:
        try:
            sys_stderr_write("dbcomposer: конфиг не сохранён (%s): %s\n" % (path, err))
        except Exception:
            pass
    return err


def sys_stderr_write(s):
    import sys
    sys.stderr.write(s)


# ----------------------------------------------------------------- строки ---


def is_gallery(preview):
    """Строка-галерея (не стих!): подпись «Иллюстрации…», картинки — в comment/images.

    Один эталон на всё: движок (recompose), каталог (make_catalog) и приложение
    (LibraryDbImporter.isGalleryRow, ignoreCase) должны считать одинаково,
    иначе fp каталога расходится с тем, что реально собрано.
    """
    if not isinstance(preview, str):
        return False
    t = preview.strip().lower()
    return t.startswith("иллюстрац") or t.startswith("illustration")


def nkey(v):
    """Нормализация координаты (song/ch/txt) ТОЛЬКО для сравнений: '028' -> '28',
    '28.0' -> '28', None/пробелы -> ''. Записываемые в БД значения не меняются.

    Без этого исключения/дедуп/ремап молча не срабатывали на источниках,
    где номера хранятся как текст с ведущими нулями."""
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    try:
        f = float(s)
        if f.is_integer() and abs(f) < 1e15:
            return str(int(f))
    except (ValueError, OverflowError):
        pass
    return s


# ------------------------------------------------------------------ пути ---


def connect_ro(path):
    """Read-only соединение. Путь percent-кодируется: '?'/'#'/'%' в путях
    иначе ломают разбор file: URI (например '%20' в папке декодируется в пробел)."""
    uri = "file:%s?mode=ro" % quote(os.path.abspath(path))
    return sqlite3.connect(uri, uri=True)


# -------------------------------------------------------------- картинки ---


def _image_sig(b):
    """Похоже ли на растр: JPEG/PNG/GIF/WEBP/BMP."""
    if not b or len(b) < 8:
        return False
    if b[:2] == b"\xff\xd8":                      # JPEG
        return True
    if b[:8] == b"\x89PNG\r\n\x1a\n":             # PNG
        return True
    if b[:6] in (b"GIF87a", b"GIF89a"):           # GIF
        return True
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":   # WEBP
        return True
    if b[:2] == b"BM":                            # BMP
        return True
    return False


def img_bytes(raw):
    """Контент images: сырой растр -> байты; иначе base64-текст -> байты.

    Порядок и проверка сигнатур важны: раньше base64 шёл первым с
    validate=False, и сырой JPEG/случайные байты «успешно» декодировались
    в мусор — превью/экспорт брали битые данные, а фолбэк был недостижим."""
    if not raw:
        return None
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "ignore")
    raw = bytes(raw)
    if _image_sig(raw):
        return raw
    if len(raw) < 100:
        return None
    try:
        data = base64.b64decode(raw, validate=False)
    except Exception:
        return None
    if _image_sig(data):
        return data
    return None
