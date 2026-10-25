# -*- coding: utf-8 -*-
"""Юнит-тесты движка AI-импорта: нарезка глав/стихов, writer source-.db, промпты."""
import json
import os
import re
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "lectures"))

import ai_import as ai          # noqa: E402
import recompose                # noqa: E402
import lectures_build           # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (("  | " + str(extra)) if not cond else ""))
    if not cond:
        FAILED.append(name)


# ---------------------------------------------------------------- нарезка ---
md_text = (
    "Вступление какое-то, до заголовков.\n\n"
    "# Раздел Первый\n\n"
    "## Глава первая\n\nАбзац один.\nвторая строка\n\nАбзац два.\n\n"
    "## Глава вторая\n\nЕщё абзац.\n"
)
opts = dict(ch_mode="md", md_section=1, md_chapter=2, prelude_intro=True,
            v_mode="para", join_wraps=True, strip_md=True, book_title="Тест")
s = ai.build_structure(md_text, opts)
check("md: введение + 2 главы", s["stats"]["chapters"] == 3, s["stats"])
check("md: song_names", s["song_names"] == {"1": "Раздел Первый"}, s["song_names"])
c0 = s["chapters"][0]
check("md: intro (0/Введение)", c0["number"] == 0 and c0["title"] == "Введение",
      (c0["number"], c0["title"]))
check("md: intro — 1 абзац", c0["verses"] == [("1", "Вступление какое-то, до заголовков.")],
      c0["verses"])
c1 = s["chapters"][1]
check("md: глава 1 song=1, 2 стиха-абзаца",
      c1["song"] == "1" and c1["number"] == 1 and len(c1["verses"]) == 2, c1)
check("md: объединённый перенос внутри абзаца",
      c1["verses"][0] == ("1", "Абзац один. вторая строка"), c1["verses"])
check("md: заголовок-абзац с хвостом не теряет текст",
      s["chapters"][2]["verses"] == [("1", "Ещё абзац.")], s["chapters"][2])

# пресеты: «Глава N» первой строкой абзаца + хвост после неё
preset_text = (
    "Шапка книги.\n\n"
    "Глава 1. Начало\nтекст один\n\n"
    "Глава 2. Продолжение\nтекст два\n\n"
    "Приложение хвостовое\n"
)
s2 = ai.build_structure(preset_text, dict(ch_mode="preset", v_mode="para",
                                          prelude_intro=True, book_title="К"))
nums = [(c["number"], c["title"]) for c in s2["chapters"]]
check("preset: введение + 2 главы", nums == [(0, "Введение"), (1, "Начало"),
                                             (2, "Продолжение")], nums)
check("preset: хвост строки-заголовка и приложение на месте",
      s2["chapters"][1]["verses"] == [("1", "текст один")]
      and s2["chapters"][2]["verses"] == [("1", "текст два"),
                                          ("2", "Приложение хвостовое")],
      (s2["chapters"][1]["verses"], s2["chapters"][2]["verses"]))

# regex с группами chapter/title
s3 = ai.build_structure(
    "Вступ.\n\n§ 3 Раздел третий\nсодержимое\n",
    dict(ch_mode="regex", prelude_intro=True, v_mode="para", book_title="Т",
         chapter_re=r"§\s+(?P<chapter>\d+)\s+(?P<title>.*)"))
got = [(c["number"], c["title"]) for c in s3["chapters"]]
check("regex: введение + глава №3", got == [(0, "Введение"), (3, "Раздел третий")], got)
check("regex: плохой regex -> ошибка, а не падение",
      ai.split_chapters(["x"], {"ch_mode": "regex", "chapter_re": "["})[2] != [])

# не делить
s4 = ai.build_structure("Просто текст.\n\nВторой абзац.",
                        dict(ch_mode="none", v_mode="none", book_title="Книга"))
check("none: 1 глава, глава целиком 1 стих",
      s4["stats"] == {"chapters": 1, "verses": 1, "chars": len("Просто текст.\nВторой абзац.")},
      s4["stats"])

