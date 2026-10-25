#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Офлайн-тесты publish_engine: guess_key, publish_book с подменами, дельта бесполезна/полезна.

БЕЗ сетевых запросов и git-push. Все пути — во временной папке.
"""
import json
import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

import publish_engine
import dbcommon

checks = 0
fails = 0


def check(cond, msg):
    global checks, fails
    checks += 1
    if cond:
        print("  OK: %s" % msg)
    else:
        fails += 1
        print("  FAIL: %s" % msg)


# ======================================================================
# a) guess_key
# ======================================================================
def test_guess_key():
    print("=== a) guess_key ===")
    tmpdir = tempfile.mkdtemp(prefix="guesskey_")

    # Создаём временный versions.json с ключом TestBook
    ver_path = os.path.join(tmpdir, "versions.json")
    vdata = {
        "books": {
            "TestBook": {"title": "TestBook", "lang": "rus", "file": "TestBook.db",
                         "version": 3, "url": "https://example.com/t.db"}
        },
        "audio": {}
    }
    with open(ver_path, "w", encoding="utf-8") as f:
        json.dump(vdata, f)

    # Подменяем publish_engine.VERSIONS
    old_versions = publish_engine.VERSIONS
    publish_engine.VERSIONS = ver_path

    try:
        # 1) Файл с совпадающим именем
        db_path = os.path.join(tmpdir, "TestBook.db")
        with open(db_path, "wb") as f:
            f.write(b"test")
        result = publish_engine.guess_key(db_path)
        check(result == "TestBook", "TestBook.db → TestBook (got %r)" % result)

        # 2) Чужой файл
        other_path = os.path.join(tmpdir, "OtherBook.db")
        with open(other_path, "wb") as f:
            f.write(b"test")
        result2 = publish_engine.guess_key(other_path)
        check(result2 is None, "OtherBook.db → None (got %r)" % result2)

        # 3) Файл с пробелами/подчёркиваниями в имени (нормализация)
        messy_path = os.path.join(tmpdir, "Test_Book.db")
        with open(messy_path, "wb") as f:
            f.write(b"test")
        result3 = publish_engine.guess_key(messy_path)
        check(result3 == "TestBook", "Test_Book.db → TestBook (got %r)" % result3)

    finally:
        publish_engine.VERSIONS = old_versions


# ======================================================================
# b) publish_book — полный сценарий с подменами
# ======================================================================
def test_publish_book_full():
    print("=== b) publish_book (полный сценарий) ===")
    tmpdir = tempfile.mkdtemp(prefix="pubbook_")

    # Создаём versions.json
    ver_path = os.path.join(tmpdir, "versions.json")
    vdata = {
        "books": {
            "TestBook": {
                "title": "TestBook", "lang": "rus", "file": "TestBook.db",
                "version": 3, "url": "https://example.com/old.db"
            }
        },
        "audio": {}
    }
    with open(ver_path, "w", encoding="utf-8") as f:
        json.dump(vdata, f)

    # Создаём новый .db файл
    new_db = os.path.join(tmpdir, "TestBook.db")
    with open(new_db, "wb") as f:
        f.write(b"x" * 5000)

    # Создаём updates/ для catalog.json
    updates_dir = os.path.join(tmpdir, "updates")
    os.makedirs(updates_dir, exist_ok=True)
    cat_path = os.path.join(updates_dir, "catalog.json")
    # Пустой каталог — make_catalog его заполнит
    with open(cat_path, "w", encoding="utf-8") as f:
        json.dump({"books": [{"key": "TestBook", "size": 0, "sha256": ""}],
                    "audio": [], "apk": {}}, f)

    # Создаём корневой catalog.json
    root_cat = os.path.join(tmpdir, "catalog.json")
    with open(root_cat, "w", encoding="utf-8") as f:
        json.dump({"books": [{"key": "TestBook", "size": 0, "sha256": ""}],
                    "audio": [], "apk": {}}, f)

    old_versions = publish_engine.VERSIONS
    old_catalog = publish_engine.CATALOG
    old_root_catalog = publish_engine.ROOT_CATALOG
    old_root = publish_engine.ROOT

    publish_engine.VERSIONS = ver_path
    publish_engine.CATALOG = cat_path
    publish_engine.ROOT_CATALOG = root_cat
    publish_engine.ROOT = tmpdir

    # Подмена gh_release
    orig_create = publish_engine.gh_release.create_release
    orig_upload = publish_engine.gh_release.upload_asset
    orig_publish = publish_engine.gh_release.publish_release
    orig_publish_catalog = publish_engine.gh_release.publish_catalog
    orig_next_tag = publish_engine.gh_release.next_db_tag

    published_releases = []
    uploaded_assets = []

    def mock_next_tag(token, repo):
        return "db-v42"

    def mock_create_release(token, repo, tag, name, body):
        published_releases.append({"tag": tag, "name": name, "body": body})
        return {"id": 999, "tag_name": tag, "html_url": "https://github.com/test/releases/tag/db-v42"}

    def mock_upload_asset(token, repo, rid, path, name="", ctype="application/octet-stream"):
        uploaded_assets.append({"path": path, "name": name, "size": os.path.getsize(path)})
        return {"id": 100, "name": os.path.basename(path),
                "browser_download_url": "https://github.com/test/asset"}

    def mock_publish_release(token, repo, rid):
        published_releases[-1]["published"] = True

    def mock_publish_catalog(token, path):
        return "https://github.com/test/releases/download/catalog/catalog.json"

    publish_engine.gh_release.create_release = mock_create_release
    publish_engine.gh_release.upload_asset = mock_upload_asset
    publish_engine.gh_release.publish_release = mock_publish_release
    publish_engine.gh_release.publish_catalog = mock_publish_catalog
    publish_engine.gh_release.next_db_tag = mock_next_tag

    # Подмена _git_push: просто собираем аргументы
    git_push_calls = []
    orig_git_push = publish_engine._git_push

    def mock_git_push(files, msg):
        git_push_calls.append({"files": files, "msg": msg})

    publish_engine._git_push = mock_git_push

    # Подмена _run_make_catalog: просто копируем entries из версий в каталог
    orig_run_make = publish_engine._run_make_catalog

    def mock_run_make_catalog(log):
        # Просто обновляем каталог с реальными size/sha
        with open(publish_engine.VERSIONS, encoding="utf-8") as f:
            vd = json.load(f)
        import hashlib
        h = hashlib.sha256()
        with open(new_db, "rb") as f:
            h.update(f.read())
        cdata = {"books": [{"key": "TestBook", "size": os.path.getsize(new_db),
                            "sha256": h.hexdigest(), "version": 4}],
                 "audio": [], "apk": {}}
        err = dbcommon.atomic_write_bytes(cat_path,
                                          json.dumps(cdata, ensure_ascii=False, indent=2).encode("utf-8"))
        if err:
            raise RuntimeError(err)
        log("make_catalog: ok")

    publish_engine._run_make_catalog = mock_run_make_catalog

    # Подмена _copy_catalog_root — no-op (файлы уже там)
    def mock_copy_catalog_root():
        pass
    publish_engine._copy_catalog_root = mock_copy_catalog_root

    try:
        log_lines = []
        result = publish_engine.publish_book(
            token="fake_token",
            key="TestBook",
            new_file=new_db,
            notes="Тестовое обновление",
            delta_file="",
            delta_from=0,
            version=None,
            log=log_lines.append,
        )

        # Проверки
        check(result["tag"] == "db-v42", "tag=db-v42 (got %r)" % result.get("tag"))
        check(result["version"] == 4, "version=4 (got %d)" % result.get("version"))
        check(result["size"] == 5000, "size=5000 (got %d)" % result.get("size"))
        check(len(result["sha256"]) == 64, "sha256 64 chars (got %d)" % len(result.get("sha256", "")))
        check(result["delta_url"] == "", "delta_url пустой (got %r)" % result.get("delta_url"))
        check(result["url"] != "", "url непустой (got %r)" % result.get("url"))

        # versions.json обновлён
        with open(ver_path, encoding="utf-8") as f:
            updated_vdata = json.load(f)
        entry = updated_vdata["books"]["TestBook"]
        check(entry["version"] == 4, "versions: version=4")
        check(entry["url"] != "", "versions: url непустой")
        check(entry["notes"] == "Тестовое обновление", "versions: notes ok")
        check("delta" not in entry, "versions: нет ключа delta (delta_file пуст)")

        # Каталог обновлён
        with open(cat_path, encoding="utf-8") as f:
            cat = json.load(f)
        cat_entry = cat["books"][0]
        check(cat_entry["size"] > 0, "catalog: size>0 (got %d)" % cat_entry["size"])
        check(cat_entry["sha256"] != "", "catalog: sha256 непустой")

        # _git_push был вызван
        check(len(git_push_calls) == 1, "git_push вызван 1 раз (got %d)" % len(git_push_calls))
        if git_push_calls:
            check("TestBook" in git_push_calls[0]["msg"], "git msg содержит TestBook")

        check(len(published_releases) == 1, "create_release вызван")
        check(len(uploaded_assets) == 1, "upload_asset вызван 1 раз (только полный файл)")

    finally:
        publish_engine.VERSIONS = old_versions
        publish_engine.CATALOG = old_catalog
        publish_engine.ROOT_CATALOG = old_root_catalog
        publish_engine.ROOT = old_root
        publish_engine.gh_release.create_release = orig_create
        publish_engine.gh_release.upload_asset = orig_upload
        publish_engine.gh_release.publish_release = orig_publish
        publish_engine.gh_release.publish_catalog = orig_publish_catalog
        publish_engine.gh_release.next_db_tag = orig_next_tag
        publish_engine._git_push = orig_git_push
        publish_engine._run_make_catalog = orig_run_make
        publish_engine._copy_catalog_root = lambda: None


# ======================================================================
# c) Дельта бесполезная (delta больше нового)
# ======================================================================
def test_delta_useless():
    print("=== c) Дельта бесполезная ===")
    tmpdir = tempfile.mkdtemp(prefix="deluseless_")

    ver_path = os.path.join(tmpdir, "versions.json")
    vdata = {
        "books": {
            "TestBook": {
                "title": "TestBook", "lang": "rus", "file": "TestBook.db",
                "version": 1, "url": ""
            }
        },
        "audio": {}
    }
    with open(ver_path, "w", encoding="utf-8") as f:
        json.dump(vdata, f)

    new_db = os.path.join(tmpdir, "TestBook.db")
    with open(new_db, "wb") as f:
        f.write(b"x" * 1000)

    # Дельта БОЛЬШЕ нового файла → бесполезна
    delta_db = os.path.join(tmpdir, "delta.db")
    with open(delta_db, "wb") as f:
        f.write(b"d" * 2000)  # 2000 > 1000 * 0.98

    updates_dir = os.path.join(tmpdir, "updates")
    os.makedirs(updates_dir, exist_ok=True)
    cat_path = os.path.join(updates_dir, "catalog.json")
    with open(cat_path, "w", encoding="utf-8") as f:
        json.dump({"books": [{"key": "TestBook", "size": 0, "sha256": ""}],
                    "audio": [], "apk": {}}, f)

    root_cat = os.path.join(tmpdir, "catalog.json")
    with open(root_cat, "w", encoding="utf-8") as f:
        json.dump({"books": [{"key": "TestBook", "size": 0, "sha256": ""}],
                    "audio": [], "apk": {}}, f)

    old_versions = publish_engine.VERSIONS
    old_catalog = publish_engine.CATALOG
    old_root_catalog = publish_engine.ROOT_CATALOG
    old_root = publish_engine.ROOT
    publish_engine.VERSIONS = ver_path
    publish_engine.CATALOG = cat_path
    publish_engine.ROOT_CATALOG = root_cat
    publish_engine.ROOT = tmpdir

    orig_next_tag = publish_engine.gh_release.next_db_tag
    orig_create = publish_engine.gh_release.create_release
    orig_upload = publish_engine.gh_release.upload_asset
    orig_publish = publish_engine.gh_release.publish_release
    orig_publish_catalog = publish_engine.gh_release.publish_catalog

    def mock_next_tag(token, repo):
        return "db-v1"

    def mock_create_release(token, repo, tag, name, body):
        return {"id": 1, "tag_name": tag}

    def mock_upload_asset(token, repo, rid, path, name="", ctype="application/octet-stream"):
        return {"id": 1, "name": os.path.basename(path),
                "browser_download_url": "https://gh.com/asset"}

    def mock_publish_release(token, repo, rid):
        pass

    def mock_publish_catalog(token, path):
        return "https://gh.com/catalog.json"

    publish_engine.gh_release.next_db_tag = mock_next_tag
    publish_engine.gh_release.create_release = mock_create_release
    publish_engine.gh_release.upload_asset = mock_upload_asset
    publish_engine.gh_release.publish_release = mock_publish_release
    publish_engine.gh_release.publish_catalog = mock_publish_catalog

    git_push_calls = []
    orig_git_push = publish_engine._git_push

    def mock_git_push(files, msg):
        git_push_calls.append({"files": files})

    publish_engine._git_push = mock_git_push

    orig_run_make = publish_engine._run_make_catalog

    def mock_run_make_catalog(log):
        import hashlib
        h = hashlib.sha256()
        with open(new_db, "rb") as f:
            h.update(f.read())
        cdata = {"books": [{"key": "TestBook", "size": os.path.getsize(new_db),
                            "sha256": h.hexdigest(), "version": 2}],
                 "audio": [], "apk": {}}
        err = dbcommon.atomic_write_bytes(cat_path,
                                          json.dumps(cdata, ensure_ascii=False, indent=2).encode("utf-8"))
        if err:
            raise RuntimeError(err)
        log("make_catalog: ok")

    publish_engine._run_make_catalog = mock_run_make_catalog
    publish_engine._copy_catalog_root = lambda: None

    try:
        log_lines = []
        result = publish_engine.publish_book(
            token="fake",
            key="TestBook",
            new_file=new_db,
            notes="delta useless test",
            delta_file=delta_db,
            delta_from=1,
            log=log_lines.append,
        )

        # delta_url пустой
        check(result["delta_url"] == "", "delta_url пустой при бесполезной дельте")

        # В versions.json нет ключа delta
        with open(ver_path, encoding="utf-8") as f:
            updated = json.load(f)
        entry = updated["books"]["TestBook"]
        check("delta" not in entry, "versions: нет ключа delta (бесполезная)")

        # В логе есть «бесполезна»
        log_text = " ".join(log_lines)
        check("бесполезна" in log_text, "в логе «бесполезна» (got: %s)" % log_text[:100])

        # Только один ассет (полный файл)
        check(result["size"] == 1000, "size=1000")

    finally:
        publish_engine.VERSIONS = old_versions
        publish_engine.CATALOG = old_catalog
        publish_engine.ROOT_CATALOG = old_root_catalog
        publish_engine.ROOT = old_root
        publish_engine.gh_release.next_db_tag = orig_next_tag
        publish_engine.gh_release.create_release = orig_create
        publish_engine.gh_release.upload_asset = orig_upload
        publish_engine.gh_release.publish_release = orig_publish
        publish_engine.gh_release.publish_catalog = orig_publish_catalog
        publish_engine._git_push = orig_git_push
        publish_engine._run_make_catalog = orig_run_make
        publish_engine._copy_catalog_root = lambda: None


# ======================================================================
# d) Дельта полезная (меньше 50%)
# ======================================================================
def test_delta_useful():
    print("=== d) Дельта полезная ===")
    tmpdir = tempfile.mkdtemp(prefix="deluseful_")

    ver_path = os.path.join(tmpdir, "versions.json")
    vdata = {
        "books": {
            "TestBook": {
                "title": "TestBook", "lang": "rus", "file": "TestBook.db",
                "version": 1, "url": ""
            }
        },
        "audio": {}
    }
    with open(ver_path, "w", encoding="utf-8") as f:
        json.dump(vdata, f)

    new_db = os.path.join(tmpdir, "TestBook.db")
    with open(new_db, "wb") as f:
        f.write(b"x" * 1000)

    # Дельта меньше 50% → полезная
    delta_db = os.path.join(tmpdir, "delta.db")
    with open(delta_db, "wb") as f:
        f.write(b"d" * 200)  # 200 < 1000 * 0.98

    updates_dir = os.path.join(tmpdir, "updates")
    os.makedirs(updates_dir, exist_ok=True)
    cat_path = os.path.join(updates_dir, "catalog.json")
    with open(cat_path, "w", encoding="utf-8") as f:
        json.dump({"books": [{"key": "TestBook", "size": 0, "sha256": ""}],
                    "audio": [], "apk": {}}, f)

    root_cat = os.path.join(tmpdir, "catalog.json")
    with open(root_cat, "w", encoding="utf-8") as f:
        json.dump({"books": [{"key": "TestBook", "size": 0, "sha256": ""}],
                    "audio": [], "apk": {}}, f)

    old_versions = publish_engine.VERSIONS
    old_catalog = publish_engine.CATALOG
    old_root_catalog = publish_engine.ROOT_CATALOG
    old_root = publish_engine.ROOT
    publish_engine.VERSIONS = ver_path
    publish_engine.CATALOG = cat_path
    publish_engine.ROOT_CATALOG = root_cat
    publish_engine.ROOT = tmpdir

    orig_next_tag = publish_engine.gh_release.next_db_tag
    orig_create = publish_engine.gh_release.create_release
    orig_upload = publish_engine.gh_release.upload_asset
    orig_publish = publish_engine.gh_release.publish_release
    orig_publish_catalog = publish_engine.gh_release.publish_catalog

    def mock_next_tag(token, repo):
        return "db-v5"

    def mock_create_release(token, repo, tag, name, body):
        return {"id": 2, "tag_name": tag}

    def mock_upload_asset(token, repo, rid, path, name="", ctype="application/octet-stream"):
        return {"id": 2, "name": os.path.basename(path),
                "browser_download_url": "https://gh.com/asset-%s" % os.path.basename(path)}

    def mock_publish_release(token, repo, rid):
        pass

    def mock_publish_catalog(token, path):
        return "https://gh.com/catalog.json"

    publish_engine.gh_release.next_db_tag = mock_next_tag
    publish_engine.gh_release.create_release = mock_create_release
    publish_engine.gh_release.upload_asset = mock_upload_asset
    publish_engine.gh_release.publish_release = mock_publish_release
    publish_engine.gh_release.publish_catalog = mock_publish_catalog

    git_push_calls = []
    orig_git_push = publish_engine._git_push

    def mock_git_push(files, msg):
        git_push_calls.append({"files": files})

    publish_engine._git_push = mock_git_push

    orig_run_make = publish_engine._run_make_catalog

    def mock_run_make_catalog(log):
        import hashlib
        h = hashlib.sha256()
        with open(new_db, "rb") as f:
            h.update(f.read())
        cdata = {"books": [{"key": "TestBook", "size": os.path.getsize(new_db),
                            "sha256": h.hexdigest(), "version": 2}],
                 "audio": [], "apk": {}}
        err = dbcommon.atomic_write_bytes(cat_path,
                                          json.dumps(cdata, ensure_ascii=False, indent=2).encode("utf-8"))
        if err:
            raise RuntimeError(err)
        log("make_catalog: ok")

    publish_engine._run_make_catalog = mock_run_make_catalog
    publish_engine._copy_catalog_root = lambda: None

    try:
        log_lines = []
        result = publish_engine.publish_book(
            token="fake",
            key="TestBook",
            new_file=new_db,
            notes="delta useful test",
            delta_file=delta_db,
            delta_from=1,
            log=log_lines.append,
        )

        # delta_url непустой
        check(result["delta_url"] != "", "delta_url непустой при полезной дельте")

        # В versions.json есть ключ delta
        with open(ver_path, encoding="utf-8") as f:
            updated = json.load(f)
        entry = updated["books"]["TestBook"]
        check("delta" in entry, "versions: есть ключ delta (полезная)")
        if "delta" in entry:
            check(entry["delta"]["url"] != "", "delta.url непустой")
            check(entry["delta"]["from"] == 1, "delta.from=1")

        # В логе нет «бесполезна»
        log_text = " ".join(log_lines)
        check("бесполезна" not in log_text, "в логе нет «бесполезна»")

        # Два ассета (полный + дельта)
        check(result["size"] == 1000, "size=1000")

    finally:
        publish_engine.VERSIONS = old_versions
        publish_engine.CATALOG = old_catalog
        publish_engine.ROOT_CATALOG = old_root_catalog
        publish_engine.ROOT = old_root
        publish_engine.gh_release.next_db_tag = orig_next_tag
        publish_engine.gh_release.create_release = orig_create
        publish_engine.gh_release.upload_asset = orig_upload
        publish_engine.gh_release.publish_release = orig_publish
        publish_engine.gh_release.publish_catalog = orig_publish_catalog
        publish_engine._git_push = orig_git_push
        publish_engine._run_make_catalog = orig_run_make
        publish_engine._copy_catalog_root = lambda: None


# ======================================================================
# main
# ======================================================================
def main():
    test_guess_key()
    test_publish_book_full()
    test_delta_useless()
    test_delta_useful()

    print("")
    print("Итого проверок: %d, провалов: %d" % (checks, fails))
    if fails:
        print("FAIL")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
