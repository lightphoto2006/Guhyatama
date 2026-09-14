#!/usr/bin/env python3
"""Кладёт FFmpeg-DLL из av.libs рядом с torchcodec (нужно на Windows).

av ссылается на свои DLL по хеш-именам (avformat-62-<hash>.dll),
а torchcodec ищет канонические (avformat-62.dll) — копируем оба варианта.
Также чинит chained-зависимости (libgcc, zlib и т.п.).
Идемпотентно: повторный запуск просто перезаписывает те же файлы.
"""
import os
import re
import shutil

import av
import torchcodec

HASHED = re.compile(r"^(.+)-[0-9a-f]{30,40}\.dll$", re.I)

src = os.path.normpath(os.path.join(os.path.dirname(av.__file__), "..", "av.libs"))
dst = os.path.dirname(torchcodec.__file__)
n = locked = 0


def put(s, d):
    """Копия с терпением к блокировкам: если файл занят, но размер совпал — считаем годным."""
    global n, locked
    if os.path.isfile(d) and os.path.getsize(d) == os.path.getsize(s):
        n += 1
        return
    try:
        shutil.copy(s, d)
        n += 1
    except PermissionError:
        if os.path.isfile(d) and os.path.getsize(d) == os.path.getsize(s):
            locked += 1
        else:
            raise


for f in sorted(os.listdir(src)):
    if not f.lower().endswith(".dll"):
        continue
    put(os.path.join(src, f), os.path.join(dst, f))
    m = HASHED.match(f)
    if m:
        put(os.path.join(src, f), os.path.join(dst, m.group(1) + ".dll"))
print("dll-copied %d, locked-ok %d (%s -> %s)" % (n, locked, src, dst))