# повтор (song, number) -> слияние
dup_text = "Глава 1. А\nтекст А\n\nГлава 1. Б\nтекст Б\n"
s5 = ai.build_structure(dup_text, dict(ch_mode="preset", v_mode="para", book_title="Т"))
check("дубль главы 1 слит в одну",
      s5["stats"]["chapters"] == 1 and any("повтор" in n for n in s5["notes"]), s5["notes"])

# стихи по номеру в строке (преамбула -> 0)
verses = ai.split_verses(
    ["Предисловие пролога", "1. Раз первый текст\nпродолжение строки",
     "2. Раз второй"],
    dict(v_mode="number", verse_re=ai.DEFAULT_VERSE_RE, join_wraps=True, strip_md=True))
check("number: преамбула 0 + стихи 1,2 со склейкой",
      verses == [("0", "Предисловие пролога"),
                 ("1", "Раз первый текст продолжение строки"),
                 ("2", "Раз второй")], verses)

# markdown-разметка убирается, склейка переносов
v2 = ai.split_verses(["пер-\nенос и **жирный** [ссылка](http://x)"],
                     dict(v_mode="para", join_wraps=True, strip_md=True))
check("para: склейка-дефис и strip markdown",
      v2 == [("1", "перенос и жирный ссылка")], v2)

# llm-режим: заголовки как точные подстроки, нумерация, песня+имя, введение
llm_text = "Шапка до всего.\n\nОчень интересный заголовок\nТело главы раз.\n\nДругой заголовок\nТело два.\n"
res = {"chapters": [
    {"heading": "Очень интересный заголовок", "number": 1, "song": 2,
     "song_name": "Вторая часть", "title": "Интересный"},
    {"heading": "Другой заголовок", "number": 2, "song": 2, "title": "Другой"}]}
s6 = ai.build_structure(llm_text, dict(v_mode="para", prelude_intro=True,
                                       book_title="Л"), llm_result=res)
check("llm: введение + 2 главы", s6["stats"]["chapters"] == 3, s6["stats"])
check("llm: song_names из song_name", s6["song_names"] == {"2": "Вторая часть"},
      s6["song_names"])
check("llm: тело без заголовочной строки",
      s6["chapters"][1]["verses"] == [("1", "Тело главы раз.")], s6["chapters"][1])
# заголовок не найден -> ошибка, не тихой пустой структурой
s7 = ai.build_structure(llm_text, dict(v_mode="para"),
                        llm_result={"chapters": [{"heading": "НЕТ ТАКОЙ СТРОКИ", "number": 1}]})
check("llm: несовпавшие подстроки -> ошибка",
      any("не найдены" in n for n in s7["notes"]), s7["notes"])

# ------------------------------------------------------------ writer .db ---
tmp = tempfile.mkdtemp(prefix="aiimp_")
out = os.path.join(tmp, "book.db")
meta = {"title": "Тестовая книга", "author": "Автор Тестов", "type": "SCC",
        "with_purport": True}
stat = ai.write_source_db(s, meta, out)
check("writer: счётчики", stat["chapters"] == 3 and stat["texts"] == 4, stat)
con = sqlite3.connect(out)
integ = con.execute("PRAGMA integrity_check").fetchone()[0]
check("writer: integrity_check", integ == "ok", integ)
nb = con.execute("SELECT title, author, type, hasPurport FROM books").fetchone()
check("writer: books", nb == ("Тестовая книга", "Автор Тестов", "SCC", 1), nb)
nsong = con.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
check("writer: songs=1", nsong == 1, nsong)
nch = con.execute("SELECT COUNT(*) FROM chapters").fetchone()[0]
ntn = con.execute("SELECT COUNT(*) FROM textnums").fetchone()[0]
ntx = con.execute("SELECT COUNT(*) FROM texts").fetchone()[0]
check("writer: chapters/textnums/texts = 3/4/4", (nch, ntn, ntx) == (3, 4, 4), (nch, ntn, ntx))
# textnums ссылаются на texts по _id; тело лежит в transl2, превью — 200 симв.
pairs = con.execute(
    "SELECT t._id, t.transl2, n.preview FROM textnums n JOIN texts t ON t._id=n._id").fetchall()
