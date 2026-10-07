# Технический аудит приложения Guhyatama (com.vedalibrary.app)

Дата: 2026-10-04 · Версия: 1.2.36 (versionCode 42) · Объём: всё приложение `app/` (Kotlin/Compose), слой данных, безопасность + отдельное исследование ColorOS/выравнивание по ширине.

Метод: ревью пяти осей (Correctness / Readability / Architecture / Security / Performance), чтение всех ключевых файлов, грепы по репозиторию, автопроверка `compileDebugKotlin` и `lintDebug`.

---

## 0. Результаты проверки сборки

| Проверка | Итог |
|---|---|
| `:app:compileDebugKotlin` | **OK** |
| `:app:lintDebug` | **FAIL: 7 ошибок, 15 предупреждений** |
| Тесты (`app/src/test`, `app/src/androidTest`) | **Отсутствуют полностью** — ни одного теста в проекте |
| detekt | не настроен |

Ошибки lint:
1. `HtmlText.kt:378-382` (6× `WrongConstant`) — lint требует константы `LineBreaker.*` вместо эквивалентных `Layout.*` (значения совпадают, ложное срабатывание, но гасит весь lint). Фикс: использовать `android.text.LineBreaker.BREAK_STRATEGY_*` / `JUSTIFICATION_MODE_*` или `@Suppress("WrongConstant")` с пояснением.
2. `LibraryScreen.kt:237` `ProduceStateDoesNotAssignValue` — `produceState` не присваивает значение в producer-lambda (реальный баг-риск: `coverPath` кэширует `null` навсегда, см. S-9).

Полезные предупреждения: устаревшие зависимости (core-ktx 1.15→1.19, navigation 2.8.9→2.10, room 2.6.1→**2.8.5**, media3 1.5→1.11), `ObsoleteSdkInt` (`HtmlText.kt:375` и `AppUpdater.kt:88` проверяют `SDK_INT >= 26` при `minSdk = 26` — проверки мертвы), `UnusedResources` (R.string.app_name), иконки без `monochrome`.

---

## 1. Текущее состояние архитектуры (снапшот)

- **UI:** single-activity Compose, `NavGraph.kt` — 5 табов + выталкиваемые экраны (`reader`, `chapter`, `verse`, `dict`, `settings`), per-entry Hilt ViewModel. Рендер двух видов: обычный Compose `Text` (списки) и `AndroidView`-обёртка `TextView` (`HtmlText.kt`, 898 строк) для HTML-тел.
- **ViewModel-слой:** 8 VM в одном файле `ViewModels.kt` (1088 строк) + `SettingsViewModel` внутри `SettingsScreen.kt`. **Слоя Repository нет** — VM инжектируют `AppDatabase` напрямую и пишут запросы/маппинг сами.
- **Данные:** Room v10 (13 entities + FTS4), один `LibraryDao`, Hilt-синглтон. Вход данных: TXT/PDF/DOCX импорт, чужие `.db` (`LibraryDbImporter`), удалённый каталог (`UpdateViewModel` → `importFile`). Состояние — DataStore + SharedPreferences (`UpdatePrefs`).
- **Обновления:** `AppUpdater`/`Downloader` (DownloadManager) + каталог на raw.githubusercontent.com, self-update APK c SHA-256, дельта-импорт книг.
- **Кросс-нинг:** процессные синглтоны (`VolumeFont.handler`, кэши `GbHtml`/`ReadFont`), VM принимают **навигационные лямбды как параметры**, массовый `catch (_: Exception) {}`.
- **Тестов нет. Нет CI.** Данные (заметки/подсветки/карточки) живут только в БД пользователя.

**Вывод:** код живой, богато закомментирован (опыт прошивочных костылей виден), но проект достиг размера, где отсутствие тестов, слоя Repository и единого места для мутаций начинает стоить дороже, чем экономит.

---

## 2. Critical — исправить до следующего релиза

