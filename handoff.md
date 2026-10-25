# Handoff: Guhyatama (VedaLibrary) — 2026-10-10

## Окружение (главное для новых сессий)
- Каноническое местоположение проекта: `F:\AI\Development\Guhyatama` (git-репозиторий).
- Старая папка `F:\AI\тест2` удалена полностью (и junction-ярлык на её месте тоже убран — Explorer показывал его как «вторую копию 3 ГБ», хотя данные одни).
- JAVA_HOME (JetBrains Runtime из Android Studio): `F:\AI\Development\Android\jbr`, версия 25.0.2.
  ВНИМАНИЕ: Gradle 8.7 может не поддерживать JDK 25 — предыдущие сборки падали на конфигурации за 2-3 сек с сообщением «25.0.2». Решения: JDK 17/21 через org.gradle.java.home в gradle.properties, или обновить Gradle/AGP.
- Android SDK: `C:\Users\light\AppData\Local\Android\Sdk` (прописан в local.properties: sdk.dir).
- local.properties содержит githubFilesToken — НЕ коммитить (файл в .gitignore).
- Версии: Gradle 8.7, AGP 8.6.0, Kotlin 2.0.21, KSP 2.0.21-1.0.25, приложение 1.3.15 (vc63), каталог vc63, сборник Acharyi_rus v9.
- gradle.properties: org.gradle.jvmargs=-Xmx4g -Dfile.encoding=UTF-8.
- Пример сборки (PowerShell):
  cd F:\AI\Development\Guhyatama
  $env:JAVA_HOME="F:\AI\Development\Android\jbr"
  .\gradlew.bat :app:compileDebugKotlin --console=plain
- Python: системный; для tools/dbcomposer нужен `pip install bsdiff4` (make_apk_delta.py).

## Git
- HEAD: d474613 (2026-10-07, docs: README (deltas, tests), release catalog, user manual).
- Незакоммичено ~48 файлов — работа этапов 2-4 и текущей сессии. Коммиты не делать без явной просьбы.
- remote не настроен.

## Выполнено
1. Звезда закладок в библиотеке: тап по правой части звезды — размер ×1.5 (33/24/39 sp, зона starZone 54.dp) — app/.../ui/screens/LibraryScreen.kt
2. Долгое нажатие снятия закладки: 2000 → 1000 мс — app/.../ui/components/BookmarkStar.kt
3. Cleanup каталога updates/: cleanupInstalledApks() удаляет установленные .apk/.part/.db и осиротевшие .bsdiff/.bsdiff.part — app/.../data/update/AppUpdater.kt
4. Дельта-обновления APK без маркета (как Play Market):
   - Клиент: Bspatch.kt (BSDIFF40-применитель, воспроизводит подписанный new.apk байт-в-байт; ключ подписи не нужен); поля delta* в ApkInfo (UpdateCatalog.kt); ветка дельты + fallback на полный APK в UpdateViewModel.download()
   - Сервер: tools/dbcomposer/make_apk_delta.py (патч от старого подписного APK к новому), make_catalog.py считает delta*-поля
   - updates/versions.json — заполнить реальными delta*-значениями при релизе
5. (Ранее) AI-импорт, дельты книг, delta-импорт — все python-тесты зелёные.
6. Релиз v1.3 (vc48) опубликован: GitHub release Guhyatama-1.3.apk, catalog.json на main обновлён до 48; следующий релиз можно дельтить от 48 (патч строится make_apk_delta.py от скачанного v1.3).

## Публикация на GitHub Releases (схема)
- В GitHub Release выкладывать ПОЛНЫЙ подписанный APK (для новых пользователей) + патч .bsdelta + обновлённый catalog.json.
- Приложение скачивает патч только если установленный versionCode == delta.from; иначе fallback: полный APK.
- Первый релиз с этой дельта-системой: все качают полный APK. Дельты начнут работать со второго релиза — для тех, кто установил первый.
- Хранить старые подписные APK байт-в-байт — от них строятся патчи.
- каталог `catalog.json` публикуется ассетом техрелиза с тегом `catalog` (prerelease), приложение читает `https://github.com/lightphoto2006/Guhyatama/releases/download/catalog/catalog.json`; raw/API — только fallback; CDN-кэш на обновления больше не влияет; ветка `master` удалена, единственная — `main`.

