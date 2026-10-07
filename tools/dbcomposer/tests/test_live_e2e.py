# -*- coding: utf-8 -*-
"""Живой E2E: /health -> chat_json (схема JSON) -> боевой промпт привязки.
Сервер, если уже запущен, не останавливаем; если подняли сами — гасим."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ai_import as ai                      # noqa: E402
import llama_client                         # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (("  | " + str(extra)) if not cond else ""))
    if not cond:
        FAILED.append(name)


cfg = llama_client.load_cfg()
srv = llama_client.LlamaServer(cfg)
mine = False
st = srv.health(timeout=2)
print("health before: %s (%s)" % (st, srv.base_url))
if st != "ready":
    mine = True
    err = srv.start(log=lambda s: print("SRV: %s" % s[:220]))
    check("запуск llama-server", err is None, err)
    if err:
        sys.exit(1)
    t0 = time.time()
    ok = srv.wait_ready(timeout=420, log=lambda s: print("WAIT: %s" % s[:220]))
    check("сервер готов за %d с" % int(time.time() - t0), ok)
    if not ok:
        sys.exit(1)
else:
    check("сервер уже готов", True)

# 1) строгий JSON roundtrip (запас токенов под reasoning-модели)
res = llama_client.chat_json(
    cfg, [{"role": "system", "content": ai.SYSTEM_JSON},
          {"role": "user", "content": "Верни JSON: {\"ok\": true, \"n\": 2}"}],
    max_tokens=1024, temperature=0.0, timeout=180)
check("chat_json: точный ответ", res == {"ok": True, "n": 2}, res)

# 2) боевой промпт привязки лекции -> validate_binding
lecture = [
    "Лекция по теме служение личности в духовной жизни.",
    "Рассмотрим стихи, где говорится о преданном служении и отречении от плодов труда.",
    "Текст: кто служит Мне, не нарушая..., тот достигает совершенства.",
]
msgs = ai.binding_messages("SCC", "без_имени.docx", lecture)
t0 = time.time()
prop = llama_client.chat_json(cfg, msgs, max_tokens=1500, temperature=0.1, timeout=300)
print("LLM за %.0f с -> %s" % (time.time() - t0, prop))
check("привязка: JSON с ключами", isinstance(prop, dict)
      and {"song", "ch", "txts"} <= set(prop), prop)
stem, notes = ai.validate_binding(prop, "SCC", {"num": "101", "paras": lecture})
check("привязка: проходит валидацию или честный None",
      stem is not None or notes, (stem, notes))
if stem:
    check("привязка: имя парсится парсером имён",
          ai.lectures_build.parse_lecture_filename(stem + ".docx") is not None, stem)

# 3) структурный промпт (обрезка) -> главы. Только на своём сервере:
# чужой может жить с дефолтным ctx 4096 — 30k-символьный промпт не влезет
if mine:
    text = ("Глава 1. Начало\nТекст первого раздела.\n\n"
            "Глава 2. Продолжение\nТекст второго раздела.\n")
    prop = llama_client.chat_json(cfg, ai.structure_messages("Тест", text),
                                  max_tokens=4096, temperature=0.1, timeout=300)
    heads = (prop or {}).get("chapters") or []
    check("структура: найдены заголовки", len(heads) >= 1, prop)
    struct = ai.build_structure(text, dict(ch_mode="preset", v_mode="para",
                                           prelude_intro=True, book_title="Тест"),
                                llm_result=prop)
    check("структура: нарезка по LLM-заголовкам дала главы",
          struct["stats"]["chapters"] >= 2, struct["stats"])
else:
    print("структурный промпт пропущен: чужой сервер (маленький ctx)")

if mine:
    srv.stop()
    time.sleep(1)
    check("свой сервер погашен", srv.health(timeout=2) == "down")
else:
    print("чужой сервер не трогаем")

print()
if FAILED:
    print("FAILED %d: %s" % (len(FAILED), ", ".join(FAILED)))
    sys.exit(1)
print("ALL OK")