**[Critical]** `data/update/UpdateCatalog.kt:13` — **GitHub PAT зашит в исходник как `const`** (`github_pat_11BDSW...`) и уезжает в APK, откуда достаётся любым декомпилятором. Используется как `Authorization: Bearer` для приватных релизов (`UpdateViewModel.kt:346-348`).
→ **Немедленно отозвать токен в GitHub (Settings → Developer settings → Fine-grained tokens).** Вынести в CI-секрет/`local.properties`+BuildConfig (не коммитить), лучше — заменить на подписанные временные URL. Файл пока untracked (`git status`), но одна `git add` — и токен в истории навсегда.

**[Critical]** `di/AppModule.kt:19` + `data/local/AppDatabase.kt:324,331-397` — `fallbackToDestructiveMigration()` при **отсутствующих миграциях 1→2 и 2→3** (существуют только 3→4 … 9→10) и `exportSchema = false`.
→ Любое расхождение схемы (включая будущие правки рукописных миграций) **молча стирает всю библиотеку, заметки, подсветки и карточки** без единого слова пользователю. Фикс: `exportSchema = true` + коммит `schemas/` + миграционные тесты (`MigrationTestHelper`), явные миграции 1→2/2→3, `fallbackToDestructiveMigrationOnDowngrade()` для отката APK, убрать слепой fallback (или заменить на колбэк с предупреждением).

**[Critical]** `data/library/LibraryDbImporter.kt:113-133` — при переимпорте книги **сначала удаляются** verses/chapters/illustrations/refs, **потом** читаются новые строки, без единой `@Transaction`; исключение попадает в `catch` → книга остаётся полупустой с `isReady=0` («⏳ Импорт идёт…» навсегда, карточка не открывается).
→ Фикс: импорт в staging-id или одна `@Transaction` на книгу с откатом; удалять старое только после успешного чтения нового.

---

## 3. Important — исправить до мержа

### Безопасность
1. **[Important]** `LibraryDbImporter.kt:304,319,821` — SQL собирается конкатенацией (`WHERE thisBook='$thisBook'`, `name='$t'`), где источник — **посторонний .db файл**. Соединение `OPEN_READONLY` ограничивает ущерб, но это всё ещё SQL-инъекция из враждебного файла. → Параметризованные аргументы (`?` + `selectionArgs`).
2. **[Important]** `UpdateViewModel.kt:336` — путь скачивания строится как `File(dir, "$key-v…db")`, где `key` приходит **verbatim из каталога**; `key` с `../` выходит за пределы каталога обновлений. → Санитайз `[^A-Za-z0-9._-] → "_"` + запрет разделителей (правило уже есть в `LibraryDbImporter.kt:38`).
3. **[Important]** `AppUpdater.kt:66-74`, `UpdateViewModel.kt:337-354` — **SHA-256 пропускается, если в каталоге поле пустое** (`sha.isBlank() || …`), и повреждённый/подменённый APK или .db принимается. Плюс `Downloader.kt:47` пишет прямо в конечный файл → «переиспользуемый» кусок >1 КБ тоже проходит. → Fail closed: нет sha256 — не ставим/не импортируем; писать во временный файл + rename; проверять SQLite-заголовок перед импортом (путь ручного импорта это уже делает, `SettingsScreen.kt:241-246`).
4. **[Important]** `AndroidManifest.xml:30` — `allowBackup="true"` без `dataExtractionRules`/`fullBackupContent`: **вся БД (заметки, подсветки, вопросы, карточки), история поиска и crash-лог** уезжают в облачный бэкап и device-to-device перенос без возможности исключить. → Явные правила с исключением `vedalibrary.db` и `crash_last.txt` (или осознанно задокументировать).
5. **[Suggestion]** `provider_paths.xml` — FileProvider отдаёт `cache-path "."` и `files-path "."` целиком; при утечке grant читается всё приватное хранилище. → Сузить до `Download/updates/`.
6. **[Suggestion]** `Downloader.kt:50` — `Authorization: Bearer <PAT>` передаётся в `DownloadManager`, который **персистит заголовки в системной БД загрузок**; токен едет в каждой книге. → Короткоживущие подписанные URL или `HttpURLConnection` для приватных скачиваний.

