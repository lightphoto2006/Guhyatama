#!/usr/bin/env python3
"""Шарды для Vagdhenu (напевный санскрит-TTS) из gitabase .db + сборка ogg под audio_pack.

Цепочка (на ПК с NVIDIA GPU):
  1. shard:   деванагари стихов -> shard.json + manifest.json
  2. рендер:  python src/render.py --shard shard.json --results res.json --outdir wav/
              (в репозитории vagdhenu; setup.sh ставит torch+веса)
  3. collect: wav -> opus/ogg с именами SB{song}.{ch}.{txt}.ogg (ffmpeg)
  4. dbcomposer audio_pack с тем же pattern -> audio_sb.db -> импорт в приложение

Примеры:
  py vagdhenu_shard.py shard --src gitabase_sb.db --book-type SB \\
      --out shard_sb.json --manifest manifest_sb.json --outdir C:/vag/wav
  py vagdhenu_shard.py collect --manifest manifest_sb.json --results res.json \\
      --wavdir C:/vag/wav --outdir sb_ogg --pattern "SB{song}.{ch}.{txt}.ogg"

Метр: угадывается по числу акшар в паде (8=anushtubh, 11=indravajra, 12=vamshastha, ...),
проверяй manifest (meter_source=guess). Точные правки — через --meter-map:
{"SB-1-2-3": "vasantatilaka"}. Имена метров — ASCII из reference_bank
(anushtubh, indravajra, vamshastha, vasantatilaka, malini, shardulavikridita, ...);
неизвестные движок сам заменит fallback'ом с предупреждением
(это слышно: мелодия чужая, слова верные).
Добивка санскрита: --src2 второй gitabase .db (например eng к rus) и
--donor JSON {"SB-11-1-1": "деванагари...", "11.1.2": "..."} (внешний текст).
Только stdlib (sqlite3/json/re) + ffmpeg на шаге collect.
"""
import argparse
import html as _html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys

# --- подсчёт акшар (дословно из vagdhenu src/render.py, чистый питон) ---
def n_aksharas(s):
    n = 0
    L = len(s)
    for i, c in enumerate(s):
        o = ord(c)
        indep = (0x0905 <= o <= 0x0914) or (0x0C85 <= o <= 0x0C94)
        cons = (0x0915 <= o <= 0x0939) or (0x0C95 <= o <= 0x0CB9)
        if indep:
            n += 1
        elif cons:
            nxt = s[i + 1] if i + 1 < L else ""
            if nxt not in ("्", "್"):
                n += 1
    return n

# число акшар в паде -> имя эталона (ASCII, как wav-имена в reference_bank).
# 11 слогов разбираются отдельно (триштубх-семья по L/G, см. trishtubh_family).
# mandakranta (17) в банке нет — уйдёт в fallback движка, это видно в логе рендера.
COUNT_METER = {
    8: "anushtubh", 12: "vamshastha", 14: "vasantatilaka",
    15: "malini", 17: "mandakranta", 19: "shardulavikridita", 21: "sragdhara",
}

TAG_RE = re.compile(r"<br\s*/?>", re.I)
TAG_ANY = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
DROP_CHARS = set(",;:.!?—–-\"'“”‘’„«»‹›*•·|/\\()[]{}0123456789०१२३४५६७८९")
# строка диктора (śrī-bhagavān uvāca и т.п.) — отдельным куском с паузой, не клеить к паде.
# После сандхи там -н-ува̄ча/-д-ува̄ча, а не чистое uvāca; плюс кап длины от ложных -vāc.
UVACA_RE = re.compile(r"(उवाच|ुवाच|ऊचुः|उचुः|आहुः)\s*$")


def is_leader(p):
    """Строка диктора: кончается -uvāca и короткая (защита от пад с -vāc внутри)."""
    return bool(UVACA_RE.search(p)) and len(p.split()) <= 4

# --- лагу-гуру (для различения триштубхов: indravajra/upendravajra/upajati) ---
_IND_SHORT = set("अइउऋऌ")
_IND_LONG = set("आईऊॠॡएऐओऔ")
_DEP_SHORT = set("िुृ")
_DEP_LONG = set("ाीूॄेैोौ")
_ANUSVARA = "ं"
_VISARGA = "ः"
_VIRAMA = "्"


def _is_cons(o):
    return 0x0915 <= o <= 0x0939


def _is_ind(o):
    return 0x0905 <= o <= 0x0914


