# -*- coding: utf-8 -*-
"""Автоопределение структуры книги: главы, названия, стихи, СОДЕРЖАНИЕ.

Работает по ЛИНИЯМ (не по абзацам), чтобы корректно обрабатывать PDF-текст,
где строки идут без пустых строк между ними.

Один вызов autodetect(text) → (opts, report, normalized_text).

Для обратной совместимости сохранены старые функции (strip_toc, detect_headings,
detect_verses), которые работают с абзацами через text_to_paragraphs.
"""
import sys
import re
import statistics

import ai_import as _ai

# ============================================================ strip_toc_lines
TOC_RE = re.compile(r"^(?:СОДЕРЖАНИЕ|ОГЛАВЛЕНИЕ)$", re.I)
TOC_LINE_RE = re.compile(r"\d+[.)\s]*\s*\.\.\.\s*$")


def strip_toc_lines(lines):
    """Найти строку «СОДЕРЖАНИЕ»/«ОГЛАВЛЕНИЕ» и обрезать всё от неё.

    Ищем строку, равную «СОДЕРЖАНИЕ» или «ОГЛАВЛЕНИЕ» (upper).
    Если после неё ≥3 строк с точками и цифрами (или это вторая половина текста) —
    удаляем этот блок.

    Returns: (new_lines, removed_count, note).
    """
    toc_idx = None
    for i in range(len(lines)):
        if TOC_RE.match(lines[i]):
            # проверяем следующие строки на паттерн «Гл. 1 ...»
            tail = lines[i + 1: i + 6]
            has_toc_pattern = any(
                TOC_LINE_RE.search(t.strip()) for t in tail if t.strip()
            )
            # ищем паттерн внутри следующих строк
            if has_toc_pattern or len(tail) > 3:
                toc_idx = i
                break
            # если нет паттерна, но это вторая половина текста — тоже обрежем
            if i > len(lines) // 2:
                toc_idx = i
                break
    if toc_idx is not None:
        removed = len(lines) - toc_idx
        note = "СОДЕРЖАНИЕ отрезано: %d строк" % removed
        return lines[:toc_idx], removed, note
    return lines, 0, ""


# ============================================================ detect_headings_lines
ROMAN_RE = re.compile(r"^[IVXLCDM]+$")

# Дополнительный шаблон: «Глава первая. Название»
HEADINGS_ORDINAL_RE = re.compile(
    r"^(?:Глава|ГЛАВА|Chapter|CHAPTER)\s+(?P<chapter>[а-яё]+)\s*[.:—–-]?\s*(?P<title>.*)$",
    re.I,
)


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


def detect_headings_lines(lines):
    """Перебор шаблонов по ЛИНИЯМ, выбор лучшего профиля.

    Шаблоны: ai_import.PRESET_CHAPTER_RES + r"^\\d{1,3}\\s*$" + свой шаблон
    для порядковых слов (Глава первая. Название).

    Returns: dict с ключами regex/title_mode/count/numbers/samples/confidence
    или None.
    """
    # Все шаблоны
    all_patterns = list(_ai.PRESET_CHAPTER_RES)
    # шаблон для порядковых слов
    all_patterns.append(HEADINGS_ORDINAL_RE.pattern)
    # шаблон для числа отдельной строкой
    all_patterns.append(r"^\d{1,3}\s*$")

    best = None
    best_score = -1

    for pattern in all_patterns:
        matched_indices = []
        matched_titles = []
        matched_numbers = []
        for i, line in enumerate(lines):
            m = re.match(pattern, line)
            if m:
                matched_indices.append(i)
                g = m.groupdict()
                matched_titles.append(g.get("title", "") if g else "")
                chapter_raw = g.get("chapter", "") if g else ""
                # для порядковых слов — конвертируем через rus_ordinal_to_int
                if chapter_raw:
                    # пробуем сначала _num (работает для чисел и RU_ORDINALS)
                    n = _num(chapter_raw)
                    if n is None:
                        # пробуем rus_ordinal_to_int
                        n = _ai.rus_ordinal_to_int(chapter_raw.lower())
                    matched_numbers.append(n)
                else:
                    matched_numbers.append(None)

        if len(matched_indices) < 2:
            continue

        # отбросить < 3 совпадений
        valid_nums = [n for n in matched_numbers if n is not None]
        if not valid_nums:
            continue
        fail_rate = (len(matched_numbers) - len(valid_nums)) / len(matched_numbers)
        if fail_rate > 0.2:
            continue

        # равномерность: gaps между ИНДЕКСАМИ СТРОК
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

        # title_mode: если title пуст/«Глава»/«Глава N» у ≥70% — проверить следующую строку
        short_titles = sum(
            1 for t in matched_titles
            if not t or re.match(r"^(глава|chapter|раздел|section)\s*", t, re.I)
        )
        if count > 0 and short_titles / count >= 0.7:
            next_lines = []
            for idx in matched_indices:
                if idx + 1 < len(lines):
                    next_lines.append(lines[idx + 1])
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
                "samples": [lines[idx] for idx in matched_indices[:3]],
                "confidence": round(min(1.0, score), 2),
            }

    return best


