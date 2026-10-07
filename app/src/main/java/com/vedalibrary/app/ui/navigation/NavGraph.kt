package com.vedalibrary.app.ui.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.ui.unit.dp
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.compose.*
import com.vedalibrary.app.ui.screens.*

object Routes {
    const val LIB = "library"; const val SEARCH = "search"; const val NOTES = "notes"
    const val CARDS = "cards"; const val QUESTIONS = "questions"
    const val READER = "reader/{bookId}"; const val VERSE = "verse/{verseId}?hl={hl}&hp={hp}"
    const val CHAPTER = "chapter/{chapterId}?index={index}&offset={offset}"
    const val SETTINGS = "settings"; const val DICT = "dict/{lang}/{type}/{word}"; const val ILLUS = "illustrations/{bookId}"
    const val ASK = "ask"; const val ASK_EDIT = "askEdit/{qid}"
    fun reader(b: String) = "reader/$b"
    fun chapter(c: String, index: Int = 0, offset: Int = 0) =
        "chapter/${android.net.Uri.encode(c)}?index=$index&offset=$offset"
    /** hp — поле подсказки из поиска (text/purport/…): экран мотает к СЕКЦИИ,
     *  где FTS нашёл слово, а не к первому вхождению в другом поле */
    fun verse(v: String, hl: String = "", hp: String? = null) =
        if (hl.isBlank()) "verse/${android.net.Uri.encode(v)}"
        else "verse/${android.net.Uri.encode(v)}?hl=${android.net.Uri.encode(hl)}" +
                if (hp.isNullOrBlank()) "" else "&hp=${android.net.Uri.encode(hp)}"
    fun dict(lang: String, type: String, w: String) = "dict/$lang/$type/${android.net.Uri.encode(w)}"
    fun illus(b: String) = "illustrations/$b"
    fun askEdit(qid: Long) = "askEdit/$qid"
}

