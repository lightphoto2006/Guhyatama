# -*- coding: utf-8 -*-
"""Smoke вкладки «AI-импорт»: табы, т1 (привязка с переименованием),
т2 (нарезка -> source-.db -> Открыть в Сборке), т3 (правка метаданных),
busy-защита закрытия. LLM замокан, llama-server не поднимается."""
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui                                  # noqa: E402
import ai_import as ai                      # noqa: E402
import lectures_build                       # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (("  | " + str(extra)) if not cond else ""))
    if not cond:
        FAILED.append(name)


def pump(root, cond, timeout=20.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        root.update()
        if cond():
            return True
        time.sleep(0.05)
    return False


def write_docx(path, paras):
    body = "".join(
        "<w:p><w:r><w:t>%s</w:t></w:r></w:p>" % t for t in paras)
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/'
           'wordprocessingml/2006/main"><w:body>%s</w:body></w:document>' % body)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)


# старт без сторонних папок/конфигов пользователя
gui.load_cfg = lambda: {}
gui.save_cfg = lambda cfg: None

app = gui.App()
app.update()

# --- диагностика: жив ли poll вкладки AI ---
_alive = []
_orig_poll = app.tab_ai.poll


def _poll_wrap():
    _alive.append(time.time())
    if len(_alive) <= 6:
        print("DBG tick#%d q=%d" % (len(_alive), app.tab_ai.q.qsize()))
    try:
        return _orig_poll()
    except Exception as e:
        print("DBG POLL RAISED: %r" % (e,))
        raise


app.tab_ai.poll = _poll_wrap
print("DBG poll ticks: %d" % len(_alive))

# ------------------------------------------------------------- вкладки ------
tabs = [app.nametowidget(t) for t in app.nb.tabs()]
check("4 вкладки", len(app.nb.tabs()) == 4,
      [app.nb.tab(t, "text") for t in app.nb.tabs()])
check("вкладка AI создана", isinstance(app.tab_ai, ai.AIImportTab))
app.nb.select(app.tab_ai)
app.update()
check("on_activate отработал (health запущен)", app.tab_ai._activated)

# ------------------------------------------------------------ т2: книга -----
tab = app.tab_ai
text = ("Шапка книги до заголовков.\n\n"
        "# Часть первая\n\n"
        "## Глава первая\n\nАбзац один.\nвторая строка\n\nАбзац два.\n\n"
        "## Глава вторая\n\nЕщё абзац.\n")
tab.txt2.insert("1.0", text)
tab.v_btitle.set("Тестовая книга")
tab.v_bauthor.set("Автор Тестов")
tab.v_btype.set("SCC")
tab.t2_parse()
app.update()
kids = tab.tv2.get_children()
check("т2: дерево структуры (введение + 2 главы)", len(kids) == 3, kids)
st = tab._struct
check("т2: структура 3 главы / 4 стиха",
      st and st["stats"]["chapters"] == 3 and st["stats"]["verses"] == 4,
      st["stats"] if st else None)

tmp = tempfile.mkdtemp(prefix="ai_gui_")
out2 = os.path.join(tmp, "Тестовая книга.db")
ai.filedialog.asksaveasfilename = lambda **kw: out2
tab.t2_save()
app.update()
check("т2: source-.db записан", os.path.isfile(out2) and os.path.getsize(out2) > 0)
check("т2: кнопка «Открыть» включена", str(tab.b_open.cget("state")) == "normal")
tab.t2_open()
app.update()
check("т2: книга в «Сборке»", len(app.rows) == 1 and
      list(app.rows.values())[0]["title"] == "Тестовая книга", list(app.rows))
check("т2: фокус на «Сборке»", app.nb.select() == app.nb.tabs()[0])

# ------------------------------------------------------ т1: привязка --------
app.nb.select(app.tab_ai)
app.update()
lect_dir = os.path.join(tmp, "lect")
os.makedirs(lect_dir)
bad = os.path.join(lect_dir, "разное.docx")
write_docx(bad, ["Тема лекции о преданности и служении.",
                 "Второй абзац без ссылок и цифр в скобках."])
