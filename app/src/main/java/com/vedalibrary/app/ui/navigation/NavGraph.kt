package com.vedalibrary.app.ui.navigation

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.compose.*
import com.vedalibrary.app.ui.screens.*

object Routes {
    const val LIB = "library"; const val SEARCH = "search"; const val NOTES = "notes"
    const val CARDS = "cards"; const val QUESTIONS = "questions"
    const val READER = "reader/{bookId}"; const val VERSE = "verse/{verseId}?hl={hl}"
    const val CHAPTER = "chapter/{chapterId}?index={index}&offset={offset}"
    const val SETTINGS = "settings"; const val DICT = "dict/{lang}/{type}/{word}"; const val ILLUS = "illustrations/{bookId}"
    const val ASK = "ask"; const val ASK_EDIT = "askEdit/{qid}"
    fun reader(b: String) = "reader/$b"
    fun chapter(c: String, index: Int = 0, offset: Int = 0) =
        "chapter/${android.net.Uri.encode(c)}?index=$index&offset=$offset"
    fun verse(v: String, hl: String = "") =
        if (hl.isBlank()) "verse/${android.net.Uri.encode(v)}"
        else "verse/${android.net.Uri.encode(v)}?hl=${android.net.Uri.encode(hl)}"
    fun dict(lang: String, type: String, w: String) = "dict/$lang/$type/${android.net.Uri.encode(w)}"
    fun illus(b: String) = "illustrations/$b"
    fun askEdit(qid: Long) = "askEdit/$qid"
}

@Composable
fun VedaNavGraph() {
    val nav = rememberNavController()
    var selected by remember { mutableStateOf(Routes.LIB) }
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
            NavigationBar {
                tabs.forEach { (r, e) ->
                    NavigationBarItem(
                        selected = selected == r,
                        onClick = { selected = r; nav.navigate(r) { launchSingleTop = true } },
                        icon = { Text(e, fontSize = 30.sp) }
                    )
                }
            }
        }
    ) { pad ->
        Box(Modifier.padding(pad)) {
            NavHost(nav, startDestination = Routes.LIB) {
                composable(Routes.LIB) {
                    LibraryScreen(
                        onOpen = { nav.navigate(Routes.reader(it)) },
                        onOpenBookmark = { b ->
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
                        onVerse = { id, query -> nav.navigate(Routes.verse(id, query)) }
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
                        onIllustrations = { nav.navigate(Routes.illus(it)) }
                    )
                }
                composable(
                    Routes.VERSE,
                    arguments = listOf(androidx.navigation.navArgument("hl") {
                        type = androidx.navigation.NavType.StringType; defaultValue = ""
                    })
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
                composable(Routes.SETTINGS) { SettingsScreen() }
            }
        }
    }
}
