#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вкладка «Релиз» dbcomposer: помощник цикла релизного процесса."""
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import gh_release
import dbcommon
import uicommon

DELTA_MAX_RATIO = 0.98


def delta_is_useless(delta_path, full_path, max_ratio=DELTA_MAX_RATIO):
    """True, если дельта почти не меньше полного файла — качать полный выгоднее."""
    try:
        d = os.path.getsize(delta_path)
        f = os.path.getsize(full_path)
    except OSError:
        return False
    return f > 0 and d >= f * max_ratio


def step3_differs(sec, fields, saved):
    """True, если ключевые поля шага 3 отличаются от сохранённых в versions.json.
    saved=None (записи нет) -> True."""
    if not saved:
        return True
    if sec == "apk":
        return (int(saved.get("versionCode", 0) or 0) != int(fields.get("versionCode", 0) or 0)
                or str(saved.get("versionName", "")) != str(fields.get("versionName", ""))
                or str(saved.get("file", "")) != str(fields.get("file", "")))
    return (int(saved.get("version", 0) or 0) != int(fields.get("version", 0) or 0)
            or str(saved.get("file", "")) != str(fields.get("file", ""))
            or str(saved.get("url", "")) != str(fields.get("url", "")))


def delta_file_problem(delta_file):
    """Пустая строка = ок; иначе текст проблемы (нет файла/не указан)."""
    p = (delta_file or "").strip()
    if not p:
        return ""
    return "" if os.path.isfile(p) else "Файл дельты не найден: %s" % p


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
UPDATES_DIR = os.path.join(ROOT, "updates")
VERSIONS_JSON = os.path.join(UPDATES_DIR, "versions.json")
CATALOG_JSON = os.path.join(UPDATES_DIR, "catalog.json")
DB_DIR = os.path.join(ROOT, "DB")
RELEASES_DIR = os.path.join(ROOT, "releases")
PY = sys.executable


def load_versions():
    try:
        with open(VERSIONS_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"apk": {}, "books": {}, "audio": {}}