# ============================================================ detect_verses_lines
VERSE_PATTERNS = [
    re.compile(r"^\s*(?P<verse>\d{1,4})\s*[.)]\s*(?P<rest>.*)$"),
    re.compile(r"^\s*(?:ТЕКСТ|Текст|TEXT|Text)\s*(?P<verse>\d{1,4})\b"),
    re.compile(r"^\s*(?P<verse>\d{1,4})\s*$"),
]


def detect_verses_lines(lines, heading_indices):
    """Строгий детект стихов по ЛИНИЯМ.

    Для каждой главы (между заголовками) собираем совпадения по шаблонам.
    Для шаблона «число отдельной строкой» дополнительно требуем:
      - следующая строка — текст длиной ≥ 20 символов
      - предыдущая строка — НЕ число

    Глава «проходит», если ≥5 совпадений, первый номер == 1 и ≥80% шагов +1.
    Стихи считаем найденными только если прошли ≥2 главы.

    Returns: dict {v_mode, verse_re, confidence, reason}.
    """
    if not heading_indices or len(heading_indices) < 2:
        return {"v_mode": "none", "verse_re": "", "confidence": 0.3,
                "reason": "мало заголовков"}

    best_pattern = None
    best_count = 0
    best_re_str = ""
    chapters_passed = 0

    for vp in VERSE_PATTERNS:
        chapter_matches = 0
        passed_chapters = 0

        for ci in range(len(heading_indices)):
            start = heading_indices[ci] + 1
            end = heading_indices[ci + 1] if ci + 1 < len(heading_indices) else len(lines)
            chapter_lines = lines[start:end]

            matches = []
            for li, cl in enumerate(chapter_lines):
                m = vp.match(cl)
                if m:
                    # Для шаблона «число отдельной строкой» — доп. проверка
                    if vp == VERSE_PATTERNS[2]:  # ^\s*(?P<verse>\d{1,4})\s*$
                        prev_ok = True
                        next_ok = True
                        if li > 0:
                            prev_line = chapter_lines[li - 1]
                            if re.match(r"^\s*\d+\s*$", prev_line):
                                prev_ok = False
                        if li + 1 < len(chapter_lines):
                            next_line = chapter_lines[li + 1]
                            if len(next_line) < 20:
                                next_ok = False
                        if not (prev_ok and next_ok):
                            continue
                    matches.append(m)

            if not matches:
                continue

            # проверяем: ≥3 совпадений, первый номер == 1, ≥80% шагов +1
            nums = []
            for m in matches:
                try:
                    nums.append(int(m.group("verse")))
                except ValueError:
                    continue

            if len(nums) < 3:
                continue
            if nums[0] != 1:
                continue
            # ≥80% шагов +1
            steps = sum(1 for i in range(len(nums) - 1) if nums[i + 1] == nums[i] + 1)
            if steps / (len(nums) - 1) < 0.8:
                continue

            chapter_matches += len(matches)
            passed_chapters += 1

        if passed_chapters >= 2 and chapter_matches > best_count:
            best_count = chapter_matches
            best_pattern = vp
            best_re_str = vp.pattern
            chapters_passed = passed_chapters

    if best_pattern and chapters_passed >= 2:
        return {
            "v_mode": "number",
            "verse_re": best_re_str,
            "confidence": min(1.0, 0.5 + chapters_passed * 0.15),
            "reason": "найдено стихов в %d главах" % chapters_passed,
        }
    return {
        "v_mode": "none",
        "verse_re": "",
        "confidence": 0.3,
        "reason": "стихи не найдены (нужны ≥2 главы с нумерацией 1..N)",
    }


