#!/usr/bin/env python3
"""Аудит дефектов санскрита для Vagdhenu: те же классы, что у ШБ 1.2.23.
Проверяет КАЖДЫЙ стих источника и считает:
  - rutva-склейки (разорванные переносом слова вида तै|र्युक्तः)
  - двоеточия-висарги (पर: -> परः) и оторванные (स्यु :)
  - куски с безгласным началом (C+вирама первым), НЕ склеенные
  - куски-карлики (<4 акшар) и куски-переростки (>30, режутся на четверти)
  - строки дикторов, пустые санскриты, uneven/gadya метры
Печатает сводку + худшие примеры. Только stdlib.
  py vag_audit.py --src gitabase_texts_rus.db --books 2 [--chapters 1]
"""
import argparse
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from vagdhenu_shard import (split_padas, guess_meter, n_aksharas, laghu_guru,
                            is_leader, syllabify, _VIRAMA, parse_chapters)


def first_akshara_vowelless(piece):
    # Настоящий обрубок: кусок начинается НЕ с буквы — с вирамы, знака гласной,
    # анусвары/висарги ( ् / ि / ं / ः ). Конъюнкт в начале (स्त्री, ब्रह्म, र्य)
    # — легитимное начало слова, НЕ флаг.
    s = piece.lstrip()
    if not s:
        return False
    o = ord(s[0])
    if o == 0x094D:  # virama
        return True
    if 0x093E <= o <= 0x094C:  # зависимый знак гласной
        return True
    if o in (0x0902, 0x0903):  # анусвара/висарга первыми
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--books", default="")
    ap.add_argument("--chapters", default="")
    a = ap.parse_args()
    con = sqlite3.connect(a.src)
    want = set(x.strip() for x in a.books.split(",") if x.strip())
    songs_only, pairs = parse_chapters(a.chapters)
    stat = {"verses": 0, "rjoins": 0, "colons": 0, "float_vis": 0,
            "vowelless": [], "tiny": [], "huge": [], "leaders": 0,
            "empty": 0, "uneven": [], "gadya": []}
    rows = con.execute(
        "SELECT n.book_id,n.song,n.ch_no,n.txt_no,t.sanskrit"
        " FROM textnums n LEFT JOIN texts t ON t._id=n._id"
        " ORDER BY n.book_id,n.song,n.ch_no,n.txt_no")
    for r in rows:
        bid, song, ch, txt = str(r[0]), str(r[1]), str(r[2]), str(r[3])
        if want and bid not in want:
            continue
        if (songs_only or pairs) and song not in songs_only and (song, ch) not in pairs:
            continue
        raw = r[4] or ""
        vid = "%s.%s.%s" % (song, ch, txt)
        if not raw.strip():
            stat["empty"] += 1
            continue
        stat["verses"] += 1
        stat["colons"] += raw.count(":")
        if re.search(r"\s[ःं]", raw):
            stat["float_vis"] += 1
        padas, hemi, joins = split_padas(raw)
        stat["rjoins"] += joins
        stat["leaders"] += sum(1 for p in padas if is_leader(p))
        for i, p in enumerate(padas):
            n = n_aksharas(p)
            if n == 0:
                continue
            if n < 4:
                stat["tiny"].append((vid, p))
            if n > 30:
                stat["huge"].append((vid, n, p[:60]))
            # Обрубок: начинается не с буквы, и это НЕ первый кусок после диктора?
            # Показываем с контекстом прошлого куска для глазной проверки.
            if first_akshara_vowelless(p):
                prev = padas[i - 1][-30:] if i > 0 else "(начало)"
                stat["vowelless"].append((vid, "%s | %s" % (prev, p[:60])))
        meter, src = guess_meter(padas)
        if src == "uneven":
            stat["uneven"].append(vid)
        if meter == "gadya":
            stat["gadya"].append(vid)
    con.close()
    print("стихов: %d, пустых: %d" % (stat["verses"], stat["empty"]))
    print("рутва-склеек: %d, двоеточий: %d, оторванных висарг: %d, дикторов: %d"
          % (stat["rjoins"], stat["colons"], stat["float_vis"], stat["leaders"]))
    print("безгласных начал (не склеено): %d" % len(stat["vowelless"]))
    for v, p in stat["vowelless"][:15]:
        print("  %s :: %s" % (v, p))
    print("карликов (<4 акшар): %d" % len(stat["tiny"]))
    for v, p in stat["tiny"][:10]:
        print("  %s :: %s" % (v, p))
    print("переростков (>30): %d" % len(stat["huge"]))
    for v, n, p in stat["huge"][:10]:
        print("  %s (%d) :: %s" % (v, n, p))
    print("uneven: %d %s" % (len(stat["uneven"]), stat["uneven"][:10]))
    print("gadya: %d %s" % (len(stat["gadya"]), stat["gadya"][:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
