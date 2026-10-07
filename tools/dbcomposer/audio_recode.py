#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audio_recode — пакетное ужатие аудио для паков (только stdlib + внешний ffmpeg).
Шлоки по одной: MP3 64k моно -> Opus 24k моно (~x3 легче, голос тот же)
или MP3 32k моно (~x2, шаблон имён не меняется).

  py audio_recode.py --src "DB/SB audio/Split" --dst "DB/SB audio/Opus"
  py audio_recode.py --src ... --dst ... --mp3-32k [--jobs 8] [--force]

Структура подпапок сохраняется, имена — тоже (кроме расширения при opus).
Повторный прогон пропускает готовое (новее+тот же размер). Нужен ffmpeg
в PATH (проверяется стартом). Дальше пак собирается из --dst обычным
audio_pack (для opus шаблон-converted: "SB{song}.{ch}.{txt}.ogg").
"""
import argparse
import concurrent.futures
import os
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def find_ffmpeg():
    env = os.environ.get("AUDIO_FFMPEG", "").strip()
    if env and os.path.exists(env):
        return env
    return shutil.which("ffmpeg")


def plan_jobs(src, exts):
    jobs = []
    for root, _, fns in os.walk(src):
        for f in sorted(fns):
            if f.lower().endswith(exts):
                jobs.append(os.path.join(root, f))
    return jobs


def convert_one(ffmpeg, src, dst, mode, force):
    if os.path.exists(dst) and not force:
        try:
            if (os.path.getsize(dst) > 1024 and
                    os.path.getmtime(dst) >= os.path.getmtime(src)):
                return "skip"
        except OSError:
            pass
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    if mode == "opus":
        args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
                "-ac", "1", "-ar", "24000", "-c:a", "libopus", "-b:a", "24k",
                "-application", "audio", dst]
    else:
        args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
                "-ac", "1", "-ar", "24000", "-c:a", "libmp3lame", "-b:a", "32k",
                dst]
    try:
        r = subprocess.run(args, capture_output=True, timeout=600,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        return "err:%s" % e
    if r.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) < 1024:
        try:
            os.remove(dst)
        except OSError:
            pass
        return "err:ffmpeg-%s" % (r.returncode if r else "?")
    return "ok"


def main(argv):
    ap = argparse.ArgumentParser(description="Ужатие аудио для паков (нужен ffmpeg)")
    ap.add_argument("--src", required=True, help="папка с исходниками (рекурсивно)")
    ap.add_argument("--dst", required=True, help="куда класть результат")
    ap.add_argument("--mp3-32k", action="store_true",
                    help="вместо opus: MP3 32k моно (имена/шаблон не меняются)")
    ap.add_argument("--jobs", type=int, default=4, help="параллельных ffmpeg (по умолч. 4)")
    ap.add_argument("--force", action="store_true", help="перекодировать заново всё")
    a = ap.parse_args(argv[1:])
    if not os.path.isdir(a.src):
        print("Нет папки: %s" % a.src)
        return 1
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("Нет ffmpeg в PATH (или AUDIO_FFMPEG). Установи и повтори.")
        return 1
    mode = "mp332" if a.mp3_32k else "opus"
    exts = (".mp3", ".ogg", ".opus", ".wav", ".m4a", ".flac")
    jobs = plan_jobs(a.src, exts)
    if not jobs:
        print("Аудиофайлов не найдено в %s" % a.src)
        return 1
    print("Файлов: %d, режим: %s, потоков: %d" % (len(jobs), mode, max(a.jobs, 1)))

    def one(src):
        rel = os.path.relpath(src, a.src)
        base, _ = os.path.splitext(rel)
        dst = os.path.join(a.dst, base + (".mp3" if mode == "mp332" else ".ogg"))
        st = convert_one(ffmpeg, src, dst, mode, a.force)
        try:
            s0 = os.path.getsize(src)
            s1 = os.path.getsize(dst) if st in ("ok", "skip") else 0
        except OSError:
            s0, s1 = 0, 0
        return st, s0, s1

    stat = {"ok": 0, "skip": 0}
    errs = []
    b0 = b1 = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(a.jobs, 1)) as ex:
        for st, s0, s1 in ex.map(one, jobs):
            b0 += s0
            b1 += s1
            if st == "ok":
                stat["ok"] += 1
            elif st == "skip":
                stat["skip"] += 1
            else:
                errs.append(st)
    print("Готово: %d, пропущено готовых: %d, ошибок: %d" % (stat["ok"], stat["skip"], len(errs)))
    for e in errs[:10]:
        print("  %s" % e)
    if b0:
        print("Вес: %.0f МБ -> %.0f МБ (x%.1f)" % (b0 / 1048576, b1 / 1048576, b0 / max(b1, 1)))
    if mode == "opus":
        print("Шаблон для audio_pack теперь: с .mp3 на .ogg "
              "(напр. \"SB{song}.{ch}.{txt}.ogg\")")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
