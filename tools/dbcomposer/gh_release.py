#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gh_release — публикация релизов/ассетов на GitHub для dbcomposer (GUI и CLI).

Только стандартная библиотека. Токен берётся из ROOT/local.properties
(githubFilesToken — fine-grained PAT с правами на Guhyatama и Guhyatama-files).

CLI:
  py gh_release.py list                     # релизы Guhyatama-files
  py gh_release.py list lightphoto2006/Guhyatama
  py gh_release.py probe                    # проверить права: пустой релиз + удалить
"""
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FILES_REPO = "lightphoto2006/Guhyatama-files"
APP_REPO = "lightphoto2006/Guhyatama"


def get_token():
    """Токен для записи (создание релизов/ассетов).

    1) git credential fill (Credential Manager, GCM OAuth gho_…) — токен с repo-scope,
       им же работают git push и релизы приложения;
    2) фолбэк: githubFilesToken из ROOT/local.properties (может быть read-only
       для файлов-репо — тогда создание релиза вернёт 403 с понятным текстом).
    """
    try:
        inp = "protocol=https\nhost=github.com\n\n".encode()
        out = subprocess.run(["git", "credential", "fill"], input=inp,
                             capture_output=True).stdout.decode("utf-8", "replace")
        for line in out.splitlines():
            if line.startswith("password="):
                v = line[len("password="):].strip()
                if v:
                    return v
    except Exception:
        pass
    p = os.path.join(ROOT, "local.properties")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s.startswith("githubFilesToken"):
                v = s.split("=", 1)[1].strip().strip('"')
                return v or None
    return None


class GHError(Exception):
    def __init__(self, status, message, url=""):
        super().__init__("HTTP %s: %s (%s)" % (status, message[:200], url))
        self.status = status
        self.message = message


def gh(url, token, method="GET", data=None, headers=None, timeout=180):
    """Запрос к GitHub API. data — bytes (не dict). Возвращает (status, тело bytes)."""
    h = {"Accept": "application/vnd.github+json",
         "User-Agent": "dbcomposer/1.0"}
    if token:
        h["Authorization"] = "Bearer " + token
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        raise GHError(e.code, e.read().decode("utf-8", "replace"), url)
    except Exception as e:  # не GitHub-ошибки: сеть и т.п.
        raise GHError(0, str(e), url)


def gh_json(url, token, method="GET", data=None, headers=None, timeout=180):
    st, body = gh(url, token, method, data, headers, timeout)
    return st, (json.loads(body.decode("utf-8")) if body else {})


# --- публичные операции -----------------------------------------------------

def list_releases(token, repo, per_page=50):
    st, d = gh_json(
        "https://api.github.com/repos/%s/releases?per_page=%d" % (repo, per_page),
        token)
    return d


def next_db_tag(token, repo=FILES_REPO):
    """Следующий тег db-vN по максимуму существующих db-vNN (иные теги игнорирует)."""
    maxlen = 0
    for r in list_releases(token, repo):
        m = re.match(r"^db-v(\d+)$", r.get("tag_name") or "")
        if m and int(m.group(1)) > maxlen:
            maxlen = int(m.group(1))
    return "db-v%d" % (maxlen + 1)


def create_release(token, repo, tag, name, body, target_commitish=""):
    st, d = gh_json(
        "https://api.github.com/repos/%s/releases" % repo,
        token, method="POST", data=json.dumps({
            "tag_name": tag,
            "name": name,
            "body": body,
            "draft": True,
            "prerelease": False,
            **({"target_commitish": target_commitish} if target_commitish else {}),
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    return d


def upload_asset(token, repo, release_id, path, name="", ctype="application/octet-stream"):
    """Ассет в draft-релиз. Возвращает обновлённый asset-объект (с id и всё в name)."""
    name = name or os.path.basename(path)
    name = urllib.request.quote(name)  # кириллица/пробелы в имени не допускает API
    with open(path, "rb") as f:
        blob = f.read()
    st, d = gh_json(
        "https://uploads.github.com/repos/%s/releases/%d/assets?name=%s"
        % (repo, release_id, name),
        token, method="POST", data=blob,
        headers={"Content-Type": ctype})
    return d


def publish_release(token, repo, release_id):
    """draft=True -> False (релиз становится видимым)."""
    st, d = gh_json(
        "https://api.github.com/repos/%s/releases/%d" % (repo, release_id),
        token, method="PATCH", data=json.dumps({"draft": False}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    return d


def delete_release(token, repo, release_id, tag=None):
    """Удалить релиз (и тег, если он есть). Тега у draft-релиза ещё нет — не ошибка."""
    gh("https://api.github.com/repos/%s/releases/%d" % (repo, release_id),
       token, method="DELETE")
    if tag:
        try:
            gh("https://api.github.com/repos/%s/git/refs/tags/%s" % (repo, tag),
               token, method="DELETE")
        except GHError as e:
            if e.status not in (404, 422):
                raise


def get_release_by_tag(token, repo, tag):
    """GET /repos/{repo}/releases/tags/{tag} → dict или None (404 → None)."""
    try:
        st, d = gh_json(
            "https://api.github.com/repos/%s/releases/tags/%s" % (repo, tag),
            token)
        if st != 200:
            return None
        return d
    except GHError as e:
        if e.status == 404:
            return None
        raise


def delete_asset(token, repo, asset_id):
    """DELETE /repos/{repo}/releases/assets/{id}."""
    gh("https://api.github.com/repos/%s/releases/assets/%d" % (repo, asset_id),
       token, method="DELETE")


def asset_api_url(repo, asset_id):
    return "https://api.github.com/repos/%s/releases/assets/%d" % (repo, asset_id)


def publish_catalog(token, path, repo=None, tag="catalog",
                    name="Каталог обновлений (технический)"):
    """Публикует файл как ассет catalog.json в релизе с тегом tag.

    - Если релиз по тегу есть — удаляет ассет с именем catalog.json (если найден)
      и загружает новый.
    - Если нет — создаёт черновик, загружает, публикует.
    - Возвращает URL: https://github.com/{repo}/releases/download/{tag}/catalog.json
    """
    repo = repo or APP_REPO
    with open(path, "rb") as f:
        blob = f.read()
    ctype = "application/json"

    rel = get_release_by_tag(token, repo, tag)
    if rel is None:
        # Создаём черновик
        rel = create_release(token, repo, tag, name, "технический релиз каталога")
        rid = rel["id"]
        upload_asset(token, repo, rid, path, name="catalog.json", ctype=ctype)
        publish_release(token, repo, rid)
    else:
        rid = rel["id"]
        # Удаляем старый ассет catalog.json, если есть
        for a in rel.get("assets", []):
            if a.get("name") == "catalog.json":
                delete_asset(token, repo, a["id"])
                break
        upload_asset(token, repo, rid, path, name="catalog.json", ctype=ctype)
        if rel.get("draft"):
            publish_release(token, repo, rid)

    return "https://github.com/%s/releases/download/%s/catalog.json" % (repo, tag)


# --- CLI --------------------------------------------------------------------

def _print_releases(d):
    for r in d:
        assets = ", ".join("%s(%d)" % (a["name"], a["size"]) for a in r["assets"])
        print("%s | %s | %s" % (r["tag_name"], r.get("name") or "-", assets))


def main(argv):
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cmd = argv[1] if len(argv) > 1 else "list"
    repo = argv[2] if len(argv) > 2 else FILES_REPO
    token = get_token()
    if not token:
        print("нет токена: githubFilesToken в local.properties")
        return 2
    if cmd == "list":
        _print_releases(list_releases(token, repo))
        return 0
    if cmd == "probe":
        # права: создать черновой релиз, удалить — репо не загрязняется
        tag = "zz-probe-%d" % int(time.time())
        rel = create_release(token, repo, tag, tag, "пустой тест публикации")
        rid, t = rel["id"], rel["tag_name"]
        delete_release(token, repo, rid, t)
        print("create+delete ok (%s, id %d), права есть" % (t, rid))
        return 0
    if cmd == "catalog":
        path = argv[3] if len(argv) > 3 else os.path.join(ROOT, "catalog.json")
        url = publish_catalog(token, path, repo=APP_REPO)
        print(url)
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv))
