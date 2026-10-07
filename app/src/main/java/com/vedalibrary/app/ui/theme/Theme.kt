package com.vedalibrary.app.ui.theme

import androidx.compose.material3.*
import androidx.compose.runtime.Composable

/** Material 3 Expressive: dynamic color + edge-to-edge + dark/light автоматом (Night mode).
 *  Dynamic color — только с Android 12 (API 31): ниже вызов роняет приложение на старте */
@Composable
fun VedaLibraryTheme(dynamicColor: Boolean = true, darkTheme: Boolean = androidx.compose.foundation.isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val useDynamic = dynamicColor && android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.S
    val scheme = when {
        useDynamic && darkTheme -> dynamicDarkColorScheme(androidx.compose.ui.platform.LocalContext.current)
        useDynamic -> dynamicLightColorScheme(androidx.compose.ui.platform.LocalContext.current)
        darkTheme -> darkColorScheme() else -> lightColorScheme()
    }
    MaterialTheme(colorScheme = scheme, typography = Typography(), content = content)
}
