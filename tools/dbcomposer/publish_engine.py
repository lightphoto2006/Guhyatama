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
import subprocess
import sys

import dbcommon
import gh_release

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
VERSIONS = os.path.join(ROOT, "updates", "versions.json")
CATALOG = os.path.join(ROOT, "updates", "catalog.json")
ROOT_CATALOG = os.path.join(ROOT, "catalog.json")


class PublishError(Exception):
    pass


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
                 version=None, log=print, title=None, lang="rus", sec="books"):
    """Публикует книгу одной кнопкой.

    Если ``key`` уже есть в ``sec`` — обновляет запись.
    Если ``key`` отсутствует — создаёт новую запись (title обязателен).

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
        sec = "books"
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
        delta_abs = os.path.abspath(delta_file)
        if dbcommon.delta_is_useless(delta_abs, new_file_abs):
            log("дельта бесполезна — публикую без неё")
        else:
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
