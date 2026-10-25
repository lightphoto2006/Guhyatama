# -*- coding: utf-8 -*-
"""Автоопределение структуры книги: главы, названия, стихи, СОДЕРЖАНИЕ.

Без ручных настроек — один вызов autodetect(text) → opts + report.
"""
import sys
import re
import statistics

import ai_import as _ai

# ============================================================ strip_toc
TOC_RE = re.compile(r"^(?:СОДЕРЖАНИЕ|ОГЛАВЛЕНИЕ)$", re.I)
TOC_LINE_RE = re.compile(r"\d+[.)\s]*\s*\.\.\.\s*$")


def strip_toc(paras):
    """Найти блок «СОДЕРЖАНИЕ»/«ОГЛАВЛЕНИЕ» и удалить его.

    Ищем параграф, чья первая строка == «СОДЕРЖАНИЕ» или «ОГЛАВЛЕНИЕ».
    Если в следующих 5 строках есть строки с многоточиями/точками и цифрами
    на конце ИЛИ их больше 3 — удаляем этот параграф и всё после него.
    Также проверяем содержимое самого параграфа (строки после первой).

    Returns: (new_paras, removed_count, note).
    """
    toc_idx = None
    for i in range(len(paras)):
        first = _ai._first_line(paras[i]).lower()
        if first in ("содержание", "оглавление"):
            # проверяем следующие 5 параграфов
            tail = paras[i + 1: i + 6]
            has_toc_pattern = any(TOC_LINE_RE.search(t.strip()) for t in tail if t.strip())
            # также проверяем строки внутри самого параграфа (после первой строки)
            inner_lines = paras[i].split("\n")[1:]
            has_inner_pattern = any(TOC_LINE_RE.search(l.strip()) for l in inner_lines if l.strip())
            if has_toc_pattern or has_inner_pattern or len(tail) > 3:
                toc_idx = i
                break
    if toc_idx is not None:
        removed = len(paras) - toc_idx
        note = "СОДЕРЖАНИЕ отрезано: %d строк" % removed
        return paras[:toc_idx], removed, note
    return paras, 0, ""


# ============================================================ detect_headings
ROMAN_RE = re.compile(r"^[IVXLCDM]+$")


def _num(v):
    """Перечисляем ту же логику, что в ai_import._num."""
    v = (v or "").strip().lower()
    if v in _ai.RU_ORDINALS:
        return _ai.RU_ORDINALS[v]
    if ROMAN_RE.match(v):
        n = _ai._roman_to_int(v)
        if n:
            return n
    try:
        return int(v)
    except ValueError:
        return None


def _detect_verses_in_text(text, chapter_paras):
    """Вспомогательная: проверить, есть ли в тексте нумерованные стихи."""
    verse_patterns = [
        re.compile(r"^\s*(?P<verse>\d{1,4})\s*[.)]\s*(?P<rest>.*)$"),
        re.compile(r"^\s*(?:ТЕКСТ|Текст|TEXT|Text)\s*(?P<verse>\d{1,4})\b"),
        re.compile(r"^\s*(?P<verse>\d{1,4})\s*$"),
    ]
    found_chapters = 0
    best_pattern = None
    best_count = 0
    best_re_str = ""

    for vp in verse_patterns:
        chapter_matches = 0
        for para in chapter_paras:
            for line in para.split("\n"):
                m = vp.match(line)
                if m:
                    chapter_matches += 1
                    break
        if chapter_matches >= 2:
            # проверяем монотонность номеров
            nums = []
            for para in chapter_paras:
                for line in para.split("\n"):
                    m = vp.match(line)
                    if m:
                        try:
                            nums.append(int(m.group("verse")))
                        except ValueError:
                            pass
                        break
            if len(nums) >= 3 and all(nums[i] < nums[i + 1] for i in range(len(nums) - 1)):
                if chapter_matches > best_count:
                    best_count = chapter_matches
                    best_pattern = vp
                    best_re_str = vp.pattern
                    found_chapters = chapter_matches

    if best_pattern and found_chapters >= 3:
        return {
            "v_mode": "number",
            "verse_re": best_re_str,
            "confidence": min(1.0, 0.5 + found_chapters * 0.05),
        }
    return {
        "v_mode": "none",
        "verse_re": "",
        "confidence": 0.3,
    }


