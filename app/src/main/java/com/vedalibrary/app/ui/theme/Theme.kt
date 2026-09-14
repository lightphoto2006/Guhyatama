package com.vedalibrary.app.ui.theme

import androidx.compose.material3.*
import androidx.compose.runtime.Composable

/** Material 3 Expressive: dynamic color + edge-to-edge + dark/light автоматом (Night mode) */
@Composable
fun VedaLibraryTheme(dynamicColor: Boolean = true, darkTheme: Boolean = androidx.compose.foundation.isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val scheme = when {
        dynamicColor && darkTheme -> dynamicDarkColorScheme(androidx.compose.ui.platform.LocalContext.current)
        dynamicColor -> dynamicLightColorScheme(androidx.compose.ui.platform.LocalContext.current)
        darkTheme -> darkColorScheme() else -> lightColorScheme()
    }
    MaterialTheme(colorScheme = scheme, typography = Typography(), content = content)
}
