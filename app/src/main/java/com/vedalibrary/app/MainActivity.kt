package com.vedalibrary.app

import android.os.Bundle
import android.view.KeyEvent
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.*
import com.vedalibrary.app.ui.navigation.VedaNavGraph
import com.vedalibrary.app.ui.theme.VedaLibraryTheme
import com.vedalibrary.app.ui.util.VolumeFont
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge() // тренд 2026: edge-to-edge по умолчанию
        setContent {
            VedaLibraryTheme(dynamicColor = true) {
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