def detect_headings(paras):
    """Перебрать шаблоны глав, выбрать лучший профиль.

    Шаблоны: ai_import.PRESET_CHAPTER_RES + дополнительный r"^(?P<chapter>\\d{1,3})\\s*$".

    Returns: dict с ключами regex/title_mode/count/numbers/samples/confidence
    или None.
    """
    extra_pat = r"^(?P<chapter>\d{1,3})\s*$"
    all_patterns = list(_ai.PRESET_CHAPTER_RES) + [extra_pat]

    best = None
    best_score = -1

    for pattern in all_patterns:
        # собрать индексы совпавших абзацев
        matched_indices = []
        matched_titles = []
        matched_numbers = []
        for i, p in enumerate(paras):
            line = _ai._first_line(p)
            m = re.match(pattern, line)
            if m:
                matched_indices.append(i)
                g = m.groupdict()
                matched_titles.append(g.get("title", ""))
                matched_numbers.append(_num(g.get("chapter") or ""))

        # отбросить < 3 совпадений
        if len(matched_indices) < 3:
            continue

        # посчитать номера: если >20% не извлекаются — отбросить
        valid_nums = [n for n in matched_numbers if n is not None]
        fail_rate = (len(matched_numbers) - len(valid_nums)) / len(matched_numbers)
        if fail_rate > 0.2:
            continue

        # равномерность: gaps между индексами
        gaps = [matched_indices[i + 1] - matched_indices[i]
                for i in range(len(matched_indices) - 1)]
        if gaps:
            mean_gap = statistics.mean(gaps)
            std_gap = statistics.stdev(gaps) if len(gaps) > 1 else 0.0
            uniformity_score = 1.0 - min(1.0, std_gap / (mean_gap + 0.001))
        else:
            uniformity_score = 1.0

        # монотонность номеров
        monotonically_increasing = all(
            valid_nums[i] < valid_nums[i + 1] for i in range(len(valid_nums) - 1)
        ) if len(valid_nums) >= 2 else True

        count = len(matched_indices)
        score = 0.5 * uniformity_score + 0.3 * min(1.0, count / 10) + (0.2 if monotonically_increasing else 0)

        # title_mode
        # Если у ≥70% совпадений группа title пустая/«Глава»/«Глава N» →
        # проверить следующую строку: если у ≥70% она короче 120 символов → "next"
        short_titles = sum(1 for t in matched_titles if not t or re.match(r"^(глава|chapter|раздел|section)\s*", t, re.I))
        if short_titles / count >= 0.7:
            next_lines = []
            for idx in matched_indices:
                if idx + 1 < len(paras):
                    next_lines.append(_ai._first_line(paras[idx + 1]))
                else:
                    next_lines.append("")
            short_next = sum(1 for nl in next_lines if len(nl) < 120)
            title_mode = "next" if short_next / len(next_lines) >= 0.7 else "same"
        else:
            title_mode = "same"

        if score > best_score:
            best_score = score
            best = {
                "regex": pattern,
                "title_mode": title_mode,
                "count": count,
                "numbers": valid_nums,
                "samples": [_ai._first_line(paras[idx]) for idx in matched_indices[:3]],
                "confidence": round(min(1.0, score), 2),
            }

    return best