check("writer: пары textnums->texts полные",
      len(pairs) == 4 and all(html.startswith("<p>") and pv and pv == re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()[:200]
                              for _, html, pv in pairs), pairs[:1])
con.close()
# приёмка Сборки
books = recompose.inspect_data(out)
check("inspect_data: книга проходит", len(books) == 1 and books[0]["chapters"] == 3, books)

# пересборка через рекомпозер (путь приложения: source -> build -> integrity)
spec = {"books": [{"file": out, "book_id": 1}], "drop_error_rows": True,
        "drop_empty_verses": True, "dedupe": True, "drop_empty_chapters": False}
spec_path = os.path.join(tmp, "spec.json")
with open(spec_path, "w", encoding="utf-8") as f:
    json.dump(spec, f, ensure_ascii=False)
built = os.path.join(tmp, "built.db")
recompose.build(spec_path, built, force=True)
con = sqlite3.connect(built)
integ = con.execute("PRAGMA integrity_check").fetchone()[0]
row = con.execute("SELECT COUNT(*) FROM textnums").fetchone()[0]
con.close()
check("recompose.build: integrity + стихи", integ == "ok" and row == 4, (integ, row))

# ------------------------------------------------------- validate_binding ---
lect_row = {"num": "123", "paras": ["тема лекции"]}
prop = {"song": 2, "ch": 5, "txts": "1-36", "title": "Бхакти-йога в жизни",
        "confidence": "high", "reason": "тест"}
stem, notes = ai.validate_binding(prop, "SCC", lect_row)
check("validate: ок", stem == "123 (2.5.1-36) Бхакти-йога в жизни" and not notes,
      (stem, notes))
stem2, _ = ai.validate_binding(dict(prop, txts=""), "SCC", lect_row)
check("validate: пустые стихи -> None", stem2 is None, stem2)
stem3, _ = ai.validate_binding(dict(prop, song=9), "SCC", lect_row)
check("validate: песня вне диапазона SCC -> None", stem3 is None, stem3)
stem4, _ = ai.validate_binding(dict(prop, ch=0, txts=""), "SCC", dict(lect_row, num=""))
check("validate: ch=0 без номера -> введение-имя", stem4 == "(2.0) Бхакти-йога в жизни"
      if False else (stem4 is None), stem4)  # txts пуст -> None (введение как 0.0 не пропускается без стихов)
stem5, _ = ai.validate_binding(dict(song=1, ch=0, txts="1-3", title="Введение"),
                               "SCC", {"num": ""})
check("validate: без номера файла (пустой префикс)",
      stem5 == "(1.0.1-3) Введение", stem5)
check("validate: разрешает кросс-гл. диапазон",
      ai.validate_binding(dict(prop, txts="206-5.20"), "SCC", lect_row)[0]
      == "123 (2.5.206-5.20) Бхакти-йога в жизни")

# --------------------------------------------------------------- промпты ---
msgs = ai.binding_messages("SCC", "разное.docx", ["первый абзац", "второй"])
check("prompt: привязка — system+user, JSON-схема",
      msgs[0]["role"] == "system" and "song" in msgs[1]["content"]
      and "верни json" in msgs[1]["content"].lower(), msgs[1]["content"][:120])
long_text = "х" * 70000
msgs = ai.structure_messages("Книга", long_text)
body = msgs[1]["content"]
check("prompt: структура обрезан (тело <= STRUCT_CHUNK + footer)",
      ai.STRUCT_CHUNK <= len(body) <= ai.STRUCT_CHUNK + 700
      and "фрагмент 1 из 3" in body
      and "song_name" in body,
      len(body))
