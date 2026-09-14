# Задача: английские LSB / LBG / TLKS из vedabase_md

## Цель
Собрать `eng_lectures.db` в **gitabase-схеме** (как исходники `gitabase_texts_*.db`), чтобы он
шёл через `dbcomposer` → импорт в приложение «Гухьятама» **без переделок кода**.
Сохранить всю связность: кнопка перевода RU/EN (по тройкам), кросс-ссылки в обе
стороны, аудио-привязка (по тройкам), главы.

Рабочая папка: `F:\AI\vedabase_work\` (НЕ лезть в `F:\AI\тест2\`, НЕ трогать rus-базы).
Рутина — скриптами (sqlite3 + re), НЕ чтением сотен md глазами.
На выходе: `eng_lectures.db` + `REPORT.md` (покрытие, остатки `?`, глоссарий, проверки).

## Эталоны (читать скриптами, не глазами)
- Структура лекций rus: `F:\AI\тест2\DB\Prabhupada_rus.db`, книги LSB/LBG/TLKS.
  Точные колонки таблиц: `PRAGMA table_info(books|chapters|textnums|texts|textrefs)`.
- Канонические транслиты для починки цитат: `F:\AI\Kevala Bhakti\source\gitabase_texts_eng.db`
  (таблицы `textnums` + `texts`, поле `translit`).
- Исходники: `F:\AI\vedabase_md\` (md по годам; смотреть только образцами).

## Маппинг файлов → книги (определять кодом имени + заголовком `# ...` / `*Type:*`)
- `*sb*` + заголовок `Srimad-Bhagavatam X.Y[.Z]` → **LSB**: song=X, ch=Y, txt=Z или диапазон
  (`03.87-88` → txt `87-88`). Главы `(song,ch)` уже есть в rus — свериться.
- `*bg*` + `Bhagavad-gita X.Y` → **LBG**: song=1, ch=X, txt=Y/диапазон.
  `Bhagavad-gita Introduction` → song=1, ch=0.
- `*r1/*r2/*r3/*mw/*len*` + `Room Conversation|Morning Walk|...` → **TLKS**:
  song=1, ch=ГОД из `Dated:` (как в rus: `1967 год` → ch `1967`), txt_no = уникальный
  код `E0001`, `E0002`, … (пар с rus нет и не надо).
- Остальные коды (`*cc*`, `*nd*`, `*bs*`, …) — ПРОПУСТИТЬ с отчётом (фаза 2: LCC и др.).

## Книги и главы
- `books`: `_id` 101=LSB (`Lectures on Srimad-Bhagavatam`), 102=LBG, 103=TLKS;
  `author` = `A. C. Bhaktivedanta Swami Prabhupada`.
- `chapters`: LSB/LBG — названия глав взять из `gitabase_texts_eng.db`
  (таблица `chapters` книг SB/BG соответственно); TLKS — title = год (`1967`).
  Колонки — как в rus DB (`_id,book_id,book,song,number,title,desc` — уточнить по PRAGMA).
- `songs`: если есть в rus DB для этих книг — скопировать строки; иначе пропустить
  (импортёр переживает отсутствие).

## Тексты (зеркалить укладку rus-лекций!)
- `translit` = `""`, `transl1` = `""` (как в rus).
- `transl2` = первый абзац body (короткое вступление).
- `comment` = ВЕСЬ текст лекции в HTML: абзацы `<p>…</p>`, шапки `<strong>…</strong>`,
  переносы `<br>`, кавычки-сущности (`&laquo;` и т.п.). Без `<html>/<body>/<style>`.
- `textnums.preview` = первые 200 символов plain-текста.
- Метаданные (дата/место/аудио) — первой строкой body:
  `<p><strong>Lecture SB 1.16.4</strong><br>(January 1st 1974, Los Angeles)</p>`.

## Цитаты → ссылки (два механизма, оба обязательны)
1. Каждая цитата `(SB 1.16.4)`, `Bg. 7.19`, `(CC Adi 3.87)` в тексте — в
   `<a href="gr://eng/texts/<code>/<path>">исходный текст</a>`:
   `code` нижним (`sb/bg/cc/bs/iso/...`), путь 3-уровневый `song/ch/txt`
   (SB: из цифр; CC: Adi/Madhya/Antya → song 1/2/3 + ch + txt;
   BG/BS/ISO: `ch/txt`, song подразумевается 1).
2. На каждую цитату — строка `textrefs`: `thisBook`/`thisSong`/`thisChapter`/`thisTextNo`
   = координаты лекции; `refbyBook` = КОД верхним; `refbySong` (может быть `""`);
   `refbyChapter`, `refbyTextNo`; `refbyText` = label **строго** вида
   `SB 1.16.4 lecture: January 1st 1974, Los Angeles`
   (числа `X.Y.Z` / `X.Y` обязательны — их парсит приложение!).

## Диакритика `?` / `�` (строго, санскрит не выдумывать!)
1. Блоки цитат (`>` + строка `(CODE x.y)` следом): санскрит ЗАМЕНИТЬ каноническим
   `translit` из `gitabase_texts_eng.db` (точный lookup по коду/номерам).
   Нет совпадения — оставить как есть + в отчёт.
2. Инлайн-слова (`K???a`, `sastra` и т.п.): частотный список → фиксированный глоссарий
   замен (`K???a` → `Kṛṣṇa`), ВЕСЬ глоссарий приложить к REPORT (проверю глазами).
3. Неизлечимое — оставить `?` + список файлов:строк в REPORT (ручной добор позже).

## Зеркало rus — критерий связности (проверяется JOIN)
- Для каждой лекции LSB/LBG: тройка `(song,ch,txt)` обязана совпадать с rus-базой
  там, где та же лекция есть (сверить скриптом; расхождения — в REPORT).
- Это даёт: кнопку перевода, входящие ссылки из rus-стихов, аудио-привязку.
- TLKS не сверяется (свои коды).

## Приёмка (проверяю я, не ты)
1. `PRAGMA table_info` всех 6 таблиц = как в rus DB.
2. JOIN `(type,song,ch,txt)` eng↔rus: % совпавших троек LSB/LBG (ожидаю высокий).
3. `?`-остатки: было/стало + список + глоссарий.
4. `textrefs`: всего строк; все `refbyBook` из известных кодов; спот-чек.
5. Импорт через dbcomposer без ошибок + открытие 3 лекций.

## Не делать
Аудио, обложки, letters/LTRS, LCC/LISO, правки rus-баз, `books._id` 1–99 (заняты rus).
