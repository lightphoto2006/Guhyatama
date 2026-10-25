#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_engine — автоматическая публикация книги одной кнопкой из вкладки «Дельта».

Читает versions.json, создаёт GitHub Release с ассетами (полный файл + дельта),
обновляет versions.json, запускает make_catalog, правит catalog.json, делает
git push и публикует catalog в релиз.
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request

import dbcommon
import gh_release

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
VERSIONS = os.path.join(ROOT, "updates", "versions.json")
CATALOG = os.path.join(ROOT, "updates", "catalog.json")
ROOT_CATALOG = os.path.join(ROOT, "catalog.json")


class PublishError(Exception):
    pass


def books_count(db_path):
    """Число книг в базе (0, если не открылась)."""
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
        try:
            return con.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        finally:
            con.close()
    except Exception:
        return 0


# ====================================================================== download_asset
# ======================================================================

def download_asset(token, repo, url_or_asset_url, out_path):
    """Скачать ассет релиза в out_path.

    Если url вида `https://api.github.com/repos/.../releases/assets/<id>` —
    GET с Authorization Bearer, Accept: application/octet-stream, следовать
    редиректам. Иначе скачать напрямую (простой GET).
    """
    api_pat = url_or_asset_url.find("/releases/assets/")
    if api_pat >= 0:
        # API URL ассета — нужен токен
        h = {
            "Accept": "application/octet-stream",
            "User-Agent": "dbcomposer/1.0",
        }
        if token:
            h["Authorization"] = "Bearer " + token
        req = urllib.request.Request(url_or_asset_url, headers=h)
        resp = urllib.request.urlopen(req, timeout=180)
        data = resp.read()
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)
        return out_path

    # Прямой URL — скачиваем без токена
    resp = urllib.request.urlopen(url_or_asset_url, timeout=180)
    data = resp.read()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path


# ====================================================================== merge_dbs
# ======================================================================

def merge_dbs(old_db, new_db, out_path, log=print):
    """Слияние двух баз: книги старой базы по порядку _id, затем новые (неповторяющиеся по type).

    spec для recompose.build:
      - сначала книги СТАРОЙ базы по порядку _id: {"file": old_db, "type": type}
      - затем книги НОВОЙ, тип которых ещё не встречался: {"file": new_db, "type": type}
      - если тип уже есть — заменить соответствующую запись старой базы на книгу из новой

    Возвращает (out_path, old_count, new_count, result_count).
    """
    def _get_books(db_path):
        """[(book_id, title, type), sorted by _id]."""
        con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
        try:
            rows = con.execute(
                "SELECT _id, title, type FROM books ORDER BY _id").fetchall()
            return rows
        finally:
            con.close()

    old_books = _get_books(old_db)
    new_books = _get_books(new_db)

    old_count = len(old_books)
    new_count = len(new_books)

    # Собираем spec: сначала старые по _id, затем новые (неповторяющиеся type)
    seen_types = set()
    spec_books = []

    # 1) Старые книги
    for bid, title, btype in old_books:
        bt = (btype or "").upper()
        spec_books.append({"file": old_db, "type": bt})
        seen_types.add(bt)

    # 2) Новые книги — только если тип ещё не встречался
    for bid, title, btype in new_books:
        bt = (btype or "").upper()
        if bt not in seen_types:
            spec_books.append({"file": new_db, "type": bt})
            seen_types.add(bt)
        # иначе: тип уже есть — заменяем (перезаписываем последнюю запись с этим типом)

    # Перезаписываем: если тип из новой базы уже был в старой — заменяем
    # Находим позицию и заменяем
    for bid, title, btype in new_books:
        bt = (btype or "").upper()
        if bt in seen_types:
            # Замена: ищем последнюю запись с этим type и заменяем
            for i in range(len(spec_books) - 1, -1, -1):
                if spec_books[i]["type"] == bt:
                    spec_books[i] = {"file": new_db, "type": bt}
                    break

    # Собираем spec
    spec = {"books": spec_books,
            "drop_error_rows": True,
            "drop_empty_verses": True,
            "dedupe": True,
            "drop_empty_chapters": False}

    # recompose.build принимает spec_path (файл) и out_path
    import recompose
    spec_path = out_path + ".spec.json"
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
    tmp_path = out_path + ".tmp"
    result = recompose.build(spec_path, tmp_path, force=True)
    # recompose.build атомарно подменяет tmp_path → out_path
    # Проверяем что файл существует
    if not os.path.isfile(out_path):
        if os.path.isfile(tmp_path):
            os.replace(tmp_path, out_path)
        else:
            raise RuntimeError("merge_dbs: сборка не создала файл: %s" % result)
    # Чистим временные
    for f in (spec_path,):
        try:
            os.remove(f)
        except OSError:
            pass

    # Считаем результат
    result_count = books_count(out_path)
    return (out_path, old_count, new_count, result_count)