# ============================================================ normalize_lines
def normalize_lines(lines, profile, verse_info):
    """Возвращать НОВЫЙ текст с пустыми строками так, чтобы заработал
    существующий конвейер (text_to_paragraphs режет по пустым строкам).

    - перед и после каждой строки-заголовка вставлять пустую строку;
    - если v_mode="number", перед каждой строкой-номером стиха вставлять пустую строку;
    - остальные строки подряд склеивать через "\n" (глава целиком останется одним абзацем).
    """
    out_lines = []
    heading_set = set(profile.get("heading_indices", [])) if profile else set()
    verse_re = None
    if verse_info.get("v_mode") == "number":
        try:
            verse_re = re.compile(verse_info["verse_re"])
        except re.error:
            verse_re = None

    i = 0
    while i < len(lines):
        line = lines[i]
        if i in heading_set:
            # пустая строка перед заголовком
            out_lines.append("")
            out_lines.append(line)
            # пустая строка после заголовка
            out_lines.append("")
            i += 1
        elif verse_re and verse_re.match(line):
            # пустая строка перед номером стиха
            out_lines.append("")
            out_lines.append(line)
            i += 1
        else:
            # склеиваем в один блок до следующего заголовка/стиха/пустой строки
            block = []
            while i < len(lines):
                if i in heading_set:
                    break
                if verse_re and verse_re.match(lines[i]):
                    break
                if lines[i] == "":
                    i += 1  # пропустить пустую строку
                    break
                block.append(lines[i])
                i += 1
            if block:
                out_lines.append("\n".join(block))
            # пустая строка после блока
            out_lines.append("")

    # убираем лишние пустые строки в начале/конце,
    # но сохраняем ведущую пустую строку если первый элемент — заголовок
    if out_lines and out_lines[0] == "":
        # если за строкой идёт заголовок — оставляем пустую строку
        if len(out_lines) > 1 and out_lines[1] not in heading_set and (not verse_re or not verse_re.match(out_lines[1])):
            out_lines.pop(0)
    while out_lines and out_lines[-1] == "":
        out_lines.pop()

    return "\n".join(out_lines)


