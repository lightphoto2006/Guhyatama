# VedaLibrary — читалка книг и лекций для Android (Native Kotlin + Compose)

Офлайн-библиотека: книги, лекции, поиск, словарь + импорт транскрибированных лекций из PDF/TXT.

## Стек (тренды 2026)
- **Kotlin + Jetpack Compose + Material 3 Expressive** (dynamic color, edge-to-edge, dark/night mode)
- **Adaptive**: NavigationSuiteScaffold (phone / foldable / tablet, List-Detail)
- **Offline-first**: Room + FTS5, Paging3, DataStore, WorkManager, Coil, R8 + Baseline Profiles
- **DI**: Hilt; **Навигация**: Navigation-Compose type-safe; **TTS**: android.speech.tts + Media3; **PDF**: pdfbox-android + PdfRenderer fallback

## Возможности (21)
| Раздел | Реализация |
|---|---|
| Search all books (sanskrit/verse/purport) | `VerseFts` (FTS4/5) + `searchFts()` + scope-фильтр в `SearchScreen` |
| Dictionary tab | `dictionaryLookup()` — все стихи со словом |
| Comparing translations | `Verse.sanskrit/text/purport` + side-by-side в Reader (TODO: второй слот перевода) |
| Highlights & notes | `Highlight`, `GeneralNote` + Reader-кнопки |
| Topics & tags / Nested tags | `Tag(parentId)` + `VerseTagCrossRef` |
| Chapters in Sanskrit | `Chapter.sanskritTitle`, `Verse.sanskrit` |
| Cross-references | `CrossRef` + `TxtImporter.extractCrossRefs()` + deep-link `vedalibrary://verse` |
| Night mode | M3 dynamic dark scheme |
| Page-by-page | `Verse.pageLabel` + LazyColumn paging |
| General notes | `GeneralNote(verseId=null)` |
| Bookstore | `StoreApi` + `PackageInstaller` (.gbpkg = zip{manifest.json, library.db}) |
| Reading aloud | TTS-кнопка в `ReaderScreen` |
| Memory cards | `Flashcard` (SM-2: ease/interval/nextReview) |
| Illustrations | `Illustration` + Coil |
| Backup & restore | TODO: SAF JSON-export `Highlight+Note+Tag` (сериализация уже подключена) |
| Random verse | `randomVerse()` + Worker |
| Reading time estimator | `Book.totalReadingMinutes = words/150` при импорте |
| Push daily verses | `DailyVerseWorker` (24ч) + channel `daily-verse` |
| AI Index | Заглушка: FTS + будущий on-device embedding (TODO) |
| Offline mode | Всё в Room, сеть только для Store |

## Импорт лекций/произведений (гибрид)
- **TXT/MD**: SAF-picker → `TxtImporter` → `TextCleaner.clean()` (мусор, колонтитулы, переносы) → `ChapterSplitter` (маркеры Глава/Лекция/## или чанки 4000 симв.) → batch-вставки по 500.
- **PDF**: SAF-picker → копия в cache → `PdfImporter` (pdfbox `sortByPosition=true` чинит 2 колонки) → тот же pipeline. Сканы без текстового слоя → сообщение «нужен OCR».
- **Пакеты**: `PackageInstaller.installFromZip()` (.gbpkg = zip{manifest.json, library.db}).

## Структура
```
app/src/main/java/com/vedalibrary/app/
  MainActivity.kt, VedaApp.kt
  data/local/AppDatabase.kt (11 таблиц + DAO)
  data/import/{TextCleaner,ChapterSplitter,TxtImporter,PdfImporter}.kt
  data/pkg/PackageInstaller.kt  data/store/StoreApi.kt
  ui/{theme/Theme,navigation/NavGraph,screens/{Library,Search,Reader},vm/ViewModels}.kt
  work/DailyVerseWorker.kt  di/AppModule.kt
```

## Сборка
1. Открыть `F:\AI\тест2` в Android Studio Ladybug+.
2. Sync Gradle, `Run ▶`. minSdk 26, target 35.
3. Тест импорта: Библиотека → FAB `TXT`/`PDF` → выбрать транскрипт лекции.

## Следующие шаги (по приоритету)
1. Reader: выделение текста (SelectContainer), цвета highlight, side-by-side переводов.
2. Backup/restore JSON через SAF + авто-бэкап в WorkManager.
3. Store-экран: список пакетов, DownloadManager, прогресс.
4. Flashcards UI + SM-2 review loop + уведомления.
5. On-device AI-индекс (MediaPipe LLM / embeddings) для тематического поиска.
6. Baseline Profile generator + Macrobenchmark.