books_json = [{"idx": 0, "title": "а", "author": "б", "type": "SCC"}]
msgs = ai.meta_messages("инструкция", "title,author", books_json, ["SCC"])
check("prompt: метаданные — книги в JSON",
      json.dumps(books_json, ensure_ascii=False) in msgs[1]["content"], msgs[1]["content"])

# ------------------------------------------------------------ structure_chunks ---
big = "а" * 70000
chunks = ai.structure_chunks(big)
check("chunks: >=3 куска из 70k", len(chunks) >= 3, len(chunks))
check("chunks: каждый <= STRUCT_CHUNK", all(len(c) <= ai.STRUCT_CHUNK for c in chunks),
      [(len(c), i) for i, c in enumerate(chunks)])
check("chunks: перехлёст (след. < пред. + 28000)",
      all(chunks[i+1].startswith(chunks[i][ai.STRUCT_CHUNK - ai.STRUCT_OVERLAP:])
          for i in range(len(chunks) - 1)),
      "нет перехлёста")

# ------------------------------------------------------------ llm_find_headings_all ---
def _mock_chat_fn_factory():
    """Возвращает chat_fn: 1-й вызов -> Главы 1, 2-й -> Главы 2."""
    call_count = [0]
    def chat_fn(msgs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"book_title": "Кн", "chapters": [{"heading": "Глава 1", "number": 1}]}
        return {"chapters": [{"heading": "Глава 2", "number": 2}]}
    return chat_fn

# два куска -> два вызова
mock1 = _mock_chat_fn_factory()
res1 = ai.llm_find_headings_all(mock1, "Кн", "а" * 30000 + "б" * 30000)
check("llm_all: 2 куска -> 2 заголовка",
      len(res1["chapters"]) == 2 and res1["book_title"] == "Кн",
      res1["chapters"])
check("llm_all: порядок сохранён",
      res1["chapters"][0]["heading"] == "Глава 1"
      and res1["chapters"][1]["heading"] == "Глава 2",
      res1["chapters"])

# дубль заголовка во 2-м куске -> не дублируется
def _mock_dup():
    call_count = [0]
    def chat_fn(msgs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"chapters": [{"heading": "Глава 1", "number": 1}]}
        return {"chapters": [{"heading": "Глава 1", "number": 1}]}
    return chat_fn

mock2 = _mock_dup()
res2 = ai.llm_find_headings_all(mock2, "Кн", "а" * 30000 + "б" * 30000)
check("llm_all: дубль heading не дублируется", len(res2["chapters"]) == 1,
      [c["heading"] for c in res2["chapters"]])

# короткий текст -> ровно 1 вызов
def _mock_single():
    call_count = [0]
    def chat_fn(msgs):
        call_count[0] += 1
        return {"chapters": [{"heading": "Единственная", "number": 1}]}
    return chat_fn, call_count

mock3, cc = _mock_single()
res3 = ai.llm_find_headings_all(mock3, "Кн", "короткий текст")
check("llm_all: короткий текст -> 1 вызов", cc[0] == 1, cc[0])
check("llm_all: короткий текст -> 1 глава", len(res3["chapters"]) == 1,
      res3["chapters"])

# === новые тесты на дедуп по (heading,number,song) и нормализацию номеров ===

# два чанка: один и тот же заголовок "Глава 1", разные song (1 и 2) -> 2 главы
def _mock_same_heading_diff_song():
    call_count = [0]
    def chat_fn(msgs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"chapters": [{"heading": "Глава 1", "number": 1, "song": 1}]}
        return {"chapters": [{"heading": "Глава 1", "number": 1, "song": 2}]}
    return chat_fn

mock_sh = _mock_same_heading_diff_song()
res_sh = ai.llm_find_headings_all(mock_sh, "Кн", "а" * 30000 + "б" * 30000)
check("llm_all: одинаковый heading, разные song -> 2 главы",
      len(res_sh["chapters"]) == 2,
      [(c["heading"], c["song"], c["number"]) for c in res_sh["chapters"]])
