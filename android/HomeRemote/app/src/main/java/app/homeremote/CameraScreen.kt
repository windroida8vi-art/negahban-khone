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
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject




@Composable
fun CameraScreen() {
    var tab by rememberSaveable { mutableStateOf("webcam") }
    val land = isLandscape()
    RotateReset()
    if (land) {
        // افقی: تصویر کل صفحه رو پر میکنه (با کیفیت بالا)؛ فقط یه نوار کوچیک بالا
        Box(Modifier.fillMaxSize().background(Color.Black)) {
            if (tab == "webcam") MjpegView(Api.base + "/camera.mjpg?hi=1", Modifier.fillMaxSize(), scale = ContentScale.Fit)
            else NvrView(viewer = false)
            Row(Modifier.align(Alignment.TopStart).padding(horizontal = 8.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Chips(listOf("webcam" to "📷 وب‌کم", "nvr" to "📹 NVR"), tab) { tab = it }
                RotateButton()
            }
        }
    } else {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
            Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Chips(listOf("webcam" to "📷 وب‌کم", "nvr" to "📹 NVR"), tab) { tab = it }
                RotateButton(onDark = false)
            }
            if (tab == "webcam") WebcamView() else NvrView(viewer = false)
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
fun WebcamView() {
    val scope = rememberCoroutineScope()
    val holder = remember { FrameHolder() }
    var full by remember { mutableStateOf(false) }
    Section("وب‌کم سیستم") {
        MjpegView(Api.base + "/camera.mjpg", Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)), holder, onClick = { full = true })
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Btn("📷 ذخیره‌ی عکس") {
                scope.launch {
                    val b = Api.bytes("/api/snapshot.jpg")
                    toast(if (b != null && saveBytes("webcam-" + stamp() + ".jpg", "image/jpeg", true, b)) "تو گالری ذخیره شد" else "عکس نیومد")
                }
            }
            Btn("⛶ تمام‌صفحه") { full = true }
        }
        Note("با باز بودن این صفحه وب‌کم روی سرور روشنه؛ با بستنش خاموش میشه.")
    }
    if (full) FullscreenStream(Api.base + "/camera.mjpg") { full = false }
}

@Composable
fun FullscreenStream(url: String, onClose: () -> Unit) {
    val hiUrl = url + (if (url.contains("?")) "&" else "?") + "hi=1"      // سرور تصویر بزرگ‌تر/باکیفیت‌تر میفرسته
    RotateReset()
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        ImmersiveMode(true, inDialog = true)
        Box(Modifier.fillMaxSize().background(Color.Black), contentAlignment = Alignment.Center) {
            MjpegView(hiUrl, Modifier.fillMaxSize(), scale = ContentScale.Fit, onClick = onClose)
            Row(Modifier.align(Alignment.TopStart).padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = onClose) { Text("✕ بستن", color = Color.White) }
                RotateButton()
            }
        }
    }
}

