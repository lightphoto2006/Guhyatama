#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Клиент llama.cpp server для вкладки «AI-импорт» dbcomposer.

- LlamaServer: /health (ready/loading/down), запуск llama-server.exe процессом
  с чтением его stdout в лог, остановка.
- chat/chat_json: POST /v1/chat/completions (OpenAI-совместимый API llama-server),
  chat_json — строгий разбор JSON (забор ```json, сырой разбор с первой {),
  одна повторная попытка с корректирующим сообщением при кривом ответе.

Конфиг — ai_gui.json (путь/модель/порт/контекст/аргументы), через dbcommon.
"""
import json
import os
import re
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.request

import dbcommon

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "ai_gui.json")

DEFAULT_CFG = {
    # llama.cpp сборка пользователя (CUDA 13 portable) + модель gemma-4-26B
    "exe": r"F:\AI\app-b11160-mix-a6922cc-windows-x64-cuda13-portable\llama-server.exe",
    "model": r"F:\AI\Models\gemma-4-26B-A4B-it-UD-Q5_K_M.gguf",
    "host": "127.0.0.1",
    "port": 8080,
    "ctx": 32768,
    "ngl": 99,
    # аргументы как в лаунчере пользователя (GLM 4.7.bat): джини-шаблоны,
    # вместимость KV через --fit + q8_0, все потоки CPU
    "extra": "--jinja --fit on -ctk q8_0 -ctv q8_0 -t -1",
}


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    cfg.update(dbcommon.load_cfg(CFG_PATH))
    return cfg


def save_cfg(patch):
    cfg = load_cfg()
    cfg.update(patch)
    dbcommon.save_cfg(CFG_PATH, cfg)


def _nowin():
    return subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


class LlamaServer:
    """Один процесс llama-server, живёт столько же, сколько открыт тулза."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.proc = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ health --
    @property
    def base_url(self):
        return "http://%s:%s" % (self.cfg.get("host", "127.0.0.1"), self.cfg.get("port", 8080))

    def health(self, timeout=1.2):
        """'ready' (200) | 'loading' (503, модель грузится) | 'down' (нет ответа)."""
        try:
            with urllib.request.urlopen(self.base_url + "/health", timeout=timeout) as r:
                return "ready" if r.status == 200 else "loading"
        except urllib.error.HTTPError as e:
            return "loading" if e.code == 503 else "down"
        except Exception:
            return "down"

    # ------------------------------------------------------------ старт ---
    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, log=lambda s: None):
        """Запуск в фоне. Возвращает None при успехе или текст ошибки."""
        with self._lock:
            if self.alive():
                return "сервер уже запущен"
            exe = self.cfg.get("exe", "")
            model = self.cfg.get("model", "")
            if not os.path.isfile(exe):
                return "не найден llama-server.exe: %s" % exe
            if not os.path.isfile(model):
                return "не найден файл модели: %s" % model
            cmd = [exe, "-m", model,
                   "--host", str(self.cfg.get("host", "127.0.0.1")),
                   "--port", str(self.cfg.get("port", 8080)),
                   "-c", str(int(self.cfg.get("ctx", 32768))),
                   "-ngl", str(int(self.cfg.get("ngl", 99)))]
            try:
                cmd += shlex.split(self.cfg.get("extra", ""), posix=False)
            except ValueError as e:
                return "плохие аргументы: %s" % e
            try:
                self.proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    cwd=os.path.dirname(exe), env=dict(os.environ), creationflags=_nowin())
            except OSError as e:
                return "не запускается: %s" % e
            log("запуск: %s" % " ".join(cmd[:1] + cmd[-8:]))
            threading.Thread(target=self._reader, args=(log,), daemon=True).start()
            return None

    def _reader(self, log):
        try:
            for line in self.proc.stdout:
                line = line.rstrip("\n").rstrip("\r")
                if line:
                    log(line[:600])
        except Exception:
            pass

    def stop(self):
        p = self.proc
        if p is None:
            return
        try:
            if p.poll() is None:
                p.terminate()
        except Exception:
            pass
        self.proc = None

    def wait_ready(self, timeout, log=lambda s: None, poll=1.0):
        """Ждать ready после запуска. Возвращает True/False (логирует прогресс)."""
        t0 = time.time()
        last = None
        while time.time() - t0 < timeout:
            st = self.health()
            if st == "ready":
                log("сервер готов: %s" % self.base_url)
                return True
            if st == "down" and (self.proc is None or self.proc.poll() is not None):
                rc = None if self.proc is None else self.proc.returncode
                log("процесс завершён (код %s)" % rc)
                return False
            if st != last:
                log("загрузка модели… (%d с)" % int(time.time() - t0))
                last = st
            time.sleep(poll)
        log("сервер не готов за %d с" % timeout)
        return False


# ------------------------------------------------------------ chat API ----
def chat(cfg, messages, max_tokens=4096, temperature=0.1, timeout=900, thinking=None):
    """Один ответ модели (не-стриминг). Текст ответа или RuntimeError.

    thinking=False — попросить шаблон модели не думать (GLM и др. reasoning:
    включается через chat_template_kwargs.enable_thinking; модели без такого
    шаблона kwargs просто игнорируют)."""
    payload = {
        "model": "llama",
        "messages": messages,
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "stream": False,
    }
    if thinking is False:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = "http://%s:%s/v1/chat/completions" % (
        cfg.get("host", "127.0.0.1"), cfg.get("port", 8080))
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        raise RuntimeError("сервер ответил %d: %s" % (e.code, detail))
    except urllib.error.URLError as e:
        raise RuntimeError("нет соединения с %s (%s). Запусти сервер на вкладке." % (url, e.reason))
    try:
        msg = data["choices"][0]["message"]
        content = msg.get("content")
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("неожиданный ответ: %s" % json.dumps(data, ensure_ascii=False)[:400])
    if not content:
        # reasoning-модели (GLM и др.) sometimes кладут всё в reasoning_content
        reason = str(msg.get("reasoning_content") or "")
        raise RuntimeError(
            "пустой ответ" +
            (" (reasoning съел все %d токенов — увеличь max_tokens)" % max_tokens
             if reason else "") +
            (": " + reason[:200] if reason else ""))
    return content


def extract_json(text):
    """JSON из ответа модели: ```json-заборы, преамбула, сырой разбор с первой {/[."""
    s = (text or "").strip()
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s = re.sub(r"\s*```$", "", s).strip()
    try:
        return json.loads(s)
    except ValueError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(s):
        if ch in "{[":
            try:
                obj, _ = dec.raw_decode(s[i:])
                return obj
            except ValueError:
                continue
    raise ValueError("в ответе нет JSON: %s" % s[:300])


def chat_json(cfg, messages, max_tokens=4096, temperature=0.1, timeout=900):
    """Ответ модели + строгий JSON.

    Пустой content (reasoning съел лимит): 1) лимит x2; 2) thinking выкл.
    При кривом JSON — одна повторная попытка."""
    attempts = [(None, int(max_tokens)),
                (False, int(max_tokens)),
                (None, min(int(max_tokens) * 2, 8192)),
                (False, min(int(max_tokens) * 2, 8192))]
    raw = None
    last = None
    for thinking, mt in attempts:
        try:
            raw = chat(cfg, messages, max_tokens=mt, temperature=temperature,
                       timeout=timeout, thinking=thinking)
            max_tokens = mt
            break
        except RuntimeError as e:
            if "пустой ответ" not in str(e):
                raise
            last = e
    if raw is None:
        raise last
    try:
        return extract_json(raw)
    except ValueError as e1:
        retry = list(messages) + [
            {"role": "assistant", "content": raw[:8000]},
            {"role": "user", "content":
             "Ответ не проходит: %s. Выдай ТОЛЬКО валидный JSON по прежней схеме, "
             "без текста вокруг." % e1},
        ]
        raw2 = chat(cfg, retry, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
        return extract_json(raw2)
