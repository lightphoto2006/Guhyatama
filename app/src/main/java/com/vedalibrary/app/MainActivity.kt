package com.vedalibrary.app

import android.os.Bundle
import android.view.KeyEvent
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.*
import com.vedalibrary.app.ui.navigation.VedaNavGraph
import com.vedalibrary.app.ui.theme.VedaLibraryTheme
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.vedalibrary.app.ui.util.CrashLog
import com.vedalibrary.app.ui.util.VolumeFont
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        CrashLog.install(this)
        val crashAtStart = CrashLog.read(this)
        enableEdgeToEdge() // тренд 2026: edge-to-edge по умолчанию
        setContent {
            VedaLibraryTheme(dynamicColor = true) {
                var crash by remember { mutableStateOf(crashAtStart) }
                if (crash != null) {
                    val short = remember(crash) { CrashLog.digest(crash!!) }
                    val clip = LocalClipboardManager.current
                    AlertDialog(
                        onDismissRequest = {},
                        title = { Text("Приложение падало") },
                        text = {
                            Text(
                                short,
                                fontSize = 12.sp,
                                modifier = Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState())
                            )
                        },
                        confirmButton = {
                            TextButton(onClick = {
                                try { clip.setText(AnnotatedString(short)) } catch (_: Exception) { }
                            }) { Text("Скопировать") }
                        },
                        dismissButton = {
                            TextButton(onClick = {
                                CrashLog.clear(this@MainActivity)
                                crash = null
                            }) { Text("Закрыть") }
                        }
                    )
                }
                VedaNavGraph()
            }
        }
    }

    /** Громкость — размер шрифта, но только если экран чтения зарегистрировал обработчик */
    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        val h = VolumeFont.handler
        if (h != null && (keyCode == KeyEvent.KEYCODE_VOLUME_UP || keyCode == KeyEvent.KEYCODE_VOLUME_DOWN)) {
            h(if (keyCode == KeyEvent.KEYCODE_VOLUME_UP) 1 else -1)
            return true
        }
        return super.onKeyDown(keyCode, event)
    }
}
