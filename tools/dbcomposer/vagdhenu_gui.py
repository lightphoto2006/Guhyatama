#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вкладка-окно Vagdhenu: деплой напевного TTS и сквозной прогон без скриптов руками.

Шаги: 1) проверка окружения 2) установка (venv + torch + зависимости + веса)
3) шард из .db 4) рендер с прогрессом 5) сборка ogg 6) audioпак.
Открывается из gui.py кнопкой. Все тяжёлые шаги — в потоках, лог через очередь.
"""
import json
import os
import queue
import shlex
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import recompose

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "vagdhenu_gui.json")
VAG_GUI_VERSION = 4  # bump при правках окна — видно в заголовке
VAG_URL = "https://github.com/prathoshap/vagdhenu.git"
BIGVGAN_URL = "https://github.com/NVIDIA/BigVGAN.git"
DEF_PY = r"F:\AI\portable-files\python\python.exe"
DEF_TORCH = "torch==2.4.1 torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cu121"


def _noop():
    return subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class VagWin(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Vagdhenu v%d — напевная озвучка санскрита" % VAG_GUI_VERSION)
        self.geometry("920x720")
        self.q = queue.Queue()
        self.proc = None
        self.busy = False
        self.stopping = False
        self.render_total = 0
        self.cfg = self._load()

        # --- окружение ---
        env = ttk.LabelFrame(self, text="1. Окружение и установка", padding=6)
        env.pack(fill="x", padx=6, pady=4)
        self.e_py = tk.StringVar(value=self.cfg.get("python", DEF_PY))
        self.e_repo = tk.StringVar(value=self.cfg.get("repo", os.path.join(HERE, "vagdhenu")))
        self.e_models = tk.StringVar(value=self.cfg.get("models", ""))
        self.e_torch = tk.StringVar(value=self.cfg.get("torch", DEF_TORCH))
        r = 0
        ttk.Label(env, text="Python:").grid(row=r, column=0, sticky="w")
        ttk.Entry(env, textvariable=self.e_py, width=52).grid(row=r, column=1, sticky="ew", padx=4)
        ttk.Button(env, text="…", width=3,
                   command=lambda: self._pick_file(self.e_py, "python.exe")).grid(row=r, column=2)
        r += 1
        ttk.Label(env, text="Папка движка:").grid(row=r, column=0, sticky="w")
        ttk.Entry(env, textvariable=self.e_repo, width=52).grid(row=r, column=1, sticky="ew", padx=4)
        ttk.Button(env, text="…", width=3,
                   command=lambda: self._pick_dir(self.e_repo)).grid(row=r, column=2)
        r += 1
        ttk.Label(env, text="Веса (пусто=папка/models):").grid(row=r, column=0, sticky="w")
        ttk.Entry(env, textvariable=self.e_models, width=52).grid(row=r, column=1, sticky="ew", padx=4)
        ttk.Button(env, text="…", width=3,
                   command=lambda: self._pick_dir(self.e_models)).grid(row=r, column=2)
        r += 1
        ttk.Label(env, text="Torch в venv:").grid(row=r, column=0, sticky="w")
        ttk.Entry(env, textvariable=self.e_torch, width=52).grid(row=r, column=1, sticky="ew", padx=4)
        env.columnconfigure(1, weight=1)
        self.v_venv = tk.BooleanVar(value=bool(self.cfg.get("venv", False)))
        ttk.Checkbutton(env, text="Изолированный venv (строго по setup.sh: свой torch 2.4.1/cu121)",
                        variable=self.v_venv).grid(row=r + 1, column=0, columnspan=3, sticky="w")
        btns = ttk.Frame(env)
        btns.grid(row=r + 2, column=0, columnspan=3, sticky="w", pady=4)
        self.b_check = ttk.Button(btns, text="Проверить", command=self.do_check)
        self.b_check.pack(side="left")
        self.b_install = ttk.Button(btns, text="Установить всё", command=self.do_install)
        self.b_install.pack(side="left", padx=4)
        self.b_test = ttk.Button(btns, text="Тест (1 стих)", command=self.do_test)
        self.b_test.pack(side="left")

        # --- шард ---
        sh = ttk.LabelFrame(self, text="2. Шард из gitabase .db", padding=6)
        sh.pack(fill="x", padx=6, pady=4)
        self.e_src = tk.StringVar(value=self.cfg.get("src", ""))
        self.e_src2 = tk.StringVar(value=self.cfg.get("src2", ""))
        self.e_books = tk.StringVar(value=self.cfg.get("books", ""))
        self.e_chapters = tk.StringVar(value=self.cfg.get("chapters", ""))
        self.e_limit = tk.StringVar(value=self.cfg.get("limit", "0"))
        self.e_sample = tk.StringVar(value=self.cfg.get("sample", "0"))
        self.e_verses = tk.StringVar(value=self.cfg.get("verses", ""))
        self.e_btype = tk.StringVar(value=self.cfg.get("btype", "SB"))
        self.e_shard = tk.StringVar(value=self.cfg.get("shard", os.path.join(HERE, "shard_sb.json")))
        self.e_mani = tk.StringVar(value=self.cfg.get("manifest", os.path.join(HERE, "manifest_sb.json")))
        self.e_wav = tk.StringVar(value=self.cfg.get("wavdir", os.path.join(HERE, "wav")))
        self.e_seed = tk.StringVar(value=self.cfg.get("seed", "60"))
        ttk.Label(sh, text=".db:").grid(row=0, column=0, sticky="w")
        ttk.Entry(sh, textvariable=self.e_src, width=46).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(sh, text="…", width=3,
                   command=lambda: self._pick_file(self.e_src, "gitabase .db")).grid(row=0, column=2)
        ttk.Label(sh, text="Тип:").grid(row=0, column=3, sticky="w")
        ttk.Entry(sh, textvariable=self.e_btype, width=6).grid(row=0, column=4)
        ttk.Label(sh, text="Шард:").grid(row=1, column=0, sticky="w")
        ttk.Entry(sh, textvariable=self.e_shard, width=46).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Label(sh, text="Донор .db:").grid(row=1, column=3, sticky="w")
        ttk.Entry(sh, textvariable=self.e_src2, width=14).grid(row=1, column=4, padx=2)
        ttk.Button(sh, text="…", width=3,
                   command=lambda: self._pick_file(self.e_src2, "второй gitabase .db")).grid(row=1, column=5)
        ttk.Label(sh, text="Wav:").grid(row=2, column=0, sticky="w")
        ttk.Entry(sh, textvariable=self.e_wav, width=46).grid(row=2, column=1, sticky="ew", padx=4)
        ttk.Button(sh, text="…", width=3,
                   command=lambda: self._pick_dir(self.e_wav)).grid(row=2, column=2)
        self.b_shard = ttk.Button(sh, text="Сгенерировать шард", command=self.do_shard)
        self.b_shard.grid(row=2, column=3, columnspan=3, padx=4)
        ttk.Label(sh, text="Книги:").grid(row=3, column=0, sticky="w")
        self.b_books = ttk.Button(sh, text="Выбрать…", command=self.pick_books)
        self.b_books.grid(row=3, column=1, sticky="w", padx=4)
        ttk.Label(sh, text="Главы:").grid(row=3, column=2, sticky="w")
        ttk.Entry(sh, textvariable=self.e_chapters, width=14).grid(row=3, column=3, padx=2)
        ttk.Label(sh, text="Лимит:").grid(row=3, column=4, sticky="w")
        ttk.Entry(sh, textvariable=self.e_limit, width=6).grid(row=3, column=5, sticky="w")
        ttk.Label(sh, text="Проба/метр:").grid(row=4, column=0, sticky="w")
        ttk.Entry(sh, textvariable=self.e_sample, width=6).grid(row=4, column=1, sticky="w", padx=4)
        ttk.Label(sh, text="Стихи:").grid(row=4, column=2, sticky="w")
        ttk.Entry(sh, textvariable=self.e_verses, width=16).grid(row=4, column=3, padx=2)
        ttk.Label(sh, text="Главы: '1'=песнь, '1.2'=гл.; стихи: '1.2.23'; проба: по N каждого метра").grid(
            row=5, column=0, columnspan=6, sticky="w")
        ttk.Label(sh, text="Донор: второй .db (напр. eng) — добирает санскрит, если в основном нет",
                  foreground="gray").grid(row=6, column=0, columnspan=6, sticky="w")
        ttk.Label(sh, text="После любых изменений выше — жми «Сгенерировать шард» заново",
                  foreground="gray").grid(row=7, column=0, columnspan=6, sticky="w")
        sh.columnconfigure(1, weight=1)

        # --- рендер ---
        rn = ttk.LabelFrame(self, text="3. Рендер (GPU)", padding=6)
        rn.pack(fill="x", padx=6, pady=4)
        self.e_res = tk.StringVar(value=self.cfg.get("results", os.path.join(HERE, "vag_results.json")))
        self.e_bank = tk.StringVar(value=self.cfg.get("bank", ""))
        ttk.Label(rn, text="Results:").grid(row=0, column=0, sticky="w")
        ttk.Entry(rn, textvariable=self.e_res, width=46).grid(row=0, column=1, sticky="ew", padx=4)
        self.prog = ttk.Progressbar(rn, mode="determinate", length=200)
        self.prog.grid(row=0, column=2, columnspan=3, padx=4, sticky="ew")
        self.b_render = ttk.Button(rn, text="Рендер", command=self.do_render)
        self.b_render.grid(row=1, column=0, pady=4)
        self.b_stop = ttk.Button(rn, text="Стоп", command=self.do_stop, state="disabled")
        self.b_stop.grid(row=1, column=1, sticky="w")
        self.lbl_stat = ttk.Label(rn, text="")
        self.lbl_stat.grid(row=2, column=2, columnspan=3, sticky="w")
        ttk.Label(rn, text="Банк эталонов:").grid(row=3, column=0, sticky="w")
        ttk.Entry(rn, textvariable=self.e_bank, width=46).grid(row=3, column=1, sticky="ew", padx=4)
        ttk.Button(rn, text="…", width=3,
                   command=lambda: self._pick_file(self.e_bank, "bank.json")).grid(row=3, column=2)
        ttk.Label(rn, text="Пусто = штатный банк. Свой — для другой манеры/темпа (см. README)",
                  foreground="gray").grid(row=4, column=0, columnspan=5, sticky="w")
        rn.columnconfigure(1, weight=1)

        # --- качество звука (всё в одном месте) ---
        ql = ttk.LabelFrame(self, text="4. Качество звука", padding=6)
        ql.pack(fill="x", padx=6, pady=4)
        self.e_speed = tk.StringVar(value=self.cfg.get("speed", "1.00"))
        self.e_gap = tk.StringVar(value=self.cfg.get("gap", "0.55"))
        self.e_nfe = tk.StringVar(value=self.cfg.get("nfe", "64"))
        self.e_cfg = tk.StringVar(value=self.cfg.get("cfg", "3.0"))
        self.e_bitrate = tk.StringVar(value=self.cfg.get("bitrate", "24k"))
        ttk.Label(ql, text="Seed:").grid(row=0, column=0, sticky="w")
        ttk.Entry(ql, textvariable=self.e_seed, width=8).grid(row=0, column=1, padx=4)
        ttk.Label(ql, text="Темп:").grid(row=0, column=2, sticky="w")
        ttk.Entry(ql, textvariable=self.e_speed, width=8).grid(row=0, column=3, padx=4)
        ttk.Label(ql, text="Пауза:").grid(row=0, column=4, sticky="w")
        ttk.Entry(ql, textvariable=self.e_gap, width=8).grid(row=0, column=5, padx=4)
        ttk.Label(ql, text="NFE:").grid(row=1, column=0, sticky="w")
        ttk.Entry(ql, textvariable=self.e_nfe, width=8).grid(row=1, column=1, padx=4)
        ttk.Label(ql, text="CFG:").grid(row=1, column=2, sticky="w")
        ttk.Entry(ql, textvariable=self.e_cfg, width=8).grid(row=1, column=3, padx=4)
        ttk.Label(ql, text="Битрейт ogg:").grid(row=1, column=4, sticky="w")
        ttk.Entry(ql, textvariable=self.e_bitrate, width=8).grid(row=1, column=5, padx=4)
        ttk.Label(ql, text="Seed — вариация исполнения; темп <1 протяжнее (1.0=эталон); пауза — тишина между полустишиями; NFE/CFG — шаги и сила модели (на длину не влияют)",
                  foreground="gray").grid(row=2, column=0, columnspan=6, sticky="w")
        ttk.Label(ql, text="Темп и seed зашиваются В ШАРД — после их смены рендер сам предложит перегенерировать",
                  foreground="gray").grid(row=3, column=0, columnspan=6, sticky="w")

        # --- сборка ---
        pk = ttk.LabelFrame(self, text="5. Ogg-пак", padding=6)
        pk.pack(fill="x", padx=6, pady=4)
        self.e_ogg = tk.StringVar(value=self.cfg.get("oggdir", os.path.join(HERE, "sb_ogg")))
        self.e_pat = tk.StringVar(value=self.cfg.get("pattern", "SB{song}.{ch}.{txt}.ogg"))
        self.e_pack = tk.StringVar(value=self.cfg.get("pack", os.path.join(os.path.expanduser("~"), "audio_sb.db")))
        ttk.Label(pk, text="Ogg:").grid(row=0, column=0, sticky="w")
        ttk.Entry(pk, textvariable=self.e_ogg, width=30).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(pk, text="Шаблон:").grid(row=0, column=2, sticky="w")
        ttk.Entry(pk, textvariable=self.e_pat, width=24).grid(row=0, column=3, padx=4)
        self.b_collect = ttk.Button(pk, text="Собрать ogg", command=self.do_collect)
        self.b_collect.grid(row=0, column=4, padx=4)
        ttk.Label(pk, text="Пак:").grid(row=1, column=0, sticky="w")
        ttk.Entry(pk, textvariable=self.e_pack, width=30).grid(row=1, column=1, sticky="ew", padx=4)
        self.v_nosong = tk.BooleanVar(value=bool(self.cfg.get("nosong", False)))
        ttk.Checkbutton(pk, text="без песни (БГ)", variable=self.v_nosong,
                        command=self.toggle_nosong).grid(row=1, column=2, columnspan=2, sticky="w")
        self.b_pack = ttk.Button(pk, text="Упаковать audio.db", command=self.do_pack)
        self.b_pack.grid(row=1, column=4, padx=4)
        ttk.Button(pk, text="📋", command=self.copy_log).grid(row=1, column=5, padx=2)
        pk.columnconfigure(1, weight=1)

        self.log = tk.Text(self, height=12, wrap="word")
        self.log.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.log.bind("<Key>", self._log_key)
        self.after(150, self.poll)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------- helpers ---
    def _load(self):
        try:
            return json.load(open(CFG_PATH, encoding="utf-8"))
        except Exception:
            return {}
    def _save(self):
        try:
            json.dump({
                "python": self.e_py.get(), "repo": self.e_repo.get(),
                "models": self.e_models.get(), "torch": self.e_torch.get(),
                "src": self.e_src.get(), "src2": self.e_src2.get(), "btype": self.e_btype.get(),
                "venv": bool(self.v_venv.get()),
                "shard": self.e_shard.get(), "manifest": self.e_mani.get(),
                "wavdir": self.e_wav.get(), "results": self.e_res.get(),
                "oggdir": self.e_ogg.get(), "pattern": self.e_pat.get(),
                "pack": self.e_pack.get(), "seed": self.e_seed.get(),
                "speed": self.e_speed.get(), "gap": self.e_gap.get(),
                "bank": self.e_bank.get(),
                "nfe": self.e_nfe.get(), "cfg": self.e_cfg.get(),
                "bitrate": self.e_bitrate.get(),
                "books": self.e_books.get(), "chapters": self.e_chapters.get(),
                "limit": self.e_limit.get(), "sample": self.e_sample.get(),
                "verses": self.e_verses.get(),
                "nosong": bool(self.v_nosong.get()),
            }, open(CFG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        except Exception:
            pass

    def on_close(self):
        if self.busy:
            messagebox.showwarning("Занято", "Дождись конца шага или нажми Стоп")
            return
        self._save()
        self.destroy()

    def _pick_file(self, var, title):
        p = filedialog.askopenfilename(title=title)
        if p:
            var.set(p)

    def _pick_dir(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(d)

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

    def poll(self):
        try:
            while True:
                item = self.msg_q_get()
                kind = item[0]
                a = item[1] if len(item) > 1 else ""
                b = item[2] if len(item) > 2 else 0
                if kind == "log":
                    self.say(a)
                elif kind == "prog":
                    self.prog.configure(maximum=b or 1, value=a)
                    self.lbl_stat.configure(text="%d/%d" % (a, b or 0))
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

    def msg_q_get(self):
        return self.q.get_nowait()

    def set_busy(self, v):
        self.busy = v
        st = "disabled" if v else "normal"
        for w in (self.b_check, self.b_install, self.b_test, self.b_shard,
                  self.b_render, self.b_collect, self.b_pack):
            w.configure(state=st)
        self.b_stop.configure(state="normal" if v else "disabled")

    def run_bg(self, fn):
        self._save()
        self.stopping = False
        self.set_busy(True)
        threading.Thread(target=self._wrap, args=(fn,), daemon=True).start()

    def _wrap(self, fn):
        try:
            fn()
        except Exception as e:
            import traceback
            self.q.put(("done", "ОШИБКА:\n%s" % traceback.format_exc()))
            return
        self.q.put(("done", ""))

    def emit(self, line):
        self.q.put(("log", line))

    def popen(self, cmd, cwd=None, env=None):
        e = dict(os.environ)
        # Детям — UTF-8 принудительно: иначе их print с юникодом (↓) падает в cp1252-консоли
        e["PYTHONIOENCODING"] = "utf-8"
        e["PYTHONUTF8"] = "1"
        if env:
            e.update(env)
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            cwd=cwd, env=e, creationflags=_noop())
        return self.proc

    def stream(self, cmd, cwd=None, env=None, parse=None):
        p = self.popen(cmd, cwd, env)
        n = 0
        for line in p.stdout:
            line = line.rstrip()
            if not line:
                continue
            self.emit(line)
            if parse:
                n = parse(line, n) or n
        p.wait()
        self.proc = None
        if p.returncode != 0:
            if self.stopping:
                self.emit("■ остановлено пользователем")
                return n
            raise RuntimeError("код %d: %s" % (p.returncode, " ".join(cmd[:3])))
        return n

    def venv_py(self):
        return os.path.join(self.e_repo.get(), "venv", "Scripts", "python.exe")

    def work_py(self):
        """Каким питоном рендерить: venv (если выбран и создан) или базовый."""
        if self.v_venv.get():
            vpy = self.venv_py()
            if not os.path.isfile(vpy):
                raise RuntimeError("venv выбран, но не создан — нажми «Установить всё»")
            return vpy
        return self.e_py.get()

    # модуль -> pip-spec (ставим ТОЛЬКО отсутствующие, имеющиеся не трогаем/не даунгрейдим)
    NEED = [
        ("f5_tts", "git+https://github.com/ai4bharat/IndicF5.git@13f7c4d627cc10111aea8fe9c0039462cacacdc7"),
        ("vocos", "vocos==0.1.0"),
        ("x_transformers", "x-transformers==2.19.7"),
        ("indic_transliteration", "indic-transliteration"),
        ("torchcodec", "torchcodec"),  # нужен свежему torchaudio для чтения wav
        ("av", "av"),  # везёт FFmpeg-DLL для torchcodec
    ]
    HAVE_OK = ("torch", "torchaudio", "transformers", "accelerate", "librosa",
               "soundfile", "huggingface_hub", "numpy")

    # ------------------------------- шаги ---
    def do_check(self):
        self.run_bg(self._check)

    def _check(self):
        py = self.e_py.get()
        self.emit("$ %s --version" % py)
        out = subprocess.run([py, "--version"], capture_output=True, text=True)
        self.emit((out.stdout or out.stderr).strip() or "нет запуска")
        self.emit("--- torch ---")
        code = ("import torch,sys; print('torch', torch.__version__);"
                "print('cuda', torch.cuda.is_available());"
                "print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else '');"
                "try:\n import torchaudio; print('torchaudio', torchaudio.__version__)\n"
                "except Exception as e: print('torchaudio НЕТ:', e)")
        for label, exe in (("venv", self.venv_py()), ("base", py)):
            if label == "venv" and not os.path.isfile(exe):
                self.emit("venv: нет (нужен только в venv-режиме)")
                continue
            r = subprocess.run([exe, "-c", code], capture_output=True, text=True)
            self.emit("[%s] %s" % (label, (r.stdout or r.stderr).strip().replace("\n", " | ")))
        self.emit("--- модули в базовом питоне ---")
        miss = [m for m, _ in self.NEED
                if subprocess.run([py, "-c", "import %s" % m],
                                  capture_output=True, timeout=120).returncode != 0]
        self.emit("не хватает: %s" % (", ".join(miss) if miss else "всё есть"))
        for cmd, name in ((["nvidia-smi", "-L"], "GPU"),
                          (["ffmpeg", "-version"], "ffmpeg"),
                          (["git", "--version"], "git")):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                first = (r.stdout or "").strip().split("\n")[0][:100]
                self.emit("%s: %s" % (name, first or "НЕТ"))
            except Exception as ex:
                self.emit("%s: НЕТ (%s)" % (name, ex))
        repo = self.e_repo.get()
        models = self.e_models.get() or os.path.join(repo, "models")
        self.emit("--- движок ---")
        self.emit("render.py: %s" % ("да" if os.path.isfile(os.path.join(repo, "src", "render.py")) else "нет"))
        self.emit("BigVGAN: %s" % ("да" if os.path.isdir(os.path.join(repo, "BigVGAN")) else "нет"))
        for w in ("voice_steer_ema_2026-06-17.pt", "voc_bigvgan_EMA_2026-06-11.pth", "vocab.txt"):
            p = os.path.join(models, w)
            self.emit("%s: %s" % (w, ("%.0f МБ" % (os.path.getsize(p) / 1048576))
                                  if os.path.isfile(p) else "нет"))
        try:
            free = shutil.disk_usage(repo if os.path.isdir(repo) else HERE).free / 1073741824
            self.emit("Свободно на диске: %.1f ГБ (веса ≈ 4 ГБ; venv-режим +≈ 8 ГБ)" % free)
        except Exception:
            pass

    def _have(self, py, mod):
        r = subprocess.run([py, "-c", "import %s" % mod],
                           capture_output=True, timeout=120)
        return r.returncode == 0

    def do_install(self):
        if self.v_venv.get():
            msg = ("Клонирую vagdhenu, создаю venv, ставлю torch+зависимости, "
                   "качаю веса (~12 ГБ). Продолжить?")
        else:
            msg = ("Доставлю ТОЛЬКО недостающее в твой питон "
                   "(проверю импорты, ничего имеющегося не трону), "
                   "склонирую движок и скачаю веса. Продолжить?")
        if not messagebox.askyesno("Установка", msg):
            return
        self.run_bg(self._install)

    def _install(self):
        if self.v_venv.get():
            self._install_venv()
        else:
            self._install_shared()

    def _clone_repo(self, repo):
        if os.path.isdir(os.path.join(repo, ".git")):
            self.emit("== git pull ==")
            self.stream(["git", "pull", "--ff-only"], cwd=repo)
        else:
            self.emit("== git clone vagdhenu ==")
            self.stream(["git", "clone", "--depth", "1", VAG_URL, repo])

    def _bigvgan(self, repo):
        bg = os.path.join(repo, "BigVGAN")
        if os.path.isdir(os.path.join(bg, ".git")):
            self.emit("BigVGAN уже есть")
        else:
            self.emit("== clone BigVGAN ==")
            self.stream(["git", "clone", "--depth", "1", BIGVGAN_URL, bg])

    def _weights(self, repo):
        self.emit("== веса (несколько ГБ с HuggingFace) ==")
        self.stream([self.work_py(), "scripts/download_weights.py"], cwd=repo)
        self.emit("ГОТОВО. Нажми «Тест (1 стих)» для проверки.")

    def _install_shared(self):
        py, repo = self.e_py.get(), self.e_repo.get()
        os.makedirs(repo, exist_ok=True)
        self._clone_repo(repo)
        self.emit("== проверка модулей (ставлю только отсутствующие) ==")
        for mod, spec in self.NEED:
            if self._have(py, mod):
                self.emit("%s: есть" % mod)
            else:
                self.emit("%s: НЕТ — ставлю" % mod)
                self.stream([py, "-m", "pip", "install", spec], cwd=repo)
        if not self._have(py, "torchaudio"):
            self.emit("torchaudio сломан/нет — обновляю под твой torch")
            self.stream([py, "-m", "pip", "install", "-U", "torchaudio"], cwd=repo)
        else:
            self.emit("torchaudio: есть")
        self._ffmpeg_dlls(py, repo)
        self._bigvgan(repo)
        self._weights(repo)

    def _ffmpeg_dlls(self, py, repo):
        """torchcodec на Windows не видит FFmpeg: кладём DLL из av.libs рядом с ним
        (и хеш-имена, и канонические — av ссылается по хешам, torchcodec по каноническим).
        Проверяем чтением эталона из банка."""
        self.emit("== FFmpeg-DLL для torchcodec ==")
        self.stream([py, os.path.join(HERE, "vag_dllfix.py")], cwd=repo)
        bank = os.path.join(repo, "src", "reference_bank", "anushtubh.wav")
        if os.path.isfile(bank):
            self.stream([py, "-c",
                         "import torchaudio, sys;"
                         "w, sr = torchaudio.load(sys.argv[1]);"
                         "print('wav-ok', tuple(w.shape), sr)", bank], cwd=repo)
        else:
            self.emit("(эталона нет — проверка чтения wav пропущена)")

    def _install_venv(self):
        py, repo = self.e_py.get(), self.e_repo.get()
        os.makedirs(repo, exist_ok=True)
        self._clone_repo(repo)
        vpy = self.venv_py()
        if not os.path.isfile(vpy):
            self.emit("== venv ==")
            self.stream([py, "-m", "venv", os.path.join(repo, "venv")])
        else:
            self.emit("venv уже есть")
        self.emit("== torch (долго, ~5 ГБ) ==")
        spec = shlex.split(self.e_torch.get(), posix=False)
        self.stream([vpy, "-m", "pip", "install", "--upgrade", "pip"], cwd=repo)
        self.stream([vpy, "-m", "pip", "install"] + spec, cwd=repo)
        self.emit("== requirements.txt ==")
        self.stream([vpy, "-m", "pip", "install", "-r", "requirements.txt"], cwd=repo)
        self._bigvgan(repo)
        self._weights(repo)

    def do_test(self):
        self.run_bg(self._test)

    def _test(self):
        repo = self.e_repo.get()
        models = self.e_models.get() or os.path.join(repo, "models")
        sample = os.path.join(repo, "examples", "sample_shard.json")
        if not os.path.isfile(sample):
            raise RuntimeError("нет examples/sample_shard.json — репозиторий не склонирован?")
        outd = os.path.join(repo, "test_out")
        os.makedirs(outd, exist_ok=True)
        res = os.path.join(repo, "test_res.json")
        self.emit("== рендер 1 клипа (1-3 мин на 4090) ==")
        self.stream(self._render_cmd(sample, res, outd),
                    cwd=repo, env=self._render_env(repo, models))
        got = [r for r in json.load(open(res, encoding="utf-8")) if "error" not in r]
        if not got:
            bad = json.load(open(res, encoding="utf-8"))
            raise RuntimeError("рендер упал: %s" % (bad[0].get("error", "?") if bad else "?"))
        self.emit("ТЕСТ ПРОШЁЛ — слушай %s" % outd)

    def _render_env(self, repo, models):
        pp = os.path.join(repo, "BigVGAN")
        old = os.environ.get("PYTHONPATH", "")
        return {"PYTHONPATH": pp + (os.pathsep + old if old else ""),
                "CHAMP_ROOT": models}

    def _num(self, var, name, integer=False):
        try:
            v = var.get().replace(",", ".")
            return ["--" + name, str(int(v) if integer else float(v))]
        except Exception:
            return []

    def _render_cmd(self, shard, results, outdir):
        repo = self.e_repo.get()
        cmd = ([self.work_py(), os.path.join(repo, "src", "render.py"),
                "--shard", shard, "--results", results, "--outdir", outdir]
               + self._num(self.e_gap, "gap")
               + self._num(self.e_nfe, "nfe", integer=True)
               + self._num(self.e_cfg, "cfg"))
        if self.e_bank.get().strip() and os.path.isfile(self.e_bank.get().strip()):
            cmd += ["--bank", self.e_bank.get().strip()]
        return cmd

    def pick_books(self):
        import sqlite3
        src = self.e_src.get()
        if not src or not os.path.isfile(src):
            messagebox.showwarning("Книги", "Сначала выбери .db")
            return
        try:
            con = sqlite3.connect(src)
            rows = list(con.execute("SELECT _id,title,type FROM books ORDER BY _id"))
            con.close()
        except Exception as ex:
            messagebox.showwarning("Книги", "Не читается: %s" % ex)
            return
        if not rows:
            messagebox.showwarning("Книги", "В файле нет книг")
            return
        win = tk.Toplevel(self)
        win.title("Книги из %s" % os.path.basename(src))
        win.geometry("420x400")
        cur = set(x.strip() for x in self.e_books.get().split(",") if x.strip())
        vars_ = {}
        fr = ttk.Frame(win, padding=6)
        fr.pack(fill="both", expand=True)
        for bid, title, typ in rows:
            v = tk.BooleanVar(value=(str(bid) in cur) or (not cur and str(typ).upper() == (self.e_btype.get() or "SB").upper()))
            vars_[str(bid)] = v
            ttk.Checkbutton(fr, text="[%s] %s" % (typ, title), variable=v).pack(anchor="w")
        bf = ttk.Frame(win, padding=6)
        bf.pack(fill="x")
        ttk.Button(bf, text="OK", command=lambda: self._books_ok(win, vars_)).pack(side="left")
        ttk.Button(bf, text="Все", command=lambda: [v.set(True) for v in vars_.values()]).pack(side="left", padx=4)
        ttk.Button(bf, text="Отмена", command=win.destroy).pack(side="right")

    def _books_ok(self, win, vars_):
        sel = sorted(b for b, v in vars_.items() if v.get())
        self.e_books.set(",".join(sel))
        self.b_books.configure(text="Выбрано: %d" % len(sel) if sel else "Выбрать…")
        win.destroy()

    def resolve_books(self, src, btype):
        """book_id для шарда: явный выбор, иначе все книги нужного типа."""
        sel = [x.strip() for x in self.e_books.get().split(",") if x.strip()]
        if sel:
            return sel
        import sqlite3
        con = sqlite3.connect(src)
        try:
            rows = list(con.execute("SELECT _id,title FROM books WHERE upper(type)=?",
                                    (btype.upper(),)))
        finally:
            con.close()
        if not rows:
            raise RuntimeError("в файле нет книг типа %s — выбери книги вручную" % btype)
        self.emit("книги по типу %s: %s" % (
            btype, ", ".join("%s (%s)" % (t, i) for i, t in rows)))
        return [str(i) for i, _ in rows]

    def do_shard(self):
        self.run_bg(self._shard)

    def _shard(self):
        src = self.e_src.get()
        if not src or not os.path.isfile(src):
            raise RuntimeError("выбери исходный .db")
        self.emit("Vagdhenu-окно v%d" % VAG_GUI_VERSION)
        btype = self.e_btype.get() or "SB"
        books = self.resolve_books(src, btype)
        titles = self.book_titles(src, books)
        self.emit("книги для шарда: %s" % ", ".join(titles))
        own = [t for t in titles if ("[%s]" % btype.upper()) in t.upper()]
        if not own:
            raise RuntimeError(
                "СТОП: выбранные книги — не %s (%s). "
                "Открой «Книги…» заново для ЭТОГО файла." % (btype, ", ".join(titles)))
        os.makedirs(os.path.dirname(os.path.abspath(self.e_shard.get())), exist_ok=True)
        os.makedirs(self.e_wav.get(), exist_ok=True)
        bank = os.path.join(self.e_repo.get(), "src", "reference_bank", "bank.json")
        self.stream([self.e_py.get(), os.path.join(HERE, "vagdhenu_shard.py"), "shard",
                     "--src", src, "--book-type", self.e_btype.get() or "SB",
                     "--out", self.e_shard.get(), "--manifest", self.e_mani.get(),
                     "--outdir", self.e_wav.get(),
                     "--seed", (self.e_seed.get() or "60"),
                     "--tempo", (self.e_speed.get().replace(",", ".") or "1.0"),
                     "--bank", bank if os.path.isfile(bank) else "",
                     "--books", ",".join(books),
                     "--chapters", self.e_chapters.get(),
                     "--limit", (self.e_limit.get() or "0"),
                     "--sample-meter", (self.e_sample.get() or "0"),
                     "--verses", self.e_verses.get()] +
                    ((["--src2", self.e_src2.get()] if self.e_src2.get() else [])))
        # Запоминаем, с какими настройками собран шард — рендер сверится
        try:
            json.dump(self._shard_params(),
                      open(self.e_shard.get() + ".params.json", "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        except Exception as ex:
            self.emit("sidecar шарда не записан: %s" % ex)

    @staticmethod
    def book_titles(src, ids):
        try:
            import sqlite3
            con = sqlite3.connect(src)
            rows = con.execute("SELECT _id,title,type FROM books")
            titles = {str(r[0]): "%s [%s]" % (r[1], r[2]) for r in rows}
            con.close()
            return ["%s=%s" % (i, titles.get(i, "?")) for i in ids]
        except Exception:
            return ids

    def _shard_params(self):
        return {"tempo": (self.e_speed.get().replace(",", ".") or "1.0"),
                "seed": (self.e_seed.get() or "60"),
                "books": self.e_books.get(), "chapters": self.e_chapters.get(),
                "limit": (self.e_limit.get() or "0"), "sample": (self.e_sample.get() or "0"),
                "src": self.e_src.get(), "src2": self.e_src2.get(),
                "btype": self.e_btype.get() or "SB"}

    def do_render(self):
        try:
            total = len(json.load(open(self.e_shard.get(), encoding="utf-8")))
        except Exception as ex:
            messagebox.showwarning("Шард", "Не читается шард: %s" % ex)
            return
        try:
            import datetime
            mt = datetime.datetime.fromtimestamp(
                os.path.getmtime(self.e_shard.get())).strftime("%d.%m %H:%M")
        except Exception:
            mt = "?"
        # Шард хранит темп/seed/фильтры внутри: сверяем с текущими полями
        stale = []
        try:
            saved = json.load(open(self.e_shard.get() + ".params.json", encoding="utf-8"))
            cur = self._shard_params()
            for k, v in cur.items():
                if str(saved.get(k, "")) != str(v):
                    stale.append("%s: в шарде %s, сейчас %s" % (k, saved.get(k, "?"), v))
        except Exception:
            stale = ["параметры шарда неизвестны (старый шард)"]
        if stale:
            if not messagebox.askyesno(
                    "Шард устарел",
                    "Настройки отличаются от шарда:\n• %s\n\nПерегенерировать шард "
                    "и потом рендерить?" % "\n• ".join(stale)):
                return
            self.render_total = 0
            self.run_bg(self._regen_and_render)
            return
        if not messagebox.askyesno("Рендер",
                "Клипов: %d (шард от %s). На 4090 это часы. Продолжить?" % (total, mt)):
            return
        self.render_total = total
        self.prog.configure(maximum=total, value=0)
        self.run_bg(self._render)

    def _regen_and_render(self):
        self.emit("== шард устарел — перегенерирую с текущими настройками ==")
        self._shard()
        try:
            self.render_total = len(json.load(open(self.e_shard.get(), encoding="utf-8")))
        except Exception:
            self.render_total = 0
        self.q.put(("prog", 0, self.render_total or 1))
        self._render()

    def _render(self):
        repo = self.e_repo.get()
        models = self.e_models.get() or os.path.join(repo, "models")
        shard, res, outd = self.e_shard.get(), self.e_res.get(), self.e_wav.get()
        os.makedirs(outd, exist_ok=True)

        def parse(line, n):
            if line.startswith("OK ") or line.startswith("FAIL "):
                n += 1
                self.q.put(("prog", n, self.render_total))
            return n

        self.emit("== рендер %d клипов ==" % self.render_total)
        self.stream(self._render_cmd(shard, res, outd), cwd=repo,
                    env=self._render_env(repo, models), parse=parse)
        self.q.put(("prog", self.render_total, self.render_total))
        self.emit("РЕНДЕР ГОТОВ. Дальше — «Собрать ogg».")

    def do_stop(self):
        p = self.proc
        if p is not None:
            self.stopping = True
            try:
                p.terminate()
                self.emit("…останавливаю")
            except Exception as ex:
                self.emit("стоп: %s" % ex)

    def toggle_nosong(self):
        """Галочка правит шаблон видимым образом: убирает/возвращает {song}."""
        import re
        p = self.e_pat.get()
        if self.v_nosong.get():
            p = re.sub(r"\{song\}[._-]?", "", p)
            # схлопнуть двойные разделители, которые могли остаться
            p = re.sub(r"([._-])\1+", r"\1", p)
        else:
            if "{song}" not in p:
                m = re.match(r"^([^{\[]+)", p)
                pre = m.group(1) if m else ""
                p = pre + "{song}." + p[len(pre):]
        self.e_pat.set(p)

    def do_collect(self):
        # Одноуровневая книга (у БГ песнь всегда одна): {song} в именах — мусор.
        # Если галочка не стоит, а манифест одно-песенный — включаем сами, видно в шаблоне.
        try:
            mani = json.load(open(self.e_mani.get(), encoding="utf-8"))
            songs = {m.get("song", "") for m in mani} if isinstance(mani, list) else set()
            if len(songs) == 1 and "{song}" in self.e_pat.get() and not self.v_nosong.get():
                self.v_nosong.set(True)
                self.toggle_nosong()
                self.say("песнь одна (%s) — {song} убран из имён" % next(iter(songs)))
        except Exception as ex:
            self.say("авто-проверка песни пропущена: %s" % ex)
        self.run_bg(self._collect)

    def _collect(self):
        self.stream([self.e_py.get(), os.path.join(HERE, "vagdhenu_shard.py"), "collect",
                     "--manifest", self.e_mani.get(), "--results", self.e_res.get(),
                     "--wavdir", self.e_wav.get(), "--outdir", self.e_ogg.get(),
                     "--pattern", self.e_pat.get() or "SB{song}.{ch}.{txt}.ogg",
                     "--bitrate", (self.e_bitrate.get() or "24k")])

    def do_pack(self):
        out = self.e_pack.get()
        if not out:
            messagebox.showwarning("Нет выхода", "Укажи выходной audio.db")
            return
        if os.path.exists(out) and not messagebox.askyesno(
                "Перезапись", "Файл есть. Перезаписать?\n%s" % out):
            return
        self.run_bg(self._pack)

    def _pack(self):
        import tempfile
        out = self.e_pack.get()
        spec = {"out": out, "books": [], "audio_pack": {
            "dir": self.e_ogg.get(), "book_type": self.e_btype.get() or "SB",
            "pattern": self.e_pat.get() or "SB{song}.{ch}.{txt}.ogg"}}
        fd, sp = tempfile.mkstemp(prefix="vagspec_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False, indent=1)
        try:
            report = recompose.build(sp, out, True)
            self.emit("ПАК ГОТОВ: %s\n%s" % (out, report))
        finally:
            try:
                os.remove(sp)
            except Exception:
                pass


def open_vag(app):
    VagWin(app)
