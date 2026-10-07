#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Окно «Базы Аудио»: всё создание аудио в одном месте.

1) Пак — папка с файлами (сканируется рекурсивно) + тип + шаблон -> audio.db
   (таблица verse_audio). Диапазоны сверяются по книге (.db) или берутся готовыми.
2) Сжатие — audio_recode: MP3 64k -> Opus 24k (~x3 легче) перед паком.
3) Нарезка — кнопка запуска отдельного приложения Audo Cut (режет вручную),
   нарезанные куски дальше идут в раздел 1 (пак).
Вкладка в gui.py (бывшее отдельное окно). Тяжёлое — в потоках, лог через очередь.
"""
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import dbcommon
import recompose

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "audio_gui.json")
WIN_VERSION = 2  # bump при правках вкладки — видно в заголовке


def _noop():
    return subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class AudioTab(ttk.Frame):
    def __init__(self, parent, app=None):
        super().__init__(parent)
        self.app = app
        self.q = queue.Queue()
        self.proc = None
        self.busy = False
        self.stopping = False
        self.cfg = self._load()

        # --- 1. пак ---
        pk = ttk.LabelFrame(self, text="1. Пак audio.db из папки", padding=6)
        pk.pack(fill="x", padx=6, pady=4)
        self.e_dir = tk.StringVar(value=self.cfg.get("dir", ""))
        self.e_type = tk.StringVar(value=self.cfg.get("type", "SB"))
        self.e_ext = tk.StringVar(value=self.cfg.get("ext", "any"))
        self.e_pat = tk.StringVar(value=self.cfg.get("pattern", ""))
        self.e_pack = tk.StringVar(value=self.cfg.get("pack", ""))
        self.e_vsrc = tk.StringVar(value=self.cfg.get("vsrc", ""))
        ttk.Label(pk, text="Папка:").grid(row=0, column=0, sticky="w")
        ttk.Entry(pk, textvariable=self.e_dir, width=52).grid(
            row=0, column=1, columnspan=3, sticky="ew", padx=4)
        ttk.Button(pk, text="…", width=3,
                   command=lambda: self._pick_dir(self.e_dir)).grid(row=0, column=4)
        ttk.Label(pk, text="Тип:").grid(row=1, column=0, sticky="w")
        ttk.Combobox(pk, textvariable=self.e_type, values=recompose.AUDIO_TYPES,
                     width=8, state="readonly").grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(pk, text="Расширение:").grid(row=1, column=2, sticky="w")
        ttk.Combobox(pk, textvariable=self.e_ext, values=recompose.AUDIO_EXTS,
                     width=8, state="readonly").grid(row=1, column=3, sticky="w")
        ttk.Label(pk, text="Шаблон:").grid(row=2, column=0, sticky="w")
        ttk.Entry(pk, textvariable=self.e_pat, width=52).grid(
            row=2, column=1, columnspan=3, sticky="ew", padx=4)
        ttk.Label(pk, text="Пак:").grid(row=3, column=0, sticky="w")
        ttk.Entry(pk, textvariable=self.e_pack, width=52).grid(
            row=3, column=1, columnspan=3, sticky="ew", padx=4)
        ttk.Button(pk, text="…", width=3,
                   command=lambda: self._pick_save(self.e_pack)).grid(row=3, column=4)
        ttk.Label(pk, text="Книга для диапазонов (.db, пусто=файл=стих):").grid(
            row=4, column=0, columnspan=2, sticky="w")
        ttk.Entry(pk, textvariable=self.e_vsrc, width=38).grid(
            row=4, column=2, sticky="ew", padx=4)
        ttk.Button(pk, text="…", width=3,
                   command=lambda: self._pick_file(self.e_vsrc, "Библиотечный .db")).grid(
                       row=4, column=4)
        btns = ttk.Frame(pk)
        btns.grid(row=5, column=0, columnspan=5, sticky="w", pady=4)
        self.b_check = ttk.Button(btns, text="Проверить", command=self.do_check)
        self.b_check.pack(side="left")
        self.b_pack = ttk.Button(btns, text="Упаковать audio.db", command=self.do_pack)
        self.b_pack.pack(side="left", padx=4)
        self.b_stop = ttk.Button(btns, text="Стоп", command=self.do_stop, state="disabled")
        self.b_stop.pack(side="left")
        self.lbl_check = ttk.Label(btns, text="")
        self.lbl_check.pack(side="left", padx=8)
        pk.columnconfigure(1, weight=1)
        if not self.e_pat.get().strip():
            self.e_pat.set(recompose.default_audio_pattern(
                self.e_type.get(), self.e_ext.get()))
        self.e_type.trace_add("write", lambda *a: self._auto_pat())
        self.e_ext.trace_add("write", lambda *a: self._auto_pat())

        # --- 2. сжатие ---
        rc = ttk.LabelFrame(self, text="2. Сжатие (MP3 -> Opus 24k, ~x3 легче)", padding=6)
        rc.pack(fill="x", padx=6, pady=4)
        self.e_rsrc = tk.StringVar(value=self.cfg.get("rsrc", ""))
        self.e_rdst = tk.StringVar(value=self.cfg.get("rdst", ""))
        self.e_rmode = tk.StringVar(value=self.cfg.get("rmode", "opus"))
        self.e_rjobs = tk.StringVar(value=self.cfg.get("rjobs", "4"))
        ttk.Label(rc, text="Откуда:").grid(row=0, column=0, sticky="w")
        ttk.Entry(rc, textvariable=self.e_rsrc, width=52).grid(
            row=0, column=1, columnspan=3, sticky="ew", padx=4)
        ttk.Button(rc, text="…", width=3,
                   command=lambda: self._pick_dir(self.e_rsrc)).grid(row=0, column=4)
        ttk.Label(rc, text="Куда:").grid(row=1, column=0, sticky="w")
        ttk.Entry(rc, textvariable=self.e_rdst, width=52).grid(
            row=1, column=1, columnspan=3, sticky="ew", padx=4)
        ttk.Button(rc, text="…", width=3,
                   command=lambda: self._pick_dir(self.e_rdst)).grid(row=1, column=4)
        ttk.Label(rc, text="Режим:").grid(row=2, column=0, sticky="w")
        ttk.Combobox(rc, textvariable=self.e_rmode, values=["opus", "mp3-32k"],
                     width=10, state="readonly").grid(row=2, column=1, sticky="w", padx=4)
        ttk.Label(rc, text="Потоки:").grid(row=2, column=2, sticky="w")
        ttk.Entry(rc, textvariable=self.e_rjobs, width=6).grid(row=2, column=3, sticky="w")
        self.b_recode = ttk.Button(rc, text="Сжать", command=self.do_recode)
        self.b_recode.grid(row=2, column=4, padx=4)
        ttk.Label(rc, text="opus: 24k моно .ogg (в паке шаблон с {ext} или .ogg); "
                           "mp3-32k: имена не меняются",
                  foreground="gray").grid(row=3, column=0, columnspan=5, sticky="w")
        rc.columnconfigure(1, weight=1)

        # --- 3. нарезка: отдельное приложение ---
        sp = ttk.LabelFrame(self, text="3. Нарезка (отдельное приложение Audo Cut)", padding=6)
        sp.pack(fill="x", padx=6, pady=4)
        self.e_acut = tk.StringVar(value=self.cfg.get(
            "acut", r"F:\AI\Development\Audo Cut\audo_cut.py"))
        ttk.Entry(sp, textvariable=self.e_acut, width=52).grid(
            row=0, column=0, columnspan=3, sticky="ew", padx=4)
        ttk.Button(sp, text="…", width=3,
                   command=lambda: self._pick_file(self.e_acut, "audo_cut.py")).grid(
                       row=0, column=3)
        self.b_opencut = ttk.Button(sp, text="✂ Открыть Audo Cut", command=self.do_opencut)
        self.b_opencut.grid(row=0, column=4, padx=4)
        ttk.Label(sp, text="Режет длинную запись на куски вручную. "
                           "Готовые куски — в раздел 1 (пак).",
                  foreground="gray").grid(row=1, column=0, columnspan=5, sticky="w")
        sp.columnconfigure(0, weight=1)

        self.log = tk.Text(self, height=10, wrap="word")
        self.log.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.log.bind("<Key>", self._log_key)
        self.after(150, self.poll)

    # ------------------------------- helpers ---
    def _auto_pat(self):
        try:
            self.e_pat.set(recompose.default_audio_pattern(
                self.e_type.get(), self.e_ext.get()))
        except Exception:
            pass

    def _load(self):
        return dbcommon.load_cfg(CFG_PATH)

    def _save(self):
        return dbcommon.save_cfg(CFG_PATH, {
            "dir": self.e_dir.get(), "type": self.e_type.get(),
            "ext": self.e_ext.get(), "pattern": self.e_pat.get(),
            "pack": self.e_pack.get(), "vsrc": self.e_vsrc.get(),
            "rsrc": self.e_rsrc.get(), "rdst": self.e_rdst.get(),
            "rmode": self.e_rmode.get(), "rjobs": self.e_rjobs.get(),
            "acut": self.e_acut.get(),
        })

    def _pick_file(self, var, title):
        p = filedialog.askopenfilename(title=title, parent=self)
        self._refocus()
        if p:
            var.set(p)

    def _pick_save(self, var):
        p = filedialog.asksaveasfilename(title="audio.db", defaultextension=".db",
                                         parent=self)
        self._refocus()
        if p:
            var.set(p)

    def _pick_dir(self, var):
        d = filedialog.askdirectory(parent=self)
        self._refocus()
        if d:
            var.set(d)

    def _refocus(self):
        """Вкладка — окно не уходит в фон (диалоги parent=frame, уже поверх)."""
        pass

    def say(self, text):
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def _log_key(self, ev):
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

    def poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                a = item[1] if len(item) > 1 else ""
                if kind == "log":
                    self.say(a)
                elif kind == "done":
                    self.set_busy(False)
                    if a:
                        self.say(a)
        except queue.Empty:
            pass
        try:
            self.after(150, self.poll)
        except Exception:
            pass

    def set_busy(self, v):
        self.busy = v
        st = "disabled" if v else "normal"
        for w in (self.b_check, self.b_pack, self.b_recode):
            w.configure(state=st)
        self.b_stop.configure(state="normal" if v else "disabled")

    def run_bg(self, fn, *args):
        self._save()
        self.stopping = False
        self.set_busy(True)
        # всё, что читает Tk-переменные, собираем ЗДЕСЬ (на главном потоке) и
        # передаём в поток аргументами: tkinter не потокобезопасен
        threading.Thread(target=self._wrap, args=(fn, args), daemon=True).start()

    def _wrap(self, fn, args):
        try:
            fn(*args)
        except Exception:
            import traceback
            self.q.put(("done", "ОШИБКА:\n%s" % traceback.format_exc()))
            return
        self.q.put(("done", ""))

    def emit(self, line):
        self.q.put(("log", line))

    def popen(self, cmd, cwd=None):
        e = dict(os.environ)
        e["PYTHONIOENCODING"] = "utf-8"
        e["PYTHONUTF8"] = "1"
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            cwd=cwd, env=e, creationflags=_noop())
        return self.proc

    def stream(self, cmd, cwd=None):
        p = self.popen(cmd, cwd)
        for line in p.stdout:
            line = line.rstrip()
            if line:
                self.emit(line)
        p.wait()
        self.proc = None
        if p.returncode != 0:
            if self.stopping:
                self.emit("■ остановлено пользователем")
                return
            raise RuntimeError("код %d: %s" % (p.returncode, " ".join(cmd[:3])))

    def do_stop(self):
        p = self.proc
        if p is not None:
            self.stopping = True
            try:
                p.terminate()
                self.emit("…останавливаю")
            except Exception as ex:
                self.emit("стоп: %s" % ex)

    # ------------------------------- шаги ---
    def _pack_spec(self):
        btype = (self.e_type.get() or "SB").upper()
        ap = {"dir": self.e_dir.get().strip(), "book_type": btype,
              "pattern": self.e_pat.get().strip() or
              recompose.default_audio_pattern(btype, self.e_ext.get())}
        vsrc = self.e_vsrc.get().strip()
        if vsrc and os.path.isfile(vsrc):
            ap["verse_source"] = {"file": vsrc, "type": btype}
        return {"out": self.e_pack.get().strip(), "books": [], "audio_pack": ap}

    def do_check(self):
        d = self.e_dir.get().strip()
        if not d or not os.path.isdir(d):
            self.say("нет папки")
            return
        try:
            rx = recompose.pattern_to_regex(self.e_pat.get().strip())
        except Exception as e:
            self.say("плохой шаблон: %s" % e)
            return
        n = ok = 0
        subs = set()
        for root, _, fns in os.walk(d):
            if os.path.abspath(root) != os.path.abspath(d):
                subs.add(os.path.relpath(root, d))
            for f in fns:
                if not f.lower().endswith((".mp3", ".ogg", ".opus")):
                    continue
                n += 1
                if rx.match(f):
                    ok += 1
        msg = "файлов: %d, совпало: %d%s" % (
            n, ok, (" (подпапок: %d)" % len(subs)) if subs else "")
        self.lbl_check.configure(text=msg)
        self.say(msg)

    def do_pack(self):
        out = self.e_pack.get().strip()
        if not out:
            messagebox.showwarning("Нет выхода", "Укажи выходной audio.db")
            return
        if not self.e_dir.get().strip() or not os.path.isdir(self.e_dir.get().strip()):
            messagebox.showwarning("Нет папки", "Укажи папку с аудио")
            return
        if os.path.exists(out) and not messagebox.askyesno(
                "Перезапись", "Файл есть. Перезаписать?\n%s" % out):
            return
        try:
            spec = self._pack_spec()   # чтение Tk-полей — только на главном потоке
        except Exception as e:
            messagebox.showerror("Спека", str(e))
            return
        self.run_bg(self._pack, spec)

    def _pack(self, spec):
        import tempfile
        fd, sp = tempfile.mkstemp(prefix="audspec_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False, indent=1)
        try:
            report = recompose.build(sp, spec["out"], True)
            self.emit("ПАК ГОТОВ: %s\n%s" % (spec["out"], report))
        finally:
            try:
                os.remove(sp)
            except Exception:
                pass

    def do_recode(self):
        if not self.e_rsrc.get().strip() or not os.path.isdir(self.e_rsrc.get().strip()):
            messagebox.showwarning("Нет папки", "Укажи папку-исходник")
            return
        if not self.e_rdst.get().strip():
            messagebox.showwarning("Нет выхода", "Укажи куда класть сжатое")
            return
        cmd = [sys.executable, os.path.join(HERE, "audio_recode.py"),
               "--src", self.e_rsrc.get().strip(),
               "--dst", self.e_rdst.get().strip(),
               "--jobs", (self.e_rjobs.get().strip() or "4")]
        if (self.e_rmode.get() or "opus") == "mp3-32k":
            cmd.append("--mp3-32k")
        self.run_bg(self._recode, cmd)

    def _recode(self, cmd):
        self.stream(cmd, cwd=HERE)
        self.emit("СЖАТИЕ ГОТОВО.")

    def do_opencut(self):
        """Запуск Audo Cut отдельным процессом (своё окно, свой питон с зависимостями)."""
        path = self.e_acut.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showwarning("Нет файла", "Укажи audo_cut.py")
            return
        # Тот же портативный питон, что в ярлыке Audo Cut.vbs (там зависимости);
        # иначе pythonw рядом с текущим python, иначе как есть
        pyw = os.path.normpath(os.path.join(r"F:\AI", "portable-files",
                                             "python", "pythonw.exe"))
        if not os.path.isfile(pyw):
            base, ext = os.path.splitext(sys.executable)
            cand = base[:-1] + "w" + ext if base.lower().endswith("n") else None
            pyw = cand if cand and os.path.isfile(cand) else sys.executable
        try:
            subprocess.Popen([pyw, path], cwd=os.path.dirname(os.path.abspath(path)),
                             creationflags=_noop())
        except Exception as ex:
            messagebox.showerror("Не запускается", str(ex))
            return
        self._save()
        self.say("Audo Cut запущен отдельным окном.")
