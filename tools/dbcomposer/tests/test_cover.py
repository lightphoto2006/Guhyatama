#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тест обложки: AI-импорт кладёт cover в source-.db, recompose переносит в сборку."""
import json
import os
import sqlite3
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_import as ai
import recompose

FAILED = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (("  | " + str(extra)) if not cond else ""))
    if not cond:
        FAILED.append(name)


# ------------------------------------------------------------------- PNG 2×2 ---
def make_png_2x2():
    """Минимальный валидный PNG 2×2 RGBA (48 байт)."""
    sig = b'\x89PNG\r\n\x1a\n'

    def chunk(ctype, data):
        c = ctype + data
        return b'' + ctype + struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

    ihdr = struct.pack('>IIBBBBB', 2, 2, 8, 6, 0, 0, 0)
    raw = b''
    for y in range(2):
        raw += b'\x00' + b'\xff\x00\x00\xff' + b'\x00\xff\x00\xff'
    idat = chunk(b'IDAT', zlib.compress(raw))
    return sig + chunk(b'IHDR', ihdr) + idat + chunk(b'IEND', b'')


# ============================================================ тест 1: source-.db с обложкой ---
def test_source_db():
    png = make_png_2x2()
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        f.write(png)
        png_path = f.name

    tmpdb = tempfile.mktemp(suffix='.db')
    meta = {"title": "Test", "author": "Auth", "type": "CHB", "cover_file": png_path}
    struct_data = {"chapters": [{"song": "1", "number": 1, "title": "Гл1",
                                 "verses": [("1", "verse1")]}],
                   "song_names": {"1": "Раздел"}}
    counters = ai.write_source_db(struct_data, meta, tmpdb)

    con = sqlite3.connect(tmpdb)
    try:
        cov = con.execute("SELECT COUNT(*) FROM covers").fetchone()[0]
        check("source: covers COUNT == 1", cov == 1, cov)

        img = con.execute("SELECT LENGTH(content) FROM images WHERE image_id='COVER_SRC'").fetchone()
        img_len = img[0] if img else 0
        check("source: images content > 0", img_len > 0, img_len)
        check("source: content == PNG bytes", img_len == len(png), "%d vs %d" % (img_len, len(png)))
    finally:
        con.close()

    os.unlink(tmpdb)
    os.unlink(png_path)


# ============================================================ тест 2: recompose переносит ---
def test_recompose():
    png = make_png_2x2()
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        f.write(png)
        png_path = f.name

    src_db = tempfile.mktemp(suffix='.db')
    meta = {"title": "TestBook", "author": "Auth", "type": "CHB", "cover_file": png_path}
    struct_data = {"chapters": [{"song": "1", "number": 1, "title": "Гл1",
                                 "verses": [("1", "verse1"), ("2", "verse2")]}],
                   "song_names": {"1": "Раздел"}}
    ai.write_source_db(struct_data, meta, src_db)

    spec_path = tempfile.mktemp(suffix='.json')
    out_db = tempfile.mktemp(suffix='.db')
    spec = {"books": [{"file": src_db, "type": "CHB"}]}
    with open(spec_path, 'w') as f:
        json.dump(spec, f)

    result = recompose.build(spec_path, out_db, force=True)

    con = sqlite3.connect(out_db)
    try:
        cov_count = con.execute("SELECT COUNT(*) FROM covers").fetchone()[0]
        check("recompose: covers >= 1", cov_count >= 1, cov_count)

        img_row = con.execute("SELECT image_id, LENGTH(content) FROM images").fetchone()
        if img_row:
            check("recompose: images с content", img_row[1] > 0, img_row)
        else:
            check("recompose: images есть", False, "нет строк images")
    finally:
        con.close()

    os.unlink(src_db)
    os.unlink(spec_path)
    if os.path.exists(out_db):
        os.unlink(out_db)
    os.unlink(png_path)


# ============================================================ запуск ---
if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("=== тест обложки ===")
    test_source_db()
    test_recompose()
    if FAILED:
        print("\nFAIL:", ", ".join(FAILED))
    else:
        print("\nALL OK")