def syllabify(pada):
    """Деванагари -> список слогов (акшара-группы с зависимыми знаками)."""
    syls, cur = [], ""
    prev = ""
    for c in pada:
        o = ord(c)
        if not cur:
            cur = c
        elif _is_ind(o) or (_is_cons(o) and prev != _VIRAMA):
            syls.append(cur)
            cur = c
        else:
            cur += c
        prev = c
    if cur:
        syls.append(cur)
    return [s for s in syls if s.strip()]


def laghu_guru(pada):
    """Пада -> строка L/G. Гуру: долгая/дифтонг, анусвара/висарга,
    краткая (включая inherent-a без знака!) перед конъюнктом.
    Последний слог — как есть (anceps не форсируем)."""
    syls = syllabify(pada)
    out = []
    for i, s in enumerate(syls):
        long_v = any(ch in _IND_LONG or ch in _DEP_LONG for ch in s)
        if long_v or _ANUSVARA in s or _VISARGA in s:
            out.append("G")
            continue
        # остальное — краткий гласный (явный знак, независимый или inherent-a);
        # перед конъюнктом (вирама в начале следующего слога) — гуру по позиции
        nxt_conj = i + 1 < len(syls) and _VIRAMA in syls[i + 1]
        out.append("G" if nxt_conj else "L")
    return "".join(out)


def html_to_text(raw):
    if not raw:
        return ""
    t = TAG_RE.sub("\n", raw)
    t = TAG_ANY.sub("", t)
    t = _html.unescape(t)
    return t


def clean_pada(p):
    # Двоеточие в источниках — это висарга (पर: = परः), как fix_colon у движка.
    # Конвертируем ДО чистки, иначе придыхание в конце теряется.
    # Оторванную пробелом висаргу/анусвару (स्यु :) приклеиваем обратно.
    p = p.replace(":-", "ः").replace(":", "ः")
    p = re.sub(r"\s+([ःं])", r"\1", p)
    p = "".join(c for c in p if c not in DROP_CHARS)
    return WS_RE.sub(" ", p).strip()


def _ends_vowel(s):
    """Конец куска — гласный (включая inherent-a согласной, анусвару/висаргу)."""
    s = s.rstrip()
    if not s:
        return False
    o = ord(s[-1])
    if s[-1] in "्।॥ \t":
        return False
    return ((0x0905 <= o <= 0x0914) or (0x093E <= o <= 0x094C) or
            o in (0x0902, 0x0903) or (0x0915 <= o <= 0x0939))


def _starts_rconj(s):
    """Начало куска — вокализованное 'р' (र्+согласная): шрам рутва-сандхи (taiḥ+yuktaḥ)."""
    s = s.lstrip()
    return len(s) >= 2 and s[0] == "र" and s[1] == _VIRAMA


def split_padas(dev_text):
    """Деванагари -> пады (четверти), затем группировка в полустишия для рендера.
    Строка диктора (uvāca) — отдельным куском: естественная пауза перед стихом,
    а не склейка с первой падой и не сирота-последыш.
    Полустишие — целиком (до 30 слогов: васантатилака 28 влазит, шардула 38 режется),
    чтобы слово на стыке пад не рвалось между инференсами. Шрам рутвы на стыке
    (...तै | र्युक्त:) склеивается без пробела, обычный стык — с пробелом.
    Возвращает (padas, hemi, joins) где joins — число рутва-склеек."""
    padas = []
    for line in html_to_text(dev_text).replace("॥", "।").split("\n"):
        for piece in line.split("।"):
            c = clean_pada(piece)
            if c:
                padas.append(c)
    leaders = [p for p in padas if is_leader(p)]
    body = [p for p in padas if p not in leaders]
    joins = 0
    hemi = list(leaders)
    i = 0
    while i < len(body):
        if i + 1 < len(body) and n_aksharas(body[i] + " " + body[i + 1]) <= 30:
            if _ends_vowel(body[i]) and _starts_rconj(body[i + 1]):
                hemi.append(body[i] + body[i + 1])
                joins += 1
            else:
                hemi.append(body[i] + " " + body[i + 1])
            i += 2
        else:
            hemi.append(body[i])
            i += 1
    return padas, [h for h in hemi if h], joins


