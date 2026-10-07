#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вкладка «Лекции DOCX» для dbcomposer: папка с Word-транскрипциями -> ОДНА книга .db.

В gui.py рядом с вкладкой «Сборка» (бывшее отдельное окно). Только стандартная
библиотека (tkinter + sqlite3). Сборка — через tools/lectures/lectures_build.py
(импортируется как модуль).

Модель: папка = ОДНА книга (название/автор/тип + одна обложка задаются разово сверху),
каждый .docx = ОДНА лекция. Иерархия — из имени файла: 001 (2.3.1-36),
338 (1.6.82-120) Величие Адвайты Ачарьи. Сортировка — по (песнь, глава, текст).

Шаги: 1) название/тип книги + обложка 2) «+ Папка DOCX» 3) проверить разбор
4) «СОБРАТЬ» 5) «На телефон (adb)» или импорт вручную (Настройки -> .db).
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
LECTURES_DIR = os.path.join(os.path.dirname(HERE), "lectures")
if LECTURES_DIR not in sys.path:
    sys.path.insert(0, LECTURES_DIR)
import lectures_build

import dbcommon

CFG_PATH = os.path.join(HERE, "lectures_gui.json")
LECTURES_VERSION = 3  # bump при правках вкладки — видно в заголовке
BOOK_TYPES = ("SCC", "SSB", "SBG", "SBRS")
TYPE_HINT = {"SCC": "Чайтанья Чаритамрита", "SSB": "Шримад-Бхагаватам",
             "SBG": "Бхагавад-гита", "SBRS": "Бхакти-расамрита-синдху"}


def load_cfg():
    return dbcommon.load_cfg(CFG_PATH)


def save_cfg(cfg):
    return dbcommon.save_cfg(CFG_PATH, cfg)


