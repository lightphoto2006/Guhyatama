# План пошаговой коррекции (без публикации в git)

Принципы:
- **Ни одного `git add/commit/push` и ни одного релиза** — всё в рабочей копии, проверяется локально.
- Каждый этап: правки → автопроверка → установка debug-сборки через Android Studio (Shift+F10) → ручной чек-лист на устройстве.
- Версию в `app/build.gradle.kts` (versionCode/versionName) не трогаем до самого конца — каталог обновлений её не видит.
- Общая автопроверка перед каждым этапом и после него:
  ```
  gradlew :app:compileDebugKotlin      # компиляция
  gradlew :app:lintDebug               # цель: 0 errors (сейчас 7)
  gradlew :app:assembleDebug           # APK для установки
  ```
  Запуск в Android Studio: открыть проект → выбрать устройство/эмулятор → Run ▶.

---

## Этап 0 — GitHub-токен (P0, ключ в исходниках)

**Ситуация:** `UpdateCatalog.kt:13` содержит `GITHUB_FILES_TOKEN = "github_pat_…"` — это **один и тот же ключ** и для скачивания приватных БД приложением, и лежащий в исходниках. Он ещё не закоммичен (`UpdateCatalog.kt` — untracked), но уже попадает в любой собранный APK. В git-истории ключей нет; S3-ключи вынесены правильно (`C:\Users\light\.secrets\filebase.json`), батник `DB git upload.bat` токена не содержит (заглушка `{encoded}`).

Шаги:
1. На github.com: Settings → Developer settings → Fine-grained tokens → **создать новый** токен, репозиторий `Guhyatama-files` (или где лежат приватные релизы), доступ только **Contents: Read-only**.
2. В `local.properties` (он в `.gitignore`, в git не попадёт) добавить:
   ```properties
   githubFilesToken=github_pat_НОВЫЙ_ТОКЕН
   ```
3. `app/build.gradle.kts`:
   ```kotlin
   buildFeatures { compose = true; buildConfig = true }
   // внутри android { }:
   val ghToken = providers.fileContents(layout.projectDirectory.file("../local.properties"))
       .asText.orNull?.lines()?.firstOrNull { it.startsWith("githubFilesToken=") }
       ?.substringAfter("=")?.trim().orEmpty()
   defaultConfig {
       buildConfigField("String", "GITHUB_FILES_TOKEN", "\"$ghToken\"")
   }
   ```
   (путь к local.properties уточнить: он в корне проекта, т.е. `layout.projectDirectory.file("../local.properties")` для модуля `app`.)
4. `UpdateCatalog.kt`: удалить `const val GITHUB_FILES_TOKEN`, заменить использования (`UpdateViewModel.kt:343,347`) на `BuildConfig.GITHUB_FILES_TOKEN`.
5. **Отозвать старый токен** на github.com (Delete) — только после успешного пункта проверки.

Проверка этапа:
- [ ] `Select-String -Path (Get-ChildItem app -Recurse *.kt) -Pattern "github_pat_"` → 0 совпадений.
- [ ] `gradlew :app:assembleDebug` → BUILD SUCCESSFUL.
- [ ] Установка через Android Studio, Настройки → «Обновить список книг» → скачать приватную книгу → новый токен работает.
- [ ] Старый токен отозван (проверка: старый отдаёт 401) → обновление приложения/книг по-прежнему работает.

---

## Этап 1 — Lint в зелёное (7 ошибок)

1. `HtmlText.kt:378-382` — заменить `android.text.Layout.BREAK_STRATEGY_*` / `JUSTIFICATION_MODE_*` на эквиваленты `android.text.LineBreaker.*` (значения идентичны, lint успокаивается). Минус-SDK-проверку `if (SDK_INT >= 26)` (`HtmlText.kt:375`, `AppUpdater.kt:88`) убрать — `minSdk = 26`.
2. `LibraryScreen.kt:237` `ProduceStateDoesNotAssignValue` + баг S-9: переписать `produceState` так, чтобы значение присваивалось в producer-lambda (на IO: `File.exists()`), **не кэшировать `null` навсегда**.

Проверка:
- [ ] `gradlew :app:lintDebug` → **0 errors** (предупреждения — по возможности, отчёт в `app/build/reports/lint-results-debug.html`).
- [ ] На устройстве: обложки книг появляются/обновляются, карточка стиха с выравниванием рендерится как раньше.

---

## Этап 2 — Защита данных (Room) (P0)