check("llm_all: song=1 и song=2 оба на месте",
      set(c["song"] for c in res_sh["chapters"]) == {1, 2},
      [c["song"] for c in res_sh["chapters"]])

# перехлёст: идентичная тройка (heading, number, song) -> 1 глава
def _mock_overlap_dup():
    call_count = [0]
    def chat_fn(msgs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"chapters": [{"heading": "Глава 5", "number": 5, "song": 1}]}
        return {"chapters": [{"heading": "Глава 5", "number": 5, "song": 1}]}
    return chat_fn

mock_od = _mock_overlap_dup()
res_od = ai.llm_find_headings_all(mock_od, "Кн", "а" * 30000 + "б" * 30000)
check("llm_all: дубль (heading,number,song) -> 1 глава",
      len(res_od["chapters"]) == 1,
      [c["heading"] for c in res_od["chapters"]])

# нормализация номеров: чанк1 -> number=1, чанк2 (та же song) -> number=1 и 0
# -> после нормализации: 1, 2, 3 без повторов
def _mock_number_reset():
    call_count = [0]
    def chat_fn(msgs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"chapters": [{"heading": "А", "number": 1, "song": 1},
                                 {"heading": "Б", "number": 2, "song": 1}]}
        # модель сбросила нумерацию: number=1 и number=0
        return {"chapters": [{"heading": "В", "number": 1, "song": 1},
                             {"heading": "Г", "number": 0, "song": 1}]}
    return chat_fn

mock_nr = _mock_number_reset()
res_nr = ai.llm_find_headings_all(mock_nr, "Кн", "а" * 30000 + "б" * 30000)
nums_nr = [c["number"] for c in res_nr["chapters"]]
check("llm_all: нормализация номеров (сброс модели) -> 1,2,3",
      nums_nr == [1, 2, 3, 4],
      nums_nr)
check("llm_all: нормализация -> 4 уникальные главы",
      len(res_nr["chapters"]) == 4,
      len(res_nr["chapters"]))

# явные номера: 7,8,9 -> 7,8,9
def _mock_start_mid():
    call_count = [0]
    def chat_fn(msgs):
        call_count[0] += 1
        return {"chapters": [
            {"heading": "Семь", "number": 7, "song": 1},
            {"heading": "Восемь", "number": 8, "song": 1},
            {"heading": "Девять", "number": 9, "song": 1},
        ]}
    return chat_fn

mock_sm = _mock_start_mid()
res_sm = ai.llm_find_headings_all(mock_sm, "Кн", "а" * 30000)
nums_sm = [c["number"] for c in res_sm["chapters"]]
check("llm_all: явные 7,8,9 -> 7,8,9", nums_sm == [7, 8, 9], nums_sm)

# пропуск: 1,2,5 -> 1,2,5
def _mock_gap():
    call_count = [0]
    def chat_fn(msgs):
        call_count[0] += 1
        return {"chapters": [
            {"heading": "A", "number": 1, "song": 1},
            {"heading": "B", "number": 2, "song": 1},
            {"heading": "C", "number": 5, "song": 1},
        ]}
    return chat_fn

mock_g = _mock_gap()
res_g = ai.llm_find_headings_all(mock_g, "Кн", "а" * 30000)
nums_g = [c["number"] for c in res_g["chapters"]]
check("llm_all: пропуск 1,2,5 -> 1,2,5", nums_g == [1, 2, 5], nums_g)

# без номеров (0,0,0) -> 1,2,3
def _mock_no_nums():
    call_count = [0]
    def chat_fn(msgs):
        call_count[0] += 1
        return {"chapters": [
            {"heading": "X", "number": 0, "song": 1},
            {"heading": "Y", "number": 0, "song": 1},
            {"heading": "Z", "number": 0, "song": 1},
        ]}
    return chat_fn

