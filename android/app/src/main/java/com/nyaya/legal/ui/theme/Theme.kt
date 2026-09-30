package com.nyaya.legal.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Navy = Color(0xFF1F3A5F)
private val Saffron = Color(0xFFB8702A)

private val Light = lightColorScheme(primary = Navy, secondary = Saffron)
private val Dark = darkColorScheme(primary = Color(0xFF9DB8DE), secondary = Color(0xFFE3A866))

// Colours for "supports / opposes / mixed" stance chips.
val SupportsColor = Color(0xFF2E7D32)
val OpposesColor = Color(0xFFC62828)
val MixedColor = Color(0xFF8D6E00)

@Composable
fun NyayaTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) Dark else Light, content = content)
}