1. `AppDatabase.kt:324` → `exportSchema = true`; в `app/build.gradle.kts` в `ksp { arg("room.schemaLocation", "$projectDir/schemas") }`. Папка `app/schemas/` останется локальной (в git не пушим).
2. `AppModule.kt:19` — добавить `fallbackToDestructiveMigrationOnDowngrade()` (откат APK на v10-БД иначе крашит приложение), **оставив** существующий fallback на время (миграции 1→2/2→3 восстановить по схемам этапа 3, если появятся старые `schemas/`; на практике живых v1/v2 пользователей нет).
3. Прогнать все рукописные миграции 3→4 … 9→10 на копиях: `Copy-Item app\schemas\*.json` + `MigrationTestHelper` (androidTest, нужен эмулятор) либо ручная проверка на устройстве ниже.

Проверка (важнее всего — путь апгрейда/даунгрейда):
- [ ] **Апгрейд:** установить лежащий в корне `Guhyatama.apk` (старая версия) → импортировать/создать заметки → поверх установить свежую debug-сборку → **заметки, подсветки, закладки, карточки на месте**.
- [ ] **Даунгрейд:** поверх новой снова поставить `Guhyatama.apk` → приложение стартует (не крашится «migration 10→9 not found»).
- [ ] `app/schemas/` содержит JSON для версии 10 (и все промежуточные — сгенерируются при сборке).

---

## Этап 3 — Целостность обновлений (sha256 fail-closed, пути)

1. `AppUpdater.kt:66-67`, `UpdateViewModel.kt:337-338` — **нет sha256 → отказ** («нет контрольной суммы — не устанавливаю/не импортирую»), вместо `sha.isBlank() || …`.
2. `Downloader.kt` — писать в `*.part`, после `STATUS_SUCCESSFUL` переименовать в конечный файл (атомарно). Тогда частичный файл >1 КБ не пройдёт проверку переиспользования.
3. `UpdateViewModel.kt:336` — санитизация `key`: `key.replace(Regex("[^A-Za-z0-9._-]"), "_")` и отказ при наличии `/` `\` `..`.
4. Перед `importFile` — проверка заголовка `SQLite format 3\0` у скачанного .db.
5. `LibraryDbImporter.kt:304,319,821` — параметризованные запросы (`?` + `selectionArgs`).

Проверка:
- [ ] Happy path: Настройки → «Обновить список книг» → скачать книгу → импорт успешен, sha сошёлся.
- [ ] Негатив (локально, временно): поднять каталог с неверным `sha256` (`python -m http.server 8000` в папке с правленым `catalog.json`), временно указать `CATALOG_URL = "http://10.0.2.2:8000/catalog.json"` (эмулятор) → скачивание заканчивается ошибкой «Контрольная сумма не сошлась», файл удалён. **Вернуть `CATALOG_URL` после проверки.**
- [ ] Негатив key: запись `{"key": "../evil", ...}` в тестовом каталоге → файл создаётся только внутри `updates/books/` либо запись отброшена.
- [ ] Книга с пустым `sha256` → отказ с внятным сообщением.

---

## Этап 4 — Манифест, бэкап, разрешения

1. `AndroidManifest.xml`: создать `res/xml/backup_rules.xml` (`fullBackupContent`, API < 31) и `res/xml/data_extraction_rules.xml` (API 31+), исключив `vedalibrary.db`, `crash_last.txt`, `shared_prefs/updates.xml`, `shared_prefs/search_history*`; подключить к `<application>`.
2. `provider_paths.xml` — сузить: только `external-files-path Download/updates/` + `cache-path` для временных импортов; убрать `files-path "."`.
3. Убрать мёртвые разрешения: `RECEIVE_BOOT_COMPLETED`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_DATA_SYNC` (нет ни receiver, ни service), `POST_NOTIFICATIONS` + мёртвый канал `daily-verse` (`VedaApp.kt:13-15`) — либо вернуть их вместе с фичей «фоновая музыка» на Этапе 8/9.
4. Deep-link `vedalibrary://verse` — **пока убрать** intent-filter (никто не парсит `intent.data`); вернуть вместе с реальной обработкой позже.

Проверка:
- [ ] `gradlew :app:lintDebug` → 0 errors, установка → приложение стартует.
- [ ] Шаринг (стих → «Поделиться») работает — FileProvider не сломан.
- [ ] Установка обновления через апдейтер работает (путь APK в provider остался).
- [ ] Настройки → книги → Скачать — работает (путь .db в provider не нужен, проверить всё равно).
- [ ] `adb shell dumpsys package com.vedalibrary.app | findstr permission` — лишних разрешений нет.

