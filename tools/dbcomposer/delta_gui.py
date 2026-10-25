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
import uicommon

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
MAKE_DELTA = os.path.join(HERE, "make_delta.py")
MAKE_CATALOG = os.path.join(HERE, "make_catalog.py")
MAKE_APK_DELTA = os.path.join(HERE, "make_apk_delta.py")


class DeltaTab(ttk.Frame):
    def __init__(self, parent, app=None):
        super().__init__(parent)
        self.app = app
        self.q = queue.Queue()
        self.busy = False
        self._build_ui()
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
        self.v_delta_old = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_delta_old).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick(self.v_delta_old, "Старая база (.db)", [("SQLite", "*.db")])).pack(side="left")

        # NEW
        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="NEW .db:", width=10).pack(side="left")
        self.v_delta_new = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_delta_new).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick(self.v_delta_new, "Новая база (.db)", [("SQLite", "*.db")])).pack(side="left")

        # OUT
        row = ttk.Frame(t)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="OUT:", width=10).pack(side="left")
        self.v_delta_out = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "delta.db"))
        ttk.Entry(row, textvariable=self.v_delta_out).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Обзор…", command=lambda: self._pick_save(self.v_delta_out, "Сохранить дельту как", [("SQLite", "*.db")])).pack(side="left")

        self.v_delta_force = tk.BooleanVar()
        ttk.Checkbutton(t, text="Перезаписать существующий", variable=self.v_delta_force).pack(anchor="w", pady=4)

        btn = ttk.Frame(t)
        btn.pack(fill="x", pady=4)
        self.b_delta = ttk.Button(btn, text="Построить дельту (make_delta)", command=self.run_make_delta)
        self.b_delta.pack(side="left")

        ttk.Separator(t, orient="horizontal").pack(fill="x", pady=8)

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

    def run_make_delta(self):
        old = self.v_delta_old.get().strip()
        new = self.v_delta_new.get().strip()
        out = self.v_delta_out.get().strip()
        if not old or not new or not out:
            messagebox.showwarning("Пустые поля", "Укажите OLD, NEW и OUT")
            return
        if os.path.exists(out) and not self.v_delta_force.get():
            if not messagebox.askyesno("Файл существует", f"{out}\nПерезаписать?"):
                return
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