## Решения
- Журнал сессии 2026-10-25: [docs/SESSION_2026-10-25.md](docs/SESSION_2026-10-25.md)

## TODO
1. Проверить компиляцию :app:compileDebugKotlin из нового ASCII-пути; решить проблему JBR/Gradle (см. Окружение).
2. Запустить python-тесты tools/dbcomposer из новой папки (пути в тестах могут содержать старый путь — проверить).
3. E2E на устройстве: звезда ×1.5, long-press 1с, дельта-обновление, очистка updates/ после установки.
4. Установить v1.3.7 на устройство (сделано 20.10: релиз v1.3.7 стоит, закладка id=45 восстановлена, удержание экрана вернулось в 0). Осталось глазами проверить поиск на месте: «праламб» → 24 стиха в 10-й песни ШБ + 8 в «Гопала Чампу» (телефон был заблокирован — экрана не видно).

## Релиз v1.3.7 (vc55) — опубликован 20.10.2026
- Коммит: 595a716 (release: v1.3.7 (vc55) + дельта 54->55), запушен в origin/main.
- GitHub Release v1.3.7 (id 418186326): Guhyatama-1.3.7.apk (5 952 530 Б, sha256 2492e10e…) + Guhyatama-delta-54-to-55.bsdiff (5 976 490 Б, sha256 8b9785a1…). Дельта самопроверена — new воспроизводится байт-в-байт.
- Каталог (updates/catalog.json + корневой catalog.json): apk vc55, deltaFrom 54, deltaSize 5976490.
- **Поиск: слова через дефис.** В книге слова написаны так («праламба-бахум», «шримад-бхагаватам»), а FTS4 `simple` режет текст по дефису на два токена. `ui/vm/SearchQuery.kt`: слово запроса с дефисом ищется и склеенным («праламба»), и по частям («пра» + «ламба»), плюс отдельная OR-группа для варианта без дефиса. Токенизация ТЕКСТА в scope-фильтре и подсветке приведена к FTS (`TOKEN = LETTER+`, дефис — граница токена) — иначе фильтр по разделу отсекал бы живые совпадения.
- Проверено настоящим Kotlin-кодом по базе устройства (68899 стихов), стенд в `C:\Users\light\AppData\Local\Temp\kilo\harness`: «праламб» → 61, «пра-ламба» → 48, «шримад-бхагаватам» → 9, «праламба-бака» → 1, «ади лила» → 75, «пра» → 24; scope «Стих»/«Коммент.» отбирает корректно, подсветка целого слова работает.

## Устройство (20.10.2026)
- Установлен релиз v1.3.7 (vc55): `adb install -r releases\Guhyatama-1.3.7.apk` (подпись — debug.keystore, обновление поверх старой версии сохраняет данные).
- Закладка восстановлена ровно как была: id=45, bookId='gb-cc-4-rus', verseId=NULL, chapterId='gb-cc-4-rus/ch-2-2', scrollIndex=34, scrollOffset=462, createdAt=1791489504114.
- **Как править БД на установленном релизе**: релизная сборка не debuggable → `run-as` не работает. Путь: поставить debug-APK той же версии (`assembleDebug`, подпись та же) → `adb exec-out "run-as com.vedalibrary.app cat databases/vedalibrary.db"` (+ `-wal`, `-shm`) → править локально (python sqlite3) → `PRAGMA wal_checkpoint(TRUNCATE)` → `adb push` в /data/local/tmp → `run-as … sh -c 'cp … databases/vedalibrary.db && rm -f databases/vedalibrary.db-wal databases/vedalibrary.db-shm'` → вернуть релизный APK. Без удаления -wal/-shm на устройстве база откроется битой.
- Экран: `screen_off_timeout=120000` (не трогали), `stay_on_while_plugged_in=0`, `mStayOn=false` — штатный режим. Внимание: `settings put system stay_on_while_plugged_in 15` на Android 17 падает («Invalid value»), максимум 7; `svc power stayon true` ставит 7 — после диагностики надо вернуть 0.
- Телефон (OPPO PLG110) периодически отваливается по USB — ADB надо перезапускать, а `adb devices` может показывать пусто.