@Composable
fun VedaNavGraph() {
    val nav = rememberNavController()
    // Апдейтер один на всё приложение: диалог поверх экранов + автопроверка при старте
    val updateVm: com.vedalibrary.app.ui.vm.UpdateViewModel = hiltViewModel()
    LaunchedEffect(Unit) { updateVm.autoCheck() }
    com.vedalibrary.app.ui.components.UpdateDialog(updateVm)
    // rememberSaveable: подсветка вкладки переживает поворот/восстановление
    // (remember стирался, а NavController стек восстанавливал — расходились)
    var selected by rememberSaveable { mutableStateOf(Routes.LIB) }
    // Вкладки-картинки: крупные цветные эмодзи по центру, без подписей
    val tabs = listOf(
        Routes.LIB to "📚",
        Routes.SEARCH to "🔍",
        Routes.NOTES to "📓",
        Routes.QUESTIONS to "❓",
        Routes.CARDS to "⭐"
    )
    Scaffold(
        bottomBar = {
            // Низкая панель (значки те же 30sp) + ОТДЕЛЬНАЯ зона под системные кнопки.
            // Фикс. высота съедала бы внутренний инсет панели (вкладки под кнопками
            // «назад/домой»), поэтому инсет — спейсером снизу: в жестовом режиме он ~0,
            // в кнопочном — высота системной панели. UI адаптируется сам
            Column(Modifier.background(MaterialTheme.colorScheme.surfaceContainer)) {
                NavigationBar(
                    modifier = Modifier.height(60.dp),
                    windowInsets = WindowInsets(0, 0, 0, 0)
                ) {
                    tabs.forEach { (r, e) ->
                        NavigationBarItem(
                            selected = selected == r,
                            onClick = {
                            selected = r
                            // Стандартная мультивкладочность: стек вкладок не растёт
                            // (saveState кладёт прежнюю вкладку, restoreState при
                            // возврате достаёт её же с состоянием), «назад» не гоняет
                            // по всем визитам (LIB→SEARCH→LIB раньше плодил копии)
                            nav.navigate(r) {
                                launchSingleTop = true
                                popUpTo(Routes.LIB) { saveState = true }
                                restoreState = true
                            }
                        },
                            icon = { Text(e, fontSize = 30.sp) }
                        )
                    }
                }
                Spacer(
                    Modifier.windowInsetsPadding(
                        WindowInsets.navigationBars.only(WindowInsetsSides.Bottom)
                    )
                )
            }
        }
    ) { pad ->
        Box(Modifier.padding(pad)) {
            NavHost(nav, startDestination = Routes.LIB) {
                composable(Routes.LIB) {
                    LibraryScreen(
                        onOpen = { nav.navigate(Routes.reader(it)) },
                        // Вход по закладке: сначала книга (чтобы «назад» вёл в неё, а не на главную),
                        // потом глава/стих поверх
                        onOpenBookmark = { b ->
                            nav.navigate(Routes.reader(b.bookId))
                            if (b.verseId != null) nav.navigate(Routes.verse(b.verseId))
                            else if (b.chapterId != null) nav.navigate(Routes.chapter(b.chapterId, b.scrollIndex, b.scrollOffset))
                        },
                        onSettings = { nav.navigate(Routes.SETTINGS) },
                        vm = hiltViewModel()
                    )
                }
                composable(Routes.SEARCH) {
                    SearchScreen(
                        vm = hiltViewModel(),
                        onVerse = { id, query, field -> nav.navigate(Routes.verse(id, query, field)) }
                    )
                }
                composable(Routes.NOTES) { NotesScreen(onVerse = { nav.navigate(Routes.verse(it)) }) }
                composable(Routes.QUESTIONS) {
                    QuestionsScreen(
                        onVerse = { nav.navigate(Routes.verse(it)) },
                        onEdit = { nav.navigate(Routes.askEdit(it)) }
                    )
                }
                composable(Routes.ASK) {
                    val prev = nav.previousBackStackEntry?.savedStateHandle
                    QuestionEditScreen(
                        qid = null,
                        verseId = prev?.get<String>("ask_verse") ?: "",
                        verseLabel = prev?.get<String>("ask_label") ?: "",
                        quote = prev?.get<String>("ask_quote") ?: "",
                        onDone = { nav.popBackStack() },
                        onVerse = { nav.navigate(Routes.verse(it)) }
                    )
                }
                composable(
                    Routes.ASK_EDIT,
                    arguments = listOf(androidx.navigation.navArgument("qid") {
                        type = androidx.navigation.NavType.LongType
                    })
                ) { entry ->
                    QuestionEditScreen(
                        qid = entry.arguments?.getLong("qid"),
                        verseId = "", verseLabel = "", quote = "",
                        onDone = { nav.popBackStack() },
                        onVerse = { nav.navigate(Routes.verse(it)) }
                    )
                }
                composable(Routes.CARDS) { FavoritesScreen(onVerse = { nav.navigate(Routes.verse(it)) }) }
                composable(Routes.READER) {
                    ReaderScreen(
                        onVerse = { nav.navigate(Routes.verse(it)) },
                        onChapter = { nav.navigate(Routes.chapter(it)) },
                        onSettings = { nav.navigate(Routes.SETTINGS) },
                        onIllustrations = { nav.navigate(Routes.illus(it)) },
                        vm = hiltViewModel()
                    )
                }
                composable(
                    Routes.CHAPTER,
                    arguments = listOf(
                        androidx.navigation.navArgument("index") {
                            type = androidx.navigation.NavType.IntType; defaultValue = 0
                        },
                        androidx.navigation.navArgument("offset") {
                            type = androidx.navigation.NavType.IntType; defaultValue = 0
                        }
                    )
                ) {
                    ChapterScreen(
                        onVerse = { nav.navigate(Routes.verse(it)) },
                        onSettings = { nav.navigate(Routes.SETTINGS) },
                        onIllustrations = { nav.navigate(Routes.illus(it)) },
                        // Свайп между главами — с заменой (не копим главы в стеке)
                        onChapterReplace = { nav.popBackStack(); nav.navigate(Routes.chapter(it)) }
                    )
                }
                composable(
                    Routes.VERSE,
                    arguments = listOf(
                        androidx.navigation.navArgument("hl") {
                            type = androidx.navigation.NavType.StringType; defaultValue = ""
                        },
                        androidx.navigation.navArgument("hp") {
                            type = androidx.navigation.NavType.StringType; defaultValue = ""
                        }
                    )
                ) {
                    VerseDetailScreen(
                        onSettings = { nav.navigate(Routes.SETTINGS) },
                        onWord = { w, l, t -> nav.navigate(Routes.dict(l, t, w)) },
                        // Тапы по ссылкам — поверх (назад вернёт откуда пришли);
                        // свайп/стрелки — с заменой (не копим десятки стихов в стеке)
                        onNavigate = { nav.navigate(Routes.verse(it)) },
                        onNavigateReplace = { nav.popBackStack(); nav.navigate(Routes.verse(it)) },
                        onAskQuestion = { verseId, label, quote ->
                            nav.currentBackStackEntry?.savedStateHandle?.apply {
                                set("ask_verse", verseId)
                                set("ask_label", label)
                                set("ask_quote", quote)
                            }
                            nav.navigate(Routes.ASK)
                        }
                    )
                }
                composable(Routes.DICT) {
                    DictScreen(onVerse = { nav.navigate(Routes.verse(it)) })
                }
                composable(Routes.ILLUS) {
                    IllustrationsScreen(onVerse = { nav.navigate(Routes.verse(it)) })
                }
                composable(Routes.SETTINGS) { SettingsScreen(updateVm = updateVm) }
            }
        }
    }
}