/** نمای NVR: هم برای ادمین (با کلیدها) و هم کاربر «فقط‌تماشا» (فقط تصویر) */
@Composable
fun NvrView(viewer: Boolean) {
    val scope = rememberCoroutineScope()
    var st by remember { mutableStateOf(JSONObject()) }
    val shown = remember { mutableStateListOf<Int>() }
    var inited by remember { mutableStateOf(false) }
    var full by remember { mutableStateOf<Int?>(null) }
    val holders = remember { mutableMapOf<Int, FrameHolder>() }

    fun saveUi() {
        if (viewer) return
        scope.launch { Api.post("/api/nvr", jsonOf("ui" to jsonOf("open" to true, "shown" to JSONArray(shown.toList())))) }
    }

    LaunchedEffect(Unit) {
        while (isActive) {
            val r = Api.get("/api/nvr/status", poll = true)
            if (r.ok) {
                st = r.json
                if (!inited) {
                    inited = true
                    val chans = r.json.optJSONArray("channels")?.objects()?.map { it.optInt("ch") } ?: emptyList()
                    val saved = r.json.obj("ui").optJSONArray("shown")?.let { a -> (0 until a.length()).map { a.optInt(it) } } ?: emptyList()
                    val want = if (viewer) chans else saved.filter { it in chans }
                    shown.addAll(if (want.isNotEmpty()) want else chans.take(1))
                }
            }
            delay(2500)
        }
    }

    val chans = st.optJSONArray("channels")?.objects() ?: emptyList()
    if (!st.flag("enabled", true) && chans.isEmpty()) {
        Section("") { Note("NVR در دسترس نیست (NVR_IP تو start.bat تنظیم نشده)", error = true) }
        return
    }

    if (isLandscape()) {
        // افقی: کانال‌های انتخاب‌شده کنار هم، کل صفحه (تا ۲ کانال با کیفیت بالا)
        val sel = chans.map { it.optInt("ch") }.filter { it in shown }
        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
            for (ch in sel) {
                val holder = holders.getOrPut(ch) { FrameHolder() }
                MjpegView(
                    Api.base + "/camera-nvr.mjpg?ch=$ch" + (if (sel.size <= 2) "&hi=1" else ""),
                    Modifier.weight(1f).fillMaxHeight(), holder, scale = ContentScale.Fit,
                    onClick = if (sel.size > 1) ({ full = ch }) else null
                )
            }
        }
        full?.let { ch -> FullscreenStream(Api.base + "/camera-nvr.mjpg?ch=$ch") { full = null } }
        return
    }

    if (!viewer) {
        Section("NVR") {
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                for (c in chans) {
                    val ch = c.optInt("ch")
                    FilterChip(
                        selected = ch in shown,
                        onClick = { if (ch in shown) shown.remove(ch) else shown.add(ch); saveUi() },
                        label = { Text("کانال $ch") }
                    )
                }
            }
            SwitchRow("🛡 تشخیص آدم (عکس، ویدیو، تلگرام)", st.flag("on")) { v -> scope.launch { val r = Api.post("/api/nvr", jsonOf("on" to v)); if (r.ok) st = r.json else toast(r.error) } }
            SwitchRow("🎞 کیفیت HD (استریم اصلی)", st.flag("hd")) { v -> scope.launch { val r = Api.post("/api/nvr", jsonOf("hd" to v)); if (r.ok) st = r.json else toast(r.error) } }
            SwitchRow("✨ بهبود کیفیت (روشن/نویز/کنتراست)", st.flag("enhance")) { v -> scope.launch { val r = Api.post("/api/nvr", jsonOf("enhance" to v)); if (r.ok) st = r.json else toast(r.error) } }
        }
    } else {
        Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (c in chans) {
                val ch = c.optInt("ch")
                FilterChip(selected = ch in shown, onClick = { if (ch in shown) shown.remove(ch) else shown.add(ch) }, label = { Text("کانال $ch") })
            }
        }
    }

    for (c in chans) {
        val ch = c.optInt("ch")
        if (ch !in shown) continue
        val holder = holders.getOrPut(ch) { FrameHolder() }
        val state = c.str("state")
        Section("کانال $ch") {
            MjpegView(Api.base + "/camera-nvr.mjpg?ch=$ch", Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)), holder, onClick = { full = ch })
            val txt = when (state) {
                "ok" -> if (viewer) "" else "✅ وصل (" + c.str("name") + ")" + (if (c.flag("hd_active")) " · HD" else "")
                "connecting" -> "⏳ در حال اتصال…"
                "error" -> if (viewer) "❌ دوربین در دسترس نیست" else "❌ " + c.str("err")
                else -> ""
            }
            if (txt.isNotEmpty()) Note(txt, error = state == "error")
            if (!viewer && st.flag("hd") && state == "ok" && !c.flag("hd_active")) Note("⚠ استریم اصلی (HD) پیدا نشد؛ استریم عادی نشون داده میشه")
            if (!viewer && c.flag("watch_broken")) Note("⚠ تشخیص آدم خراب شد: " + c.str("watch_err"), error = true)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Btn("📷 عکس") {
                    scope.launch {
                        val b = Api.bytes("/api/nvr/snapshot.jpg?ch=$ch")
                        toast(if (b != null && saveBytes("nvr$ch-" + stamp() + ".jpg", "image/jpeg", true, b)) "تو گالری ذخیره شد" else "عکس نیومد")
                    }
                }
                Btn("⛶ تمام‌صفحه") { full = ch }
            }
        }
    }
    full?.let { ch -> FullscreenStream(Api.base + "/camera-nvr.mjpg?ch=$ch") { full = null } }
}