def trishtubh_family(padas):
    """11-сложные пады: indravajra (начало GGG) / upendravajra (начало LGL) / upajati (смесь)."""
    votes = []
    for p in padas:
        if n_aksharas(p) != 11:
            continue
        head = laghu_guru(p)[:3]
        if head == "GGG":
            votes.append("I")
        elif head == "LGL":
            votes.append("U")
        else:
            votes.append("?")
    if not votes:
        return "indravajra", "family-empty"
    if all(v == "I" for v in votes):
        return "indravajra", "family"
    if all(v == "U" for v in votes):
        return "upendravajra", "family"
    return "upajati", "family-mixed"


def guess_meter(padas, default="anushtubh"):
    """Мажоритарный подсчёт акшар по первым 4 НЕ-дикторским падам.
    11 слогов — разбор семьи по L/G; разнобой длин — gadya (проза)."""
    verse = [p for p in padas if not is_leader(p)]
    counts = [n_aksharas(p) for p in verse[:4] if n_aksharas(p) > 0]
    if not counts:
        return default, "empty"
    top = max(set(counts), key=counts.count)
    if counts.count(top) * 2 < len(counts):
        return "gadya", "uneven"
    if top == 11:
        return trishtubh_family(verse[:4])
    return COUNT_METER.get(top, default), ("guess" if top in COUNT_METER else "default")


def safe(s):
    return re.sub(r'[^\w.\-]+', '_', str(s), flags=re.U).strip("_") or "x"


def load_fallback(src2, books2, btype):
    """{(song,ch,txt): sanskrit} из второго .db (книги --books2 или того же типа)."""
    fb = {}
    if not src2 or not os.path.isfile(src2):
        return fb
    c2 = sqlite3.connect(src2)
    c2.row_factory = sqlite3.Row
    try:
        ids = {str(r["_id"]) for r in c2.execute("SELECT _id,type FROM books")}
        want2 = set(x.strip() for x in (books2 or "").split(",") if x.strip())
        if not want2:
            want2 = {str(r["_id"]) for r in
                     c2.execute("SELECT _id FROM books WHERE upper(type)=?", (btype,))}
            if not want2:
                want2 = ids
        q = ("SELECT n.song,n.ch_no,n.txt_no,t.sanskrit FROM textnums n"
             " LEFT JOIN texts t ON t._id=n._id WHERE n.book_id IN (%s)"
             % ",".join("?" * len(want2)))
        for r in c2.execute(q, tuple(want2)):
            if r["sanskrit"] and str(r["sanskrit"]).strip():
                fb.setdefault((str(r["song"]), str(r["ch_no"]), str(r["txt_no"])),
                              r["sanskrit"])
    except Exception:
        pass
    c2.close()
    return fb


def parse_chapters(s):
    """'1,2.3' -> (songs={'1'}, pairs={('2','3')}). Пусто = всё."""
    songs, pairs = set(), set()
    for t in (s or "").split(","):
        t = t.strip()
        if not t:
            continue
        if "." in t:
            a, b = t.split(".", 1)
            pairs.add((a.strip(), b.strip()))
        else:
            songs.add(t)
    return songs, pairs


def parse_verses(s):
    """'1.2.23,1.2.24' -> {('1','2','23'),...}. Точечный добор/перерендер."""
    out = set()
    for t in (s or "").split(","):
        p = [x.strip() for x in t.strip().split(".")]
        if len(p) == 3 and all(p):
            out.add((p[0], p[1], p[2]))
    return out


def load_bank_sps(bank_path):
    """метр -> sec_per_syll из reference_bank (ключи как у движка: lower + имя wav)."""
    lut = {}
    if not bank_path or not os.path.isfile(bank_path):
        return lut
    try:
        bank = json.load(open(bank_path, encoding="utf-8"))
    except Exception:
        return lut
    for k, v in bank.items():
        if k.startswith("_") or not isinstance(v, dict) or "wav" not in v:
            continue
        sps = float(v.get("sec_per_syll", 0) or 0)
        if sps > 0:
            lut[k.lower()] = sps
            lut[v["wav"].replace(".wav", "").lower()] = sps
    return lut


