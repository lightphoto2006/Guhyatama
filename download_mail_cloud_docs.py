#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скачивание всех .doc/.docx из публичной папки cloud.mail.ru
с группировкой по ГОЛОВНЫМ папкам (подпапки сплющиваются).

Источник: https://cloud.mail.ru/public/5NXL/5mk6cGm3U
Результат: <OUT>/<Имя головной папки>/<файлы>.doc[x]

- Токен не нужен: публичный API v4 + weblink_get из HTML страницы.
- Дубликаты имён (один и тот же файл лежит в разных подпапках):
  если размер совпадает — пропускаем, иначе сохраняем как "имя (2).docx".
- Повторный запуск докачивает недостающее (skip по размеру).
- Пишет manifest.csv: головная папка | исходный подпуть | исходное имя | сохранённое имя | размер | weblink

Запуск:
    python download_mail_cloud_docs.py
    python download_mail_cloud_docs.py --out mail_cloud_docs
    python download_mail_cloud_docs.py --list-only   # только посмотреть, сколько файлов
"""
import argparse
import csv
import re
import sys
import time
import urllib.parse
from pathlib import Path

try:
    import requests
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "requests"], check=True)
    import requests

PUBLIC_URL = "https://cloud.mail.ru/public/5NXL/5mk6cGm3U"
ROOT_WEBLINK = "5NXL/5mk6cGm3U"
API = "https://cloud.mail.ru/api/v4/public/list"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

ILLEGAL = '<>:"/\\|?*'


def sanitize(name: str) -> str:
    for ch in ILLEGAL:
        name = name.replace(ch, "_")
    name = name.strip().rstrip(".")
    return name or "_unnamed_"


def is_doc(name: str) -> bool:
    low = name.lower()
    return low.endswith(".doc") or low.endswith(".docx")


def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def get_weblink_get(s: requests.Session) -> str:
    r = s.get(PUBLIC_URL, timeout=30)
    r.raise_for_status()
    m = re.search(r'"weblink_get".*?"url"\s*:\s*"([^"]+)"', r.text)
    if not m:
        raise RuntimeError("Не нашёл weblink_get в HTML страницы. Возможно, Mail.ru поменял вёрстку.")
    return m.group(1)


def api_ls(s: requests.Session, weblink: str) -> dict:
    params = {"weblink": weblink, "sort": "name", "order": "asc",
              "offset": "0", "limit": "500", "version": "4"}
    for attempt in range(5):
        try:
            r = s.get(API, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 4:
                raise
            print(f"  retry ls ({attempt+1}/5) {weblink[:60]}: {e}", flush=True)
            time.sleep(2 + attempt * 2)


def download_url(wg_url: str, weblink: str) -> str:
    safe = "/".join(urllib.parse.quote(p, safe="") for p in weblink.split("/"))
    return f"{wg_url}/{safe}"


def download_file(s: requests.Session, url: str, dest: Path, expect_size: int) -> bool:
    """Качает с ретраями. Возвращает True при успехе."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size == expect_size:
        return True  # уже скачан
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(5):
        try:
            with s.get(url, stream=True, timeout=60, allow_redirects=True) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
            if expect_size and tmp.stat().st_size != expect_size:
                print(f"  размер не совпал {dest.name}: ждали {expect_size}, получили {tmp.stat().st_size}", flush=True)
                tmp.unlink(missing_ok=True)
                continue
            tmp.replace(dest)
            return True
        except Exception as e:
            print(f"  retry download ({attempt+1}/5) {dest.name}: {e}", flush=True)
            time.sleep(2 + attempt * 2)
    return False


def api_ls_all(s: requests.Session, weblink: str) -> list:
    """Все элементы папки с пагинацией (offset/limit), а не только первые 500."""
    items: list = []
    off = 0
    while True:
        params = {"weblink": weblink, "sort": "name", "order": "asc",
                  "offset": str(off), "limit": "500", "version": "4"}
        for attempt in range(5):
            try:
                r = s.get(API, params=params, timeout=30)
                r.raise_for_status()
                data = r.json()
                break
            except Exception as e:
                if attempt == 4:
                    raise
                print(f"  retry ls ({attempt+1}/5) {weblink[:60]}: {e}", flush=True)
                time.sleep(2 + attempt * 2)
        lst = data.get("list", [])
        items.extend(lst)
        if len(lst) < 500:
            break
        off += 500
    return items