def save_versions(data):
    os.makedirs(UPDATES_DIR, exist_ok=True)
    err = dbcommon.atomic_write_bytes(
        VERSIONS_JSON,
        json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    return err


def gh_asset_url(repo, asset_name):
    return f"https://api.github.com/repos/{repo}/releases/assets/{asset_name}"


def gh_release_url(repo, tag):
    return f"https://github.com/{repo}/releases/tag/{tag}"


def gh_releases_page(repo):
    return f"https://github.com/{repo}/releases"


class ReleaseTab(ttk.Frame):
    def __init__(self, parent, app=None):
        super().__init__(parent)
        self.app = app
        self.q = queue.Queue()
        self.busy = False
        self.repo = "lightphoto2006/Guhyatama"
        self.files_repo = "lightphoto2006/Guhyatama-files"
        self._build_ui()
        self._refresh_publish_hint()
        self._refresh_versions_list()
        self._refresh_book_keys()  # автозагрузка ключей при старте
        self.after(150, self.poll)

    def on_activate(self):
        """Вызывается при показе вкладки (см. App.on_tab)."""
        self._refresh_book_keys()
        self._refresh_versions_list()
        self._refresh_publish_hint()

    def _build_ui(self):
        nb = ttk.Notebook(self)
        self.nb = nb
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        # --- Шаг 1: Подготовка ---
        self._build_step1(nb)

        # --- Шаг 2: Дельта ---
        self._build_step2(nb)

        # --- Шаг 3: Версии / versions.json ---
        self._build_step3(nb)

        # --- Шаг 4: Каталог ---
        self._build_step4(nb)

        # --- Шаг 5: Загрузка ---
        self._build_step5(nb)

        # Лог
        logf = ttk.Frame(self, padding=(6, 0, 6, 6))
        logf.pack(fill="x")
        self.prog = ttk.Progressbar(logf, mode="indeterminate", length=100)
        self.prog.pack(side="left", padx=(0, 6))
        self.log = tk.Text(logf, height=6, wrap="word")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.bind("<Key>", uicommon.log_key)
        uicommon.attach_log_menu(self.log)

    def _build_step1(self, nb):
        t = ttk.Frame(nb, padding=6)
        nb.add(t, text="1 · Новая сборка .db")

        ttk.Label(t, text="Соберите новую библиотечную базу во вкладке «Сборка», затем укажите путь:", wraplength=600).pack(anchor="w", pady=(0, 6))

        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="NEW .db:", width=10).pack(side="left")
        self.v_new_db = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_new_db).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick(self.v_new_db, "Новая база (.db)", [("SQLite", "*.db")])).pack(side="left")

        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Ключ книги:", width=12).pack(side="left")
        self.v_book_key = tk.StringVar()
        self.cmb_book_key = ttk.Combobox(row, textvariable=self.v_book_key, width=30)
        self.cmb_book_key.pack(side="left", padx=4)
        ttk.Button(row, text="Обновить список", command=self._refresh_book_keys).pack(side="left")

        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Тип релиза:", width=12).pack(side="left")
        self.v_release_type = tk.StringVar(value="books")
        for val, label in (("books", "Книги (books)"), ("audio", "Аудио (audio)"), ("apk", "APK (apk)")):
            ttk.Radiobutton(row, text=label, value=val, variable=self.v_release_type, command=self._on_type_change).pack(side="left", padx=4)

        self.b_step1_next = ttk.Button(t, text="Далее → Дельта", command=self._go_step2)
        self.b_step1_next.pack(anchor="e", pady=10)

    def _build_step2(self, nb):
        t = ttk.Frame(nb, padding=6)
        nb.add(t, text="2 · Дельта (опционально)")

        ttk.Label(t, text="Если книга уже у пользователей — сделайте дельту для инкрементального обновления:", wraplength=600).pack(anchor="w", pady=(0, 6))

        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="OLD .db:", width=10).pack(side="left")
        self.v_old_db = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_old_db).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick(self.v_old_db, "Старая база (.db)", [("SQLite", "*.db")])).pack(side="left")

        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="OUT дельта:", width=10).pack(side="left")
        self.v_delta_out = tk.StringVar(value=os.path.join(RELEASES_DIR, "delta.db"))
        ttk.Entry(row, textvariable=self.v_delta_out).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick_save(self.v_delta_out, "Сохранить дельту", [("SQLite", "*.db")])).pack(side="left")

        self.v_make_delta = tk.BooleanVar(value=True)
        ttk.Checkbutton(t, text="Сделать дельту сейчас (make_delta.py)", variable=self.v_make_delta).pack(anchor="w", pady=4)

        btnf = ttk.Frame(t)
        btnf.pack(fill="x", pady=6)
        self.b_make_delta = ttk.Button(btnf, text="Построить дельту", command=self._run_make_delta)
        self.b_make_delta.pack(side="left")
        self.b_step2_next = ttk.Button(btnf, text="Далее → Версии", command=self._go_step3)
        self.b_step2_next.pack(side="right")

    def _build_step3(self, nb):
        t = ttk.Frame(nb, padding=6)
        nb.add(t, text="3 · versions.json")

        ttk.Label(t, text="Запись в versions.json для новой версии:", wraplength=600).pack(anchor="w", pady=(0, 6))

        # Книга
        f_book = ttk.LabelFrame(t, text="Книга / Аудио", padding=6)
        f_book.pack(fill="x", pady=4)

        row = ttk.Frame(f_book)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Ключ:", width=8).pack(side="left")
        self.v_ver_key = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_ver_key, width=30).pack(side="left", padx=4)

        row = ttk.Frame(f_book)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Название:", width=8).pack(side="left")
        self.v_ver_title = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_ver_title, width=50).pack(side="left", padx=4)

        row = ttk.Frame(f_book)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Язык:", width=8).pack(side="left")
        self.v_ver_lang = tk.StringVar(value="rus")
        ttk.Combobox(row, textvariable=self.v_ver_lang, width=8, values=["rus", "eng", "hin", "ben"]).pack(side="left", padx=4)

        row = ttk.Frame(f_book)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Файл:", width=8).pack(side="left")
        self.v_ver_file = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_ver_file, width=50).pack(side="left", padx=4)

        row = ttk.Frame(f_book)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Версия:", width=8).pack(side="left")
        self.v_ver_version = tk.IntVar(value=1)
        ttk.Spinbox(row, from_=1, to=999, textvariable=self.v_ver_version, width=6).pack(side="left", padx=4)
        ttk.Button(row, text="Авто (макс+1)", command=self._auto_version).pack(side="left", padx=4)

        row = ttk.Frame(f_book)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="URL:", width=8).pack(side="left")
        self.v_ver_url = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_ver_url, width=70).pack(side="left", padx=4)

        row = ttk.Frame(f_book)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Примечания:", width=10).pack(side="left")
        self.v_ver_notes = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_ver_notes, width=70).pack(side="left", padx=4)

        # Дельта
        f_delta = ttk.LabelFrame(t, text="Дельта (если есть)", padding=6)
        f_delta.pack(fill="x", pady=4)

        row = ttk.Frame(f_delta)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Файл дельты:", width=12).pack(side="left")
        self.v_ver_delta_file = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_ver_delta_file, width=50).pack(side="left", padx=4)

        row = ttk.Frame(f_delta)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="URL дельты:", width=12).pack(side="left")
        self.v_ver_delta_url = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_ver_delta_url, width=70).pack(side="left", padx=4)

        row = ttk.Frame(f_delta)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="from version:", width=12).pack(side="left")
        self.v_ver_delta_from = tk.IntVar(value=0)
        ttk.Spinbox(row, from_=0, to=999, textvariable=self.v_ver_delta_from, width=6).pack(side="left", padx=4)

        # APK
        f_apk = ttk.LabelFrame(t, text="APK (если тип apk)", padding=6)
        f_apk.pack(fill="x", pady=4)

        row = ttk.Frame(f_apk)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="versionCode:", width=12).pack(side="left")
        self.v_apk_vcode = tk.IntVar(value=56)
        ttk.Spinbox(row, from_=1, to=999, textvariable=self.v_apk_vcode, width=8).pack(side="left", padx=4)

        row = ttk.Frame(f_apk)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="versionName:", width=12).pack(side="left")
        self.v_apk_vname = tk.StringVar(value="1.3.8")
        ttk.Entry(row, textvariable=self.v_apk_vname, width=15).pack(side="left", padx=4)

        row = ttk.Frame(f_apk)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="APK файл:", width=12).pack(side="left")
        self.v_apk_file = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_apk_file, width=50).pack(side="left", padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick(self.v_apk_file, "APK файл", [("APK", "*.apk")])).pack(side="left")

        row = ttk.Frame(f_apk)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="URL APK:", width=12).pack(side="left")
        self.v_apk_url = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_apk_url, width=70).pack(side="left", padx=4)

        # Кнопки
        btnf = ttk.Frame(t)
        btnf.pack(fill="x", pady=6)
        ttk.Button(btnf, text="Сохранить в versions.json", command=self._save_versions).pack(side="left")
        ttk.Button(btnf, text="Открыть versions.json", command=lambda: self._open_file(VERSIONS_JSON)).pack(side="left", padx=4)
        self.b_step3_next = ttk.Button(btnf, text="Далее → Каталог", command=self._go_step4)
        self.b_step3_next.pack(side="right")

    def _build_step4(self, nb):
        t = ttk.Frame(nb, padding=6)
        nb.add(t, text="4 · catalog.json")

        ttk.Label(t, text="Соберите catalog.json (make_catalog.py) — он пропишет size/sha256/fingerprint:", wraplength=600).pack(anchor="w", pady=(0, 6))

        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Папка .db:", width=12).pack(side="left")
        self.v_cat_src = tk.StringVar(value=DB_DIR)
        ttk.Entry(row, textvariable=self.v_cat_src).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick_dir(self.v_cat_src)).pack(side="left")

        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="OUT:", width=12).pack(side="left")
        self.v_cat_out = tk.StringVar(value=CATALOG_JSON)
        ttk.Entry(row, textvariable=self.v_cat_out).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick_save(self.v_cat_out, "Сохранить каталог", [("JSON", "*.json")])).pack(side="left")

        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="versions:", width=12).pack(side="left")
        self.v_cat_versions = tk.StringVar(value=VERSIONS_JSON)
        ttk.Entry(row, textvariable=self.v_cat_versions).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick(self.v_cat_versions, "versions.json", [("JSON", "*.json")])).pack(side="left")

        btnf = ttk.Frame(t)
        btnf.pack(fill="x", pady=6)
        self.b_make_catalog = ttk.Button(btnf, text="Собрать catalog.json", command=self._run_make_catalog)
        self.b_make_catalog.pack(side="left")
        ttk.Button(btnf, text="Открыть catalog.json", command=lambda: self._open_file(CATALOG_JSON)).pack(side="left", padx=4)
        self.b_step4_next = ttk.Button(btnf, text="Далее → Загрузка", command=self._go_step5)
        self.b_step4_next.pack(side="right")

    def _build_step5(self, nb):
        t = ttk.Frame(nb, padding=6)
        nb.add(t, text="5 · Загрузка на GitHub")

        ttk.Label(t, text="Файлы для загрузки в GitHub Releases:", wraplength=600).pack(anchor="w", pady=(0, 6))

        self.tv_files = ttk.Treeview(t, columns=("path", "size"), show="tree headings", height=8)
        self.tv_files.heading("#0", text="Файл")
        self.tv_files.column("#0", width=250)
        self.tv_files.heading("path", text="Путь")
        self.tv_files.column("path", width=300)
        self.tv_files.heading("size", text="Размер")
        self.tv_files.column("size", width=80, anchor="e")
        self.tv_files.pack(fill="both", expand=True, pady=4)

        btnf = ttk.Frame(t)
        btnf.pack(fill="x", pady=6)
        ttk.Button(btnf, text="Обновить список", command=self._refresh_upload_list).pack(side="left")

        ttk.Separator(t, orient="horizontal").pack(fill="x", pady=8)

        self.l_publish_hint = ttk.Label(t, text="", wraplength=700, justify="left")
        self.l_publish_hint.pack(anchor="w", pady=(0, 4))

        pubf = ttk.Frame(t)
        pubf.pack(fill="x")
        self.b_publish = ttk.Button(pubf, text="🚀 Опубликовать релиз", command=self._publish_release)
        self.b_publish.pack(side="left")
        ttk.Label(pubf, text=" — релиз+ассеты в GitHub, URL в versions.json,"
                             " catalog.json, коммит и пуш — одним нажатием",
                  foreground="gray").pack(side="left")

        ttk.Separator(t, orient="horizontal").pack(fill="x", pady=8)

        btnf2 = ttk.Frame(t)
        btnf2.pack(fill="x", pady=2)
        self.b_publish_catalog = ttk.Button(btnf2, text="📤 Обновить catalog.json в релизе (catalog)",
                                            command=self._publish_catalog_only)
        self.b_publish_catalog.pack(side="left")
        ttk.Label(btnf2, text=" — только каталог как ассет релиза (без git-коммита)",
                  foreground="gray").pack(side="left")

        ttk.Label(t, text="Публикация: книги/аудио → Guhyatama-files (тег db-vN),"
                          " APK → Guhyatama (тег vX.Y.Z). Перед публикацией шаг 3"
                          " должен быть СОХРАНЁН («Сохранить в versions.json»).",
                  foreground="gray", wraplength=700, justify="left").pack(fill="x", pady=(2, 0))

    def _refresh_book_keys(self):
        data = load_versions()
        section = self.v_release_type.get()
        keys = list(data.get(section, {}).keys())
        self.cmb_book_key["values"] = keys
        if keys:
            self.cmb_book_key.current(0)
            self._on_book_key_change()

    def _on_book_key_change(self, *args):
        key = self.v_book_key.get()
        data = load_versions()
        section = self.v_release_type.get()
        if key in data.get(section, {}):
            meta = data[section][key]
            self.v_ver_key.set(key)
            self.v_ver_title.set(meta.get("title", ""))
            self.v_ver_lang.set(meta.get("lang", "rus"))
            self.v_ver_file.set(meta.get("file", ""))
            self.v_ver_version.set(int(meta.get("version", 0)) + 1)
            self.v_ver_url.set(meta.get("url", ""))
            self.v_ver_notes.set(meta.get("notes", ""))
            delta = meta.get("delta", {})
            self.v_ver_delta_file.set(delta.get("file", ""))
            self.v_ver_delta_url.set(delta.get("url", ""))
            self.v_ver_delta_from.set(int(delta.get("from", 0)))

    def _on_type_change(self):
        self._refresh_book_keys()

    def _auto_version(self):
        key = self.v_book_key.get()
        data = load_versions()
        section = self.v_release_type.get()
        if key in data.get(section, {}):
            cur = int(data[section][key].get("version", 0))
            self.v_ver_version.set(cur + 1)

    def _save_versions(self):
        data = load_versions()
        section = self.v_release_type.get()
        key = self.v_ver_key.get().strip()
        if not key:
            messagebox.showwarning("Пусто", "Укажите ключ книги")
            return
        meta = {
            "title": self.v_ver_title.get().strip(),
            "lang": self.v_ver_lang.get().strip(),
            "file": self.v_ver_file.get().strip(),
            "version": int(self.v_ver_version.get()),
            "url": self.v_ver_url.get().strip(),
            "notes": self.v_ver_notes.get().strip(),
            "auth": "github",
        }
        df = self.v_ver_delta_file.get().strip()
        du = self.v_ver_delta_url.get().strip()
        dfrom = int(self.v_ver_delta_from.get())
        if df and du and dfrom > 0:
            meta["delta"] = {"file": df, "url": du, "from": dfrom}
        if section == "apk":
            meta = {
                "versionCode": int(self.v_apk_vcode.get()),
                "versionName": self.v_apk_vname.get().strip(),
                "file": self.v_apk_file.get().strip(),
                "url": self.v_apk_url.get().strip(),
                "notes": self.v_ver_notes.get().strip(),
            }
            if df and du and dfrom > 0:
                meta["delta"] = {"file": df, "url": du, "from": dfrom}
        if section not in data:
            data[section] = {}
        data[section][key] = meta
        err = save_versions(data)
        if err:
            messagebox.showerror("Ошибка", err)
        else:
            self.say(f"versions.json обновлён: {section}.{key} v{meta.get('version', meta.get('versionCode'))}")
            self._refresh_versions_list()

    def _refresh_versions_list(self):
        for i in self.tv_files.get_children():
            self.tv_files.delete(i)
        data = load_versions()
        for section in ("books", "audio"):
            for key, meta in data.get(section, {}).items():
                fn = meta.get("file", "")
                size = ""
                if fn and os.path.exists(os.path.join(RELEASES_DIR, fn)):
                    size = f"{os.path.getsize(os.path.join(RELEASES_DIR, fn)) // 1024} КБ"
                elif fn and os.path.exists(os.path.join(DB_DIR, fn)):
                    size = f"{os.path.getsize(os.path.join(DB_DIR, fn)) // 1024} КБ"
                self.tv_files.insert("", "end", text=f"{section}.{key} v{meta.get('version', '?')}",
                                     values=(fn, size))
        # APK has different structure
        apk = data.get("apk", {})
        if apk and "versionCode" in apk:
            fn = apk.get("file", "")
            size = ""
            if fn and os.path.exists(fn):
                size = f"{os.path.getsize(fn) // 1024} КБ"
            self.tv_files.insert("", "end", text=f"apk v{apk.get('versionName', apk.get('versionCode', '?'))}",
                                 values=(fn, size))

    def _refresh_upload_list(self):
        self._refresh_versions_list()
        # Add delta file if exists
        delta = self.v_delta_out.get().strip()
        if delta and os.path.exists(delta):
            size = f"{os.path.getsize(delta) // 1024} КБ"
            self.tv_files.insert("", "end", text="Δ дельта", values=(delta, size))

    def _run_make_delta(self):
        if not self.v_make_delta.get():
            self.say("Дельта пропущена (галочка снята)")
            return
        old = self.v_old_db.get().strip()
        new = self.v_new_db.get().strip()
        out = self.v_delta_out.get().strip()
        if not old or not new or not out:
            missing = []
            if not old:
                missing.append("OLD")
            if not new:
                missing.append("NEW")
            if not out:
                missing.append("OUT")
            messagebox.showwarning("Пустые поля",
                "Вкладка «Релиз», шаг 2.\n"
                "Пусто: " + ", ".join(missing) + "\n\n"
                "OLD: " + repr(self.v_old_db.get().strip()) + "\n"
                "NEW: " + repr(self.v_new_db.get().strip()) + "\n"
                "OUT: " + repr(self.v_delta_out.get().strip()) + "\n\n"
                "(Поля вкладки «Δ Дельта БД» — отдельные.)")
            return
        cmd = [PY, os.path.join(HERE, "make_delta.py"), "--old", old, "--new", new, "--out", out]
        self._run_bg(cmd, "make_delta")

    def _run_make_catalog(self):
        src = self.v_cat_src.get().strip()
        versions = self.v_cat_versions.get().strip()
        out = self.v_cat_out.get().strip()
        if not os.path.exists(versions):
            messagebox.showerror("Нет versions.json", versions)
            return
        cmd = [PY, os.path.join(HERE, "make_catalog.py"), "--src", src, "--versions", versions, "--out", out]
        self._run_bg(cmd, "make_catalog")

    def _go_step2(self):
        if not self.v_new_db.get().strip():
            messagebox.showwarning("Пусто", "Укажите NEW .db")
            return
        if not self.v_book_key.get().strip():
            messagebox.showwarning("Пусто", "Выберите ключ книги")
            return
        # Pre-fill step 3
        self._on_book_key_change()
        # Pre-fill step 2
        data = load_versions()
        section = self.v_release_type.get()
        key = self.v_book_key.get()
        if key in data.get(section, {}):
            meta = data[section][key]
            old_file = meta.get("file", "")
            if old_file:
                # Try to find old file
                for base in (RELEASES_DIR, DB_DIR):
                    p = os.path.join(base, old_file)
                    if os.path.exists(p):
                        self.v_old_db.set(p)
                        break
        self.nb.select(1)

    def _step3_fields(self):
        """Dict с ключевыми полями шага 3 из текущих Tk-переменных."""
        sec = self.v_release_type.get()
        if sec == "apk":
            return {
                "versionCode": int(self.v_apk_vcode.get()),
                "versionName": self.v_apk_vname.get(),
                "file": self.v_apk_file.get(),
            }
        return {
            "version": int(self.v_ver_version.get()),
            "file": self.v_ver_file.get(),
            "url": self.v_ver_url.get(),
        }

    def _check_step3(self, saved_must_exist=False):
        """bool «можно идти дальше»: проверяет несохранённые изменения."""
        sec = self.v_release_type.get()
        fields = self._step3_fields()
        if not os.path.exists(VERSIONS_JSON) and saved_must_exist:
            messagebox.showwarning("Нет versions.json",
                                   "Сначала сохрани данные в шаге 3")
            return False
        saved = load_versions().get(sec, {})
        if sec == "apk":
            saved = saved if saved else {}
        else:
            key = self.v_ver_key.get().strip()
            saved = saved.get(key, {}) if saved else {}
        if step3_differs(sec, fields, saved):
            return messagebox.askyesno("Не сохранено",
                                       "Изменения шага 3 не сохранены в versions.json.\nПерейти дальше?")
        return True

    def _go_step3(self):
        self.nb.select(2)

    def _go_step4(self):
        if not self._check_step3():
            return
        self.nb.select(3)

    def _go_step5(self):
        if not self._check_step3(saved_must_exist=True):
            return
        prob = delta_file_problem(self.v_ver_delta_file.get())
        if prob:
            messagebox.showwarning("Дельта", prob)
            return
        self._refresh_upload_list()
        self.nb.select(4)

    # --- публикация: роль кнопки — вся цепочка одним нажатием --------------------

    def _refresh_publish_hint(self):
        has = bool(gh_release.get_token())
        self.l_publish_hint.configure(
            text=("Токен: ok (git credential / local.properties)" if has
                  else "Токен НЕ найден (githubFilesToken в local.properties / git credential)"))

    def _resolve_file(self, fn):
        """Абсолютный путь файла: сам путь, либо DB/, releases/, updates/."""
        fn = (fn or "").strip()
        if not fn:
            raise RuntimeError("пустой путь файла")
        if os.path.isabs(fn):
            if not os.path.exists(fn):
                raise RuntimeError("файл не найден: %s" % fn)
            return fn
        for base in (DB_DIR, RELEASES_DIR, UPDATES_DIR):
            p = os.path.join(base, fn)
            if os.path.exists(p):
                return p
        raise RuntimeError("файл не найден ни в DB/, ни в releases/, ни в updates/: %s" % fn)

    @staticmethod
    def _sha256(path):
        import hashlib
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def _publish_release(self):
        """Кнопка «Опубликовать»: вся цепочка в фоне. Работает по СОХРАНЁННОМУ
        versions.json (шаг 3) — пользователь сначала сохраняет, потом публикует."""
        if self.busy:
            return
        data = load_versions()
        sec = self.v_release_type.get()
        key = self.v_ver_key.get().strip()
        if sec == "apk":
            meta = dict(data.get("apk", {}))
            if not meta.get("versionCode"):
                messagebox.showwarning("Пусто", "Сначала заполните и сохраните apk в шаге 3")
                return
        else:
            meta = dict(data.get(sec, {}).get(key, {}))
            if not meta:
                messagebox.showwarning("Пусто", "Сначала заполните и сохраните запись в шаге 3")
                return
        if not messagebox.askyesno(
                "Публиковать?",
                "%s • файл: %s\nВерсия: %s\n\nОпубликовать релиз на GitHub?"
                % (key or "apk", meta.get("file", "?"),
                   meta.get("version", meta.get("versionName", "?"))),
                parent=self):
            return
        self.set_busy(True)
        self.say("публикация: запуск…")
        threading.Thread(target=self._publish_worker, args=(sec, key, meta),
                         daemon=True).start()

    def _publish_worker(self, sec, key, meta):
        def say(t):
            self.q.put(("log", str(t)))
        try:
            token = gh_release.get_token()
            if not token:
                raise RuntimeError("нет токена (githubFilesToken в local.properties)")
            if sec == "apk":
                repo = gh_release.APP_REPO
                tag = "v%s" % meta["versionName"]
                fpath = self._resolve_file(meta.get("file", ""))
                body = ["APK v%s (versionCode %s)" % (meta["versionName"], meta["versionCode"])]
            else:
                repo = gh_release.FILES_REPO
                version = int(meta["version"])
                if version <= 0:
                    raise RuntimeError("версия книги не указана (шаг 3)")
                tag = gh_release.next_db_tag(token, repo)
                fpath = self._resolve_file(meta.get("file", ""))
                body = ["%s — v%d (%s, %s)" % (meta.get("title", key), version, key,
                                               meta.get("lang", ""))]
            notes = (meta.get("notes") or "").strip()
            if notes:
                body += ["", notes]
            body += ["", "sha256 (%s): `%s`" % (os.path.basename(fpath), self._sha256(fpath))]
            say("тег: %s → %s" % (tag, repo))
            rel = gh_release.create_release(token, repo, tag, tag, "\n".join(body))
            rid = rel["id"]
            say("черновик создан (id %s)" % rid)
            up = gh_release.upload_asset(token, repo, rid, fpath)
            full_url = gh_release.asset_api_url(repo, up["id"])
            full_size = up.get("size") or os.path.getsize(fpath)
            full_sha = self._sha256(fpath)
            say("ассет: %s" % full_url)
            delta_url, delta_size, delta_sha = "", 0, ""
            delta_ok = False
            d = meta.get("delta") or {}
            if int(d.get("from") or 0) > 0:
                dpath = self._resolve_file(d.get("file", ""))
                if delta_is_useless(dpath, fpath):
                    say("дельта бесполезна (%.1f%% от файла) — публикую без неё" % (100.0 * os.path.getsize(dpath) / max(1, os.path.getsize(fpath))))
                else:
                    up2 = gh_release.upload_asset(token, repo, rid, dpath)
                    delta_url = gh_release.asset_api_url(repo, up2["id"])
                    delta_size = up2.get("size") or os.path.getsize(dpath)
                    delta_sha = self._sha256(dpath)
                    delta_ok = True
                    say("дельта: %s" % delta_url)
            gh_release.publish_release(token, repo, rid)
            say("релиз опубликован: %s" % gh_release.gh_release_url(repo, tag))
            # вписываем в versions.json ТОЛЬКО url/delta.url — поля шага 3 не трогаем
            data = load_versions()
            m = data.get("apk", {}) if sec == "apk" else data.get(sec, {}).get(key)
            if m is None:
                raise RuntimeError("запись %s исчезла из versions.json" % key)
            m["url"] = full_url
            if delta_ok:
                if isinstance(m.get("delta"), dict):
                    m["delta"]["url"] = delta_url
            elif isinstance(m.get("delta"), dict):
                m.pop("delta", None)
                say("versions.json: дельта убрана — поедет полный файл")
            err = save_versions(data)
            if err:
                raise RuntimeError(err)
            say("versions.json: URL указывают на asset-ссылки")
            self._regen_catalog_worker(say)
            self._patch_catalog_worker(say, sec, key,
                                       size=full_size, sha=full_sha,
                                       dsize=delta_size, dsha=delta_sha)
            self._publish_catalog_worker(say)
            self._git_push_worker(say, sec, key, meta, tag)
            self.q.put(("done", "публикация завершена: %s" % tag))
        except gh_release.GHError as e:
            self.q.put(("error", "GitHub: %s" % e.message[:300]))
        except Exception as e:
            self.q.put(("error", str(e)))

    def _regen_catalog_worker(self, say):
        cmd = [PY, os.path.join(HERE, "make_catalog.py"), "--src", DB_DIR,
               "--out", CATALOG_JSON]
        say("make_catalog: запуск…")
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900)
        out = ((p.stdout or "") + (p.stderr or "")).strip()
        if p.returncode != 0:
            raise RuntimeError("make_catalog: код %s\n%s" % (p.returncode, out[-800:]))
        say("make_catalog: ok")

    def _load_catalog(self):
        with open(CATALOG_JSON, encoding="utf-8") as f:
            return json.load(f)

    def _save_catalog(self, data):
        err = dbcommon.atomic_write_bytes(
            CATALOG_JSON, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
        if err:
            raise RuntimeError(err)

    def _copy_catalog_to_root(self, say):
        with open(CATALOG_JSON, "rb") as f:
            err = dbcommon.atomic_write_bytes(os.path.join(ROOT, "catalog.json"), f.read())
        if err:
            raise RuntimeError(err)
        say("каталог скопирован в корень (catalog.json)")

    def _patch_catalog_worker(self, say, sec, key, size, sha, dsize, dsha):
        """make_catalog может не найти исходные .db в DB/ (их там давно нет) и
        обнуляет size/sha256 — публикуемый ключ патчем получает реальные значения."""
        if sec == "apk":
            self._copy_catalog_to_root(say)
            return
        c = self._load_catalog()
        entry = None
        for e in c.get(sec, []):
            if e.get("key") == key:
                entry = e
                break
        if entry is None:
            raise RuntimeError("в catalog.json нет записи %s.%s" % (sec, key))
        entry["size"] = size
        entry["sha256"] = sha
        if dsize and dsha:
            entry["deltaSize"] = dsize
            entry["deltaSha"] = dsha
            say("каталог: size/sha256 + deltaSize/deltaSha записаны")
        else:
            say("каталог: size/sha256 записаны (дельты нет)")
        self._save_catalog(c)
        self._copy_catalog_to_root(say)

    def _git_push_worker(self, say, sec, key, meta, tag):
        files = ["updates/versions.json", "updates/catalog.json", "catalog.json"]
        if sec == "apk":
            msg = "release: v%s (vc%s) — каталог %s" % (meta["versionName"],
                                                       meta["versionCode"], tag)
        else:
            msg = "books: %s v%d — каталог %s" % (key, meta.get("version", 0), tag)

        def run(args, allow_fail=False):
            r = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
            if r.returncode != 0 and not allow_fail:
                raise RuntimeError("git %s: %s" % (args[0], (r.stderr or r.stdout)[-400:]))
            return r

        run(["add"] + files)
        r = run(["commit", "-m", msg, "--"] + files, allow_fail=True)
        if r.returncode != 0:
            say("git commit: %s" % ((r.stderr or r.stdout or "").strip()[:200]))
        run(["push", "origin", "HEAD:main"])  # клиент читает каталог из main
        say("git: запушено (%s)" % msg)

    def _publish_catalog_worker(self, say):
        """Публикация catalog.json ассетом в релиз с тегом catalog."""
        token = gh_release.get_token()
        if not token:
            raise RuntimeError("нет токена (githubFilesToken в local.properties)")
        url = gh_release.publish_catalog(token, os.path.join(ROOT, "catalog.json"))
        say("каталог опубликован ассетом: %s" % url)

    def _publish_catalog_only(self):
        """Отдельная кнопка: только публикация catalog.json в релиз (без git)."""
        if self.busy:
            return
        self.set_busy(True)
        self.say("публикация catalog.json в релиз: запуск…")
        threading.Thread(target=self._publish_catalog_bg, daemon=True).start()

    def _publish_catalog_bg(self):
        def say(t):
            self.q.put(("log", str(t)))
        try:
            self._publish_catalog_worker(say)
            self.q.put(("done", "catalog.json опубликован в релиз"))
        except gh_release.GHError as e:
            self.q.put(("error", "GitHub: %s" % e.message[:300]))
        except Exception as e:
            self.q.put(("error", str(e)))

    def _pick(self, var, title, filetypes):
        p = filedialog.askopenfilename(title=title, filetypes=filetypes, parent=self)
        if p:
            var.set(p)

    def _pick_save(self, var, title, filetypes):
        p = filedialog.asksaveasfilename(title=title, filetypes=filetypes, defaultextension=filetypes[0][1], parent=self)
        if p:
            var.set(p)

    def _pick_dir(self, var):
        d = filedialog.askdirectory(title="Выберите папку", parent=self)
        if d:
            var.set(d)

    def _open_file(self, path):
        if os.path.exists(path):
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.run(["xdg-open", path])

    def set_busy(self, v):
        uicommon.set_busy(self, v, (self.b_make_delta, self.b_make_catalog, self.b_step1_next, self.b_step2_next, self.b_step3_next, self.b_step4_next, self.b_publish), self.prog)

    def say(self, text):
        uicommon.say(self.log, text)

    def poll(self):
        try:
            while True:
                kind, text = self.q.get_nowait()
                if kind == "log":
                    self.say(text)
                elif kind == "done":
                    self.set_busy(False)
                    self.say(text)
                elif kind == "error":
                    self.set_busy(False)
                    messagebox.showerror("Ошибка", text)
                    self.say("ОШИБКА: " + text)
        except queue.Empty:
            pass
        self.after(150, self.poll)

    def _run_bg(self, cmd, label):
        self.set_busy(True)
        self.say(f"{label}: запуск…")
        threading.Thread(target=self._run_subprocess, args=(cmd, label), daemon=True).start()

    def _run_subprocess(self, cmd, label):
        try:
            # Use system encoding on Windows to avoid garbled Cyrillic
            import locale
            enc = locale.getpreferredencoding(False) or "utf-8"
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding=enc, errors="replace", bufsize=1)
            out_lines = []
            for line in proc.stdout:
                line = line.rstrip("\n\r")
                if line:
                    out_lines.append(line)
                    self.q.put(("log", line))
            proc.wait()
            if proc.returncode == 0:
                self.q.put(("done", f"{label}: готово"))
            else:
                self.q.put(("error", f"{label}: код {proc.returncode}\n" + "\n".join(out_lines[-20:])))
        except Exception as e:
            self.q.put(("error", f"{label}: {e}"))