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
import androidx.activity.result.contract.ActivityResultContracts
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject




data class Track(val id: Int, val title: String, val artist: String, val duration: Double)

@Composable
fun MusicScreen() {
    val scope = rememberCoroutineScope()
    var st by remember { mutableStateOf(JSONObject()) }
    var tracks by remember { mutableStateOf(listOf<Track>()) }
    var query by rememberSaveable { mutableStateOf("") }
    var drag by remember { mutableStateOf<Float?>(null) }
    var busy by remember { mutableStateOf(false) }

    suspend fun loadTracks() {
        val r = Api.get("/api/tracks")
        if (r.ok) {
            tracks = r.arr.objects().map { Track(it.optInt("id"), it.str("title"), it.str("artist"), it.num("duration")) }
        }
    }

    fun act(path: String, body: JSONObject? = null) {
        scope.launch {
            val r = Api.post(path, body)
            if (r.ok) { st = r.json; Mirror.sync(r.json) } else toast(r.error)
        }
    }

    LaunchedEffect(Unit) {
        loadTracks()
        while (isActive) {
            val r = Api.get("/api/state", poll = true)
            if (r.ok) {
                st = r.json
                Mirror.sync(r.json)
                if (r.json.optInt("count") != tracks.size) loadTracks()
            }
            delay(1000)
        }
    }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) {
            busy = true
            scope.launch {
                val r = Api.upload("/api/upload", uris, "files")
                busy = false
                toast(if (r.ok) "${r.json.optInt("saved")} آهنگ آپلود شد" else r.error)
                loadTracks()
            }
        }
    }

    val dur = st.num("duration", 0.0)
    val pos = st.num("position", 0.0)
    val playing = st.flag("playing")
    val volume = st.num("volume", 0.7)
    val repeat = st.str("repeat", "off")
    val curId = if (st.isNull("current")) -1 else st.optInt("current", -1)

    Column(Modifier.fillMaxSize()) {
        Section("") {
            Text(if (st.isNull("title") || st.str("title").isEmpty()) "چیزی پخش نمیشه" else st.str("title"), fontWeight = FontWeight.Bold, fontSize = 18.sp, maxLines = 2)
            if (st.str("artist").isNotEmpty()) Note(st.str("artist"))
            Slider(
                value = (drag ?: pos.toFloat()).coerceIn(0f, maxOf(dur.toFloat(), 1f)),
                onValueChange = { drag = it },
                valueRange = 0f..maxOf(dur.toFloat(), 1f),
                onValueChangeFinished = { drag?.let { v -> act("/api/seek", jsonOf("pos" to v.toDouble())) }; drag = null },
                enabled = dur > 0
            )
            Row(Modifier.fillMaxWidth()) {
                Text(fmtTime(drag?.toDouble() ?: pos), fontSize = 12.sp)
                Spacer(Modifier.weight(1f))
                Text(fmtTime(dur), fontSize = 12.sp)
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly, verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = { act("/api/shuffle") }) { Text(if (st.flag("shuffle")) "🔀✓" else "🔀", fontSize = 22.sp) }
                TextButton(onClick = { act("/api/prev") }) { Text("⏮", fontSize = 26.sp) }
                FilledIconButton(onClick = { act("/api/toggle") }, modifier = Modifier.size(60.dp)) { Text(if (playing) "⏸" else "▶", fontSize = 26.sp) }
                TextButton(onClick = { act("/api/next") }) { Text("⏭", fontSize = 26.sp) }
                TextButton(onClick = { act("/api/repeat") }) { Text(when (repeat) { "all" -> "🔁"; "one" -> "🔂"; else -> "➡" }, fontSize = 22.sp) }
            }
            SliderRow("🔊 صدای خونه", volume.toFloat(), 0f..1f, { "${(it * 100).toInt()}٪" }) { act("/api/volume", jsonOf("value" to it.toDouble())) }
            SwitchRow("🎧 شنیدن همزمان (پخش رو گوشی هم)", Mirror.on) { if (it) Mirror.start() else Mirror.stop() }
        }
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(value = query, onValueChange = { query = it }, singleLine = true, placeholder = { Text("جستجو…") }, modifier = Modifier.weight(1f))
            Btn("⬆ آپلود", enabled = !busy) { picker.launch(arrayOf("audio/*")) }
            Btn("↻") { scope.launch { Api.post("/api/rescan"); loadTracks() } }
        }
        val shown = remember(tracks, query) {
            val q = query.trim().lowercase()
            if (q.isEmpty()) tracks else tracks.filter { it.title.lowercase().contains(q) || it.artist.lowercase().contains(q) }
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), contentPadding = PaddingValues(vertical = 6.dp)) {
            items(shown, key = { it.id }) { t ->
                val cur = t.id == curId
                Row(
                    Modifier.fillMaxWidth().clickable { act("/api/play", jsonOf("id" to t.id)) }
                        .background(if (cur) MaterialTheme.colorScheme.surfaceVariant else Color.Transparent)
                        .padding(horizontal = 16.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(if (cur && playing) "🔊" else "♪", Modifier.width(28.dp))
                    Column(Modifier.weight(1f)) {
                        Text(t.title, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = if (cur) FontWeight.Bold else FontWeight.Normal)
                        if (t.artist.isNotEmpty()) Note(t.artist)
                    }
                    Note(fmtTime(t.duration))
                }
            }
        }
    }
}