## Релиз v1.3.6 (vc54) — опубликован 20.10.2026
- Коммиты: 20f3d17 (правки) + 079766c (релиз). Запушено в origin/main.
- GitHub Release v1.3.6 (id 418160161): Guhyatama-1.3.6.apk (5 952 530 Б) + Guhyatama-delta-53-to-54.bsdiff (5 957 674 Б). Подпись та же (debug.keystore), патч самопроверен — new воспроизводится байт-в-байт.
- Каталог (updates/catalog.json и корневой catalog.json — его читает клиент, CATALOG_URL): apk vc54, size 5952530, sha256 3ac09da2…, deltaFrom 53, deltaSize 5957674, deltaSha bf80fa93….
- **make_catalog.py теперь сам считает size/sha256 APK** из versions.json («file») — раньше эти поля в каталог попадали вручную, а без sha256 клиент отменяет обновление (AppUpdater.download: «в каталоге нет контрольной суммы»). В versions.json у apk теперь есть «file».

## Правки 19–20.10.2026 (закоммичены, релиз v1.3.6)
- **Поиск** (жалоба: «ищу праламбасур, пишу праламб — ничего не находит; с большой буквы — одно вхождение»). Причина: FTS4-токенизатор `simple` сворачивает регистр ТОЛЬКО для ASCII — кириллица искалась строго по написанию, а точная фраза не ловит частичное слово. Новый `ui/vm/SearchQuery.kt`: слова запроса с вариантами регистра (строчное/С-заглавной/ПРОПИСНОЕ), префикс у последнего слова (от 4 букв — на 2–3 буквах выдача взрывается), scope-фильтр по разделам перенесён в Kotlin (в FTS4 `col:"фраза"` всегда 0 строк, `col:(...)` фильтрует только первый терм — раздел «Стих»/«Санскрит»/«Коммент.» не отбирал ничего), сниппет и подсветка ищут ТОКЕН, а не подстроку запроса. Проверено настоящим Kotlin-кодом по базе устройства (68899 стихов): «праламб» → 61 совпадение (было 0), из них 24 в 10-й песни ШБ и 8 в «Гопала Чампу». Словарь — та же правка.
- **Звезда закладки — свой вектор** `ui/components/StarIcons.kt` (залитый/контурный из одного контура). Причина: у `material-icons-core` нет контурной звезды (неактивная закладка выглядела бы как активная), а текстовый глиф «★» и эмодзи «⚙️» имеют разные метрики и разъезжались по вертикали. Размер 26.dp.
- **Шестерёнка** в шапках главы и стиха — `Icons.Filled.Settings` (тот же вектор, тот же размер). Замер на устройстве: центры иконок 434/436 px (было 411/413 при разных размерах).
- **Закладка в главе**: `saveChapterBookmark` пишет `verseId = null` (текущее место главы = позиция списка), `active` в шапке главы больше не требует `verseId == null` — звезда горит, если закладка стоит в этой главе.
- **Закладка в читалке стиха**: `setBookmark` переносит её на текущий стих, сохраняя позицию главы, если закладка уже была в этой главе.
- **Justify**: строки из 3+ слов растягиваются до правого края всегда; порог `add > spaceW * 2` остался только для строк из ДВУХ слов (одного промежутка). Подробности — `docs/JUSTIFY.md`.