def cmd_shard(a):
    con = sqlite3.connect(a.src)
    con.row_factory = sqlite3.Row
    books = {str(r["_id"]): dict(r) for r in
             con.execute("SELECT _id,title,author,type FROM books")}
    if not books:
        print("В файле нет таблицы books или она пуста")
        return 1
    want = set(x.strip() for x in (a.books or "").split(",") if x.strip())
    btype = (a.book_type or "").upper()
    if not btype:
        types = {str(b.get("type") or "").upper() for b in books.values()}
        btype = types.pop() if len(types) == 1 else ""
    if not btype:
        print("Несколько типов книг, укажи --book-type. Доступно:")
        for bid, b in books.items():
            print("  %s: %s [%s]" % (bid, b.get("title"), b.get("type")))
        return 1
    mfix = {}
    if a.meter_map and os.path.isfile(a.meter_map):
        mfix = json.load(open(a.meter_map, encoding="utf-8"))
    donor = {}
    if a.donor and os.path.isfile(a.donor):
        donor = json.load(open(a.donor, encoding="utf-8"))
    fb = load_fallback(a.src2, a.books2, btype)
    if fb:
        print("Fallback-источник: %d санскритов" % len(fb))
    bank = load_bank_sps(a.bank)
    tempo = a.tempo if a.tempo and a.tempo > 0 else 1.0
    if tempo != 1.0:
        # Темп — через speed БЕЗ фиксированной длительности: sps=0 отключает холст
        # (иначе модель поёт в своём темпе, а лишний холст гейт срезает как тишину).
        # speed идёт от базовых 0.90 движка: 0.85 -> 0.765.
        print("Темп x%.2f: sps=0 (без фикс. длительности) + speed=%.3f (проверь на 2-3 клипах!)"
              % (tempo, round(0.9 * tempo, 3)))
    outdir = os.path.abspath(a.outdir or "wav")
    shard, manifest = [], []
    seen = set()
    songs_only, pairs = parse_chapters(a.chapters)
    want_verses = parse_verses(a.verses)
    stat = {"verses": 0, "no_sanskrit": 0, "dupes": 0, "skipped": 0,
            "wrong_type": 0, "meters": {}, "by_book": {}}
    type_of = {bid: str(b.get("type") or "").upper() for bid, b in books.items()}
    if want:
        alien = sorted(bid for bid in want if bid in type_of and type_of[bid] != btype)
        if alien:
            print("ВНИМАНИЕ: id %s — это не %s, а %s. Проверь выбор книг!"
                  % (",".join(alien), btype,
                     ", ".join("%s=%s" % (i, type_of[i]) for i in alien)))
    rows = con.execute(
        "SELECT n.book_id,n.song,n.ch_no,n.txt_no,t.sanskrit"
        " FROM textnums n LEFT JOIN texts t ON t._id=n._id"
        " ORDER BY n.book_id,n.song,n.ch_no,n.txt_no")
    cands = []
    for r in rows:
        bid = str(r["book_id"])
        if want and bid not in want:
            continue
        if type_of.get(bid, btype) != btype:
            # чужой тип (id приплыли из другого файла) — не молчим, а режем
            stat["wrong_type"] += 1
            continue
        song, ch, txt = str(r["song"]), str(r["ch_no"]), str(r["txt_no"])
        if want_verses and (song, ch, txt) not in want_verses:
            stat["skipped"] += 1
            continue
        if songs_only or pairs:
            if song not in songs_only and (song, ch) not in pairs:
                stat["skipped"] += 1
                continue
        key = (song, ch, txt)
        if key in seen:
            # рус+англ источники в одном файле: санскрит один, второй пропуск
            stat["dupes"] += 1
            continue
        seen.add(key)
        san = r["sanskrit"] or ""
        origin = "primary"
        if not san.strip() and key in fb:
            san, origin = fb[key], "src2"
        vid = "%s-%s-%s-%s" % (btype, safe(song), safe(ch), safe(txt))
        if not san.strip() and vid in donor:
            san, origin = donor[vid], "donor"
        if not san.strip() and "%s.%s.%s" % key in donor:
            san, origin = donor["%s.%s.%s" % key], "donor"
        padas, hemi, rj = split_padas(san)
        stat["rjoins"] = stat.get("rjoins", 0) + rj
        if not hemi:
            stat["no_sanskrit"] += 1
            continue
        meter, msrc = guess_meter(padas, a.default_meter)
        if vid in mfix:
            meter, msrc = mfix[vid], "manual"
        cands.append({"vid": vid, "bid": bid, "song": song, "ch": ch, "txt": txt,
                      "meter": meter, "msrc": msrc, "origin": origin,
                      "padas": padas, "hemi": hemi})
    if a.sample_meter and a.sample_meter > 0:
        # проба: по K стихов каждого метра (для теста разных напевов)
        by_m = {}
        for e in cands:
            by_m.setdefault(e["meter"], []).append(e)
        cands = sorted([e for m in by_m.values() for e in m[:a.sample_meter]],
                       key=lambda e: e["vid"])
    if a.limit and a.limit > 0:
        cands = cands[:a.limit]
    for e in cands:
        vid = e["vid"]
        out = os.path.join(outdir, vid + ".wav")
        clip = {"id": vid, "meter": e["meter"], "padas": e["hemi"],
                "seed": a.seed, "no_sandhi": not a.sandhi, "out": out}
        if tempo != 1.0:
            clip["sps"] = 0
            clip["speed"] = round(0.9 * tempo, 3)
        shard.append(clip)
        manifest.append({"id": vid, "book_type": btype, "book_id": e["bid"],
                         "song": e["song"], "ch": e["ch"], "txt": e["txt"],
                         "meter": e["meter"], "meter_source": e["msrc"],
                         "sanskrit_from": e["origin"],
                         "syllables": [n_aksharas(p) for p in e["padas"]],
                         "lg": [laghu_guru(p) for p in e["padas"]],
                         "padas": e["hemi"]})
        stat["verses"] += 1
        stat["meters"][e["meter"]] = stat["meters"].get(e["meter"], 0) + 1
        bk = books.get(e["bid"], {}).get("title", e["bid"])
        stat["by_book"][bk] = stat["by_book"].get(bk, 0) + 1
    con.close()
    json.dump(shard, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(manifest, open(a.manifest, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # Ревизия метров: всё не-guess (default/uneven/gadya/family-empty) — на проверку ухом,
    # движок такое поёт fallback-мелодией. Формат: id | meter (source) | слоги | L/G | пады.
    SUSPECT = ("default", "uneven", "empty", "family-empty")
    rev = []
    for m in manifest:
        if m["meter_source"] in SUSPECT or m["meter"] == "gadya":
            lgs = "/".join(m.get("lg", []))
            syl = ",".join(str(x) for x in m.get("syllables", []))
            rev.append("%s | %s (%s) | [%s] | %s | %s" % (
                m["id"], m["meter"], m["meter_source"], syl, lgs,
                " / ".join(m.get("padas", []))[:160]))
    if rev:
        rp = a.out + ".review.txt"
        open(rp, "w", encoding="utf-8").write(
            "Подозрительные метры (%d) — прослушать и при нужде задать --meter-map:\n" % len(rev)
            + "\n".join(rev) + "\n")
        print("Ревизия метров: %d -> %s" % (len(rev), rp))
    else:
        print("Ревизия метров: подозрительных нет")
    print("Стихов в шарде: %d, без санскрита: %d, дублей rus/eng: %d, отсеяно фильтром: %d, чужого типа отрезано: %d, рутва-склеек: %d"
          % (stat["verses"], stat["no_sanskrit"], stat["dupes"], stat["skipped"],
             stat["wrong_type"], stat.get("rjoins", 0)))
    print("По книгам: " + "; ".join("%s=%d" % kv for kv in sorted(stat["by_book"].items())))
    print("Метры: " + ", ".join("%s=%d" % kv for kv in sorted(stat["meters"].items())))
    if bank:
        unknown = sorted(m for m in stat["meters"] if m.lower() not in bank)
        if unknown:
            print("ВНИМАНИЕ: этих метров нет в банке — движок споёт fallback'ом: "
                  + ", ".join(unknown))
    guess_n = sum(1 for m in manifest if m["meter_source"] == "guess")
    print("Проверь метры-guess (%d): выгрузи спорные через meter_source" % guess_n)
    print("Дальше: render.py --shard %s --results res.json --outdir %s" % (a.out, outdir))
    return 0


def cmd_collect(a):
    if not shutil.which("ffmpeg"):
        print("Нет ffmpeg в PATH")
        return 1
    manifest = {m["id"]: m for m in json.load(open(a.manifest, encoding="utf-8"))}
    results = {r["id"]: r for r in json.load(open(a.results, encoding="utf-8"))}
    os.makedirs(a.outdir, exist_ok=True)
    ok = fail = missing = 0
    total = 0
    bad = []
    seen_names = {}
    done_names = []
    for vid, m in manifest.items():
        r = results.get(vid, {})
        if "error" in r:
            fail += 1
            bad.append((vid, r["error"][:80]))
            continue
        wav = os.path.join(a.wavdir, vid + ".wav")
        if not os.path.isfile(wav) or os.path.getsize(wav) < 1024:
            missing += 1
            bad.append((vid, "нет wav"))
            continue
        dur = float(r.get("dur", 0) or 0)
        if dur and not (0.5 <= dur <= 180):
            fail += 1
            bad.append((vid, "подозрительная длительность %s" % dur))
            continue
        name = a.pattern.format(song=safe_fn(m["song"]), ch=safe_fn(m["ch"]), txt=safe_fn(m["txt"]))
        if name in seen_names:
            fail += 1
            bad.append((vid, "ДУБЛЬ имени %s (уже у %s) — в шаблоне не хватает {song}?" % (name, seen_names[name])))
            continue
        seen_names[name] = vid
        dst = os.path.join(a.outdir, name)
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", wav,
               "-ac", "1", "-ar", "24000", "-c:a", "libopus", "-b:a", a.bitrate, dst]
        try:
            pr = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except Exception as e:
            fail += 1
            bad.append((vid, "ffmpeg: %s" % e))
            continue
        if pr.returncode != 0 or not os.path.isfile(dst) or os.path.getsize(dst) < 5 * 1024:
            fail += 1
            bad.append((vid, "ffmpeg err: %s" % (pr.stderr or "")[:80]))
            continue
        ok += 1
        total += os.path.getsize(dst)
        if len(done_names) < 3:
            done_names.append(name)
    print("Готово: ok=%d fail=%d missing=%d, всего %.1f МБ" % (ok, fail, missing, total / 1048576))
    for vid, why in bad[:15]:
        print("  %s: %s" % (vid, why))
    if ok:
        print("примеры: %s" % ", ".join(done_names))
        print("Дальше: audio_pack {dir: %s, book_type: %s, pattern: %s}"
              % (os.path.abspath(a.outdir), manifest[next(iter(manifest))]["book_type"], a.pattern))
    return 0 if ok else 1


def safe_fn(s):
    return re.sub(r'[\\/:\*\?"<>\|]', "_", str(s)).strip() or "x"


def main():
    p = argparse.ArgumentParser(description="Vagdhenu: шарды из .db и сборка ogg")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shard", help="шард+манифест из gitabase .db")
    s.add_argument("--src", required=True, help="исходный gitabase .db (ШБ)")
    s.add_argument("--src2", default="", help="второй .db-донор санскрита (напр. eng к rus)")
    s.add_argument("--books2", default="", help="book_id в src2 (иначе книги того же типа)")
    s.add_argument("--donor", default="", help='JSON {id или "s.ch.t": деванагари} (внешний текст)')
    s.add_argument("--book-type", default="", help="SB (иначе авто, если тип один)")
    s.add_argument("--books", default="", help="book_id через запятую (иначе все)")
    s.add_argument("--chapters", default="",
                   help="фильтр: '1' = вся песнь 1, '1.2' = песнь 1 гл.2; через запятую")
    s.add_argument("--verses", default="",
                   help="точечно: '1.2.23,1.2.24' (песнь.глава.стих) для добора/перерендера")
    s.add_argument("--limit", type=int, default=0, help="первые N (0 = все)")
    s.add_argument("--sample-meter", type=int, default=0,
                   help="проба: по N стихов каждого метра (для теста напевов)")
    s.add_argument("--out", required=True, help="shard.json для render.py")
    s.add_argument("--manifest", required=True, help="manifest.json для collect")
    s.add_argument("--outdir", default="wav", help="куда render положит wav")
    s.add_argument("--default-meter", default="anushtubh")
    s.add_argument("--meter-map", default="", help="JSON {id: meter} ручных правок")
    s.add_argument("--seed", type=int, default=60)
    s.add_argument("--tempo", type=float, default=1.0,
                   help="множитель темпа (1=эталон; 0.85 протяжнее): sps=0 + speed=0.9*tempo")
    s.add_argument("--bank", default="",
                   help="reference_bank/bank.json движка (для темпа через sps)")
    s.add_argument("--sandhi", action="store_true",
                   help="включить sandhi-нормализацию (по умолчанию no_sandhi, как в sample)")
    c = sub.add_parser("collect", help="wav -> opus/ogg именами под audio_pack")
    c.add_argument("--manifest", required=True)
    c.add_argument("--results", required=True, help="results.json из render.py")
    c.add_argument("--wavdir", required=True)
    c.add_argument("--outdir", required=True)
    c.add_argument("--pattern", default="SB{song}.{ch}.{txt}.ogg")
    c.add_argument("--bitrate", default="24k")
    a = p.parse_args()
    return cmd_collect(a) if a.cmd == "collect" else cmd_shard(a)


if __name__ == "__main__":
    sys.exit(main())