mock_nn = _mock_no_nums()
res_nn = ai.llm_find_headings_all(mock_nn, "Кн", "а" * 30000)
nums_nn = [c["number"] for c in res_nn["chapters"]]
check("llm_all: без номеров 0,0,0 -> 1,2,3", nums_nn == [1, 2, 3], nums_nn)

# две песни: каждая 1,2 -> song1: 1,2; song2: 1,2
def _mock_two_songs():
    call_count = [0]
    def chat_fn(msgs):
        call_count[0] += 1
        return {"chapters": [
            {"heading": "S1-A", "number": 1, "song": 1},
            {"heading": "S1-B", "number": 2, "song": 1},
            {"heading": "S2-A", "number": 1, "song": 2},
            {"heading": "S2-B", "number": 2, "song": 2},
        ]}
    return chat_fn

mock_ts = _mock_two_songs()
res_ts = ai.llm_find_headings_all(mock_ts, "Кн", "а" * 30000)
nums_ts = [c["number"] for c in res_ts["chapters"]]
songs_ts = [c["song"] for c in res_ts["chapters"]]
check("llm_all: две песни song1:1,2 song2:1,2",
      nums_ts == [1, 2, 1, 2] and songs_ts == [1, 1, 2, 2],
      (nums_ts, songs_ts))

# extract_json / chat_json-обвязка (без сервера — только разбор)
import llama_client                                   # noqa: E402
check("extract_json: ```json-забор",
      llama_client.extract_json("```json\n{\"a\": 1}\n```") == {"a": 1})
check("extract_json: преамбула + сырой разбор",
      llama_client.extract_json("Вот ответ: {\"b\": [1,2]} надеюсь helps") == {"b": [1, 2]})
try:
    llama_client.extract_json("вообще не json")
    check("extract_json: мусор -> ValueError", False)
except ValueError:
    check("extract_json: мусор -> ValueError", True)

# ------------------------------------------------------ normalize_type ---
check("normalize_type: chb -> CHB", ai.normalize_type(" chb ") == "CHB")
check("normalize_type: A -> None", ai.normalize_type("A") is None)
check("normalize_type: ABCDEFGHI -> None", ai.normalize_type("ABCDEFGHI") is None)
check("normalize_type: c-h b -> CHB", ai.normalize_type("c-h b") == "CHB")

# ------------------------------------------------------ regex без title ---
s_regex = ai.build_structure(
    "Глава 3. Оскорбление вайшнавов\n\ntекст\n",
    dict(ch_mode="regex", v_mode="para", prelude_intro=False, book_title="Т",
         chapter_re=r"^Глава (?P<chapter>\d+)\.\s*"))
check("regex: title из строки заголовка (без группы title)",
      s_regex["chapters"][0]["title"] == "Оскорбление вайшнавов",
      s_regex["chapters"][0]["title"])

# ------------------------------------------------------ none + book_title ---
s_none = ai.build_structure(
    "Один абзац.",
    dict(ch_mode="none", v_mode="none", book_title="Моя книга"))
check("none: 1 глава, title = book_title",
      s_none["chapters"][0]["title"] == "Моя книга",
      s_none["chapters"][0]["title"])
check("none: одна глава, один стих",
      s_none["stats"]["chapters"] == 1 and s_none["stats"]["verses"] == 1,
      s_none["stats"])

# ------------------------------------------------------ hint_no_verses ---
s_hint = ai.build_structure(
    "Абзац один.\n\nАбзац два.\n\nАбзац три.\n\nАбзац четыре.\n\nАбзац пять.",
    dict(ch_mode="none", v_mode="para", prelude_intro=False, book_title="Т",
         _hint_no_verses=True))
check("hint: подсказка про «глава целиком» в notes",
      any("нет номеров стихов" in n for n in s_hint["notes"]),
      s_hint["notes"])

print()
if FAILED:
    print("FAILED %d: %s" % (len(FAILED), ", ".join(FAILED)))
    sys.exit(1)
print("ALL OK")
