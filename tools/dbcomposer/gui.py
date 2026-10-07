#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dbcomposer GUI — чистка и пересборка библиотечных .db для Гухьятамы.

Запуск:  py gui.py   (только стандартная библиотека: tkinter + sqlite3)
Вкладки сверху: Сборка | Лекции DOCX | Базы Аудио | AI-импорт (переключение кликом).
Логика сборки — в recompose.py (импортируется как модуль).
"""
import json
import os
import queue
import re
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import dbcommon
import recompose
import lectures_gui
import audio_gui
import ai_import

APP_TITLE = "dbcomposer v%s — чистка библиотечных баз" % recompose.TOOLS_VERSION
CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dbcomposer.json")


def load_cfg():
    return dbcommon.load_cfg(CFG_PATH)


def save_cfg(cfg):
    return dbcommon.save_cfg(CFG_PATH, cfg)


def file_sig(p):
    st = os.stat(p)
    return [st.st_size, st.st_mtime]


#: типы писем, раскладываемых по темам (пара «письма + темы», напр. LTRS + LTR)
LETTER_TYPES = ("LTRS", "LTR")


def _title_script(row):
    """Письменность названия: 'cy' (есть кириллица) или 'lat». Смешивать языки
    в merge нельзя (русские письма + английские темы = каша)."""
    t = row.get('new_title') or row.get('title') or ''
    return 'cy' if re.search(r'[А-Яа-яЁё]', t) else 'lat'


def find_topic_donor(letters_row, all_rows):
    """Книга тем для писем: ПАРНЫЙ тип (LTRS<->LTR), есть главы, нет стихов.
    Тот же файл — всегда можно; чужой файл — только та же письменность
    (русские письма не мержим с английскими темами и наоборот).
    Возвращает (row-донор, отвергнутый) или (None, None). Второй элемент нужен,
    чтобы объяснить в логе, почему не смержили (темы на другом языке)."""
    lt = (letters_row.get('type') or '').upper()
    if lt not in LETTER_TYPES or not letters_row.get('verses'):
        return None, None
    want = [t for t in LETTER_TYPES if t != lt]
    cands = [r for r in all_rows
             if r is not letters_row
             and (r.get('type') or '').upper() in want
             and r.get('chapters') and not r.get('verses')]
    if not cands:
        return None, None
    same = [r for r in cands if r.get('file') == letters_row.get('file')]
    if same:
        return same[0], None
    lscript = _title_script(letters_row)
    for r in cands:
        if _title_script(r) == lscript:
            return r, None
    # донор есть, но на другом языке — не мержим, объясняем почему
    return None, cands[0]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1040x720")
        # iid -> dict(file, book_id, title, author, type, chapters, verses, images, junk, checked,
        #            new_title, new_author, new_type)
        self.rows = {}
        self.msg_q = queue.Queue()
        self.building = False
        self.sort_col = None
        self.sort_rev = False
        # (file, book_id) -> {'chapters': {(song,num)}, 'verses': {(song,ch,txt)}}
        self.excl = {}
        # (file, book_id) -> set(image_id) на удаление
        self.imgdrop = {}
        # (file, book_id) -> ('id', image_id) | ('file', path) | отсутствует
        self.covers = {}

        # вкладки сверху: содержимое сборки — в «Сборке», инструменты — в своих
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        build = ttk.Frame(self.nb)
        self.nb.add(build, text="Сборка")

        top = ttk.Frame(build, padding=6)
        top.pack(fill="x")
        ttk.Button(top, text="+ Файлы .db", command=self.add_files).pack(side="left")
        ttk.Button(top, text="+ Папка", command=self.add_folder).pack(side="left", padx=4)
        ttk.Button(top, text="Очистить", command=self.clear_all).pack(side="left")
        ttk.Button(top, text="Выбрать все", command=lambda: self.set_all(True)).pack(side="right")
        ttk.Button(top, text="Снять все", command=lambda: self.set_all(False)).pack(side="right", padx=4)
        ttk.Button(top, text="Содержимое", command=self.open_content).pack(side="right", padx=4)

        cols = ("title", "type", "chapters", "verses", "junk", "file")
        self.tv = ttk.Treeview(build, columns=cols, show="tree headings", selectmode="browse")
        self.tv.heading("#0", text="✓")
        self.tv.column("#0", width=36, stretch=False, anchor="center")
        for c, label, w, anchor in (
                ("title", "Книга ▲▼", 260, "w"), ("type", "Тип ▲▼", 60, "center"),
                ("chapters", "Глав ▲▼", 60, "e"), ("verses", "Стихов ▲▼", 70, "e"),
                ("junk", "Мусор", 220, "w"), ("file", "Файл ▲▼", 220, "w")):
            self.tv.heading(c, text=label, command=lambda cc=c: self.sort_by(cc))
            self.tv.column(c, width=w, anchor=anchor, stretch=c in ("title", "junk", "file"))
        self.tv.pack(fill="both", expand=True, padx=6)
        self.tv.bind("<ButtonRelease-1>", self.on_click)
        self.tv.bind("<space>", self.on_space)
        self.tv.bind("<Double-Button-1>", self.on_double)
        self.tv.bind("<<TreeviewSelect>>", self.on_select)

        edit = ttk.LabelFrame(build, text="Выбранная книга (переименовать при сборке)", padding=6)
        edit.pack(fill="x", padx=6, pady=4)
        self.e_title = tk.StringVar()
        self.e_author = tk.StringVar()
        self.e_type = tk.StringVar()
        ttk.Label(edit, text="Название:").grid(row=0, column=0, sticky="w")
        ttk.Entry(edit, textvariable=self.e_title, width=48).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(edit, text="Тип:").grid(row=0, column=2, sticky="w")
        ttk.Entry(edit, textvariable=self.e_type, width=10).grid(row=0, column=3, padx=4)
        ttk.Label(edit, text="Автор:").grid(row=1, column=0, sticky="w")
        ttk.Entry(edit, textvariable=self.e_author, width=48).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Button(edit, text="Применить", command=self.apply_edit).grid(row=1, column=2, columnspan=2)
        edit.columnconfigure(1, weight=1)

        opts = ttk.LabelFrame(build, text="Чистка", padding=6)
        opts.pack(fill="x", padx=6, pady=4)
        self.v_err = tk.BooleanVar(value=True)
        self.v_empty = tk.BooleanVar(value=True)
        self.v_dup = tk.BooleanVar(value=True)
        self.v_ch = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="@ERROR-строки", variable=self.v_err).pack(side="left")
        ttk.Checkbutton(opts, text="пустые стихи", variable=self.v_empty).pack(side="left")
        ttk.Checkbutton(opts, text="дубли", variable=self.v_dup).pack(side="left")
        ttk.Checkbutton(opts, text="пустые главы", variable=self.v_ch).pack(side="left")
        self.v_merge = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="📨 письма по темам (LTRS+LTR)",
                        variable=self.v_merge).pack(side="left")

        out = ttk.Frame(build, padding=6)
        out.pack(fill="x")
        ttk.Label(out, text="Выход:").pack(side="left")
        self.e_out = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "clean_library.db"))
        ttk.Entry(out, textvariable=self.e_out).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(out, text="Обзор…", command=self.pick_out).pack(side="left")
        self.b_build = ttk.Button(out, text="СОБРАТЬ", command=self.start_build)
        self.b_build.pack(side="left", padx=6)
        self.prog = ttk.Progressbar(out, mode="indeterminate", length=120)
        self.prog.pack(side="left")
        ttk.Button(out, text="📋", command=self.copy_log).pack(side="left", padx=4)

        self.log = tk.Text(build, height=9, wrap="word")
        self.log.pack(fill="both", expand=False, padx=6, pady=(0, 6))
        self.log.bind("<Key>", self._log_key)

        # вкладки-инструменты (бывшие отдельные окна). Создаются сразу, но
        # тяжёлая инициализация — при первом показе (см. on_tab/on_activate)
        self.tab_lectures = lectures_gui.LecturesTab(self.nb, self)
        self.nb.add(self.tab_lectures, text="📖 Лекции DOCX")
        self.tab_audio = audio_gui.AudioTab(self.nb, self)
        self.nb.add(self.tab_audio, text="🎧 Базы Аудио")
        self.tab_ai = ai_import.AIImportTab(self.nb, self)
        self.nb.add(self.tab_ai, text="🤖 AI-импорт")
        self.nb.bind("<<NotebookTabChanged>>", self.on_tab)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.after(150, self.poll)
        self.after(400, self.startup_scan)

    def on_tab(self, _ev):
        """Первый показ вкладки — её разовый тяжёлый activate (папка лекций)."""
        try:
            w = self.nb.nametowidget(self.nb.select())
        except tk.TclError:
            return
        act = getattr(w, "on_activate", None)
        if act is not None:
            act()

    def on_close(self):
        """Крестик окна: не даём оборвать идущую работу, конфиги сохраняем."""
        busy = []
        if self.building:
            busy.append("сборка библиотеки")
        if self.tab_lectures.building:
            busy.append("сборка лекций")
        if self.tab_audio.busy:
            busy.append("аудио-задача")
        if self.tab_ai.busy:
            busy.append("ИИ-задача")
        if busy:
            messagebox.showwarning(
                "Занято",
                "Идёт: %s.\nДождись конца или нажми Стоп." % ", ".join(busy))
            return
        try:
            self.tab_audio._save()
        except Exception:
            pass
        # llama-server, поднятый этой вкладкой, — гасим вместе с окном
        try:
            if self.tab_ai.server.alive():
                self.tab_ai.server.stop()
        except Exception:
            pass
        self.destroy()

    def startup_scan(self):
        """При старте — молча подхватить запомненную папку. Без изменений — без шума."""
        cfg = load_cfg()
        d = cfg.get("last_folder", "")
        if not d or not os.path.isdir(d):
            return
        saved = cfg.get("files", {})
        cur = {}
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".db") and "journal" not in f.lower():
                p = os.path.join(d, f)
                try:
                    cur[p] = file_sig(p)
                except OSError:
                    pass
        if not cur:
            return
        if cur == saved:
            for p in cur:
                self.load_file(p, quiet=True, silent=True)
            self.say("Папка %s: без изменений, файлов %d" % (d, len(cur)))
        else:
            self.say("Папка %s: есть изменения — сканирую" % d)
            self.add_folder_path(d)

    # ------------------------------------------------------------ файлы ---
    def add_files(self):
        for p in filedialog.askopenfilenames(
                title="Библиотечный .db", filetypes=[("SQLite", "*.db"), ("Все", "*.*")]):
            self.load_file(p)

    def add_folder(self):
        d = filedialog.askdirectory(title="Папка с .db")
        if not d:
            return
        self.add_folder_path(d)

    def add_folder_path(self, d):
        n = skipped = 0
        sigs = {}
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".db") and "journal" not in f.lower():
                p = os.path.join(d, f)
                r = self.load_file(p, quiet=True)
                if r == "ok":
                    n += 1
                    try:
                        sigs[p] = file_sig(p)
                    except OSError:
                        pass
                elif r == "skip":
                    skipped += 1
        cfg = load_cfg()
        cfg["last_folder"] = d
        cfg["files"] = sigs
        save_cfg(cfg)
        self.say("Папка %s: файлов %d%s" % (
            d, n, (", пропущено не-библиотечных: %d" % skipped) if skipped else ""))

    def clear_all(self):
        self.rows.clear()
        for i in self.tv.get_children():
            self.tv.delete(i)

    def load_file(self, path, quiet=False, silent=False):
        """Возвращает ok/skip/err. Не-библиотечные .db (без books) — тихий пропуск."""
        try:
            books = recompose.inspect_data(path)
        except Exception as e:
            msg = str(e)
            if "no such table" in msg.lower() and "books" in msg.lower():
                if not silent:
                    self.say("Пропуск (не библиотека): %s" % os.path.basename(path))
                return "skip"
            if quiet:
                if not silent:
                    self.say("Пропуск %s: %s" % (os.path.basename(path), msg[:100]))
                return "skip"
            messagebox.showerror("Ошибка", "%s\n%s" % (path, e))
            return "err"
        for b in books:
            iid = "%s||%d" % (path, b['book_id'])
            if iid in self.rows:
                continue
            self.rows[iid] = dict(b, file=path, checked=True,
                                  new_title=b['title'], new_author=b['author'], new_type=b['type'])
            mark = "◉ " if (path, b['book_id']) in self.covers else ""
            self.tv.insert("", "end", iid=iid, text="☑", values=(
                mark + b['title'][:60], b['type'], b['chapters'], b['verses'],
                "; ".join(b['junk']) or "—", os.path.basename(path)))
        if not silent:
            self.say("%s: книг %d" % (os.path.basename(path), len(books)))
        return "ok"

    def refresh_cover_marks(self):
        """◉ в таблице у книг с назначенной обложкой (видно до сборки)."""
        for iid, r in self.rows.items():
            try:
                vals = list(self.tv.item(iid, "values"))
                title = vals[0] if vals else ""
                base = title[2:] if title.startswith("◉ ") else title
                if (r['file'], r['book_id']) in self.covers:
                    vals[0] = "◉ " + base
                else:
                    vals[0] = base
                self.tv.item(iid, values=vals)
            except Exception:
                pass

    # ------------------------------------------------------------ таблица --
    def set_all(self, v):
        for iid in self.rows:
            self.rows[iid]['checked'] = v
            self.tv.item(iid, text="☑" if v else "☐")

    def toggle(self, iid):
        if iid in self.rows:
            r = self.rows[iid]
            r['checked'] = not r['checked']
            self.tv.item(iid, text="☑" if r['checked'] else "☐")

    def sort_by(self, col):
        if self.sort_col == col:
            self.sort_rev = not self.sort_rev
        else:
            self.sort_col, self.sort_rev = col, False

        def key(iid):
            r = self.rows.get(iid)
            if not r:
                return (1, "", "")
            if col in ("chapters", "verses"):
                try:
                    return (0, float(r[col]), "")
                except (TypeError, ValueError):
                    return (0, -1.0, "")
            v = {"title": r['title'], "type": r['type']}.get(col, "")
            if col == "file":
                v = os.path.basename(r['file'])
            return (1, str(v).lower(), "")

        for pos, iid in enumerate(sorted(self.rows, key=key, reverse=self.sort_rev)):
            self.tv.move(iid, "", pos)
        arrow = " ▲" if not self.sort_rev else " ▼"
        names = {"title": "Книга", "type": "Тип", "chapters": "Глав",
                 "verses": "Стихов", "file": "Файл"}
        for c, label in names.items():
            self.tv.heading(c, text=label + (arrow if c == col else ""))

    def on_click(self, ev):
        iid = self.tv.identify_row(ev.y)
        if iid and self.tv.identify_column(ev.x) == "#0":
            self.toggle(iid)

    def on_space(self, ev):
        for iid in self.tv.selection():
            self.toggle(iid)
        return "break"

    def on_double(self, ev):
        iid = self.tv.identify_row(ev.y)
        if iid and iid in self.rows:
            if iid not in self.tv.selection():
                self.tv.selection_set(iid)
            self.on_select(None)
            self.open_content()
        return "break"

    def on_select(self, ev):
        sel = self.tv.selection()
        if not sel:
            return
        r = self.rows.get(sel[0])
        if not r:
            return
        self.e_title.set(r['new_title'])
        self.e_author.set(r['new_author'])
        self.e_type.set(r['new_type'])

    def apply_edit(self):
        for iid in self.tv.selection():
            r = self.rows.get(iid)
            if not r:
                continue
            r['new_title'] = self.e_title.get().strip() or r['title']
            r['new_author'] = self.e_author.get().strip()
            r['new_type'] = (self.e_type.get().strip() or r['type'])
            self.tv.set(iid, "title", r['new_title'][:60])
            self.tv.set(iid, "type", r['new_type'])
        self.say("Переименование применено к выделенной строке")

    # ------------------------------------------------------------ сборка ---
    def open_content(self):
        sel = self.tv.selection()
        if not sel:
            messagebox.showinfo("Содержимое", "Выдели строку книги")
            return
        r = self.rows.get(sel[0])
        if not r:
            return
        ContentWin(self, r['file'], r['book_id'], r['title'], self.excl)

    def pick_out(self):
        p = filedialog.asksaveasfilename(title="Куда сохранить", defaultextension=".db",
                                         filetypes=[("SQLite", "*.db")])
        if p:
            self.e_out.set(p)

    def start_build(self):
        if self.building:
            return
        chosen = [r for r in self.rows.values() if r['checked']]
        if not chosen:
            messagebox.showwarning("Пусто", "Отметь хотя бы одну книгу")
            return
        out = self.e_out.get().strip()
        if not out:
            messagebox.showwarning("Нет выхода", "Укажи выходной файл")
            return
        if os.path.exists(out) and not messagebox.askyesno("Перезапись", "Файл есть. Перезаписать?\n%s" % out):
            return
        # merge писем по темам: книга тем (главы есть, стихов нет) отдаёт главы,
        # сама из сборки исключается — иначе в приложении висят 256 пустых тем
        merge_notes = []
        donors_used = set()
        topics_map = {}
        if self.v_merge.get():
            for r in chosen:
                d, refused = find_topic_donor(r, list(self.rows.values()))
                if d is None:
                    if (r.get('type') or '').upper() in LETTER_TYPES and r.get('verses'):
                        if refused is not None:
                            merge_notes.append(
                                "merge: '%s' НЕ тронута — книга тем '%s' на другом языке" %
                                (r['title'][:40], refused['title'][:40]))
                        else:
                            merge_notes.append(
                                "merge: для '%s' нет книги тем (парный тип без стихов) — сборка по годам" %
                                r['title'][:40])
                    continue
                topics_map[id(r)] = {"file": d['file'], "book_id": d['book_id']}
                donors_used.add((d['file'], d['book_id']))
                merge_notes.append("merge: '%s' -> по темам из '%s'" %
                                   (r['title'][:40], d['title'][:40]))
        chosen = [r for r in chosen if (r['file'], r['book_id']) not in donors_used]
        if donors_used:
            merge_notes.append("книги тем из сборки исключены (их главы — внутри писем)")
        spec = {
            "out": out,
            "drop_error_rows": self.v_err.get(),
            "drop_empty_verses": self.v_empty.get(),
            "dedupe": self.v_dup.get(),
            "drop_empty_chapters": self.v_ch.get(),
            "books": [{
                "file": r['file'], "book_id": r['book_id'],
                "title": r['new_title'], "author": r['new_author'], "type": r['new_type'],
                "exclude_chapters": sorted(self.excl.get((r['file'], r['book_id']), {}).get('chapters', set())),
                "exclude_verses": sorted(self.excl.get((r['file'], r['book_id']), {}).get('verses', set())),
                "drop_images": sorted(self.imgdrop.get((r['file'], r['book_id']), set())),
                **self._cover_spec(r),
                **(({"topics_from": topics_map[id(r)]} if id(r) in topics_map else {})),
            } for r in chosen],
        }
        fd, spec_path = tempfile.mkstemp(prefix="dbspec_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False, indent=1)
        for n in merge_notes:
            self.say(n)
        self.building = True
        self.b_build.state(["disabled"])
        self.prog.start(12)
        threading.Thread(target=self.run_build, args=(spec_path, out), daemon=True).start()

    def _cover_spec(self, r):
        c = self.covers.get((r['file'], r['book_id']))
        if not c:
            return {}
        if c[0] == 'file':
            return {"cover_file": c[1]}
        return {"cover_image": c[1]}

    def run_build(self, spec_path, out):
        try:
            report = recompose.build(spec_path, out, True)
            self.msg_q.put(("done", "ГОТОВО: %s\n%s" % (out, report)))
        except Exception as e:
            import traceback
            self.msg_q.put(("done", "ОШИБКА:\n%s" % traceback.format_exc()))
        finally:
            try:
                os.remove(spec_path)
            except Exception:
                pass

    def poll(self):
        try:
            while True:
                kind, text = self.msg_q.get_nowait()
                if kind == "done":
                    self.building = False
                    self.b_build.state(["!disabled"])
                    self.prog.stop()
                self.say(text)
        except queue.Empty:
            pass
        self.after(150, self.poll)

    def say(self, text):
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def _log_key(self, ev):
        """Лог только для чтения. Копирование — вручную по коду физ. клавиши
        (65=A/Ф выделить всё, 67=C/С скопировать), раскладка не важна."""
        if ev.state & 0x4:  # Ctrl
            w = ev.widget
            if ev.keycode == 65:
                w.tag_add("sel", "1.0", "end-1c")
                return "break"
            if ev.keycode in (67, 45):
                try:
                    sel = w.get("sel.first", "sel.last")
                    w.clipboard_clear()
                    w.clipboard_append(sel)
                except Exception:
                    pass
                return "break"
            return "break"
        if ev.keysym in ("Up", "Down", "Left", "Right", "Home", "End",
                         "Prior", "Next", "Shift_L", "Shift_R",
                         "Control_L", "Control_R", "Caps_Lock"):
            return None
        return "break"

    def copy_log(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.log.get("1.0", "end-1c"))
        except Exception:
            pass


class ContentWin(tk.Toplevel):
    """Содержимое книги: главы (со счётчиком стихов!), стихи с фильтрами, мусор.
    Галочка — исключить из сборки (главы тянут свои стихи)."""

    def __init__(self, app, path, book_id, title, excl):
        super().__init__(app)
        self.app = app
        self.path = path
        self.book_id = book_id
        self.excl = excl
        self.key = (path, book_id)
        if self.key not in self.excl:
            self.excl[self.key] = {'chapters': set(), 'verses': set()}
        # iid -> ключ строки (iid уникальны счётчиком: в базах есть полные дубли)
        self._keys = {}
        self._n = 0
        self.title("Содержимое: %s" % title[:60])
        self.geometry("980x560")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        # --- главы ---
        f1 = ttk.Frame(nb)
        nb.add(f1, text="Главы")
        self.tv_ch = ttk.Treeview(f1, columns=("num", "title", "verses"), show="tree headings")
        self.tv_ch.heading("#0", text="✕")
        self.tv_ch.column("#0", width=36, stretch=False, anchor="center")
        self.tv_ch.heading("num", text="№")
        self.tv_ch.column("num", width=70, anchor="center")
        self.tv_ch.heading("title", text="Название")
        self.tv_ch.column("title", width=420)
        self.tv_ch.heading("verses", text="Стихов")
        self.tv_ch.column("verses", width=70, anchor="e")
        self.tv_ch.pack(fill="both", expand=True)
        self.tv_ch.bind("<ButtonRelease-1>", self.on_ch_click)
        ttk.Label(f1, text="Клик по ✕ — исключить главу (и её стихи) из сборки").pack(anchor="w")
        self._safe_load(self.load_chapters)

        # --- стихи ---
        f2 = ttk.Frame(nb)
        nb.add(f2, text="Стихи")
        fr = ttk.Frame(f2)
        fr.pack(fill="x")
        ttk.Label(fr, text="Показать:").pack(side="left")
        self.v_kind = tk.StringVar(value="all")
        kinds = [("all", "все"), ("error", "@ERROR"), ("dup", "дубли"),
                 ("empty", "пустые"), ("orphan", "без глав"), ("gallery", "галереи")]
        for val, label in kinds:
            ttk.Radiobutton(fr, text=label, value=val, variable=self.v_kind).pack(side="left")
        self.e_search = tk.StringVar()
        ttk.Entry(fr, textvariable=self.e_search, width=24).pack(side="left", padx=6)
        ttk.Button(fr, text="Найти", command=self.load_verses).pack(side="left")
        self.tv_v = ttk.Treeview(f2, columns=("song", "ch", "txt", "preview"), show="tree headings")
        self.tv_v.heading("#0", text="✕")
        self.tv_v.column("#0", width=36, stretch=False, anchor="center")
        for c, label, w in (("song", "song", 70), ("ch", "ch", 70),
                            ("txt", "txt", 90), ("preview", "preview", 480)):
            self.tv_v.heading(c, text=label)
            self.tv_v.column(c, width=w, anchor="w" if c == "preview" else "center")
        self.tv_v.pack(fill="both", expand=True)
        self.tv_v.bind("<ButtonRelease-1>", self.on_v_click)
        ttk.Label(f2, text="Клик по ✕ — исключить стих из сборки").pack(anchor="w")
        self._safe_load(self.load_verses)

        # --- мусор ---
        f3 = ttk.Frame(nb)
        nb.add(f3, text="Мусор")
        self.tx = tk.Text(f3, wrap="word", state="disabled")
        self.tx.pack(fill="both", expand=True)
        self._safe_load(self.load_junk)

        # --- картинки ---
        f4 = ttk.Frame(nb)
        nb.add(f4, text="Картинки")
        fr4 = ttk.Frame(f4)
        fr4.pack(fill="x")
        self.img_info = ttk.Label(fr4, text="…")
        self.img_info.pack(side="left")
        ttk.Button(fr4, text="Выделить все", command=self.toggle_all_images).pack(side="right")
        ttk.Button(fr4, text="Экспорт в папку", command=self.export_images).pack(side="right")
        ttk.Button(fr4, text="Обложка из файла…", command=self.cover_from_file).pack(side="right", padx=4)
        ttk.Button(fr4, text="✕ обложка", command=self.cover_clear).pack(side="right", padx=4)
        self.tv_img = ttk.Treeview(f4, columns=("size", "dim", "link", "desc", "cover"),
                                   show="tree headings")
        self.tv_img.heading("#0", text="✕")
        self.tv_img.column("#0", width=36, stretch=False, anchor="center")
        self.tv_img.heading("size", text="КБ ▲▼", command=lambda: self.sort_img("size"))
        self.tv_img.column("size", width=70, anchor="e")
        for c, label, w in (("dim", "Размер", 90),
                            ("link", "Привязка", 110), ("desc", "Описание", 320),
                            ("cover", "Обложка", 70)):
            self.tv_img.heading(c, text=label)
            self.tv_img.column(c, width=w, anchor="w" if c == "desc" else "center")
        self.tv_img.pack(fill="both", expand=True)
        self.tv_img.bind("<ButtonRelease-1>", self.on_img_click)
        self.tv_img.bind("<<TreeviewSelect>>", self.on_img_select)
        ttk.Label(f4, text="✕ — удалить из сборки · ○ — назначить обложкой · клик по строке — предпросмотр").pack(anchor="w")
        pv = ttk.Frame(f4)
        pv.pack(fill="x")
        self.preview_img = ttk.Label(pv, text="Предпросмотр: выбери картинку")
        self.preview_img.pack(side="left", padx=6)
        self.preview_info = ttk.Label(pv, text="", justify="left")
        self.preview_info.pack(side="left", anchor="n")
        self._img_sort_rev = False
        self._img_photo = None
        self._safe_load(self.load_images)

    def _imgkey(self):
        return (self.path, self.book_id)

    def load_images(self):
        for i in self.tv_img.get_children():
            self.tv_img.delete(i)
        try:
            rows = recompose.image_info(self.path, self.book_id)
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
            return
        app = self.app
        drop = app.imgdrop.get(self._imgkey(), set())
        cover = app.covers.get(self._imgkey())
        cover_id = cover[1] if cover and cover[0] == 'id' else None
        total_kb = 0
        for r in rows:
            iid = r['image_id']
            total_kb += r['kb']
            nid = self._new_iid("img", iid)
            self.tv_img.insert("", "end", iid=nid,
                               text="✕" if iid in drop else "☐",
                               values=(r['kb'], r['dim'],
                                       "%s/%s/%s" % (r['song'], r['ch'], r['txt']),
                                       r['desc'][:60],
                                       "◉" if iid == cover_id else "○"))
        extra = ""
        if cover and cover[0] == 'file':
            extra = " · обложка из файла: %s" % os.path.basename(cover[1])
        self.img_info.configure(
            text="Картинок: %d, %d КБ%s" % (len(rows), total_kb, extra))

    def sort_img(self, col):
        self._img_sort_rev = not self._img_sort_rev if getattr(self, '_img_sort_col', None) == col else False
        self._img_sort_col = col
        idx = {"size": 0, "dim": 1, "link": 2, "desc": 3, "cover": 4}[col]

        def key(iid):
            vals = self.tv_img.item(iid, "values")
            v = vals[idx] if idx < len(vals) else ""
            if col == "size":
                try:
                    return (0, float(v))
                except (TypeError, ValueError):
                    return (0, -1.0)
            if col == "dim":
                try:
                    w, h = v.lower().split("x")
                    return (0, float(w) * float(h))
                except Exception:
                    return (0, -1.0)
            return (1, str(v).lower())

        for pos, iid in enumerate(sorted(self.tv_img.get_children(), key=key,
                                         reverse=self._img_sort_rev)):
            self.tv_img.move(iid, "", pos)
        arrow = " ▼" if self._img_sort_rev else " ▲"
        names = {"size": "КБ", "dim": "Размер", "link": "Привязка",
                 "desc": "Описание", "cover": "Обложка"}
        for c, label in names.items():
            self.tv_img.heading(c, text=label + (arrow if c == col else ""))

    def toggle_all_images(self):
        """Выделить всё под удаление — повторный клик снимает все метки."""
        kids = self.tv_img.get_children()
        if not kids:
            return
        s = self.app.imgdrop.setdefault(self._imgkey(), set())
        imgs = [self._keys[i] for i in kids if i in self._keys]
        if all(x in s for x in imgs):
            for x in imgs:
                s.discard(x)
            mark = "☐"
        else:
            for x in imgs:
                s.add(x)
            mark = "✕"
        for i in kids:
            self.tv_img.item(i, text=mark)
        self.app.say("Помечено к удалению: %d (файл %s)" % (
            len(s), os.path.basename(self.path)))

    def on_img_click(self, ev):
        iid = self.tv_img.identify_row(ev.y)
        col = self.tv_img.identify_column(ev.x)
        if not iid or iid not in self._keys:
            return
        img = self._keys[iid]
        app = self.app
        if col == "#0":
            s = app.imgdrop.setdefault(self._imgkey(), set())
            if img in s:
                s.discard(img)
                self.tv_img.item(iid, text="☐")
            else:
                s.add(img)
                self.tv_img.item(iid, text="✕")
        elif col == "#5":
            cur = app.covers.get(self._imgkey())
            if cur == ('id', img):
                app.covers.pop(self._imgkey(), None)
            else:
                app.covers[self._imgkey()] = ('id', img)
            self.load_images()
            app.refresh_cover_marks()

    def on_img_select(self, ev):
        sel = self.tv_img.selection()
        if not sel or sel[0] not in self._keys:
            return
        self.show_preview(self._keys[sel[0]])

    def show_preview(self, image_id):
        try:
            from PIL import Image as _PILImage, ImageTk as _PILImageTk
        except Exception:
            self.preview_img.configure(text="Нет Pillow:\npy -m pip install pillow")
            self.preview_info.configure(text="")
            return
        import io as _io
        try:
            con = dbcommon.connect_ro(self.path)
            r = con.execute("SELECT content FROM images WHERE image_id=?", (image_id,)).fetchone()
            con.close()
            if not r or not r[0]:
                raise ValueError("пусто")
            data = dbcommon.img_bytes(r[0])
            if not data:
                raise ValueError("контент не распознан (не JPEG/PNG/base64)")
            img = _PILImage.open(_io.BytesIO(data))
            img.thumbnail((300, 300))
            photo = _PILImageTk.PhotoImage(img)
            self.preview_img.configure(image=photo, text="")
            self._img_photo = photo
            self.preview_info.configure(
                text="%s\n%d КБ · %dx%d · %s" % (
                    image_id, len(data) // 1024, img.width, img.height, img.mode))
        except Exception as e:
            self.preview_img.configure(text="Не открылось:\n%s" % e, image="")
            self.preview_info.configure(text="")

    def cover_from_file(self):
        p = filedialog.askopenfilename(title="JPEG для обложки",
                                       filetypes=[("JPEG", "*.jpg *.jpeg"), ("Все", "*.*")])
        if p:
            self.app.covers[self._imgkey()] = ('file', p)
            self.load_images()
            self.app.say("Обложка из файла назначена: %s (видно в сборке)" % os.path.basename(p))
            self.app.refresh_cover_marks()

    def cover_clear(self):
        self.app.covers.pop(self._imgkey(), None)
        self.load_images()
        self.app.refresh_cover_marks()

    def export_images(self):
        d = filedialog.askdirectory(title="Куда выгрузить JPEG")
        if not d:
            return
        n = 0
        try:
            con = dbcommon.connect_ro(self.path)
            try:
                iids = [r[0] for r in con.execute(
                    "SELECT DISTINCT image_id FROM image_nums WHERE bid=?", (self.book_id,)).fetchall()]
            except Exception:
                iids = [r[0] for r in con.execute("SELECT DISTINCT image_id FROM image_nums").fetchall()]
            for iid in iids:
                r = con.execute("SELECT content FROM images WHERE image_id=?", (iid,)).fetchone()
                if not r or not r[0]:
                    continue
                data = dbcommon.img_bytes(r[0])
                if not data:
                    continue
                safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in iid)[:40]
                with open(os.path.join(d, safe + ".jpg"), "wb") as f:
                    f.write(data)
                n += 1
            con.close()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
            return
        messagebox.showinfo("Экспорт", "Файлов: %d → %s" % (n, d))
        # сразу открыть папку: миниатюры проводника заменяют предпросмотр
        try:
            os.startfile(d)
        except Exception:
            pass

    def _ex(self):
        return self.excl[self.key]

    def _safe_load(self, fn):
        """Одна упавшая вкладка не роняет окно: ошибка — строкой в лог родителя."""
        try:
            fn()
        except Exception as e:
            try:
                self.app.say("Вкладка: ошибка (%s)" % e)
            except Exception:
                pass

    def _new_iid(self, prefix, key):
        self._n += 1
        iid = "%s%d" % (prefix, self._n)
        self._keys[iid] = key
        return iid

    def load_chapters(self):
        for i in self.tv_ch.get_children():
            self.tv_ch.delete(i)
        try:
            rows = recompose.chapter_verses(self.path, self.book_id)
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
            return
        ex = self._ex()['chapters']
        for r in rows:
            key = (r['song'], r['number'])
            iid = self._new_iid("ch", key)
            mark = "✕" if key in ex else "☐"
            self.tv_ch.insert("", "end", iid=iid, text=mark, values=(
                "%s/%s" % (r['song'], r['number']), r['title'][:80], r['verses']))
        self.title("Содержимое: глав %d" % len(rows))

    def on_ch_click(self, ev):
        iid = self.tv_ch.identify_row(ev.y)
        if iid and self.tv_ch.identify_column(ev.x) == "#0" and iid in self._keys:
            key = self._keys[iid]
            ex = self._ex()['chapters']
            if key in ex:
                ex.discard(key)
                self.tv_ch.item(iid, text="☐")
            else:
                ex.add(key)
                self.tv_ch.item(iid, text="✕")
            self.app.say("Исключено глав: %d (файл %s)" % (
                len(ex), os.path.basename(self.path)))

    def load_verses(self):
        for i in self.tv_v.get_children():
            self.tv_v.delete(i)
        try:
            rows = recompose.find_verses(self.path, self.book_id,
                                         kind=self.v_kind.get(),
                                         search=self.e_search.get().strip())
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
            return
        ex = self._ex()['verses']
        for r in rows:
            key = (r['song'], r['ch_no'], r['txt_no'])
            iid = self._new_iid("v", key)
            mark = "✕" if key in ex else "☐"
            self.tv_v.insert("", "end", iid=iid, text=mark, values=(
                r['song'], r['ch_no'], r['txt_no'], r['preview'][:80]))

    def on_v_click(self, ev):
        iid = self.tv_v.identify_row(ev.y)
        if iid and self.tv_v.identify_column(ev.x) == "#0" and iid in self._keys:
            key = self._keys[iid]
            ex = self._ex()['verses']
            if key in ex:
                ex.discard(key)
                self.tv_v.item(iid, text="☐")
            else:
                ex.add(key)
                self.tv_v.item(iid, text="✕")

    def load_junk(self):
        try:
            rows = recompose.inspect_data(self.path)
            b = next((x for x in rows if x['book_id'] == self.book_id), None)
        except Exception as e:
            b = None
        self.tx.configure(state="normal")
        if not b:
            self.tx.insert("end", "Книга не найдена")
        else:
            self.tx.insert("end", "Глав: %d, стихов: %d, картинок: %d\n\n" % (
                b['chapters'], b['verses'], b['images']))
            if b['junk']:
                self.tx.insert("end", "Мусор:\n• " + "\n• ".join(b['junk']) + "\n\n")
            else:
                self.tx.insert("end", "Мусора нет.\n\n")
            self.tx.insert("end",
                "Что это значит:\n"
                "@ERROR — битые строки (song/ch/txt = '@ERROR'), их не открыть;\n"
                "пустые — нет ни preview, ни текста ни в одном поле;\n"
                "дубли — одинаковые (song, ch, txt), в приложение попадёт первый;\n"
                "глав без стихов — главы, к которым не привязан ни один стих;\n"
                "стихов без глав — стихи, для которых нет главы (приложение кладёт в первую).\n\n"
                "Всё это видно во вкладках «Главы»/«Стихи»; галочкой ✕ исключаешь из сборки.")
        self.tx.configure(state="disabled")


if __name__ == "__main__":
    App().mainloop()