# ============================================================ autodetect (entry point)
def autodetect(text):
    """Главный интерфейс: текст → (opts, report, normalized_text).

    opts = {
        "ch_mode": "regex",
        "chapter_re": str,
        "v_mode": "number"|"none",
        "verse_re": str,
    }
    report = [str, ...] — строки отчёта.
    normalized_text — текст с пустыми строками вокруг заголовков/стихов.
    """
    if not text or not text.strip():
        return (
            {"ch_mode": "none", "chapter_re": "", "v_mode": "none", "verse_re": ""},
            ["пустой текст"],
            "",
        )

    # 1) Работаем по ЛИНИЯМ
    lines = [l.strip() for l in text.replace("\r\n", "\n").split("\n")]

    # 2) strip_toc_lines
    cleaned, toc_removed, toc_note = strip_toc_lines(lines)
    if toc_removed:
        lines = cleaned

    # 3) detect_headings_lines
    profile = detect_headings_lines(lines)
    if profile is None:
        report = ["главы не найдены ни одним шаблоном"]
        if toc_note:
            report.append(toc_note)
        report.append("уверенность: 0")
        return (
            {"ch_mode": "none", "chapter_re": "", "v_mode": "none", "verse_re": ""},
            report,
            text,
        )

    # 4) detect_verses_lines
    heading_indices = []
    pattern = profile["regex"]
    for i, line in enumerate(lines):
        if re.match(pattern, line):
            heading_indices.append(i)
    profile["heading_indices"] = heading_indices

    verse_info = detect_verses_lines(lines, heading_indices)

    # 5) normalize_lines
    normalized_text = normalize_lines(lines, profile, verse_info)

    # 6) собрать report
    report = []
    report.append("глав: %d (%s)" % (profile["count"],
                                   profile["samples"][0] if profile["samples"] else "—"))
    mode_labels = {"same": "название в той же строке", "next": "название: следующая строка"}
    report.append("название: %s" % mode_labels.get(profile["title_mode"], profile["title_mode"]))
    if verse_info["v_mode"] == "number":
        report.append("стихи: нумерованные (regex: %s)" % verse_info["verse_re"])
    else:
        report.append("стихов не найдено — %s" % verse_info.get("reason", "глава целиком"))
    if toc_note:
        report.append(toc_note)
    report.append("уверенность: %.2f" % profile["confidence"])

    opts = {
        "ch_mode": "regex",
        "chapter_re": profile["regex"],
        "v_mode": verse_info["v_mode"],
        "verse_re": verse_info["verse_re"],
    }
    return opts, report, normalized_text


# ============================================================ Backward-compat wrappers (paragraph-based API)
# Старые функции, которые используют text_to_paragraphs, оставлены для
# обратной совместимости с существующими тестами.


def strip_toc(paras):
    """Обёртка: абзацы → строки → strip_toc_lines → абзацы."""
    raw_text = "\n\n".join(paras)
    lines = [l for l in raw_text.split("\n")]
    cleaned, removed, note = strip_toc_lines(lines)
    # reconstruct paragraphs from cleaned lines
    cleaned_text = "\n".join(cleaned)
    cleaned_paras = _ai.text_to_paragraphs(cleaned_text)
    return cleaned_paras, removed, note


def detect_headings(paras):
    """Обёртка: абзацы → строки → detect_headings_lines → профиль."""
    raw_text = "\n\n".join(paras)
    lines = [l for l in raw_text.split("\n")]
    return detect_headings_lines(lines)


def _detect_verses_in_text(text, chapter_paras):
    """Вспомогательная: проверить, есть ли в тексте нумерованные стихи.

    Старая реализация — для обратной совместимости с detect_verses.
    """
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


def detect_verses(text, chapter_profile):
    """Обёртка: старый API — текст + профиль → verse_info.

    Использует line-based подход для корректной работы с PDF-текстом,
    где стихи идут сразу после заголовка без пустых строк.
    """
    if not chapter_profile:
        return {"v_mode": "none", "verse_re": "", "confidence": 0.3}

    lines = [l.strip() for l in text.replace("\r\n", "\n").split("\n")]
    pattern = chapter_profile["regex"]
    heading_indices = []
    for i, line in enumerate(lines):
        if re.match(pattern, line):
            heading_indices.append(i)

    if len(heading_indices) < 2:
        return {"v_mode": "none", "verse_re": "", "confidence": 0.3}

    return detect_verses_lines(lines, heading_indices)


def regex_from_sample(line):
    """Сгенерировать regex из одной строки-примера заголовка."""
    digit_match = re.search(r"\d+", line)
    if digit_match:
        before = re.escape(line[:digit_match.start()])
        return r"^%s(?P<chapter>\d+)\s*[.:—–-]?\s*(?P<title>.*)$" % before
    for word, _ in _ai.RU_ORDINALS.items():
        if word in line.lower():
            idx = line.lower().index(word)
            before = re.escape(line[:idx])
            return r"^%s(?P<chapter>[а-яё]+)\s*[.:—–-]?\s*(?P<title>.*)$" % before
    return r"^%s(?P<chapter>.+)(?P<title>.*)$" % re.escape(line)