class LecturesTab(ttk.Frame):
    def __init__(self, parent, app=None):
        super().__init__(parent)
        self.app = app
        # path -> dict(song, ch, txts, title, ref, paras, src, unparsed, checked)
        self.rows = {}
        self.msg_q = queue.Queue()
        self.building = False
        self.book_cover = None
        self._photo = None
        self._activated = False
        cfg = load_cfg()
        self.last_folder = cfg.get("last_folder", "")

        # --- книга (одна на всю папку) ---
        book = ttk.LabelFrame(self, text="Книга (одна на всю папку)", padding=6)
        book.pack(fill="x", padx=6, pady=4)
        self.e_btitle = tk.StringVar(value=cfg.get("book_title", "Чайтанья Чаритамрита. Лекции"))
        self.e_bauthor = tk.StringVar(value=cfg.get("author", "Шьямакунда прабху"))
        self.e_btype = tk.StringVar(value=cfg.get("book_type", "SCC"))
        ttk.Label(book, text="Название:").grid(row=0, column=0, sticky="w")
        ttk.Entry(book, textvariable=self.e_btitle, width=46).grid(
            row=0, column=1, sticky="ew", padx=4)
        ttk.Label(book, text="Тип:").grid(row=0, column=2, sticky="w")
        ttk.Combobox(book, textvariable=self.e_btype, values=list(BOOK_TYPES),
                     width=6, state="readonly").grid(row=0, column=3, padx=4)
        self.type_hint = ttk.Label(book, text="")
        self.type_hint.grid(row=0, column=4, sticky="w")
        self.e_btype.trace_add("write", lambda *a: self.on_type_change())
        ttk.Label(book, text="Автор:").grid(row=1, column=0, sticky="w")
        ttk.Entry(book, textvariable=self.e_bauthor, width=46).grid(
            row=1, column=1, sticky="ew", padx=4)
        ttk.Button(book, text="Обложка…", command=self.pick_cover).grid(
            row=1, column=2, padx=4)
        ttk.Button(book, text="✕", command=self.clear_cover, width=3).grid(row=1, column=3)
        self.cover_preview = ttk.Label(book, text="без обложки")
        self.cover_preview.grid(row=1, column=4, padx=4)
        book.columnconfigure(1, weight=1)
        self.refresh_hint()
        if cfg.get("cover") and os.path.exists(cfg["cover"]):
            self.book_cover = cfg["cover"]
            self.show_cover()

        # --- файлы ---
        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        ttk.Button(top, text="+ Папка DOCX", command=self.add_folder).pack(side="left")
        ttk.Button(top, text="+ Файлы Word", command=self.add_files).pack(side="left", padx=4)
        ttk.Button(top, text="Очистить", command=self.clear_all).pack(side="left")
        ttk.Button(top, text="Выбрать все", command=lambda: self.set_all(True)).pack(side="right")
        ttk.Button(top, text="Снять все", command=lambda: self.set_all(False)).pack(side="right", padx=4)
        self.sum_label = ttk.Label(top, text="лекций: 0")
        self.sum_label.pack(side="right", padx=8)

        cols = ("section", "chapter", "texts", "title", "words", "file")
        self.tv = ttk.Treeview(self, columns=cols, show="tree headings", selectmode="browse")
        self.tv.heading("#0", text="✓")
        self.tv.column("#0", width=36, stretch=False, anchor="center")
        for c, label, w, anchor in (
                ("section", "Раздел", 90, "center"), ("chapter", "Глава", 60, "center"),
                ("texts", "Тексты", 80, "center"), ("title", "Заголовок", 280, "w"),
                ("words", "Слов", 60, "e"), ("file", "Файл", 260, "w")):
            self.tv.heading(c, text=label)
            self.tv.column(c, width=w, anchor=anchor, stretch=c in ("title", "file"))
        self.tv.pack(fill="both", expand=True, padx=6)
        self.tv.bind("<ButtonRelease-1>", self.on_click)
        self.tv.bind("<space>", self.on_space)
        self.tv.bind("<<TreeviewSelect>>", self.on_select)

        edit = ttk.Frame(self, padding=6)
        edit.pack(fill="x")
        ttk.Label(edit, text="Имя лекции:").pack(side="left")
        self.e_title = tk.StringVar()
        ttk.Entry(edit, textvariable=self.e_title, width=60).pack(
            side="left", fill="x", expand=True, padx=4)
        ttk.Button(edit, text="Применить", command=self.apply_title).pack(side="left")
        self.info = ttk.Label(self, text="Порядок в книге — по столбцам Раздел/Глава/Тексты, не по именам файлов.",
                              padding=(6, 0))
        self.info.pack(fill="x")

        out = ttk.Frame(self, padding=6)
        out.pack(fill="x")
        ttk.Label(out, text="Выход:").pack(side="left")
        self.e_out = tk.StringVar(
            value=cfg.get("out") or os.path.join(os.path.expanduser("~"), "lectures_clean.db"))
        ttk.Entry(out, textvariable=self.e_out).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(out, text="Обзор…", command=self.pick_out).pack(side="left")
        self.b_build = ttk.Button(out, text="СОБРАТЬ", command=self.start_build)
        self.b_build.pack(side="left", padx=6)
        self.prog = ttk.Progressbar(out, mode="indeterminate", length=100)
        self.prog.pack(side="left")

        phone = ttk.LabelFrame(self, text="На телефон", padding=6)
        phone.pack(fill="x", padx=6, pady=4)
        self.b_adb = ttk.Button(phone, text="📲 На телефон (adb push)", command=self.push_adb)
        self.b_adb.pack(side="left")
        ttk.Button(phone, text="Открыть папку", command=self.open_out_dir).pack(side="left", padx=4)
        ttk.Label(phone, text="или вручную: приложение -> Настройки -> .db -> выбрать файл").pack(
            side="left", padx=8)

        self.log = tk.Text(self, height=7, wrap="word")
        self.log.pack(fill="both", expand=False, padx=6, pady=(0, 6))
        self.after(150, self.poll)

    def on_activate(self):
        """Первый показ вкладки: тяжёлый разбор папки — только здесь, не на старте."""
        if self._activated:
            return
        self._activated = True
        if self.last_folder and os.path.isdir(self.last_folder):
            self.add_folder_path(self.last_folder)

    def refresh_hint(self):
        self.type_hint.configure(text=TYPE_HINT.get(self.e_btype.get(), ""))

    def on_type_change(self):
        # смена типа меняет префиксы REF и имена разделов — переразбираем, сохраняя галочки и ручные имена
        self.refresh_hint()
        if not self.rows:
            return
        keep = {p: (l["checked"], l.get("custom", False), l["name"]) for p, l in self.rows.items()}
        self.rows.clear()
        for p, (checked, custom, name) in keep.items():
            try:
                l = lectures_build.parse_single_lecture(p, self.e_btype.get() or "SCC")
            except Exception:
                continue
            l["checked"] = checked
            if custom:
                l["name"] = name
                l["custom"] = True
                l["title"] = lectures_build.build_display(
                    l["num"], l["txts"], l["name"], l["intro"]) or l["title"]
            self.rows[p] = l
        lectures_build.assign_intro_song(list(self.rows.values()))
        self.refresh_table()

    # ------------------------------------------------------------ файлы ---
    def _refocus(self):
        """Вкладка — окно не уходит в фон (диалоги parent=frame, уже поверх)."""
        pass

    def add_files(self):
        for p in filedialog.askopenfilenames(
                title="Word-транскрипции (каждый файл = одна лекция)",
                filetypes=[("Word", "*.docx *.doc"), ("Все", "*.*")],
                parent=self):
            self.load_docx(p)
        self._refocus()
        self.remember()

    def add_folder(self):
        d = filedialog.askdirectory(title="Папка с лекциями Word (станет ОДНОЙ книгой)",
                                    parent=self)
        self._refocus()
        if not d:
            return
        self.add_folder_path(d)

    def add_folder_path(self, d):
        n = 0
        for f in sorted(os.listdir(d)):
            if f.lower().endswith((".docx", ".doc")) and not f.startswith("~"):
                if self.load_docx(os.path.join(d, f), quiet=True):
                    n += 1
        self.last_folder = d
        self.remember()
        self.say("Папка %s: файлов Word %d" % (d, n))

    def load_docx(self, path, quiet=False):
        if path in self.rows:
            return False
        try:
            l = lectures_build.parse_single_lecture(path, self.e_btype.get() or "SCC")
        except Exception as e:
            if not quiet:
                messagebox.showerror("Ошибка", "%s\n%s" % (path, e))
            else:
                self.say("Пропуск %s: %s" % (os.path.basename(path), str(e)[:100]))
            return False
        l["checked"] = True
        self.rows[path] = l
        lectures_build.assign_intro_song(list(self.rows.values()))
        self.refresh_table()
        return True

    def section_name(self, song):
        names = dict(lectures_build.WORK_SONG_NAMES.get(self.e_btype.get() or "SCC", {}))
        if song == lectures_build.MISC_SONG:
            return "Разное"
        return names.get(song, "Раздел %s" % song)

    def refresh_table(self):
        for i in self.tv.get_children():
            self.tv.delete(i)
        def key(p):
            l = self.rows[p]
            try:
                s = int(l["song"])
            except Exception:
                s = 999
            try:
                c = int(l["ch"])
            except Exception:
                c = 999
            return (s, c, lectures_build.txt_start(l["txts"]), os.path.basename(p))
        for p in sorted(self.rows, key=key):
            l = self.rows[p]
            words = sum(len(x.split()) for x in l["paras"] if x.strip())
            mark = "?" if l["unparsed"] else ""
            ch_disp = "Введение" if l.get("intro") else ("" if l["unparsed"] else l["ch"])
            self.tv.insert("", "end", iid=p, text="☑" if l["checked"] else "☐", values=(
                mark + self.section_name(l["song"]), ch_disp,
                l["txts"] or "—", l["title"][:60], words, os.path.basename(p)))
        n = sum(1 for l in self.rows.values() if l["checked"])
        misc = sum(1 for l in self.rows.values() if l["unparsed"] and l["checked"])
        self.sum_label.configure(
            text="лекций: %d%s" % (n, (" (без привязки: %d)" % misc) if misc else ""))

    def clear_all(self):
        self.rows.clear()
        self.refresh_table()

    def set_all(self, v):
        for l in self.rows.values():
            l["checked"] = v
        self.refresh_table()

    def on_click(self, ev):
        iid = self.tv.identify_row(ev.y)
        if iid and self.tv.identify_column(ev.x) == "#0" and iid in self.rows:
            r = self.rows[iid]
            r["checked"] = not r["checked"]
            self.refresh_table()

    def on_space(self, ev):
        for iid in self.tv.selection():
            if iid in self.rows:
                self.rows[iid]["checked"] = not self.rows[iid]["checked"]
        self.refresh_table()
        return "break"

    def on_select(self, ev):
        sel = self.tv.selection()
        if not sel or sel[0] not in self.rows:
            return
        l = self.rows[sel[0]]
        # правится ИМЯ (часть после «Лекция №.. по стихам .. — »), каркас не трогаем
        self.e_title.set(l["name"])
        body = " ".join(x.strip() for x in l["paras"] if x.strip())
        self.info.configure(text="%s | %s | %s" % (
            l["title"][:80], l["ref"] or "без привязки", body[:160]))

    def apply_title(self):
        for iid in self.tv.selection():
            if iid in self.rows and self.e_title.get().strip():
                l = self.rows[iid]
                l["name"] = self.e_title.get().strip()
                l["custom"] = True
                l["title"] = lectures_build.build_display(
                    l["num"], l["txts"], l["name"], l["intro"]) or l["title"]
        self.refresh_table()

    # ------------------------------------------------------------ обложка --
    def pick_cover(self):
        # сразу диалог файла: выбирать строку не нужно, обложка одна на книгу.
        # WEBP/BMP тоже можно — сборка сама пережмёт в JPEG (нужен Pillow)
        p = filedialog.askopenfilename(title="Обложка книги (JPEG/PNG/WEBP/BMP)",
                                       filetypes=[("Картинки", "*.jpg *.jpeg *.png *.webp *.bmp"),
                                                  ("Все", "*.*")],
                                       parent=self)
        self._refocus()
        if p:
            self.book_cover = p
            self.show_cover()
            self.remember()
            self.say("Обложка книги: %s" % os.path.basename(p))

    def clear_cover(self):
        self.book_cover = None
        self.show_cover()
        self.remember()

    def show_cover(self):
        if not self.book_cover:
            self.cover_preview.configure(text="без обложки", image="")
            self._photo = None
            return
        try:
            from PIL import Image as _PILImage, ImageTk as _PILImageTk
            img = _PILImage.open(self.book_cover)
            img.thumbnail((120, 120))
            photo = _PILImageTk.PhotoImage(img)
            self.cover_preview.configure(image=photo, text="")
            self._photo = photo
        except Exception:
            self.cover_preview.configure(
                text="◉ " + os.path.basename(self.book_cover)[:24], image="")
            self._photo = None

    # ------------------------------------------------------------ сборка ---
    def pick_out(self):
        p = filedialog.asksaveasfilename(title="Куда сохранить .db", defaultextension=".db",
                                         filetypes=[("SQLite", "*.db")],
                                         parent=self)
        self._refocus()
        if p:
            self.e_out.set(p)
            self.remember()

    def start_build(self):
        if self.building:
            return
        chosen = [p for p, l in self.rows.items() if l["checked"]]
        if not chosen:
            messagebox.showwarning("Пусто", "Отметь хотя бы одну лекцию")
            return
        out = self.e_out.get().strip()
        if not out:
            messagebox.showwarning("Нет выхода", "Укажи выходной файл")
            return
        if os.path.exists(out) and not messagebox.askyesno(
                "Перезапись", "Файл есть. Перезаписать?\n%s" % out):
            return
        spec = {
            "out": out,
            "book": {
                "title": self.e_btitle.get().strip() or "Лекции",
                "type": self.e_btype.get().strip() or "SCC",
                "author": self.e_bauthor.get().strip() or "Шьямакунда прабху",
                **({"cover_file": self.book_cover} if self.book_cover else {}),
            },
            "files": [{"docx": p} for p in chosen],
        }
        # имена (сырая часть, НЕ готовый заголовок!) едут force-ключами
        for f in spec["files"]:
            n = self.rows[f["docx"]]["name"]
            if n:
                f["force_title"] = n
        fd, spec_path = tempfile.mkstemp(prefix="lecspec_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(spec, fh, ensure_ascii=False, indent=1)
        self.remember()
        self.building = True
        self.b_build.state(["disabled"])
        self.prog.start(12)
        threading.Thread(target=self.run_build, args=(spec_path, out), daemon=True).start()

    def run_build(self, spec_path, out):
        try:
            report = lectures_build.build_lectures_book(spec_path, out, True)
            self.msg_q.put(("done", "ГОТОВО: %s\n%s" % (out, report)))
        except Exception:
            import traceback
            self.msg_q.put(("done", "ОШИБКА:\n%s" % traceback.format_exc()))
        finally:
            try:
                os.remove(spec_path)
            except Exception:
                pass

    # ------------------------------------------------------------ телефон --
    def push_adb(self):
        out = self.e_out.get().strip()
        if not out or not os.path.exists(out):
            messagebox.showwarning("Нет файла", "Сначала СОБРАТЬ — выходного .db нет")
            return
        adb = shutil.which("adb")
        if not adb:
            messagebox.showinfo(
                "Нет adb",
                "adb не найден в PATH.\n\nВручную: скопируй\n%s\nна телефон и открой в приложении "
                "(Настройки -> .db)." % out)
            return
        self.b_adb.state(["disabled"])
        threading.Thread(target=self.run_push, args=(adb, out), daemon=True).start()

    def run_push(self, adb, out):
        try:
            dest = "/sdcard/Download/%s" % os.path.basename(out)
            r = subprocess.run([adb, "push", out, dest],
                               capture_output=True, text=True, timeout=600)
            log = (r.stdout + "\n" + r.stderr).strip()
            if r.returncode == 0:
                self.msg_q.put(("info",
                                "На телефоне: %s\nОткрой приложение -> Настройки -> .db "
                                "и выбери файл.\n%s" % (dest, log)))
            else:
                self.msg_q.put(("info", "adb push не удался (код %d):\n%s"
                                % (r.returncode, log)))
        except Exception as e:
            self.msg_q.put(("info", "adb push: %s" % e))
        finally:
            self.msg_q.put(("adb_done", ""))

    def open_out_dir(self):
        out = self.e_out.get().strip()
        d = os.path.dirname(out) if out else ""
        if d and os.path.isdir(d):
            try:
                os.startfile(d)
            except Exception:
                pass

    # ------------------------------------------------------------ прочее ---
    def remember(self):
        save_cfg({"last_folder": self.last_folder,
                  "author": self.e_bauthor.get().strip(),
                  "book_title": self.e_btitle.get().strip(),
                  "book_type": self.e_btype.get().strip(),
                  "cover": self.book_cover,
                  "out": self.e_out.get().strip()})

    def poll(self):
        try:
            while True:
                kind, text = self.msg_q.get_nowait()
                if kind == "done":
                    self.building = False
                    self.b_build.state(["!disabled"])
                    self.prog.stop()
                if kind == "adb_done":
                    try:
                        self.b_adb.state(["!disabled"])
                    except Exception:
                        pass
                    continue
                self.say(text)
        except queue.Empty:
            pass
        self.after(150, self.poll)

    def say(self, text):
        self.log.insert("end", text + "\n")
        self.log.see("end")