def collect(s: requests.Session):
    """Обход: {top_name: [(rel_subpath, file_dict), ...]}"""
    tops = [it for it in api_ls_all(s, ROOT_WEBLINK) if it.get("type") == "folder"]
    grouped: dict[str, list] = {}
    for top in tops:
        tname = top["name"]
        twl = top["weblink"]
        found: list = []
        stack = [(twl, "")]
        while stack:
            wl, rel = stack.pop()
            for it in api_ls_all(s, wl):
                if it.get("type") == "folder":
                    sub = f"{rel}/{it['name']}" if rel else it["name"]
                    stack.append((it["weblink"], sub))
                else:
                    if is_doc(it.get("name", "")):
                        found.append((rel, it))
        grouped[tname] = found
    return grouped


def main():
    ap = argparse.ArgumentParser(description="Скачать doc/docx из cloud.mail.ru, сгруппировав по головным папкам")
    ap.add_argument("--out", default="mail_cloud_docs", help="Куда сложить папки (default: mail_cloud_docs)")
    ap.add_argument("--list-only", action="store_true", help="Только показать структуру, не качать")
    args = ap.parse_args()

    out = Path(args.out)
    s = get_session()

    print(f"Источник: {PUBLIC_URL}", flush=True)
    print("Получаю weblink_get ...", flush=True)
    wg = get_weblink_get(s)
    print(f"weblink_get: {wg}", flush=True)

    print("Сканирую папки (рекурсивно) ...", flush=True)
    grouped = collect(s)
    total = sum(len(v) for v in grouped.values())
    print(f"Головных папок: {len(grouped)}, doc/docx файлов: {total}", flush=True)
    for tname, files in grouped.items():
        print(f"  [{len(files):3d}] {tname}", flush=True)

    if args.list_only or total == 0:
        return

    out.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    ok, fail, skipped_dup = 0, 0, 0

    for tname, files in grouped.items():
        if not files:
            continue  # пустые головные папки локально не создаём
        top_dir = out / sanitize(tname)
        top_dir.mkdir(parents=True, exist_ok=True)
        used: dict[str, int] = {}  # saved_name.lower() -> size
        # подхватить уже существующие (для рерана без пересканирования дублей)
        for p in top_dir.iterdir():
            if p.is_file() and p.suffix != ".part" and p.name != "manifest.csv":
                used.setdefault(p.name.lower(), p.stat().st_size)

        for rel, it in files:
            orig = it["name"]
            size = it.get("size", 0)
            wl = it.get("weblink", "")
            if "." in orig:
                stem = orig.rsplit(".", 1)[0]
                ext = "." + orig.rsplit(".", 1)[1]
            else:
                stem, ext = orig, ""
            cand = orig
            key = cand.lower()
            if key in used:
                if used[key] == size and (top_dir / cand).exists():
                    skipped_dup += 1
                    manifest_rows.append([tname, rel, orig, cand, size, wl])
                    continue
                # коллизия имён — подбираем "имя (2).ext"
                i = 2
                while True:
                    cand = f"{stem} ({i}){ext}"
                    if cand.lower() not in used:
                        break
                    i += 1
            used[cand.lower()] = size
            dest = top_dir / sanitize(cand)
            # sanitize мог изменить имя — зафиксируем фактическое
            saved = dest.name
            url = download_url(wg, wl)
            tag = f"[{tname[:30]}] {orig}"
            if dest.exists() and dest.stat().st_size == size:
                ok += 1
                manifest_rows.append([tname, rel, orig, saved, size, wl])
                continue
            print(f"  ↓ {tag} -> {tname}/{saved} ({size} б)", flush=True)
            if download_file(s, url, dest, size):
                ok += 1
            else:
                fail += 1
                print(f"  ✗ НЕ СКАЧАЛСЯ: {tag}", flush=True)
            manifest_rows.append([tname, rel, orig, saved, size, wl])

    with open(out / "manifest.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["top_folder", "original_subpath", "original_name", "saved_name", "size", "weblink"])
        w.writerows(manifest_rows)

    print("=" * 60, flush=True)
    print(f"Готово. Успешно: {ok}, пропущено дублей: {skipped_dup}, ошибок: {fail}", flush=True)
    print(f"Папки лежат в: {out.resolve()}", flush=True)
    print(f"Соответствие исходных подпапок → файлам: {out.resolve() / 'manifest.csv'}", flush=True)


if __name__ == "__main__":
    main()
