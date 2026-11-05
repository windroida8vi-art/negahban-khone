package app.homeremote

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.ActivityInfo
import android.content.res.Configuration
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.window.DialogWindowProvider
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

fun Context.findActivity(): Activity? {
    var c: Context? = this
    while (c is ContextWrapper) {
        if (c is Activity) return c
        c = c.baseContext
    }
    return null
}

@Composable
fun isLandscape(): Boolean = LocalConfiguration.current.orientation == Configuration.ORIENTATION_LANDSCAPE

/** نوار وضعیت و ناوبری رو مخفی میکنه (تمام‌صفحه‌ی واقعی)؛ با کشیدن از لبه‌ی صفحه موقتا برمیگرده */
@Composable
fun ImmersiveMode(on: Boolean, inDialog: Boolean = false) {
    val ctx = LocalContext.current
    val view = LocalView.current
    DisposableEffect(on, inDialog) {
        val window = if (inDialog) (view.parent as? DialogWindowProvider)?.window else ctx.findActivity()?.window
        val ctrl = if (window != null) WindowCompat.getInsetsController(window, view) else null
        if (on && ctrl != null) {
            ctrl.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            ctrl.hide(WindowInsetsCompat.Type.systemBars())
        }
        onDispose { if (on && ctrl != null) ctrl.show(WindowInsetsCompat.Type.systemBars()) }
    }
}

/** وقتی این صفحه بسته شد، چرخش دوباره دست خود گوشی (خودکار) باشه */
@Composable
fun RotateReset() {
    val ctx = LocalContext.current
    DisposableEffect(Unit) {
        onDispose { ctx.findActivity()?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED }
    }
}

/** چرخوندن دستی (حتی اگه چرخش خودکار گوشی خاموشه): عمودی ↔ افقی */
@Composable
fun RotateButton(modifier: Modifier = Modifier, onDark: Boolean = true) {
    val ctx = LocalContext.current
    val land = isLandscape()
    TextButton(modifier = modifier, onClick = {
        ctx.findActivity()?.requestedOrientation =
            if (land) ActivityInfo.SCREEN_ORIENTATION_SENSOR_PORTRAIT else ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
    }) { Text(if (land) "🔄 عمودی" else "🔄 افقی", color = if (onDark) Color.White else Color.Unspecified) }
}
