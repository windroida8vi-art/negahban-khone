package app.homeremote

import androidx.compose.foundation.*
import androidx.compose.foundation.gestures.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.*
import androidx.compose.foundation.text.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.*
import androidx.compose.ui.*
import androidx.compose.ui.draw.*
import androidx.compose.ui.geometry.*
import androidx.compose.ui.graphics.*
import androidx.compose.ui.input.pointer.*
import androidx.compose.ui.layout.*
import androidx.compose.ui.platform.*
import androidx.compose.ui.text.*
import androidx.compose.ui.text.font.*
import androidx.compose.ui.text.input.*
import androidx.compose.ui.text.style.*
import androidx.compose.ui.unit.*
import androidx.compose.ui.viewinterop.*
import androidx.compose.ui.window.*
import androidx.activity.compose.*




private val DarkColors = darkColorScheme(
    primary = Color(0xFF27C46B),
    onPrimary = Color(0xFF06210F),
    secondary = Color(0xFF7FD1FF),
    background = Color(0xFF0B0F14),
    onBackground = Color(0xFFE8EDF2),
    surface = Color(0xFF121821),
    onSurface = Color(0xFFE8EDF2),
    surfaceVariant = Color(0xFF1C2430),
    onSurfaceVariant = Color(0xFFB8C2CF),
    error = Color(0xFFFF6B6B),
)

@Composable
fun AppTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = DarkColors) {
        CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
            Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                content()
            }
        }
    }
}

@Composable
fun Section(title: String, modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        modifier = modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp)
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (title.isNotEmpty()) Text(title, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            content()
        }
    }
}

@Composable
fun SwitchRow(label: String, checked: Boolean, enabled: Boolean = true, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChange, enabled = enabled)
    }
}

@Composable
fun SliderRow(label: String, value: Float, range: ClosedFloatingPointRange<Float>, text: (Float) -> String, onDone: (Float) -> Unit) {
    var v by remember(value) { mutableStateOf(value) }
    Column {
        Row(Modifier.fillMaxWidth()) {
            Text(label, Modifier.weight(1f))
            Text(text(v), color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Slider(value = v, onValueChange = { v = it }, valueRange = range, onValueChangeFinished = { onDone(v) })
    }
}

@Composable
fun Chips(options: List<Pair<String, String>>, selected: String, onSelect: (String) -> Unit) {
    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        for ((k, label) in options) {
            FilterChip(selected = k == selected, onClick = { onSelect(k) }, label = { Text(label) })
        }
    }
}

@Composable
fun Btn(text: String, modifier: Modifier = Modifier, enabled: Boolean = true, tonal: Boolean = true, onClick: () -> Unit) {
    if (tonal) {
        FilledTonalButton(onClick = onClick, modifier = modifier, enabled = enabled, contentPadding = PaddingValues(horizontal = 14.dp, vertical = 8.dp)) { Text(text) }
    } else {
        Button(onClick = onClick, modifier = modifier, enabled = enabled, contentPadding = PaddingValues(horizontal = 14.dp, vertical = 8.dp)) { Text(text) }
    }
}

@Composable
fun Note(text: String, modifier: Modifier = Modifier, error: Boolean = false) {
    Text(
        text, modifier = modifier, fontSize = 13.sp,
        color = if (error) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant
    )
}

@Composable
fun Confirm(title: String, text: String, onYes: () -> Unit, onNo: () -> Unit) {
    AlertDialog(
        onDismissRequest = onNo,
        title = { Text(title) },
        text = { Text(text) },
        confirmButton = { TextButton(onClick = onYes) { Text("بله") } },
        dismissButton = { TextButton(onClick = onNo) { Text("نه") } }
    )
}