# ====================================================================== publish_addition
# ======================================================================

def publish_addition(token, key, new_file, notes, log=print):
    """Добавить книги из new_file к существующему сборнику.

    1) Читаем meta = versions[books][key]; если нет — PublishError.
    2) old_file = meta["file"]; если не существует — скачать meta["url"] в %TEMP%.
    3) Слияние: merged = <key>_merged.db в F:\\AI\\Development\\Book DB\\.
    4) Дельта: make_delta old→merged в %TEMP% (--force).
    5) publish_book(..., new_file=merged, delta_file=delta, delta_from=int(meta["version"]),
       old_file=old_file, log=log).
    """
    with open(VERSIONS, encoding="utf-8") as f:
        versions_data = json.load(f)

    meta = versions_data.get("books", {}).get(key)
    if not meta:
        raise PublishError("ключ %s не найден в versions.json[books]" % key)

    old_file = meta.get("file", "")
    if old_file and not os.path.isfile(old_file):
        url = meta.get("url", "")
        if url:
            log("файл %s отсутствует, скачиваю из %s" % (old_file, url))
            tmp_dir = tempfile.gettempdir()
            old_file = os.path.join(tmp_dir, os.path.basename(old_file))
            download_asset(token, gh_release.FILES_REPO, url, old_file)
        else:
            raise PublishError("meta.file существует, но url пуст: %s" % key)

    # Слияние
    book_db_dir = r"F:\AI\Development\Book DB"
    os.makedirs(book_db_dir, exist_ok=True)
    merged_path = os.path.join(book_db_dir, "%s_merged.db" % key)
    log("merge_dbs: %s + %s → %s" % (os.path.basename(old_file), os.path.basename(new_file), os.path.basename(merged_path)))
    merge_dbs(old_file, new_file, merged_path, log)

    # Дельта
    delta_dir = tempfile.gettempdir()
    delta_path = os.path.join(delta_dir, "%s_delta.db" % key)
    log("make_delta: %s → %s" % (os.path.basename(old_file), os.path.basename(delta_path)))
    cmd = [
        sys.executable,
        os.path.join(HERE, "make_delta.py"),
        "--old", old_file,
        "--new", merged_path,
        "--out", delta_path,
        "--force",
    ]
    log("make_delta: запуск…")
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        creationflags=dbcommon.nowin(),
    )
    out_text = ((p.stdout or "") + (p.stderr or "")).strip()
    if p.returncode != 0:
        raise RuntimeError("make_delta: код %s\n%s" % (p.returncode, out_text[-800:]))
    log("make_delta: готово")

    # Публикация
    prev_version = int(meta.get("version", 0))
    return publish_book(
        token=token,
        key=key,
        new_file=merged_path,
        notes=notes,
        delta_file=delta_path,
        delta_from=prev_version,
        old_file=old_file,
        log=log,
    )


# ====================================================================== guess_key
# ======================================================================

