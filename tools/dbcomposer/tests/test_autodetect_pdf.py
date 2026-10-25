#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тест autodetect на синтетическом PDF-подобном тексте (18 глав, без пустых строк).

Симулирует результат extract_pdf_text: строки идут подряд, без пустых строк
между абзацами — как в PDF, где каждая строка текста — отдельная строка.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autodetect import autodetect, detect_headings_lines, strip_toc_lines

FAILED = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (("  | " + str(extra)) if not cond else ""))
    if not cond:
        FAILED.append(name)


# ============================================================ Синтетический PDF-текст с 18 главами
# Симуляция: каждая строка текста идёт подряд, без пустых строк.
# Пустые строки только между главами (как иногда делает pdfplumber).

chapters_data = [
    (1, "Введение", "В этой книге мы рассмотрим основы вайшнавской философии и практики преданного служения."),
    (2, "Описание Шри Маха-Вишну", "Шри Маха-Вишну — это первая экспансия Кришны, из которого исходят все кауварана-гава."),
    (3, "Создание материального мира", "Материальный мир создан из 24 таттв, которые описаны в Сат-сангхе."),
    (4, "Джivas в материальном мире", "Дживы — это вечные частицы Кришны, которые могут быть освобождены или связаны."),
    (5, "Путь освобождения", "Освобождение достигается через бхакти-йогу и преданное служение Господу."),
    (6, "Кришна — источник всего", "Кришна является источником всех аватар и всех материальных и духовных миров."),
    (7, "Радха и Кришна", "Радха — это внутренняя энергия Кришны, и их любовная игра — суть духовного мира."),
    (8, "Бхакти-раса", "Бхакти-раса — это сладость любовного служения Кришне в различных отношениях."),
    (9, "Гопи и их служение", "Гопи — это лучшие преданные Кришны, чья любовь к Нему безгранична."),
    (10, "Слава nama-sankirtana", "Нама-санкиртана — это величайший дар Кали-юги для духовного освобождения."),
    (11, "Гуна-рати и их виды", "Гуна-рати — это виды любовного служения в зависимости от настроения преданного."),
    (12, "Сварупа-шакти и татаstха-шакти", "Шримад-Бхагаватам описывает три вида шакти: свараупа, татаstха и бхима."),
    (13, "Аватары Вишну", "Вишну имеет множество аватар, которые нисходят для защиты дхармы."),
    (14, "Прана-прапти и ачарья", "Прана-прапти — это процесс получения духовного знания от ачарьи."),
    (15, "Садху-санга и её сила", "Садху-санга — общение с преданными — это ключ к духовному прогрессу."),
    (16, "Бхакти-садхана", "Бхакти-садхана — это практика преданного служения, описанная в шастрах."),
    (17, "Расика-бхакта и их свойства", "Расика-бхакта — это преданные, достигшие высшей стадии бхакти."),
    (18, "Заключение", "Заключительные размышления о вечной природе преданного служения и любви к Кришне."),
]

# Строим PDF-подобный текст: строки идут подряд, без пустых строк внутри главы
pdf_lines = []
for num, title, body in chapters_data:
    pdf_lines.append("Глава %d. %s" % (num, title))
    # разбиваем тело на строки (как в PDF — каждая строка текста)
    words = body.split()
    current_line = ""
    for w in words:
        if len(current_line) + len(w) + 1 > 80:
            if current_line:
                pdf_lines.append(current_line)
            current_line = w
        else:
            if current_line:
                current_line += " " + w
            else:
                current_line = w
    if current_line:
        pdf_lines.append(current_line)
    # пустая строка между главами (как иногда делает pdfplumber)
    pdf_lines.append("")

pdf_text = "\n".join(pdf_lines)

# ============================================================ Тест autodetect на PDF-тексте
opts, report, normalized = autodetect(pdf_text)

print()
print("=== PDF-тест (18 глав) ===")
print("opts:", opts)
print()
for r in report:
    print("  ", r)
print()

# Проверки
check("pdf: ch_mode = regex", opts["ch_mode"] == "regex", opts["ch_mode"])
check("pdf: chapter_re не пуст", bool(opts["chapter_re"]), opts["chapter_re"])

# Извлекаем число глав из report
chapter_count = None
for r in report:
    m = re.match(r"глав: (\d+)", r)
    if m:
        chapter_count = int(m.group(1))
        break

check("pdf: найдено 18 глав", chapter_count == 18, "got %d" % (chapter_count or 0))

# Проверяем normalized_text: пустые строки вокруг заголовков
check("pdf: normalized не пуст", bool(normalized), normalized)
check("pdf: нормализация содержит пустые строки вокруг заголовков",
      "\n\nГлава " in normalized, normalized[:200])

# Проверяем v_mode — в этом тексте нет нумерованных стихов
check("pdf: v_mode = none (нет стихов)", opts["v_mode"] == "none", opts["v_mode"])

# Проверяем уверенность
confidence = None
for r in report:
    m = re.match(r"уверенность: ([\d.]+)", r)
    if m:
        confidence = float(m.group(1))
        break
check("pdf: уверенность > 0.5", confidence and confidence > 0.5, confidence)

# Показываем первые 5 и последние 2 названия
if opts["chapter_re"]:
    rx = re.compile(opts["chapter_re"])
    all_lines = [l.strip() for l in pdf_text.replace("\r\n", "\n").split("\n")]
    found_chapters = []
    for line in all_lines:
        m = rx.match(line)
        if m:
            g = m.groupdict()
            title = (g.get("title") or "").strip()
            if not title:
                # title из следующей строки
                idx = all_lines.index(line)
                if idx + 1 < len(all_lines):
                    title = all_lines[idx + 1]
            found_chapters.append(title)
    print()
    print("Первые 5 названий:")
    for t in found_chapters[:5]:
        print("  ", t)
    print("Последние 2 названия:")
    for t in found_chapters[-2:]:
        print("  ", t)

# ============================================================ Ложные номера страниц (1..20) НЕ считаются стихами
fake_pages_text = "\n".join(str(i) for i in range(1, 21))
opts_f, report_f, norm_f = autodetect(fake_pages_text)
check("fake_pages: v_mode = none", opts_f["v_mode"] == "none", opts_f["v_mode"])
check("fake_pages: chapters = 0 (числа страниц ≠ заголовки)",
      opts_f["ch_mode"] == "none", opts_f["ch_mode"])

# ============================================================ summary
print()
if FAILED:
    print("FAILED %d: %s" % (len(FAILED), ", ".join(FAILED)))
    sys.exit(1)
print("ALL OK")