## Ключевые файлы
- Выравнивание по ширине (ColorOS, ручная доводка): `docs/JUSTIFY.md` + `app/src/main/java/com/vedalibrary/app/ui/components/HtmlText.kt`
- Звезда закладки (вектор): `app/src/main/java/com/vedalibrary/app/ui/components/StarIcons.kt` + `BookmarkStar.kt`
- app/src/main/java/com/vedalibrary/app/data/update/{AppUpdater,Bspatch,UpdateCatalog,Downloader}.kt
- app/src/main/java/com/vedalibrary/app/ui/vm/UpdateViewModel.kt
- app/src/main/java/com/vedalibrary/app/ui/screens/LibraryScreen.kt
- app/src/main/java/com/vedalibrary/app/ui/components/BookmarkStar.kt
- tools/dbcomposer/{make_apk_delta.py,make_catalog.py,README.md}
- updates/versions.json (+ catalog.json)

## Ключи GitHub (маски, где лежат)
Инвентарь от 2026-10-11. Значения нигде не выводились; маска = первые 8 символов + «…». Проверка типов: GET /user (владелец) и GET /repos/{owner}/{repo} → поле permissions (специального эндпоинта /permissions в GitHub API нет — отвечает 404; коды зафиксированы ниже). X-OAuth-Scopes пуст везде — все живые ключи fine-grained (у них scopes нет, вместо них access-листы).

| файл | маска | тип | Guhyatama (app) | Guhyatama-files | примечание |
|---|---|---|---|---|---|
| `C:\Users\light\.secrets\github_pat.txt` | github_p… | fine-grained PAT | admin/maintain/push/pull/triage — все true | все true | владелец lightphoto2006; рабочий; самый широкий |
| `C:\Users\light\.secrets\github_pat_catalog.txt` | github_p… | fine-grained PAT | admin/maintain/push/pull/triage — все true | нет доступа (404 на GET репо — репозиторий для него не виден) | владелец lightphoto2006; рабочий; только для каталога/app-репо |
| `C:\Users\light\.secrets\github_pat_ro.txt` | github_p… | fine-grained PAT | 401 | 401 | НЕДЕЙСТИВЕН (просрочен/отозван); ничего не может |
| `githubFilesToken` в `F:\AI\Development\Guhyatama\local.properties` | github_p… | fine-grained PAT | все true | все true | владелец lightphoto2006; НЕ совпадает ни с одним ключом из .secrets; ⚠ через BuildConfig попадает в собранный APK (см. ниже) |
| `C:\Users\light\.secrets\filebase.json` | access: `4D5B4D43…` (20), secret: `B8bWutVm…` (40) | Filebase S3 (не GitHub) | — | — | endpoint `https://…` (22 симв.); используется tools/dbcomposer/s3filebase.py; значения в файлах репо не найдены |

- Пуш приложения делается через Credential Manager (GCM OAuth gho_…, scopes repo) — git push работает без явного токена. Релизы — тем же GCM-токеном через API (git credential fill).
- Все 4 GitHub-ключа маскируются одинаково (github_p…), различаются только именем файла; первые 17 символов у всех четырёх совпадают.
- Ни одно значение из `.secrets\*` и `githubFilesToken` не встречается в исходниках/доках репозитория (проверено поиском по значениям). Ссылки на путь `C:\Users\light\.secrets\` (без значений) есть в `tools/dbcomposer/s3filebase.py` (CREDS) и `docs/CORRECTION_PLAN.md`.
- ⚠ build-артефакты содержат githubFilesToken (он вшивается в BuildConfig): `.gradle\8.7\executionHistory\executionHistory.bin`, `app\build\**` (BuildConfig.java/.class, classes.dex release). Всё это покрыто `.gitignore` (проверено `git check-ignore`), но токен физически внутри релизного APK — при случае его стоит ротировать/ограничить (CORRECTION_PLAN.md называл это «плохим токеном»; хардкода в UpdateCatalog.kt уже нет — проверено).
- ⚠ `docs/AUDIT.md` содержит 17-символьный префикс живых токенов (первые 17 симв. совпадают у всех четырёх) — это не значение целиком, но при публичном репо фрагмент лучше убрать.
- Каталог `.secrets` лежит вне репозитория (в домашней папке), в `.gitignore` упоминаний значений нет; `local.properties` в `.gitignore` включён.