def guess_key(old_file, data=None):
    """Пытаемся определить ключ книги по имени файла.

    Алгоритм:
    1. Сравниваем stem файла с basename из data[sec][key]["file"] (без регистра,
       убираем пробелы, _, -, точки).
    2. Затем — вхождение cleaned key в stem файла.

    Возвращает ключ или None.
    """
    if data is None:
        try:
            with open(VERSIONS, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None

    old_stem = os.path.splitext(os.path.basename(old_file))[0]

    for sec in ("books", "audio"):
        entries = data.get(sec, {})
        for key, meta in entries.items():
            fn = (meta.get("file") or "").strip()
            if not fn:
                continue
            # Убираем расширение из имени файла в meta
            meta_stem = os.path.splitext(os.path.basename(fn))[0]
            # Нормализация: убираем пробелы, _, -, точки, нижний регистр
            def _clean(s):
                return "".join(
                    c for c in s.lower()
                    if c.isalnum()
                )
            c_stem = _clean(old_stem)
            c_meta = _clean(meta_stem)
            if c_stem == c_meta:
                return key
            if c_meta and c_meta in c_stem:
                return key
    return None


# ====================================================================== publish_book
# ======================================================================

def _db_composition_changed(old_file, new_file):
    """Сравнивает состав книг и обложки двух баз.

    Возвращает True, если состав «плохой» (дельта отключается):
      - какая-то книга СТАРОЙ базы отсутствует в новой (по type), ИЛИ
      - у существующих (совпадающих по type) книг изменилась обложка (image sha).

    Добавление новых книг НЕ является причиной отключать дельту.
    """
    def _get_types(db_path):
        """{type: [book_id, ...]} — типы книг в базе."""
        con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
        try:
            rows = con.execute(
                "SELECT _id, type FROM books").fetchall()
            result = {}
            for book_id, btype in rows:
                bt = (btype or "").upper()
                result.setdefault(bt, []).append(book_id)
            return result
        finally:
            con.close()

    def _get_covers(db_path):
        """(book_id, sha256) для каждой обложки."""
        con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
        try:
            rows = con.execute(
                "SELECT c.book_id, i.content FROM covers c "
                "JOIN images i ON i.image_id = c.image_id "
                "ORDER BY c.book_id, c.image_id").fetchall()
            out = []
            for book_id, content in rows:
                h = hashlib.sha256()
                h.update(content)
                out.append((book_id, h.hexdigest()))
            return out
        except Exception:
            return []
        finally:
            con.close()

    old_types = _get_types(old_file)
    new_types = _get_types(new_file)

    # 1) Проверка: все типы старой базы присутствуют в новой
    for bt, old_bids in old_types.items():
        if bt not in new_types:
            return True  # книга старой базы отсутствует в новой

    # 2) Проверка обложек: для совпадающих по type книг — сравниваем sha
    old_covers = _get_covers(old_file)
    new_covers = _get_covers(new_file)

    # Собираем словарь book_id -> sha для каждой базы
    old_cover_map = dict(old_covers)
    new_cover_map = dict(new_covers)

    # Проверяем только книги, которые есть в старой базе (совпадающие по type)
    for bt, old_bids in old_types.items():
        new_bids = new_types.get(bt, [])
        for old_bid in old_bids:
            if old_bid in new_cover_map and old_bid in old_cover_map:
                if new_cover_map[old_bid] != old_cover_map[old_bid]:
                    return True  # обложка изменилась

    return False


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_make_catalog(log):
    """Запускает make_catalog.py и возвращает результат."""
    cmd = [
        sys.executable,
        os.path.join(HERE, "make_catalog.py"),
        "--src", os.path.join(ROOT, "DB"),
        "--out", CATALOG,
    ]
    log("make_catalog: запуск…")
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        creationflags=dbcommon.nowin(),
    )
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    if p.returncode != 0:
        raise PublishError("make_catalog: код %s\n%s" % (p.returncode, out[-800:]))
    log("make_catalog: ok")