### Потеря данных
7. **[Important]** `LibraryDbImporter.kt:465-475` — аудио-импорт материализует **все BLOB'ы в список** (до 20 000 строк × до 8 МБ) до первой записи → гарантированный OOM на реальных паках. → Потоковая запись row-by-row в батчах.
8. **[Important]** `BackupManager.kt:42-50` — restore: (а) ошибки глотаются, а метод **всё равно печатает «Восстановлено записей: N»**; (б) повторный restore **дублирует** записи (id сбрасываются в 0), composite-PK `verse_tags` падает constraint'ом и откатывает всю транзакцию — опять «успешно». → Upsert со стабильными id, честный отчёт, rethrow.
9. **[Important]** `TxtImporter.kt:37-49` — импорт TXT (книга → главы → чанки по 500 → refs → ready) идёт **отдельными транзакциями**; падение посреди → невосстановимая полукнига `isReady=false`. → Одна `@Transaction` + очистка при сбое.
10. **[Important]** `ViewModels.kt:430` — `saveChapterBookmark` делает `deleteBookmarksOfBook(bookId)` + `insertBookmark` не атомарно: звезда в главе **без предупреждения уничтожает стиховую закладку** книги. → Upsert в `@Transaction`.
11. **[Important]** `SettingsScreen.kt:295-296`, `LibraryDbImporter.kt:616,626` — автобэкап перезаписывается **на месте** (крэш посреди write рвёт единственную копию), манифесты аудио — обычным `writeText`. → `*.tmp` + `ATOMIC_MOVE`.