---

## Этап 5 — Критичные баги данных (P0)

1. `LibraryDbImporter.kt:113-133` — переимпорт книги в одной `@Transaction` DAO-методом: сначала прочитать всё новое (staging), потом удалять старое; при исключении — откат и старая книга цела, `isReady` не трогаем.
2. Единый `deleteBook` (один DAO `@Transaction`: verses/chapters/illustrations/refs/bookmarks + удаление файлов аудио/обложек + инвалидация кэшей) вместо двух разных (`ViewModels.kt:122`, `SettingsScreen.kt:60`).
3. `ViewModels.kt:430` — `saveChapterBookmark` → upsert в `@Transaction` без `deleteBookmarksOfBook` (звезда главы не уничтожает стиховую закладку).
4. `TxtImporter.kt:37-49` — весь импорт в одной транзакции (или cleanup при ошибке).
5. `BackupManager.kt:42-50` — rethrow ошибок, честный отчёт числа записей, идемпотентность (upsert/дедуп при повторном restore).

Проверка (ручные сценарии на устройстве):
- [ ] Скачать/обновить книгу → выключить Wi-Fi посреди импорта → книга либо старая целая, либо новая целая; карточка не «⏳» навсегда.
- [ ] Удалить книгу с аудио из экрана Библиотеки → в Настройках файлы пака ушли (нет сирот в `filesDir/audio`).
- [ ] Поставить ★ на главе → стиховая закладка той же книги осталась.
- [ ] Импорт TXT с принудительной ошибкой (обрыв) → книга не появляется полупустой.
- [ ] Настройки → бэкап → Восстановить **дважды** → число заметок не удвоилось; при битом JSON — сообщение об ошибке, а не «Восстановлено».

---

## Этап 6 — Поиск и навигация

1. `ViewModels.kt:195-207` — экранирование FTS (квотирование токенов как в `DictViewModel:976`), пайплайн `debounce(250).distinctUntilChanged().flatMapLatest { … }`, история — только по IME-поиску/после паузы.
2. `NavGraph.kt:72` — табы: `nav.navigate(r) { launchSingleTop = true; popUpTo(Routes.LIB) { saveState = true }; restoreState = true }`.
3. `NavGraph.kt:49` — `selected` выводить из `nav.currentBackStackEntryAsState()` (единый источник правды, переживает поворот).

Проверка:
- [ ] Поиск: ввести `Шримад-Бхагаватам` (дефис!) → есть результаты, не пусто и без ошибки.
- [ ] Быстро печатать → один-два запроса (Profiler/логи), старый результат не затирает новый.
- [ ] История после ввода `krish…` хранит финальную фразу, а не префиксы.
- [ ] Табы: LIB→SEARCH→NOTES→LIB → одно нажатие «назад» закрывает, а не проходит по всем визитам.
- [ ] Поворот экрана → активный таб подсвечен тот же.

---

## Этап 7 — Остальные Important (корректность/UX)

1. `VerseDetailScreen.kt:231-234` — `VerseAudioPlayer` из item'а LazyColumn на уровень экрана (release по DisposableEffect с ключом стиха).
2. `VerseDetailScreen.kt:110` — «стих не найден» по реальному состоянию загрузки, а не по 3-секундному таймеру; `:160-197` — учесть появление аудио-строки в ключах scroll-цели.
3. `ChapterScreen.kt:64-78` — ждать `verses.isNotEmpty()` перед `scrollToItem`; route-аргументы скролла только при первом входе.
4. `ViewModels.kt:471` — try/catch у `addNote`; во всех `catch (_: Exception)` — rethrow `CancellationException` (минимум: в `deleteBook`, импортах, `downloadBook`).
5. `ViewModels.kt:183-187,1001` — публичные `MutableStateFlow` → `StateFlow` + сеттеры.
6. `ReaderSettings.kt:92-145` — read-modify-write внутрь одного `updateData {}` (порядок книг, шрифт по громкости).
7. `VolumeFont.kt:10` — вместо процессного синглтона: `CompositionLocal`/стек владельцев.
8. Уточнить `isColorOs()`-использование: не трогать (нужен для Этапа 9).

Проверка:
- [ ] Стих с аудио → прокрутить за экран и обратно → воспроизведение продолжается/корректно останавливается, TTS не «зависает».
- [ ] Медленная БД (профилировщиком замедлить) → нет ложного «стих не найден».
- [ ] Возврат из стиха в главу из закладки → скролл там, где читал; поворот — тоже там.
- [ ] Быстрые нажатия громкости → шрифт меняется по одному шагу на нажатие (не теряются).
- [ ] Поворот экрана на поиске → ввод/выдача на месте.

