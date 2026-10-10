#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_apk_delta — строит bsdiff-патч СТАРОГО APK к НОВОМУ для автообновления
приложения без скачивания целого APK (идея как в Play Market). Клиент
(app/.../data/update/Bspatch.kt) применяет патч к уже установленному APK
(applicationInfo.sourceDir) и воспроизводит новый подписанный APK
байт-в-байт — приватный ключ подписи клиенту не нужен.

Контейнер — BSDIFF40, но блоки (ctrl/diff/extra) пишутся В ОТКРЫТОМ виде,
без bzip2: на Android в stdlib нет bzip2-декомпрессора, поэтому тулза сама
распаковывает блоки стандартного bsdiff4 и пересобирает заголовок с длинами
несжатых блоков. Семантика magic "BSDIFF40" и троек (x, y, z) — без изменений.
Пустой deltaUrl в каталоге = дельты нет, клиент качает полный APK (fallback).

  py tools/dbcomposer/make_apk_delta.py --old old.apk --new new.apk --out patch.bsdiff [--force]

Нужен pip-пакет bsdiff4:  py -m pip install bsdiff4
Размер/хэш для каталога (deltaSize/deltaSha в секции "apk") считает
make_catalog.py; deltaFrom = versionCode старого APK, с которого патч применим.