# ============================================================ detect_verses
def detect_verses(text, chapter_profile):
    """Для глав, определённых chapter_profile, проверить наличие стихов.

    Returns: dict с v_mode/verse_re/confidence.
    """
    if not chapter_profile:
        return {"v_mode": "none", "verse_re": "", "confidence": 0.3}

    paras = _ai.text_to_paragraphs(text)
    chapter_indices = []
    pattern = chapter_profile["regex"]
    for i, p in enumerate(paras):
        if re.match(pattern, _ai._first_line(p)):
            chapter_indices.append(i)

    if not chapter_indices:
        return {"v_mode": "none", "verse_re": "", "confidence": 0.3}

    # берём 2-3 главы
    sample_chapters = chapter_indices[: min(3, len(chapter_indices))]
    chapter_paras_list = []
    for ci in sample_chapters:
        # тело главы = от след. строки до след. заголовка
        end = chapter_indices[chapter_indices.index(ci) + 1] if chapter_indices.index(ci) + 1 < len(chapter_indices) else len(paras)
        body = [paras[j] for j in range(ci + 1, end)
                if not re.match(pattern, _ai._first_line(paras[j]))]
        if body:
            chapter_paras_list.append(body)

    if not chapter_paras_list:
        return {"v_mode": "none", "verse_re": "", "confidence": 0.3}

    # flatten: список списков -> плоский список абзацев
    flat_paras = [p for chapter in chapter_paras_list for p in chapter]
    return _detect_verses_in_text(text, flat_paras)


# ============================================================ regex_from_sample
def regex_from_sample(line):
    """Сгенерировать regex из одной строки-примера заголовка.

    Экранирует текст, заменяет первую группу цифр на (?P<chapter>\\d+),
    если цифр нет, но есть русское порядковое слово — на (?P<chapter>[а-яё]+),
    остаток строки — (?P<title>.*)
    """
    digit_match = re.search(r"\d+", line)
    if digit_match:
        # экранируем до цифр, вставляем группу, остаток = title
        before = re.escape(line[:digit_match.start()])
        return r"^%s(?P<chapter>\d+)\s*[.:—–-]?\s*(?P<title>.*)$" % before
    # ищем русское порядковое слово
    for word, _ in _ai.RU_ORDINALS.items():
        if word in line.lower():
            idx = line.lower().index(word)
            before = re.escape(line[:idx])
            return r"^%s(?P<chapter>[а-яё]+)\s*[.:—–-]?\s*(?P<title>.*)$" % before
    # fallback: весь текст как chapter, остаток title
    return r"^%s(?P<chapter>.+)(?P<title>.*)$" % re.escape(line)


# ============================================================ autodetect (entry point)
def autodetect(text):
    """Главный интерфейс: текст → (opts, report).

    opts = {
        "ch_mode": "regex",
        "chapter_re": str,
        "v_mode": "number"|"none",
        "verse_re": str,
    }
    report = [str, ...] — строки отчёта.
    """
    paras = _ai.text_to_paragraphs(text)
    if not paras:
        return {"ch_mode": "none", "chapter_re": "", "v_mode": "none", "verse_re": ""}, ["пустой текст"]

    # 1) strip_toc
    cleaned, toc_removed, toc_note = strip_toc(paras)
    if toc_removed:
        paras = cleaned

    # 2) detect_headings
    profile = detect_headings(paras)
    if profile is None:
        report = ["главы не найдены ни одним шаблоном"]
        if toc_note:
            report.append(toc_note)
        report.append("уверенность: 0")
        return {
            "ch_mode": "none",
            "chapter_re": "",
            "v_mode": "none",
            "verse_re": "",
        }, report

    # 3) detect_verses
    verse_info = detect_verses(text, profile)

    # 4) собрать report
    report = []
    report.append("глав: %d (%s)" % (profile["count"],
                                   profile["samples"][0] if profile["samples"] else "—"))
    mode_labels = {"same": "название в той же строке", "next": "название: следующая строка"}
    report.append("название: %s" % mode_labels.get(profile["title_mode"], profile["title_mode"]))
    if verse_info["v_mode"] == "number":
        report.append("стихи: нумерованные (regex: %s)" % verse_info["verse_re"])
    else:
        report.append("стихов не найдено — глава целиком")
    if toc_note:
        report.append(toc_note)
    report.append("уверенность: %.2f" % profile["confidence"])

    opts = {
        "ch_mode": "regex",
        "chapter_re": profile["regex"],
        "v_mode": verse_info["v_mode"],
        "verse_re": verse_info["verse_re"],
    }
    return opts, report