lect = app.tab_lectures
lrow = lectures_build.parse_single_lecture(bad, "SCC")
check("т1: файл без привязки unparsed", lrow["unparsed"] and lrow["song"] == "99", lrow["song"])
lect._activated = True
lect.rows[bad] = lrow

calls = []
def fake_chat_json(cfg, messages, **kw):
    calls.append(messages)
    if "границы ГЛАВ" in messages[-1]["content"]:
        return {"book_title": "x", "chapters": []}
    if "привязку лекции" in messages[-1]["content"]:
        return {"song": 2, "ch": 5, "txts": "1-3", "title": "Тема преданности",
                "confidence": "high", "reason": "по содержанию"}
    return {"proposals": [{"idx": 0, "field": "title",
                           "value": "Новое название", "confidence": "medium",
                           "reason": "тест"}]}
ai.llama_client.chat_json = fake_chat_json
tab._need_server = lambda: True

tab.t1_load()
check("т1: список загружен", pump(app, lambda: bool(tab.tv1.get_children())) and
      len(tab.tv1.get_children()) == 1, tab.tv1.get_children())
tab.t1_run()
ok = pump(app, lambda: tab._t1.get(bad) and tab._t1[bad].get("prop"))
check("т1: proposal от LLM", ok and tab._t1[bad]["prop"]["stem"]
      == "(2.5.1-3) Тема преданности", tab._t1.get(bad))
check("т1: не busy после готово", not tab.busy)
tab.t1_apply()
app.update()
newp = os.path.join(lect_dir, "(2.5.1-3) Тема преданности.docx")
check("т1: файл переименован", os.path.isfile(newp) and not os.path.exists(bad))
check("т1: строка лекций перепривязана",
      newp in lect.rows and not lect.rows[newp]["unparsed"], lect.rows.get(newp, {}).get("unparsed"))
check("т1: список пуст после применения", not tab.tv1.get_children())

# ------------------------------------------------------ т3: метаданные ------
print("DBG before t3_load: exists=%s kids=%s" % (
    tab.tv3.winfo_exists(), tab.tv3.get_children()))
tab.t3_load()
check("т3: книги загружены", len(tab.tv3.get_children()) == 1, tab.tv3.get_children())
tab.t3_run()
print("DBG after t3_run: exists=%s kids=%s q=%d busy=%s ticks=%d last_tick_age=%.1fs" % (
    tab.tv3.winfo_exists(), tab.tv3.get_children(), tab.q.qsize(), tab.busy,
    len(_alive), time.time() - _alive[-1] if _alive else -1))
ok = pump(app, lambda: bool(tab.tv3.get_children()) and len(tab._t3props) == 1)
print("DBG after pump: kids=%s props=%s" % (tab.tv3.get_children(), tab._t3props))
with open(os.path.join(tempfile.gettempdir(), "ai_tab_log.txt"), "w",
          encoding="utf-8") as f:
    f.write(tab.log.get("1.0", "end"))
print("DBG AI LOG -> %s" % os.path.join(tempfile.gettempdir(), "ai_tab_log.txt"))
check("т3: proposal от LLM", ok, tab._t3props)
row = list(app.rows.values())[0]
check("т3: до правки", row["new_title"] == "Тестовая книга", row["new_title"])
tab.t3_apply()
app.update()
check("т3: new_title изменён", row["new_title"] == "Новое название", row["new_title"])
check("т3: ячейка дерева обновлена",
      tab.tv3.set(list(tab.tv3.get_children())[0], "value") == "Новое название")
check("т3: галочка снята", tab.tv3.item(tab.tv3.get_children()[0], "text") == "")

# ------------------------------------------------------ busy / закрытие ------
warned = []
gui.messagebox.showwarning = lambda title, msg, **kw: warned.append(msg)
tab.set_busy(True)
app.on_close()
check("закрытие заблокировано при busy", warned and app.winfo_exists())
tab.set_busy(False)
app.on_close()
check("закрытие прошло без busy", True)

print()
if FAILED:
    print("FAILED %d: %s" % (len(FAILED), ", ".join(FAILED)))
    sys.exit(1)
print("ALL OK (llm-запросов: %d)" % len(calls))
shutil.rmtree(tmp, ignore_errors=True)
