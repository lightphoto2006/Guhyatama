#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_catalog — собирает catalog.json для автообновлений из готовых файлов.
Версии/названия/ссылки/«что нового» — в updates/versions.json (правится руками),
сюда дописываются только размер и sha256 с реальных файлов.

  py tools/dbcomposer/make_catalog.py --src DB --out updates/catalog.json

Секции: apk (руками в versions.json), books (файлы .db), audio (аудиопаки .db,
дельты — позже). Ключ книги стабилен (имя файла-источника), версия растёт
с каждым выпуском — приложение сравнивает и качает только новое.

При отсутствии исходных .db в --src: берёт size/sha256 из существующего
выходного каталога (--out), если там есть запись с тем же ключом и URL.
Если и там пусто — оставляет 0/"" и печатает «ФАЙЛ НЕ НАЙДЕН … (размеров нет)».
"""
import argparse
import hashlib
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbcommon  # noqa: E402  (эталонная логика лежит рядом со скриптом)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def is_gallery(preview):
    # один эталон на движок, каталог и приложение — иначе fp расходится со сборкой
    return dbcommon.is_gallery(preview)


def fingerprint(p):
    """Отпечаток книг файла: [{t,g,l?,v}] — тип, _id, число стихов без строк-галерей
    (галереи в приложение не едут — см. LibraryDbImporter.isGalleryRow).
    Приложение сверяет со своим содержимым и усыновляет уже стоящие книги
    (ставили вручную из телеграма) без повторного скачивания.
    Открытие строго read-only: раньше фолбэк открывал БД на запись (sidecar/WAL
    рядом с источником), а ошибки глохли молча."""
    out = []
    try:
        con = dbcommon.connect_ro(p)
    except Exception as e:
        print("  fingerprint %s: не открылось (%s)" % (os.path.basename(p), e))
        return out
    try:
        books = list(con.execute("SELECT _id,type FROM books"))
        for bid, typ in books:
            try:
                rows = con.execute(
                    "SELECT preview FROM textnums WHERE book_id=?", (bid,)).fetchall()
                n = sum(1 for (pr,) in rows if not is_gallery(pr))
                # vg: как было до чистки галерей (старые импорты тащили их в verses,
                # миграция v9 их потом сносила — усыновляем и такие)
                out.append({"t": str(typ or "").lower(), "g": int(bid),
                            "v": n, "vg": len(rows)})
            except Exception as e:
                print("  fingerprint %s/#%s: %s" % (os.path.basename(p), bid, e))
    except Exception as e:
        print("  fingerprint %s: %s" % (os.path.basename(p), e))
    try:
        con.close()
    except Exception:
        pass
    return out


def _load_prev_catalog(out_path):
    """Загрузить предыдущий каталог из --out, если он существует.
    Если --out не существует (первый запуск) — пробуем updates/catalog.json."""
    candidates = [out_path]
    # fallback: если --out не существует, берём updates/catalog.json
    if out_path and not os.path.exists(out_path):
        fallback = os.path.join(ROOT, "updates", "catalog.json")
        if fallback not in candidates and os.path.exists(fallback):
            candidates.append(fallback)
    for path in candidates:
        try:
            with open(path, encoding="utf-8") as f:
                cat = json.load(f)
            # Build lookup: (section, key) -> {size, sha256, url}
            prev = {}
            for section_name in ("books", "audio"):
                for item in cat.get(section_name, []):
                    prev[(section_name, item["key"])] = {
                        "size": item.get("size", 0),
                        "sha256": item.get("sha256", ""),
                        "url": item.get("url", ""),
                    }
            return prev
        except Exception:
            continue
    return {}


def main(argv):
    ap = argparse.ArgumentParser(description="Сборка catalog.json для автообновлений")
    ap.add_argument("--src", default=os.path.join(ROOT, "DB"),
                    help="папка с готовыми .db (по умолч. DB)")
    ap.add_argument("--versions", default=os.path.join(ROOT, "updates", "versions.json"),
                    help="sidecar с версиями/ссылками/«что нового»")
    ap.add_argument("--out", default=os.path.join(ROOT, "updates", "catalog.json"),
                    help="куда писать каталог")
    a = ap.parse_args(argv[1:])
    if not os.path.exists(a.versions):
        print("Нет sidecar: %s (образец: updates/versions.example.json)" % a.versions)
        return 1

    # Загружаем предыдущий каталог для fallback size/sha256
    prev_catalog = _load_prev_catalog(a.out)

    with open(a.versions, encoding="utf-8") as f:
        side = json.load(f)

    def section(name):
        items = []
        for key, meta in (side.get(name) or {}).items():
            fn = meta.get("file", "")
            p = fn if os.path.isabs(fn) else os.path.join(a.src, fn)
            entry = {"key": key, "title": meta.get("title", key),
                     "version": int(meta.get("version", 0)),
                     "url": meta.get("url", ""), "notes": meta.get("notes", "")}
            if "lang" in meta:
                entry["lang"] = meta["lang"]
            if "auth" in meta:
                entry["auth"] = meta["auth"]
            # дельта для растущих баз: размер/хэш с файла, from — из sidecar
            if "delta" in meta and isinstance(meta["delta"], dict):
                dm = meta["delta"]
                dfn = dm.get("file", "")
                dp = dfn if os.path.isabs(dfn) else os.path.join(a.src, dfn)
                entry["deltaFrom"] = int(dm.get("from", -1))
                if os.path.exists(dp):
                    entry["deltaUrl"] = dm.get("url", "")
                    entry["deltaSize"] = os.path.getsize(dp)
                    entry["deltaSha"] = sha256(dp)
                    print("  delta %s: v%s, %.0f МБ ok" % (
                        key, entry["deltaFrom"], entry["deltaSize"] / 1048576))
                else:
                    entry["deltaUrl"] = ""
                    entry["deltaSize"] = 0
                    entry["deltaSha"] = ""
                    print("  delta %s: ФАЙЛ НЕ НАЙДЕН (%s)" % (key, dp))
            # adopt=false: текстовые правки при том же числе стихов (усыновление
            # по счётчикам их бы пропустило) — только books
            if name == "books" and meta.get("adopt") is False:
                entry["adopt"] = False
            if os.path.exists(p):
                entry["size"] = os.path.getsize(p)
                entry["sha256"] = sha256(p)
                if name == "books":
                    fp = fingerprint(p)
                    if fp:
                        entry["fp"] = fp
                print("%s/%s: v%s, %.0f МБ ok" % (
                    name, key, entry["version"], entry["size"] / 1048576))
            else:
                # Файл не найден в --src: пробуем взять size/sha256 из предыдущего каталога
                prev_key = (name, key)
                if prev_key in prev_catalog:
                    prev_entry = prev_catalog[prev_key]
                    # Проверяем, что URL совпадает
                    if prev_entry["url"] == entry["url"]:
                        if prev_entry["size"] > 0 and prev_entry["sha256"]:
                            entry["size"] = prev_entry["size"]
                            entry["sha256"] = prev_entry["sha256"]
                            print("%s/%s: ФАЙЛ НЕ НАЙДЕН (%s) — размеры из прошлого каталога" % (
                                name, key, p))
                        else:
                            entry["size"] = 0
                            entry["sha256"] = ""
                            print("%s/%s: ФАЙЛ НЕ НАЙДЕН (%s) — (размеров нет)" % (
                                name, key, p))
                    else:
                        entry["size"] = 0
                        entry["sha256"] = ""
                        print("%s/%s: ФАЙЛ НЕ НАЙДЕН (%s) — (размеров нет)" % (
                            name, key, p))
                else:
                    entry["size"] = 0
                    entry["sha256"] = ""
                    print("%s/%s: ФАЙЛ НЕ НАЙДЕН (%s) — (размеров нет)" % (
                        name, key, p))
            items.append(entry)
        return items

    # apk: размер и sha256 — с файла APK (в sidecar только "file"), дельта —
    # так же, как у books (см. section выше): владелец пишет в versions.json
    # "file" (путь к APK) и "delta": {file,url,from}.
    # size/sha256 у APK ОБЯЗАТЕЛЬНЫ: клиент без sha256 отменяет обновление
    # (AppUpdater.download: "в каталоге нет контрольной суммы — обновление
    # отменено"), поэтому считаем их здесь, а не руками.
    apk = dict(side.get("apk") or {})  # копия: не мутируем исходный side
    afn = apk.get("file", "")
    if afn:
        ap = afn if os.path.isabs(apk.get("file", "")) else os.path.join(a.src, afn)
        if os.path.exists(ap):
            apk["size"] = os.path.getsize(ap)
            apk["sha256"] = sha256(ap)
            print("  apk: %d байт, sha ok" % apk["size"])
        else:
            apk["size"] = 0
            apk["sha256"] = ""
            print("  apk: ФАЙЛ НЕ НАЙДЕН (%s) — sha пустой, обновление не скачается" % ap)
    dm = apk.get("delta")
    if isinstance(dm, dict):
        dfn = dm.get("file", "")
        dp = dfn if os.path.isabs(dfn) else os.path.join(a.src, dfn)
        apk["deltaFrom"] = int(dm.get("from", -1))
        if os.path.exists(dp):
            apk["deltaUrl"] = dm.get("url", "")
            apk["deltaSize"] = os.path.getsize(dp)
            apk["deltaSha"] = sha256(dp)
            print("  apk delta: v%s, %.0f МБ ok" % (
                apk["deltaFrom"], apk["deltaSize"] / 1048576))
        else:
            apk["deltaUrl"] = ""
            apk["deltaSize"] = 0
            apk["deltaSha"] = ""
            print("  apk delta: ФАЙЛ НЕ НАЙДЕН (%s)" % dp)

    cat = {"catalogVersion": 1, "apk": apk,
           "books": section("books"), "audio": section("audio")}
    # атомарно: обрыв посреди записи не должен оставить полукаталог
    err = dbcommon.atomic_write_bytes(
        a.out, json.dumps(cat, ensure_ascii=False, indent=2).encode("utf-8"))
    if err:
        print("КАТАЛОГ НЕ ЗАПИСАН (%s): %s" % (a.out, err))
        return 1
    print("Записан: %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
