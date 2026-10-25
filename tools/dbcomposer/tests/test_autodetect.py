# -*- coding: utf-8 -*-
"""Тесты модуля autodetect: главы, названия, стихи, СОДЕРЖАНИЕ, regex из выделения,
нормализация, построчный детект."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_import as _ai  # noqa: E402
from autodetect import (  # noqa: E402
    autodetect,
    detect_headings,
    detect_headings_lines,
    detect_verses,
    detect_verses_lines,
    normalize_lines,
    regex_from_sample,
    strip_toc,
    strip_toc_lines,
)

FAILED = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (("  | " + str(extra)) if not cond else ""))
    if not cond:
        FAILED.append(name)


# ============================================================ strip_toc
toc_text = "Глава первая\nтекст гл1\n\nГлава вторая\nтекст гл2\n\nСОДЕРЖАНИЕ\nГл. 1 ...\nГл. 2 ...\n"
paras = _ai.text_to_paragraphs(toc_text)
cleaned, removed, note = strip_toc(paras)
check("strip_toc: обнаружил СОДЕРЖАНИЕ", removed > 0, removed)
check("strip_toc: заметка содержит СОДЕРЖАНИЕ", "СОДЕРЖАНИЕ" in note, note)
clean_text = "\n".join(cleaned)
check("strip_toc: СОДЕРЖАНИЕ не в очищенном", "СОДЕРЖАНИЕ" not in clean_text, clean_text)

# без СОДЕРЖАНИЕ
no_toc_text = "Глава первая\nтекст\n\nГлава вторая\nтекст\n"
paras2 = _ai.text_to_paragraphs(no_toc_text)
cleaned2, removed2, note2 = strip_toc(paras2)
check("strip_toc: без СОДЕРЖАНИЕ — 0 удалений", removed2 == 0, removed2)
check("strip_toc: без СОДЕРЖАНИЕ — note пуст", note2 == "", note2)


# ============================================================ detect_headings
# Текст с "Глава первая" / "Глава вторая"
heading_text = (
    "Глава первая\n"
    "Краткое изложение\n"
    "текст главы 1.\n"
    "\n"
    "Глава вторая\n"
    "Явление Кришны\n"
    "текст главы 2.\n"
    "\n"
    "Глава третья\n"
    "Слава Господа\n"
    "текст главы 3.\n"
)
paras_h = _ai.text_to_paragraphs(heading_text)
profile = detect_headings(paras_h)
check("detect_headings: нашёл профиль", profile is not None, profile)
if profile:
    check("detect_headings: >= 3 глав", profile["count"] >= 3, profile["count"])
    check("detect_headings: title_mode = next", profile["title_mode"] == "next", profile["title_mode"])
    check("detect_headings: confidence > 0", profile["confidence"] > 0, profile["confidence"])
    check("detect_headings: regex содержит chapter", "chapter" in profile["regex"], profile["regex"])


# ============================================================ detect_verses — стихов нет
v_text = (
    "Глава первая\n"
    "Краткое изложение\n"
    "текст главы 1.\n"
    "\n"
    "Глава вторая\n"
    "Явление Кришны\n"
    "текст главы 2.\n"
)
paras_v = _ai.text_to_paragraphs(v_text)
profile_v = detect_headings(paras_v)
if profile_v:
    verse_info = detect_verses(v_text, profile_v)
    check("detect_verses: v_mode = none (без нумерованных стихов)",
          verse_info["v_mode"] == "none", verse_info["v_mode"])


# ============================================================ detect_verses — с нумерованными стихами
verse_text = (
    "Глава первая\n"
    "1. Стих первый текст\n"
    "продолжение\n"
    "2. Стих второй текст\n"
    "продолжение\n"
    "3. Стих третий текст\n"
    "\n"
    "Глава вторая\n"
    "1. Стих первый текст главы 2\n"
    "продолжение\n"
    "2. Стих второй текст главы 2\n"
    "продолжение\n"
    "3. Стих третий текст главы 2\n"
)
paras_v2 = _ai.text_to_paragraphs(verse_text)
profile_v2 = detect_headings(paras_v2)
if profile_v2:
    verse_info2 = detect_verses(verse_text, profile_v2)
    check("detect_verses: v_mode = number (с нумерованными стихами)",
          verse_info2["v_mode"] == "number", verse_info2["v_mode"])
    check("detect_verses: verse_re содержит verse",
          "verse" in verse_info2["verse_re"], verse_info2["verse_re"])
    # проверить что regex матчит
    if verse_info2["verse_re"]:
        m = re.match(verse_info2["verse_re"], "1. Стих первый текст")
        check("detect_verses: verse_re матчит пример", m is not None, m)


# ============================================================ autodetect — полный цикл
full_text = (
    "Глава первая\n"
    "Краткое изложение\n"
    "текст главы 1.\n"
    "\n"
    "Глава вторая\n"
    "Явление Кришны\n"
    "текст главы 2.\n"
    "\n"
    "Глава третья\n"
    "Слава Господа\n"
    "текст главы 3.\n"
    "\n"
    "СОДЕРЖАНИЕ\n"
    "Гл. 1 ...\n"
    "Гл. 2 ...\n"
)
opts, report, normalized_text = autodetect(full_text)
check("autodetect: ch_mode = regex", opts["ch_mode"] == "regex", opts["ch_mode"])
check("autodetect: chapter_re не пуст", bool(opts["chapter_re"]), opts["chapter_re"])
check("autodetect: v_mode = none", opts["v_mode"] == "none", opts["v_mode"])
check("autodetect: report содержит СОДЕРЖАНИЕ",
      any("СОДЕРЖАНИЕ" in r for r in report), report)
check("autodetect: report содержит уверенность",
      any("уверенность" in r for r in report), report)
check("autodetect: report содержит кол-во глав",
      any("глав:" in r for r in report), report)
# нормализация: пустые строки вокруг заголовков
check("autodetect: normalized_text не пуст", bool(normalized_text), normalized_text)


# ============================================================ regex_from_sample
sample = "Глава 3. Оскорбление вайшнавов"
regex = regex_from_sample(sample)
check("regex_from_sample: содержит (?P<chapter>\\d+)",
      "(?P<chapter>\\d+)" in regex, regex)
check("regex_from_sample: содержит (?P<title>.*)",
      "(?P<title>.*)" in regex, regex)
# проверить матчинг
m = re.match(regex, sample)
check("regex_from_sample: матчит оригинал", m is not None, m)
if m:
    check("regex_from_sample: chapter = 3", m.group("chapter") == "3", m.group("chapter"))
    check("regex_from_sample: title = Оскорбление вайшнавов",
          m.group("title") == "Оскорбление вайшнавов", m.group("title"))


# ============================================================ regex_from_sample — порядковое слово
sample2 = "Глава первая. Введение"
regex2 = regex_from_sample(sample2)
check("regex_from_sample: порядковое слово — содержит (?P<chapter>[а-яё]+)",
      "(?P<chapter>[а-яё]+)" in regex2, regex2)
check("regex_from_sample: содержит (?P<title>.*)",
      "(?P<title>.*)" in regex2, regex2)
m2 = re.match(regex2, sample2)
check("regex_from_sample: порядковое слово — матчит", m2 is not None, m2)
if m2:
    check("regex_from_sample: порядковое слово — chapter", m2.group("chapter"), m2.group("chapter"))


# ============================================================ autodetect — пустой текст
opts_empty, report_empty, norm_empty = autodetect("")
check("autodetect: пустой текст -> ch_mode = none",
      opts_empty["ch_mode"] == "none", opts_empty["ch_mode"])


# ============================================================ Нормализация: пустые строки вокруг заголовков
norm_text = (
    "Глава первая\n"
    "Краткое изложение\n"
    "текст главы 1.\n"
    "\n"
    "Глава вторая\n"
    "Явление Кришны\n"
    "текст главы 2.\n"
)
opts_n, report_n, normalized_n = autodetect(norm_text)
check("normalize: пустая строка после 'Глава первая'",
      "Глава первая\n\n" in normalized_n, normalized_n)
check("normalize: пустая строка после 'Глава вторая'",
      "Глава вторая\n\n" in normalized_n, normalized_n)
check("normalize: пустая строка перед 'Глава вторая'",
      "\n\nГлава вторая" in normalized_n, normalized_n)


# ============================================================ Построчный детект: 2 главы
line_text = (
    "Глава первая\n"
    "Название\n"
    "текст\n"
    "Глава вторая\n"
    "Название2\n"
    "текст2\n"
    "Глава третья\n"
    "Название3\n"
    "текст3\n"
)
opts_l, report_l, norm_l = autodetect(line_text)
check("line_detect: 3 главы",
      any("глав: 3" in r for r in report_l), report_l)
check("line_detect: ch_mode = regex",
      opts_l["ch_mode"] == "regex", opts_l["ch_mode"])


# ============================================================ Ложные номера страниц НЕ считаются стихами
fake_pages = "\n".join(str(i) for i in range(1, 21))
opts_f, report_f, norm_f = autodetect(fake_pages)
check("fake_pages: v_mode = none (числа страниц ≠ стихи)",
      opts_f["v_mode"] == "none", opts_f["v_mode"])


# ============================================================ strip_toc_lines: вторая половина текста
half_text = (
    "Глава первая\n"
    "текст гл1\n"
    "Глава вторая\n"
    "текст гл2\n"
    "СОДЕРЖАНИЕ\n"
    "Гл. 1 ...\n"
    "Гл. 2 ...\n"
    "Гл. 3 ...\n"
)
lines = [l.strip() for l in half_text.replace("\r\n", "\n").split("\n")]
cleaned_l, removed_l, note_l = strip_toc_lines(lines)
check("strip_toc_lines: обнаружил СОДЕРЖАНИЕ", removed_l > 0, removed_l)
check("strip_toc_lines: заметка содержит СОДЕРЖАНИЕ", "СОДЕРЖАНИЕ" in note_l, note_l)


# ============================================================ detect_headings_lines: порядковые слова
ordinal_text = (
    "Глава первая. Введение\n"
    "текст\n"
    "Глава вторая. Оглавление\n"
    "текст\n"
    "Глава третья. Заключительная\n"
    "текст\n"
)
lines_o = [l.strip() for l in ordinal_text.replace("\r\n", "\n").split("\n")]
profile_o = detect_headings_lines(lines_o)
check("ordinal: нашёл профиль", profile_o is not None, profile_o)
if profile_o:
    check("ordinal: >= 3 глав", profile_o["count"] >= 3, profile_o["count"])
    check("ordinal: номера монотонны", profile_o["numbers"] == [1, 2, 3], profile_o["numbers"])
    check("ordinal: title_mode = same (заголовки содержат title)", profile_o["title_mode"] == "same", profile_o["title_mode"])


# ============================================================ summary
print()
if FAILED:
    print("FAILED %d: %s" % (len(FAILED), ", ".join(FAILED)))
    sys.exit(1)
print("ALL OK")