def _patch_catalog(key, sec, size, sha, delta_size, delta_sha):
    """Правит updates/catalog.json: size/sha256 для ключа."""
    with open(CATALOG, encoding="utf-8") as f:
        catalog = json.load(f)

    entry = None
    for e in catalog.get(sec, []):
        if e.get("key") == key:
            entry = e
            break
    if entry is None:
        raise PublishError("в catalog.json нет записи %s.%s" % (sec, key))

    entry["size"] = size
    entry["sha256"] = sha
    if delta_size and delta_sha:
        entry["deltaSize"] = delta_size
        entry["deltaSha"] = delta_sha
    else:
        entry.pop("deltaSize", None)
        entry.pop("deltaSha", None)

    err = dbcommon.atomic_write_bytes(
        CATALOG,
        json.dumps(catalog, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    if err:
        raise PublishError("catalog.json запись: %s" % err)


def _copy_catalog_root():
    """Атомарная запись updates/catalog.json в корневой catalog.json."""
    with open(CATALOG, "rb") as f:
        err = dbcommon.atomic_write_bytes(ROOT_CATALOG, f.read())
    if err:
        raise PublishError("catalog.json корень: %s" % err)


def _git_push(files, msg):
    """git add/commit/push через subprocess."""
    def run(args, allow_fail=False):
        r = subprocess.run(
            ["git"] + args,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=dbcommon.nowin(),
        )
        if r.returncode != 0 and not allow_fail:
            raise PublishError("git %s: %s" % (args[0], (r.stderr or r.stdout)[-400:]))
        return r

    run(["add"] + files)
    r = run(["commit", "-m", msg, "--"] + files, allow_fail=True)
    if r.returncode != 0:
        pass  # уже есть коммиты — пушим без нового
    run(["push", "origin", "HEAD:main"])


def publish_book(token, key, new_file, notes, delta_file="", delta_from=0,
                 version=None, log=print, title=None, lang="rus", sec="books",
                 old_file=None):
    """Публикует книгу одной кнопкой.

    Если ``key`` уже есть в ``sec`` — обновляет запись.
    Если ``key`` отсутствует — создаёт новую запись (title обязателен).

    ``old_file`` — путь к предыдущей .db. Если задан вместе с ``delta_file``,
    сравнивает состав книг и обложки; при расхождении дельта игнорируется.

    Возвращает {"tag", "url", "size", "sha256", "delta_url", "version", "prev_version"}.
    """
    # 1) Читаем versions.json, определяем секцию
    with open(VERSIONS, encoding="utf-8") as f:
        versions_data = json.load(f)

    if key in versions_data.get("books", {}):
        sec = "books"
        old_key = True
    elif key in versions_data.get("audio", {}):
        sec = "audio"
        old_key = True
    else:
        # --- новая книга ---
        if not title:
            raise PublishError("для новой книги нужно название")
        meta = {"title": title, "lang": lang, "file": "", "version": 0,
                "url": "", "notes": "", "auth": "github"}
        versions_data.setdefault(sec, {})[key] = meta
        old_key = False
    meta = dict(versions_data[sec][key])

    # 2) Version и хэш
    prev_version = int(meta.get("version", 0))
    if version is None:
        version = prev_version + 1
    new_file_abs = os.path.abspath(new_file)
    new_sha = _sha256(new_file_abs)
    new_size = os.path.getsize(new_file_abs)
    log("файл: %s, v%d, size=%d, sha=%s" % (
        os.path.basename(new_file_abs), version, new_size, new_sha[:12]))

    # 3) Тег и тело релиза
    tag = gh_release.next_db_tag(token, gh_release.FILES_REPO)
    title = meta.get("title", key)
    lang = meta.get("lang", "")
    body_parts = [
        "%s — v%d (%s, %s)" % (title, version, key, lang),
    ]
    if notes:
        body_parts += ["", notes]
    body_parts += ["", "sha256 (%s): `%s`" % (os.path.basename(new_file_abs), new_sha)]
    body = "\n".join(body_parts)
    log("тег: %s → %s" % (tag, gh_release.FILES_REPO))

    # 4) create_release → upload_asset
    rel = gh_release.create_release(token, gh_release.FILES_REPO, tag, tag, body)
    rid = rel["id"]
    log("черновик создан (id %s)" % rid)
    up = gh_release.upload_asset(token, gh_release.FILES_REPO, rid, new_file_abs)
    full_url = gh_release.asset_api_url(gh_release.FILES_REPO, up["id"])
    log("ассет: %s" % full_url)

    # 5) Дельта
    delta_url = ""
    delta_size = 0
    delta_sha = ""
    delta_ok = False
    if delta_file and os.path.isfile(delta_file):
        if prev_version == 0:
            log("первая публикация — дельта не нужна")
        elif old_file and os.path.isfile(old_file):
            # Сравниваем состав книг и обложки old vs new
            if _db_composition_changed(old_file, new_file_abs):
                log("состав книг/обложки изменились — публикую полный файл")
            elif dbcommon.delta_is_useless(os.path.abspath(delta_file), new_file_abs):
                log("дельта бесполезна — публикую без неё")
            else:
                delta_abs = os.path.abspath(delta_file)
                up2 = gh_release.upload_asset(token, gh_release.FILES_REPO, rid, delta_abs)
                delta_url = gh_release.asset_api_url(gh_release.FILES_REPO, up2["id"])
                delta_size = up2.get("size") or os.path.getsize(delta_abs)
                delta_sha = _sha256(delta_abs)
                delta_ok = True
                log("дельта: %s (%d байт)" % (delta_url, delta_size))
        elif dbcommon.delta_is_useless(os.path.abspath(delta_file), new_file_abs):
            log("дельта бесполезна — публикую без неё")
        else:
            delta_abs = os.path.abspath(delta_file)
            up2 = gh_release.upload_asset(token, gh_release.FILES_REPO, rid, delta_abs)
            delta_url = gh_release.asset_api_url(gh_release.FILES_REPO, up2["id"])
            delta_size = up2.get("size") or os.path.getsize(delta_abs)
            delta_sha = _sha256(delta_abs)
            delta_ok = True
            log("дельта: %s (%d байт)" % (delta_url, delta_size))

    # 6) publish_release
    gh_release.publish_release(token, gh_release.FILES_REPO, rid)
    log("релиз опубликован: https://github.com/%s/releases/tag/%s" % (gh_release.FILES_REPO, tag))

    # 7) Обновляем versions.json (обновляем существующую запись, сохраняя поля)
    entry = versions_data[sec][key]
    entry.update({"title": title, "lang": lang, "file": new_file_abs,
                  "version": version, "url": full_url,
                  "notes": (notes or "").strip(), "auth": "github"})
    if delta_ok:
        entry["delta"] = {"from": delta_from, "file": delta_abs, "url": delta_url}
    else:
        entry.pop("delta", None)

    err = dbcommon.atomic_write_bytes(
        VERSIONS,
        json.dumps(versions_data, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    if err:
        raise PublishError("versions.json: %s" % err)
    log("versions.json обновлён")

    # 8) make_catalog
    _run_make_catalog(log)

    # 8.5) Для новой книги — создать запись в каталоге, если её нет
    if not old_key:
        with open(CATALOG, encoding="utf-8") as f:
            catalog_data = json.load(f)
        if not any(e.get("key") == key for e in catalog_data.get(sec, [])):
            catalog_data.setdefault(sec, []).append(
                {"key": key, "size": 0, "sha256": ""})
            err = dbcommon.atomic_write_bytes(
                CATALOG,
                json.dumps(catalog_data, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            if err:
                raise PublishError("catalog.json создание: %s" % err)

    # 9) Patch catalog + copy to root
    _patch_catalog(key, sec, new_size, new_sha, delta_size, delta_sha)
    _copy_catalog_root()
    log("каталог обновлён")

    # 10) Git push
    _git_push(
        files=["updates/versions.json", "updates/catalog.json", "catalog.json"],
        msg="books: %s v%d — каталог %s" % (key, version, tag),
    )
    log("git: запушено")

    # 11) Publish catalog
    gh_release.publish_catalog(token, ROOT_CATALOG)
    log("catalog.json опубликован")

    return {
        "tag": tag,
        "url": full_url,
        "size": new_size,
        "sha256": new_sha,
        "delta_url": delta_url if delta_ok else "",
        "version": version,
        "prev_version": prev_version,
    }