ВНИМАНИЕ: патч строится от КОНКРЕТНОГО старого APK (байты установленного
файла, включая подпись). Пересоберённый старый APK с другими байтами — другая
основа, патч не ляжет (клиент тихо откатится на полный APK).
"""
import argparse
import bz2
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MAGIC = b"BSDIFF40"


def die(msg):
    """Внятная ошибка в stderr и выход с кодом 1."""
    sys.stderr.write("make_apk_delta: %s\n" % msg)
    sys.exit(1)


def read_bytes(path, label):
    """Прочитать файл целиком в bytes или внятно упасть."""
    if not os.path.exists(path):
        die("%s: файл не найден: %s" % (label, path))
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as e:
        die("%s: не читается (%s): %s" % (label, e, path))


def i64(b, off):
    """int64 в кодировке BSDIFF40 (encode/decode_int64 из bsdiff4/core.c):
    little-endian величина в байтах 0..6, знак — бит 0x80 байта 7.
    Для неотрицательных < 2^56 совпадает с обычным LE. Границы проверяют
    вызывающие."""
    x = b[off + 7] & 0x7F
    for i in range(6, -1, -1):
        x = (x << 8) | b[off + i]
    return -x if (b[off + 7] & 0x80) else x


def enc_i64(v):
    """int64 BSDIFF40 -> 8 байт (обратная к i64)."""
    sign = 0x80 if v < 0 else 0x00
    m = -v if v < 0 else v
    bs = bytearray(((m >> (8 * i)) & 0xFF) for i in range(8))
    bs[7] |= sign
    return bytes(bs)


def bz_decompress(block):
    """bz2.decompress, у которого пустой вход — пустой выход (а не EOFError)."""
    return bz2.decompress(block) if block else b""


def to_raw_container(patch):
    """BSDIFF40 со сжатыми (bzip2) блоками -> тот же BSDIFF40, но блоки в
    открытом виде: magic/тройки те же, ctrl_len и diff_len в заголовке —
    длины уже НЕСЖАТЫХ блоков, extra — остаток до конца файла. Ровно этот
    формат читает клиентский Bspatch.kt без bzip2 на борту."""
    if len(patch) < 32 or patch[:8] != MAGIC:
        raise ValueError("не BSDIFF40: magic не найден")
    ctrl_len, diff_len, newsize = i64(patch, 8), i64(patch, 16), i64(patch, 24)
    if ctrl_len < 0 or diff_len < 0 or newsize < 0:
        raise ValueError("битый патч: отрицательная длина в заголовке")
    c_end = 32 + ctrl_len
    e_start = c_end + diff_len
    if e_start > len(patch):
        raise ValueError("битый патч: блоки не влезают в файл")
    ctrl = bz_decompress(patch[32:c_end])
    diff = bz_decompress(patch[c_end:e_start])
    extra = bz_decompress(patch[e_start:])
    if len(ctrl) % 24:
        raise ValueError("битый патч: ctrl-блок не кратен тройке int64")
    header = (MAGIC + enc_i64(len(ctrl)) + enc_i64(len(diff)) + enc_i64(newsize))
    return header + ctrl + diff + extra


def raw_bspatch(old, patch):
    """Референс клиента (байт-в-байт mirror Bspatch.kt и bsdiff4/core.c patch):
    применяет патч из открытого контейнера к old и возвращает new.
    Тройка ctrl (x, y, z): x байт из diff складываются с old (вне границ old —
    берётся как есть), y байт копируются ИЗ extra, z — знаковый переход oldpos.
    Финал: newpos == newsize и оба блока израсходованы ровно до конца."""
    if len(patch) < 32 or patch[:8] != MAGIC:
        raise ValueError("битый патч")
    ctrl_len, diff_len, newsize = i64(patch, 8), i64(patch, 16), i64(patch, 24)
    if ctrl_len < 0 or diff_len < 0 or newsize < 0 or ctrl_len % 24:
        raise ValueError("битый патч")
    ctrl_end = 32 + ctrl_len
    diff_end = ctrl_end + diff_len
    if ctrl_end > len(patch) or diff_end > len(patch):
        raise ValueError("битый патч")
    new = bytearray(newsize)
    oldpos = 0
    newpos = 0
    d = ctrl_end       # diff-блок в открытом виде, сразу за ctrl
    e = diff_end       # extra-блок — остаток до конца файла
    c = 32
    while c + 24 <= ctrl_end:
        x = i64(patch, c)
        y = i64(patch, c + 8)
        z = i64(patch, c + 16)
        c += 24
        if x < 0 or y < 0:
            raise ValueError("битый патч")
        if x:
            if newpos + x > newsize or d + x > diff_end:
                raise ValueError("битый патч")
            for j in range(x):
                v = patch[d + j]
                oi = oldpos + j
                if 0 <= oi < len(old):
                    v = (v + old[oi]) & 0xFF
                new[newpos + j] = v
            newpos += x
            oldpos += x
            d += x
        if y:
            if newpos + y > newsize or e + y > len(patch):
                raise ValueError("битый патч")
            for j in range(y):
                new[newpos + j] = patch[e + j]
            newpos += y
            e += y
        oldpos += z
    if newpos != newsize or d != diff_end or e != len(patch):
        raise ValueError("битый патч")
    return bytes(new)


def build(old_path, new_path, out_path):
    try:
        import bsdiff4
    except ImportError:
        die("нужен пакет bsdiff4: py -m pip install bsdiff4")
    old = read_bytes(old_path, "old")
    new = read_bytes(new_path, "new")
    if not old:
        die("old: пустой файл")
    try:
        compressed = bsdiff4.diff(old, new)
    except Exception as e:  # noqa: BLE001 — выводим как есть, код 1
        die("bsdiff4 не смог построить патч: %s" % e)
    try:
        raw = to_raw_container(compressed)
    except (ValueError, OSError, EOFError) as e:
        die("не распечатать контейнер патча bsdiff4: %s" % e)
    # Самопроверка: клиентский алгоритм (тот же, что Bspatch.kt) обязан
    # воспроизвести new байт-в-байт — иначе такой патч клиенту нельзя отдавать
    try:
        got = raw_bspatch(old, raw)
    except ValueError as e:
        die("самопроверка патча не прошла (%s) — патч не записан" % e)
    if got != new:
        die("самопроверка: патч не воспроизводит new байт-в-байт — не записан")
    try:
        with open(out_path, "wb") as f:
            f.write(raw)
    except OSError as e:
        die("не записан --out (%s): %s" % (out_path, e))
    ratio = (len(raw) / len(new)) * 100.0 if new else 0.0
    print("old:    %d байт" % len(old))
    print("new:    %d байт" % len(new))
    print("patch:  %d байт (raw BSDIFF40, без bzip2)" % len(raw))
    print("патч/полный APK: %.2f%% (полная замена — %d байт)" % (ratio, len(new)))
    print("Самопроверка: new воспроизведён байт-в-байт — OK")
    print("Записан: %s" % out_path)


def main(argv):
    ap = argparse.ArgumentParser(
        description="bsdiff-патч СТАРОГО APK к НОВОМУ (raw BSDIFF40) — "
                    "для автообновления клиента без полного APK")
    ap.add_argument("--old", required=True, help="установленный APK (старая версия)")
    ap.add_argument("--new", required=True, help="новый APK (что патч должен воспроизвести)")
    ap.add_argument("--out", required=True, help="куда положить patch.bsdiff")
    ap.add_argument("--force", action="store_true",
                    help="перезаписать существующий --out")
    a = ap.parse_args(argv[1:])
    out = os.path.abspath(a.out)
    # без --force существующий файл не трогаем никогда
    if os.path.exists(out) and not a.force:
        die("--out уже существует: %s (перезапись — с --force)" % out)
    out_dir = os.path.dirname(out) or "."
    if not os.path.isdir(out_dir):
        die("нет папки для --out: %s" % out_dir)
    build(a.old, a.new, out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