---

## Этап 8 — Производительность и мелочи

1. `LibraryDbImporter.kt:465-475` — потоковая запись аудио (строка → файл → освободить), батчами; `:504-512` — `WHERE id IN (…)`.
2. `ViewModels.kt:747,786-793` — `LIMIT 1` вместо загрузки главы; `UpdateViewModel.kt:219` — `GROUP BY`-счётчики; `audioPacks()` — кэш размеров в манифесте.
3. `HtmlText.kt:34,195,220` — precompile regex; `ChapterScreen.kt:197`, `SearchScreen.kt:110` — plain-text строк считать один раз в VM.
4. `Log.d("SelMenu")` — под `if (BuildConfig.DEBUG)`; `-assumenosideeffects` для Log в proguard (release).
5. Мёртвое: `SearchViewModel.dictionary`, `SettingsViewModel.importDb`, `R.string.app_name`-lint.
6. `ReadFont.kt:29` — кэшировать и неудачу загрузки шрифта.
7. `proguard-rules.pro` — убрать `-keep class androidx.room.** { *; }`.

Проверка:
- [ ] `gradlew :app:lintDebug` → 0 errors, warnings заметно меньше.
- [ ] Android Studio → Profiler: импорт большого аудио-пака — **без OOM** (heap-график), скролл `ReaderScreen`/`SearchScreen` — без фризов (FrameTimeline).
- [ ] Настройки → книги: время обновления списка заметно меньше.
- [ ] Release-сборка (`assembleRelease` локально, без публикации): `Log.d` отсутствует (проверить logcat после установки release с debuggable-флагом или по APK через `apkanalyzer`).

---

## Этап 9 — ColorOS: выравнивание по ширине (после стабилизации)

Диагностика на ColorOS-устройстве (15 минут):
1. Проба A: список стихов (Compose `TextAlign.Justify`) vs карточка стиха (TextView `INTER_WORD`) — выравнивается ли каждый путь по отдельности.
2. Проба B: `canvas.drawText("aa bb cc dd", paint.wordSpacing = 40f)` — растут ли зазоры (нативный word-spacing жив → хватит ручного onDraw).
3. Проба C: временно снять `setTextIsSelectable(true)` — исключить вторичный фактор.

Реализация (по результату):
- Если жив word-spacing → **вариант 2a**: свой `onDraw` поверх `StaticLayout` (уже настроенного: HIGH_QUALITY/BALANCED + hyphenation FULL), растяжение пробелов не-последних строк (~50-100 строк кода), включается через существующий `isColorOs()`.
- Если мёртв → **вариант 1**: WebView-блок для перевода/комментария (`text-align: justify; hyphens: auto`) либо вариант 2b (позиционирование каждого слова вручную).

Проверка:
- [ ] Samsung: картинка не изменилась (регрессия — визуально + скриншоты до/после).
- [ ] ColorOS: правый край ровный в блоках перевода/комментария; последняя строка абзаца не выровнена (так и должно быть).
- [ ] Выделение текста, ссылки-цитаты, меню «В заметку» на ColorOS работают как раньше.

---

## Порядок и контрольные точки

| Этап | Риск | Гейт перед следующим |
|---|---|---|
| 0 Токен | Critical | Книги качаются новым токеном, `github_pat_` в *.kt = 0 |
| 1 Lint | Important | `lintDebug` 0 errors |
| 2 Room | Critical | Апгрейд с `Guhyatama.apk` сохраняет данные, даунгрейд не крашит |
| 3 sha256/пути | Important | Негативный тест с битой суммой даёт отказ |
| 4 Манифест | Important | Шаринг и апдейтер работают |
| 5 Баги данных | Critical | Все 5 ручных сценариев пройдены |
| 6 Поиск/навигация | Important | Чек-лист из 5 пунктов пройден |
| 7 Корректность | Important | Аудио/скролл/повороты — без регрессий |
| 8 Перф/мелочи | Suggestion | Profiler без OOM и фризов |
| 9 ColorOS | Product | Ровный край на ColorOS, Samsung без изменений |

После каждого этапа — `compileDebugKotlin` + `lintDebug` + `assembleDebug` + Run ▶ из Android Studio. Git не трогаем до полного прохождения всех этапов; versionCode не трогаем.