### Корректность
12. **[Important]** `ViewModels.kt:195-207` (поиск) — сырой ввод пользователя уходит в FTS `MATCH` (`"sanskrit:$q"`) без экранирования: дефис/кавычка/звёздочка = синтаксическая ошибка → исключение глотается → **пустая выдача вместо ошибки**; плюс `search()` гоняется на **каждой клавише** без debounce и без отмены предыдущего job (гонка результатов), и `saveHistory(q)` пишет в историю префиксы (`kr`, `kri`, `krish`…). → Экранирование как в `DictViewModel:976`, пайплайн `debounce(250).distinctUntilChanged().flatMapLatest{}`, история — по submit.
13. **[Important]** `NavGraph.kt:72` — табы: `navigate(r) { launchSingleTop }` **без `popUpTo(saveState)/restoreState`** → back проходит по всем визитам в табы, стек растёт. `NavGraph.kt:49` — `selected` не `rememberSaveable` и не из NavController → после поворота подсветка таба расходится с реальным стеком.
14. **[Important]** `VerseDetailScreen.kt:231-234` — `VerseAudioPlayer` создаётся **внутри item'а LazyColumn**: прокрутка строки аудио за экран вызывает `onDispose → release()` и **режет воспроизведение** посреди стиха. → Играть на уровне экрана, release по ключу стиха.
15. **[Important]** `ChapterScreen.kt:64-78` — восстановление скролла: (а) из закладки возврат «назад»/поворот **возвращает к закладке**, а не к месту чтения; (б) `scrollToItem` на ещё пустом списке молча коэрсится → первая попытка «успевает» до загрузки из Room и позиция теряется. → Ждать `verses.isNotEmpty()`, route-аргументы только при первом входе.
16. **[Important]** `ViewModels.kt:471` — `addNote` — единственный мутатор **без try/catch**: падение Room = крэш приложения. `ViewModels.kt:58` и десятки мест — `catch (_: Exception) {}` **глотает `CancellationException`** (отменённый `deleteBook` продолжает чистить файлы) и прятает реальные сбои.
17. **[Important]** `ViewModels.kt:183-187` — VM отдают **публичные `MutableStateFlow`**, в которые Composable'ы пишут напрямую (`vm.query.value = it`) — мутабельное состояние снаружи, валидация невозможна. → `StateFlow` + сеттеры.
18. **[Important]** `ReaderSettings.kt:92-145`, `ViewModels.kt:43,84,95` — read-then-write DataStore **не атомарен**: быстрые нажатия громкости теряют шаги шрифта, два быстрых изменения порядка книг затирают друг друга. → Всё внутри одного `updateData {}`.
19. **[Important]** Дублирование: `deleteBook` существует дважды (`ViewModels.kt:122` и `SettingsScreen.kt:60`) и **уже разошёлся** (путь из Library не чистит аудио своей книги → сироты файлов); `copyVerse`/`toCards` тоже продублированы. → Один use-case.
20. **[Important]** `VerseDetailScreen.kt:110,160-197` — таймер «стих не найден» срабатывает через 3 с независимо от прогресса (ложный отказ на медленной БД); скролл к подсветке не учитывает асинхронное появление аудио-строки (секция уезжает на одну вниз).
21. **[Important]** `VolumeFont.kt:10` — процессный синглтон с одним handler'ом (лямбда захватывает composition-scope и VM) из 12 точек регистрации; порядок dispose решает всё. → CompositionLocal или стек владельцев.
22. **[Important]** `AndroidManifest.xml` — **объявлены, но не используются**: `RECEIVE_BOOT_COMPLETED` (нет receiver'а), `FOREGROUND_SERVICE`+`FOREGROUND_SERVICE_DATA_SYNC` (нет сервиса), `POST_NOTIFICATIONS` (канал `daily-verse` в `VedaApp.kt:13` создаётся и никогда не используется, на API 33+ без запроса всё равно не покажется). Deep-link `vedalibrary://verse` объявлен (`AndroidManifest.xml:42-47`), но **никто не парсит `intent.data`** — ссылка молча открывает библиотеку. Плюс: фоновой аудио не существует (ExoPlayer внутри Activity, `release()` в `onDispose`) — при сворачивании музыка/ТTS умирает, Foreground Service был бы уместен.

### Производительность
23. **[Important]** `LibraryDbImporter.kt:504-512` — существование стиха проверяется **по одному PK на каждую аудио-запись × кандидат-книга** (до 20 000 round-trip'ов). → `WHERE id IN (...)` батчем (`verseLightsByIds` уже есть).
24. **[Important]** `ViewModels.kt:747,786-793` — `neighborVerse`/`findInChapter`: до 50 итераций, каждая грузит **все лёгкие стихи главы**, чтобы взять `first()`/`last()`. → `ORDER BY … LIMIT 1`.
25. **[Important]** N+1 в `UpdateViewModel.kt:219-221` — `countVerses(id)` на каждую установленную книгу при каждой проверке каталога; `audioPacks()` (`LibraryDbImporter.kt:646-702`) на каждый открытие настроек перечитывает все манифесты и `stat()`-ит все аудио-файлы.

---

## 4. Suggestions (по желанию, но дешёвые)

- **S-1** `HtmlText.kt:34` — `GbHtml.rich()` создаёт **7 новых `Regex` на каждый вызов** (вызывается сотнями строк), `wholeWord:220` компилирует regex на строку. При этом в файле уже есть образец precompile (`linkRe`, `tagRe`). → Вынести в top-level `val`.
- **S-2** `HtmlText.kt:661,702,777,794,817` — `Log.d("SelMenu", …)` в release-пути (R8 не стрипает Log без `-assumenosideeffects`). → `if (BuildConfig.DEBUG)` или правило ProGuard.
- **S-3** `ChapterScreen.kt:197`, `SearchScreen.kt:110` — `GbHtml.plain()` (полный HTML-парс) выполняется в composition на каждую строку и **пере-парсится при каждом возврате строки в viewport** (state в lazy-item теряется). → Считать plain-text один раз при построении `VerseItem`.
- **S-4** `ViewModels.kt:261,365` — иллюстрации грузятся целиком ради счётчика / фильтруются в памяти. → `COUNT(*)` и запрос по главе.
- **S-5** `ReadFont.kt:29` — кэш typeface не кэширует **неудачу** (бесконечные повторные попытки загрузки шрифта).
- **S-6** Мёртвый код: `SearchViewModel.dictionary` (`ViewModels.kt:208`), `SettingsViewModel.importDb` (`SettingsScreen.kt:121`) — без вызовов.
- **S-7** `proguard-rules.pro:2` — `-keep class androidx.room.** { *; }` отключает любую shrinking-пользу Room; достаточно consumer-rules самой библиотеки.
- **S-8** VM принимают навигационные лямбды параметрами (`ViewModels.kt:44,291,306,153`) — устаревший NavController из освобождённой композиции. → Возвращать значения, навигировать в вызывающем через `rememberUpdatedState`.
- **S-9** `LibraryScreen.kt:237` — `coverPath` делает `File.exists()` на главном потоке и **навсегда кэширует null** (обложки, добавленные позже, не появятся до пересоздания VM) — это и есть ошибка lint.
- **S-10** `TxtImporter.kt:28` и др. — `openInputStream(uri)!!` → NPE при отозванном SAF-grant; `PdfImporter.kt:33` — «Пустой PDF» импортируется **как книга** с текстом-заглушкой вместо ошибки.
- **S-11** `LibraryDbImporter.kt:810-818` — импорт заметок: до 10 000 insert'ов по одному, `book_id`/`txt_row_id` отбрасываются (все заметки «общие»).
- **S-12** `NotesScreen` лежит в `LibraryScreen.kt:310`, `FavoritesScreen` — там же, `SettingsViewModel` — в `SettingsScreen.kt`, всё вместе с 1088-строчным `ViewModels.kt`. → Разбить по фичам.
- **S-13** Размер diff: рабочая копия меняет **38 файлов / ~4600 строк** разом (плюс untracked) — при таком темпе ревью невозможно. Дробить на коммиты по фиче (обновления / шрифты / CrashLog / навигация).

---

## 5. Что сделано хорошо

- **Нет** `GlobalScope`, `runBlocking`, `allowMainThreadQueries`; все DAO — suspend/Flow, тяжёлое — на `Dispatchers.IO`.
- DI чистый: один `AppDatabase`-синглтон, импортеры `@Singleton`, VM — `@HiltViewModel`, `StateFlow` из VM (кроме отмеченных исключений).
- SHA-256 для обновлений **есть** (хотя и fail-open), проверка целостности файла >1 КБ, FileProvider непубличный, экспортный экран — только `MainActivity`.
- Юникод/PUA-таблицы, NFC-нормализация со смещениями (O(n²) → линейная), regex'ы частично прекомпилированы — видна забота о производительности.
- Комментарии объясняют *почему* (включая костыли под Xiaomi/ColorOS) — это редкость и ценность.
- Бэкап-менеджер + авто-бэкап заметок — правильный инстинкт защиты данных.
- Своя эмодзи-навигация и «спокойный» M3 — UI-консистентность держится.

---

## 6. План действий (приоритезированный)

**P0 — сегодня:**
1. Отозвать GitHub PAT, вынуть из исходника (Critical 1).
2. Решить судьбу destructive fallback: `exportSchema=true` + миграции 1→2/2→3 + downgrade-fallback (Critical 2).
3. `@Transaction` на переимпорт книги (Critical 3).

**P1 — до следующего релиза:**
4. Fail-closed sha256 + санитизация `key` + параметризованный SQL.
5. `dataExtractionRules` (allowBackup) + сузить FileProvider.
6. Атомарный DataStore, `CancellationException` rethrow, try/catch у `addNote`.
7. Debounce/экранирование поиска, `popUpTo(saveState)` у табов, аудио-плеер на уровне экрана.
8. Потоковый аудио-импорт, честный restore-отчёт, единый `deleteBook`.
9. Прогнать `lintDebug` в зелёное (фикс 7 ошибок).

**P2 — технический долг:**
10. Первые тесты: миграции Room (MigrationTestHelper), `GbHtml`/regex-парсеры, `parseBookInfos`, FTS-экранирование — это чистые JVM-тесты без эмулятора.
11. Слой Repository (хотя бы для книги/заметок/поиска) + разбить `ViewModels.kt`.
12. Выкинуть мёртвые разрешения/код, включить `Log.d`-стрип, обновить room/media3/navigation.
13. Фоновая музыка: Foreground Service (иначе зачем разрешения).

---

## 7. Отдельно: почему на ColorOS не работает выравнивание по ширине

### Что настраивает приложение (и что НЕ является причиной)

`HtmlText.kt:375-384` при `justify=true` (перевод/комментарий в `VerseDetailScreen.kt:325,332`):
- `justificationMode = JUSTIFICATION_MODE_INTER_WORD` ✅
- `hyphenationFrequency = HYPHENATION_FREQUENCY_FULL` ✅
- `breakStrategy = HIGH_QUALITY`, на ColorOS — `BALANCED` (хак `isColorOs()`, `HtmlText.kt:378`) ⚠️
- `gravity = START`, `textAlignment = INHERIT` для не-центра ✅
- Списки глав/стихов идут отдельным путём: Compose `Text(textAlign = TextAlign.Justify)` (`ReaderScreen.kt:44`, `ChapterScreen.kt:50`)

Все эти настройки **достаточны и правильны для стокового Android** — на Samsung они и работают.

### Корневая причина (уверенность: высокая)

**ColorOS (OPPO/Realme/OnePlus) патчит собственный текстовый стек и молча выбрасывает justification на уровне фреймворка/рендера.** Не ошибка в настройках приложения — вызов доходит до `StaticLayout`/`Layout`, но пиксели не растягиваются: ни ошибки, ни лога, ни возврата.

Доказательство — управляемый инструментированный репро (сентябрь 2026):
- **RN-issue:** https://github.com/react/react-native/issues/58652 — «textAlign: justify silently ignored on ColorOS 15»
- **Репо с 13-вариантной матрицей:** https://github.com/kaushaldarji29/ColorOSJustifyRepro — проверили по отдельности: plain justify, +HIGH_QUALITY, +BALANCED, +SIMPLE, +lineHeight, +hyphenation, вложенные тексты, **4 шрифта (системный, sans-serif, два вшитых в APK)**, `includeFontPadding:false`.
- **Стоковый Android 16 (эмулятор): все пробы выравнивают. ColorOS 15 (Realme RMX3686, API 35): «JUSTIFIED on this device: none»** — меряли ширину строк попиксельно.
- То есть опровергнуты гипотезы: не шрифт, не break strategy, не hyphenation, не lineHeight, не «нужен HIGH_QUALITY + hyphenation».

**Где именно рвётся** (ниже уровня приложения, два кандидата):
- **Слой A — Java-фреймворк:** в AOSP justification применяется при **отрисовке**: `Layout.drawLine()` → `TextLine.justify()` → `Paint.setWordSpacing()` (AOSP `Layout.java` ~933, `TextLine.java` 293-330). Патч, делающий `isJustificationRequired() == false` или `TextLine.justify()` no-op, убивает всё, при этом `getJustificationMode()` продолжает отвечать `INTER_WORD`.
- **Слой B — нативный рендер (hwui/Minikin/Skia):** натяжение считается в Java, но рисуется через word-spacing в нативе; ColorOS-патч там убивает результат после вычисления.
- ColorOS — один из самых переписанных форков Android (`oplus-framework.jar` поверх патченного `framework.jar`), глобально переопределяет шрифты/веса («无极字体», OPPO Sans). Точный слой определяется только дампом `framework.jar` с устройства и диффом `android.text.Layout`/`TextLine`.

**Почему Samsung работает:** никаких признаков того, что One UI *включает* выравнивание само. Samsung подменяет шрифт (One UI Sans), но **не трогает путь `Layout/TextLine` → word-spacing**, поэтому ваш настройенный API просто работает.

**Также проверено и НЕ является причиной на ColorOS:**
- `setTextIsSelectable(true)` (`HtmlText.kt:335`) — известно, что selectable может гасить justify на части AOSP-устройств (SO 58600246, 69777647), но RN-репро работает **без selectable** и всё равно падает на ColorOS → основная причина — OEM; на ваших Samsung с тем же selectable выравнивание есть.
- Последняя строка абзаца никогда не выравнивается (by design), строка без ASCII-пробелов тоже — не путать с багом.

### Диагностика (15 минут, ColorOS-устройство)

1. **Проба Compose vs TextView:** список стихов (`TextAlign.Justify`) против карточки стиха (TextView). Если списки выравниваются, а карточка нет — патч только в `TextView`; тогда перенос карточки на Compose-текст = дешёвый фикс. Если оба нет — патч ниже (скорее всего).
2. **Проба word-spacing:** нарисовать строку `canvas.drawText("aa bb cc dd", paint.apply { wordSpacing = 40f })`. Зазоры выросли → патч в Java-слое, достаточно workaround 2a. Не выросли → патч в нативе, нужен 2b/WebView.
3. **Проба selectable:** временно снять `setTextIsSelectable(true)` на ColorOS — исключить вторичный фактор.

### Решения (по трудоёмкости × шансу)

| # | Решение | Труд | Шанс на ColorOS |
|---|---|---|---|
| 1 | **WebView** (`text-align: justify; hyphens: auto`) — Blink делает свою вёрстку, не зависит от `android.text` и word-spacing | средне | **высокий** (исторически принятый ответ сообщества: SO 1292575) |
| 2a | **Свой `onDraw` + `StaticLayout` + `paint.wordSpacing` на строку** (разбивка по пробелам строки, ручное растяжение ~50-100 строк) | низко-средне | высокий, **если** проба 2 показала рабочий word-spacing |
| 2b | **Свой `onDraw` с позиционированием каждого слова** (`x += measureText(word) + gap`) | средне-высоко | **максимальный** (обходит оба слоя) — так делают все justify-библиотеки: github.com/nikoo28/justify-textview-android, github.com/bluejamesbond/TextJustify-Android |
| 3 | Compose `TextAlign.Justify` вместо TextView | тривиально | неизвестен → **бесплатный тест**, но RN-репро через `StaticLayout` упал → вряд ли |
| 4 | Вставка thin/soft-hyphen символов в текст | средне | низкий, хрупкий (нужны границы строк заранее) |
| 5 | `LineBreaker` API (33+) | — | это только измеритель, рисовать всё равно самому |
| 6 | **Детект + фоллбэк:** `isColorOs()` (уже есть в `HtmlText.kt:392`) переключает путь рендера | низко | надёжная продуктовая стратегия: «на ColorOS — запасной рендер» |

**Рекомендация:** (1) диагностика по пробам 1-3; (2) если нативный word-spacing жив — вариант **2a** (самый лёгкий, переиспользует ваш уже настроенный `StaticLayout` с hyphenation'ом); (3) если мёртв — вариант **1 (WebView)** для блока перевода/комментария или **2b**, если хочется остаться в TextView; (4) детект через существующий `isColorOs()`. Стоит additionally оставить информацию в RN-issue #58652 (там как раз собирают подтверждения) и в dev-канале OPPO.

**Источники:**
- RN #58652: https://github.com/react/react-native/issues/58652 · репро: https://github.com/kaushaldarji29/ColorOSJustifyRepro
- AOSP mechanics: `Layout.java` (isJustificationRequired/justify при draw), `TextLine.java` (setWordSpacing), `TextView.java` (дефолты SIMPLE + NONE), Minikin `LineBreaker.cpp`/`OptimalLineBreaker.cpp` (break strategy влияет на *качество*, не на вкл/выкл)
- Compose mapping: `AndroidParagraph.android.kt` (`TextAlign.Justify → JUSTIFICATION_MODE_INTER_WORD`)
- selectable-гасящие баги: https://stackoverflow.com/questions/58600246/, https://stackoverflow.com/questions/69777647/
- Ручная реализация: https://github.com/nikoo28/justify-textview-android, https://github.com/bluejamesbond/TextJustify-Android
- Цвет/переопределение шрифтов в ColorOS: https://github.com/callstack/react-native-paper/issues/3472
