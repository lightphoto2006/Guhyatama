#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вкладка «Дельта/Каталог» dbcomposer: GUI для make_delta, make_catalog, make_apk_delta."""
import json
import locale
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import dbcommon
import gh_release
import uicommon

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
CFG = os.path.join(HERE, "dbcomposer.json")
MAKE_DELTA = os.path.join(HERE, "make_delta.py")
MAKE_CATALOG = os.path.join(HERE, "make_catalog.py")
MAKE_APK_DELTA = os.path.join(HERE, "make_apk_delta.py")
ROOT = os.path.dirname(os.path.dirname(HERE))


def _cfg_load():
    return dbcommon.load_cfg(CFG)


def _cfg_save(patch):
    cur = _cfg_load()
    cur.update(patch)
    dbcommon.save_cfg(CFG, cur)


class DeltaTab(ttk.Frame):
    def __init__(self, parent, app=None):
        super().__init__(parent)
        self.app = app
        self.q = queue.Queue()
        self.busy = False
        self._build_ui()
        self._refresh_pub_keys()
        self.after(150, self.poll)

    def _build_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        # --- Дельта БД ---
        self._build_delta_db_tab(nb)

        # --- Каталог ---
        self._build_catalog_tab(nb)

        # --- APK Дельта ---
        self._build_apk_delta_tab(nb)

        # Лог
        logf = ttk.Frame(self, padding=(6, 0, 6, 6))
        logf.pack(fill="x")
        self.prog = ttk.Progressbar(logf, mode="indeterminate", length=100)
        self.prog.pack(side="left", padx=(0, 6))
        self.log = tk.Text(logf, height=6, wrap="word")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.bind("<Key>", uicommon.log_key)
        uicommon.attach_log_menu(self.log)

    def _build_delta_db_tab(self, nb):
        t = ttk.Frame(nb, padding=6)
        nb.add(t, text="Δ Дельта БД")

        # OLD
        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="OLD .db:", width=10).pack(side="left")
        _d = _cfg_load()
        _old_def = _d.get("delta_old", "")
        self.v_delta_old = tk.StringVar(value=_old_def)
        ttk.Entry(row, textvariable=self.v_delta_old).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick(self.v_delta_old, "Старая база (.db)", [("SQLite", "*.db")])).pack(side="left")

        # NEW
        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="NEW .db:", width=10).pack(side="left")
        _new_def = _d.get("delta_new", "")
        self.v_delta_new = tk.StringVar(value=_new_def)
        ttk.Entry(row, textvariable=self.v_delta_new).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick(self.v_delta_new, "Новая база (.db)", [("SQLite", "*.db")])).pack(side="left")

        # OUT
        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="OUT:", width=10).pack(side="left")
        _d = _cfg_load()
        _out_def = _d.get("delta_out") or os.path.join(os.path.expanduser("~"), "delta.db")
        self.v_delta_out = tk.StringVar(value=_out_def)
        ttk.Entry(row, textvariable=self.v_delta_out).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick_save(self.v_delta_out, "Сохранить дельту как", [("SQLite", "*.db")])).pack(side="left")

        self.v_delta_force = tk.BooleanVar()
        ttk.Checkbutton(t, text="Перезаписать существующий", variable=self.v_delta_force).pack(anchor="w", pady=4)

        btn = ttk.Frame(t)
        btn.pack(fill="x", pady=4)
        self.b_delta = ttk.Button(btn, text="Построить дельту (make_delta)", command=self.run_make_delta)
        self.b_delta.pack(side="left")

        ttk.Separator(t, orient="horizontal").pack(fill="x", pady=8)

        # --- 4. Публикация книги ---
        pubf = ttk.LabelFrame(t, text="4. Публикация книги", padding=6)
        pubf.pack(fill="x", pady=4)

        # Ключ
        row = ttk.Frame(pubf)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Ключ:", width=8).pack(side="left")
        self.v_pub_key = tk.StringVar()
        self.cmb_pub_key = ttk.Combobox(row, textvariable=self.v_pub_key, width=30)
        self.cmb_pub_key.pack(side="left", padx=4)
        ttk.Button(row, text="Обновить", command=self._refresh_pub_keys).pack(side="left")

        # Версия
        row = ttk.Frame(pubf)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Версия:", width=8).pack(side="left")
        self.v_pub_ver = tk.Label(row, text="—", foreground="gray")
        self.v_pub_ver.pack(side="left", padx=4)

        # Примечание
        row = ttk.Frame(pubf)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Примечание:", width=8).pack(side="left")
        self.v_pub_notes = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_pub_notes, width=70).pack(side="left", padx=4)

        # Галочка дельты
        self.v_pub_delta = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            pubf,
            text="Собрать дельту перед публикацией",
            variable=self.v_pub_delta,
        ).pack(anchor="w", pady=4)

        # Кнопка публикации
        self.b_publish_book = ttk.Button(
            pubf, text="🚀 Опубликовать книгу", command=self._publish_book
        )
        self.b_publish_book.pack(anchor="e", pady=6)

        # Подсказка
        ttk.Label(
            pubf,
            text=(
                "Достаточно указать OLD/NEW/OUT выше и примечание. "
                "Версия, ссылки, каталог и git — автоматически."
            ),
            foreground="gray",
            wraplength=500,
            justify="left",
        ).pack(anchor="w", pady=(0, 4))

        # Инфо
        info = ("Дельта содержит только изменённые стихи OLD→NEW.\n"
                "Приложение качает дельту и применяет upsert по координатам стихов.\n"
                "Книги сопоставляются по type (+ lang, если есть). _id в дельте = старый _id.")
        ttk.Label(t, text=info, foreground="gray", wraplength=500, justify="left").pack(fill="x")

    def _build_catalog_tab(self, nb):
        t = ttk.Frame(nb, padding=6)
        nb.add(t, text="📋 Каталог")

        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Папка БД:", width=10).pack(side="left")
        self.v_cat_src = tk.StringVar(value=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "DB"))
        ttk.Entry(row, textvariable=self.v_cat_src).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick_dir(self.v_cat_src)).pack(side="left")

        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="versions.json:", width=12).pack(side="left")
        self.v_cat_versions = tk.StringVar(value=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "updates", "versions.json"))
        ttk.Entry(row, textvariable=self.v_cat_versions).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick(self.v_cat_versions, "versions.json", [("JSON", "*.json")])).pack(side="left")

        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="OUT:", width=10).pack(side="left")
        self.v_cat_out = tk.StringVar(value=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "updates", "catalog.json"))
        ttk.Entry(row, textvariable=self.v_cat_out).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick_save(self.v_cat_out, "Сохранить каталог как", [("JSON", "*.json")])).pack(side="left")

        self.b_catalog = ttk.Button(t, text="Собрать catalog.json (make_catalog)", command=self.run_make_catalog)
        self.b_catalog.pack(fill="x", pady=4)

        info = ("make_catalog читает versions.json, считает size/sha256 у файлов,\n"
                "добавляет fingerprint книг и дельты, пишет catalog.json.\n"
                "Формат versions.json см. updates/versions.example.json")
        ttk.Label(t, text=info, foreground="gray", wraplength=500, justify="left").pack(fill="x")

    def _build_apk_delta_tab(self, nb):
        t = ttk.Frame(nb, padding=6)
        nb.add(t, text="📦 APK Дельта")

        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="OLD APK:", width=10).pack(side="left")
        self.v_apk_old = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_apk_old).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick(self.v_apk_old, "Старый APK", [("APK", "*.apk")])).pack(side="left")

        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="NEW APK:", width=10).pack(side="left")
        self.v_apk_new = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_apk_new).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick(self.v_apk_new, "Новый APK", [("APK", "*.apk")])).pack(side="left")

        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="OUT:", width=10).pack(side="left")
        self.v_apk_out = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "patch.bsdiff"))
        ttk.Entry(row, textvariable=self.v_apk_out).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick_save(self.v_apk_out, "Сохранить патч как", [("BSD Patch", "*.bsdiff")])).pack(side="left")

        self.v_apk_force = tk.BooleanVar()
        ttk.Checkbutton(t, text="Перезаписать существующий", variable=self.v_apk_force).pack(anchor="w", pady=4)

        self.b_apk_delta = ttk.Button(t, text="Построить bsdiff-патч (make_apk_delta)", command=self.run_make_apk_delta)
        self.b_apk_delta.pack(fill="x", pady=4)

        info = ("bsdiff-патч от СТАРОГО установленного APK к НОВОМУ.\n"
                "Клиент применяет патч к уже установленному APK — не нужен полный файл.\n"
                "Нужен пакет bsdiff4: pip install bsdiff4")
        ttk.Label(t, text=info, foreground="gray", wraplength=500, justify="left").pack(fill="x")

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

    def set_busy(self, v):
        uicommon.set_busy(self, v, (self.b_delta, self.b_catalog, self.b_apk_delta), self.prog)

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
            enc = locale.getpreferredencoding(False) or "utf-8"
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding=enc, errors="replace", bufsize=1,
                                    creationflags=dbcommon.nowin())
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

    def run_make_delta(self):
        old = self.v_delta_old.get().strip().strip('"').strip("'")
        new = self.v_delta_new.get().strip().strip('"').strip("'")
        out = self.v_delta_out.get().strip().strip('"').strip("'")
        if not old or not new or not out:
            missing = []
            if not old:
                missing.append("OLD")
            if not new:
                missing.append("NEW")
            if not out:
                missing.append("OUT")
            messagebox.showwarning("Пустые поля",
                "Вкладка «Δ Дельта БД».\n"
                "Пусто: " + ", ".join(missing) + "\n\n"
                "OLD: " + repr(self.v_delta_old.get().strip()) + "\n"
                "NEW: " + repr(self.v_delta_new.get().strip()) + "\n"
                "OUT: " + repr(self.v_delta_out.get().strip()) + "\n\n"
                "(Поля на вкладке «Релиз» — отдельные, они не подставляются сюда.)")
            return
        if not os.path.exists(old):
            messagebox.showerror("Нет файла", "OLD: " + old + "\nне найден")
            return
        if not os.path.exists(new):
            messagebox.showerror("Нет файла", "NEW: " + new + "\nне найден")
            return
        out_dir = os.path.dirname(out) or "."
        if not os.path.isdir(out_dir):
            messagebox.showerror("Нет папки", "Папка для OUT не существует:\n" + out_dir)
            return
        _cfg_save({"delta_old": old, "delta_new": new, "delta_out": out})
        cmd = [PY, MAKE_DELTA, "--old", old, "--new", new, "--out", out]
        if self.v_delta_force.get():
            cmd.append("--force")
        self._run_bg(cmd, "make_delta")

    def run_make_catalog(self):
        src = self.v_cat_src.get().strip()
        versions = self.v_cat_versions.get().strip()
        out = self.v_cat_out.get().strip()
        if not src or not versions or not out:
            messagebox.showwarning("Пустые поля", "Укажите папку БД, versions.json и OUT")
            return
        if not os.path.exists(versions):
            messagebox.showerror("Нет versions.json", f"Файл не найден: {versions}")
            return
        cmd = [PY, MAKE_CATALOG, "--src", src, "--versions", versions, "--out", out]
        self._run_bg(cmd, "make_catalog")

    def run_make_apk_delta(self):
        old = self.v_apk_old.get().strip()
        new = self.v_apk_new.get().strip()
        out = self.v_apk_out.get().strip()
        if not old or not new or not out:
            messagebox.showwarning("Пустые поля", "Укажите OLD APK, NEW APK и OUT")
            return
        if os.path.exists(out) and not self.v_apk_force.get():
            if not messagebox.askyesno("Файл существует", f"{out}\nПерезаписать?"):
                return
        cmd = [PY, MAKE_APK_DELTA, "--old", old, "--new", new, "--out", out]
        if self.v_apk_force.get():
            cmd.append("--force")
        self._run_bg(cmd, "make_apk_delta")


    # ------------------------------------------------------------------- публикация
    # -------------------------------------------------------------------

    def _refresh_pub_keys(self):
        """Загружаем список ключей из updates/versions.json (books + audio)."""
        try:
            import json
            with open(os.path.join(ROOT, "updates", "versions.json"), encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"books": {}, "audio": {}}
        keys = []
        for sec in ("books", "audio"):
            keys.extend(data.get(sec, {}).keys())
        self.cmb_pub_key["values"] = keys
        if keys:
            self.cmb_pub_key.current(0)
        self._update_pub_ver()

    def _update_pub_ver(self):
        """Обновляем метку версии для выбранного ключа."""
        key = self.v_pub_key.get()
        if not key:
            self.v_pub_ver.configure(text="—")
            return
        try:
            import json
            with open(os.path.join(ROOT, "updates", "versions.json"), encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            self.v_pub_ver.configure(text="—")
            return
        for sec in ("books", "audio"):
            meta = data.get(sec, {}).get(key, {})
            if meta:
                cur = int(meta.get("version", 0))
                self.v_pub_ver.configure(text="v%d → v%d" % (cur, cur + 1))
                return
        self.v_pub_ver.configure(text="—")

    def _on_pub_fields_change(self, *args):
        """При изменении OLD/NEW — пробуем auto-guess ключ."""
        old = self.v_delta_old.get().strip()
        if old:
            import publish_engine
            guessed = publish_engine.guess_key(old)
            if guessed:
                self.v_pub_key.set(guessed)
                self._update_pub_ver()
            elif len(self.cmb_pub_key["values"]) == 1:
                self.v_pub_key.set(self.cmb_pub_key["values"][0])
                self._update_pub_ver()
        # Обновляем галочку дельты
        new_f = self.v_delta_new.get().strip()
        out_f = self.v_delta_out.get().strip()
        self.v_pub_delta.set(bool(old and new_f and out_f))

    def _publish_book(self):
        """Кнопка публикации книги в фоне."""
        if self.busy:
            return
        new = self.v_delta_new.get().strip()
        key = self.v_pub_key.get()
        delta_checked = self.v_pub_delta.get()
        old = self.v_delta_old.get().strip()
        out = self.v_delta_out.get().strip()

        # Проверки
        if not new or not os.path.exists(new):
            messagebox.showwarning("Нет NEW", "Укажите существующий NEW .db")
            return
        if not key:
            messagebox.showwarning("Нет ключа", "Выберите ключ книги")
            return
        if delta_checked and (not old or not out):
            messagebox.showwarning("Нет дельты",
                                   "Снята галочка 'Собрать дельту', но OLD/OUT пусты.\n"
                                   "Укажите OLD/OUT для сборки дельты.")
            return

        # Сводка
        delta_info = " (будет собрана дельта)" if delta_checked else ""
        summary = ("Книга: %s\n"
                   "Версия: %s\n"
                   "Файл: %s%s" % (key, self.v_pub_ver.cget("text"), new, delta_info))
        if not messagebox.askyesno("Публиковать?", summary, parent=self):
            return

        self.set_busy(True)
        self.say("публикация: запуск…")
        threading.Thread(target=self._publish_worker, args=(new, key, delta_checked, old, out),
                         daemon=True).start()

    def _publish_worker(self, new_file, key, delta_checked, old, out):
        def say(t):
            self.q.put(("log", str(t)))
        try:
            import publish_engine
            import locale
            enc = locale.getpreferredencoding(False) or "utf-8"

            # 1) Собрать дельту если нужно
            delta_file = ""
            if delta_checked and old and out:
                say("make_delta: запуск…")
                cmd = [PY, MAKE_DELTA, "--old", old, "--new", new_file, "--out", out]
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding=enc, errors="replace", bufsize=1,
                    creationflags=dbcommon.nowin(),
                )
                out_lines = []
                for line in proc.stdout:
                    line = line.rstrip("\n\r")
                    if line:
                        out_lines.append(line)
                        self.q.put(("log", line))
                proc.wait()
                if proc.returncode != 0:
                    raise RuntimeError("make_delta: код %s\n%s" % (
                        proc.returncode, "\n".join(out_lines[-20:])))
                say("make_delta: готово")
                delta_file = out
            elif delta_checked and old and out:
                delta_file = out

            # 2) Публикация
            notes = self.v_pub_notes.get().strip()
            result = publish_engine.publish_book(
                token=gh_release.get_token(),
                key=key,
                new_file=new_file,
                notes=notes,
                delta_file=delta_file,
                delta_from=0,
                log=say,
            )
            self.q.put(("done", "Опубликовано: %s" % result["url"]))
            self._update_pub_ver()
            self._refresh_pub_keys()
        except gh_release.GHError as e:
            self.q.put(("error", "GitHub: %s" % e.message[:300]))
        except Exception as e:
            self.q.put(("error", str(e)))

    def set_busy(self, v):
        uicommon.set_busy(self, v, (self.b_delta, self.b_catalog, self.b_apk_delta,
                                     self.b_publish_book), self.prog)

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
            enc = locale.getpreferredencoding(False) or "utf-8"
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding=enc, errors="replace", bufsize=1,
                                    creationflags=dbcommon.nowin())
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

    def run_make_delta(self):
        old = self.v_delta_old.get().strip().strip('"').strip("'")
        new = self.v_delta_new.get().strip().strip('"').strip("'")
        out = self.v_delta_out.get().strip().strip('"').strip("'")
        if not old or not new or not out:
            missing = []
            if not old:
                missing.append("OLD")
            if not new:
                missing.append("NEW")
            if not out:
                missing.append("OUT")
            messagebox.showwarning("Пустые поля",
                "Вкладка «Δ Дельта БД».\n"
                "Пусто: " + ", ".join(missing) + "\n\n"
                "OLD: " + repr(self.v_delta_old.get().strip()) + "\n"
                "NEW: " + repr(self.v_delta_new.get().strip()) + "\n"
                "OUT: " + repr(self.v_delta_out.get().strip()) + "\n\n"
                "(Поля на вкладке «Релиз» — отдельные, они не подставляются сюда.)")
            return
        if not os.path.exists(old):
            messagebox.showerror("Нет файла", "OLD: " + old + "\nне найден")
            return
        if not os.path.exists(new):
            messagebox.showerror("Нет файла", "NEW: " + new + "\nне найден")
            return
        out_dir = os.path.dirname(out) or "."
        if not os.path.isdir(out_dir):
            messagebox.showerror("Нет папки", "Папка для OUT не существует:\n" + out_dir)
            return
        _cfg_save({"delta_old": old, "delta_new": new, "delta_out": out})
        cmd = [PY, MAKE_DELTA, "--old", old, "--new", new, "--out", out]
        if self.v_delta_force.get():
            cmd.append("--force")
        self._run_bg(cmd, "make_delta")

    def run_make_catalog(self):
        src = self.v_cat_src.get().strip()
        versions = self.v_cat_versions.get().strip()
        out = self.v_cat_out.get().strip()
        if not src or not versions or not out:
            messagebox.showwarning("Пустые поля", "Укажите папку БД, versions.json и OUT")
            return
        if not os.path.exists(versions):
            messagebox.showerror("Нет versions.json", f"Файл не найден: {versions}")
            return
        cmd = [PY, MAKE_CATALOG, "--src", src, "--versions", versions, "--out", out]
        self._run_bg(cmd, "make_catalog")

    def run_make_apk_delta(self):
        old = self.v_apk_old.get().strip()
        new = self.v_apk_new.get().strip()
        out = self.v_apk_out.get().strip()
        if not old or not new or not out:
            messagebox.showwarning("Пустые поля", "Укажите OLD APK, NEW APK и OUT")
            return
        if os.path.exists(out) and not self.v_apk_force.get():
            if not messagebox.askyesno("Файл существует", f"{out}\nПерезаписать?"):
                return
        cmd = [PY, MAKE_APK_DELTA, "--old", old, "--new", new, "--out", out]
        if self.v_apk_force.get():
            cmd.append("--force")
        self._run_bg(cmd, "make_apk_delta")


def test_imports():
    """Проверка импортов для бэкграундного запуска."""
    try:
        import bsdiff4
    except ImportError:
        return "bsdiff4 не установлен (pip install bsdiff4)"
    return None


if __name__ == "__main__":
    err = test_imports()
    if err:
        print(err)
    root = tk.Tk()
    root.title("Δ Дельта/Каталог")
    root.geometry("800x600")
    DeltaTab(root).pack(fill="both", expand=True)
    root.mainloop()