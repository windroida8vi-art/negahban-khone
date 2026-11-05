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
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONObject




private val KEYS = listOf(
    "enter" to "Enter", "backspace" to "⌫", "tab" to "Tab", "esc" to "Esc", "delete" to "Del", "space" to "Space",
    "up" to "↑", "down" to "↓", "left" to "←", "right" to "→", "home" to "Home", "end" to "End",
    "page_up" to "PgUp", "page_down" to "PgDn", "win" to "Win",
    "ctrl+c" to "Ctrl+C", "ctrl+v" to "Ctrl+V", "ctrl+a" to "Ctrl+A", "ctrl+z" to "Ctrl+Z", "alt+tab" to "Alt+Tab", "alt+f4" to "Alt+F4",
)

@Composable
fun DesktopScreen() {
    if (Session.serviceMode) {
        Box(Modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
            Note("🖥 دسکتاپ بعد از ورود به ویندوز فعال میشه (الان سرور تو حالت سرویسه). بعد از ورود، خودکار وصل میشه.")
        }
    } else {
        DesktopContent()
    }
}

/** دسکتاپ زنده + موس و کیبورد (روی همون اتصال WebSocket). دو حالت: لمس مستقیم / تاچ‌پد.
 *  افقی: تصویر کل صفحه، کیفیت خودکار بالا، ابزارها پشت دکمه‌ی ☰ */
@Composable
fun DesktopContent() {
    val scope = rememberCoroutineScope()
    val land = isLandscape()
    var frame by remember { mutableStateOf<Bitmap?>(null) }
    var cursor by remember { mutableStateOf<Pair<Float, Float>?>(null) }
    var status by remember { mutableStateOf("در حال اتصال…") }
    var boxSize by remember { mutableStateOf(IntSize.Zero) }
    var monitors by remember { mutableStateOf(1) }
    var mon by rememberSaveable { mutableStateOf(1) }
    var quality by rememberSaveable { mutableStateOf("auto") }
    var touchpad by rememberSaveable { mutableStateOf(false) }
    var showKeys by remember { mutableStateOf(false) }
    var showBar by remember { mutableStateOf(false) }
    var typed by remember { mutableStateOf("") }
    var wsRef by remember { mutableStateOf<WebSocket?>(null) }
    var dragging by remember { mutableStateOf(false) }
    var lastMove by remember { mutableStateOf(0L) }

    RotateReset()
    fun sendJson(o: JSONObject) { wsRef?.send(o.toString()) }
    fun cfg(): JSONObject {
        // «خودکار»: عمودی = متوسط، افقی = باکیفیت (۱۹۲۰ پیکسل)
        val q = if (quality == "auto") (if (land) "high" else "mid") else quality
        return jsonOf("cfg" to jsonOf(
            "m" to mon,
            "w" to (when (q) { "low" -> 800; "high" -> 1920; else -> 1280 }),
            "q" to (when (q) { "low" -> 40; "high" -> 80; else -> 60 }),
            "fps" to (when (q) { "low" -> 10; "high" -> 24; else -> 18 })
        ))
    }

    LaunchedEffect(Unit) {
        val r = Api.get("/api/info")
        if (r.ok) monitors = r.json.optInt("monitors", 1)
    }

    // اتصال WebSocket؛ با عوض شدن مانیتور/کیفیت/چرخش دوباره تنظیم میشه
    DisposableEffect(Unit) {
        val frames = Channel<ByteArray>(Channel.CONFLATED)
        val decoder = CoroutineScope(Dispatchers.Default).launch {
            for (b in frames) {
                val bmp = BitmapFactory.decodeByteArray(b, 0, b.size)
                if (bmp != null) { frame = bmp; status = "" }
            }
        }
        var alive = true
        var socket: WebSocket? = null
        fun open() {
            if (!alive) return
            socket = Api.ws("/ws/desk", object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    wsRef = webSocket
                    webSocket.send(cfg().toString())
                }
                override fun onMessage(webSocket: WebSocket, bytes: ByteString) { frames.trySend(bytes.toByteArray()) }
                override fun onMessage(webSocket: WebSocket, text: String) {
                    try {
                        val c = JSONObject(text).optJSONArray("c")
                        if (c != null) cursor = Pair(c.optDouble(0).toFloat(), c.optDouble(1).toFloat())
                    } catch (e: Exception) { }
                }
                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    status = "قطع شد؛ دوباره وصل میشم…"
                    wsRef = null
                    if (alive) scope.launch { delay(2000); open() }
                }
                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    status = "بسته شد"
                    wsRef = null
                    if (alive) scope.launch { delay(2000); open() }
                }
            })
        }
        open()
        onDispose {
            alive = false
            socket?.cancel()
            wsRef = null
            decoder.cancel()
            frames.close()
        }
    }
    LaunchedEffect(mon, quality, land, wsRef) { wsRef?.send(cfg().toString()) }

    /** مختصات لمس روی تصویر -> ۰..۱ */
    fun norm(o: Offset): Pair<Float, Float>? {
        val f = frame ?: return null
        if (boxSize.width == 0 || boxSize.height == 0) return null
        val bw = f.width.toFloat()
        val bh = f.height.toFloat()
        val sc = minOf(boxSize.width / bw, boxSize.height / bh)
        val dw = bw * sc
        val dh = bh * sc
        val ox = (boxSize.width - dw) / 2f
        val oy = (boxSize.height - dh) / 2f
        return Pair(((o.x - ox) / dw).coerceIn(0f, 1f), ((o.y - oy) / dh).coerceIn(0f, 1f))
    }

    val toolbar: @Composable (Boolean) -> Unit = { withRotate ->
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
            if (monitors > 1) for (i in 1..monitors) FilterChip(selected = mon == i, onClick = { mon = i }, label = { Text("🖥 $i") })
            // نکته: Chips خودش horizontalScroll داره؛ تو یه Row اسکرولی دیگه قرار گرفتنش کرش میداد (عرض بی‌نهایت)
            for ((k, label) in listOf("auto" to "خودکار", "low" to "کم‌حجم", "mid" to "متوسط", "high" to "باکیفیت")) {
                FilterChip(selected = quality == k, onClick = { quality = k }, label = { Text(label) })
            }
            FilterChip(selected = touchpad, onClick = { touchpad = !touchpad }, label = { Text(if (touchpad) "تاچ‌پد" else "لمس مستقیم") })
            if (withRotate) RotateButton(onDark = false)
            Btn("⌨") { showKeys = !showKeys }
            Btn("🖱 راست‌کلیک") { sendJson(jsonOf("type" to "clickhere", "button" to "right")) }
            Btn("⇅ ▲") { sendJson(jsonOf("type" to "scroll", "dy" to 3)) }
            Btn("⇅ ▼") { sendJson(jsonOf("type" to "scroll", "dy" to -3)) }
        }
    }
    val keysPanel: @Composable () -> Unit = {
        if (showKeys) {
            Column(Modifier.padding(horizontal = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(value = typed, onValueChange = { typed = it }, singleLine = true, placeholder = { Text("متنی که میخوای تایپ بشه…") }, modifier = Modifier.weight(1f))
                    Btn("ارسال") { if (typed.isNotEmpty()) { sendJson(jsonOf("type" to "type", "text" to typed)); typed = "" } }
                }
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for ((k, label) in KEYS) Btn(label) { sendJson(jsonOf("type" to "key", "key" to k)) }
                }
            }
        }
    }
    val videoBox: @Composable (Modifier) -> Unit = { mod ->
        Box(
            mod.background(Color.Black).onSizeChanged { boxSize = it }
                .pointerInput(touchpad, frame != null) {
                    detectTapGestures(
                        onTap = { o ->
                            if (touchpad) sendJson(jsonOf("type" to "clickhere"))
                            else norm(o)?.let { (x, y) -> sendJson(jsonOf("type" to "click", "x" to x, "y" to y, "m" to mon)) }
                        },
                        onDoubleTap = { o ->
                            if (touchpad) sendJson(jsonOf("type" to "clickhere", "double" to true))
                            else norm(o)?.let { (x, y) -> sendJson(jsonOf("type" to "click", "x" to x, "y" to y, "m" to mon, "double" to true)) }
                        },
                        onLongPress = { o ->
                            if (touchpad) sendJson(jsonOf("type" to "clickhere", "button" to "right"))
                            else norm(o)?.let { (x, y) -> sendJson(jsonOf("type" to "click", "x" to x, "y" to y, "m" to mon, "button" to "right")) }
                        }
                    )
                }
                .pointerInput(touchpad, frame != null) {
                    detectDragGestures(
                        onDragStart = { o ->
                            if (!touchpad) norm(o)?.let { (x, y) ->
                                sendJson(jsonOf("type" to "move", "x" to x, "y" to y, "m" to mon))
                                sendJson(jsonOf("type" to "down", "x" to x, "y" to y, "m" to mon))
                                dragging = true
                            }
                        },
                        onDrag = { change, delta ->
                            change.consume()
                            val now = System.currentTimeMillis()
                            if (now - lastMove >= 35) {
                                lastMove = now
                                if (touchpad) {
                                    val w = maxOf(boxSize.width, 1).toFloat()
                                    sendJson(jsonOf("type" to "rel", "dx" to delta.x / w * 1.6f, "dy" to delta.y / w * 1.6f, "m" to mon))
                                } else if (dragging) {
                                    norm(change.position)?.let { (x, y) -> sendJson(jsonOf("type" to "move", "x" to x, "y" to y, "m" to mon)) }
                                }
                            }
                        },
                        onDragEnd = { if (dragging) { sendJson(jsonOf("type" to "up")); dragging = false } },
                        onDragCancel = { if (dragging) { sendJson(jsonOf("type" to "up")); dragging = false } }
                    )
                },
            contentAlignment = Alignment.Center
        ) {
            val f = frame
            if (f != null) {
                Image(f.asImageBitmap(), contentDescription = null, modifier = Modifier.fillMaxSize(), contentScale = ContentScale.Fit, filterQuality = FilterQuality.High)
            } else {
                CircularProgressIndicator()
            }
            if (status.isNotEmpty()) Text(status, color = Color.White, modifier = Modifier.align(Alignment.BottomCenter).padding(8.dp), fontSize = 12.sp)
        }
    }

    if (!land) {
        Column(Modifier.fillMaxSize()) {
            toolbar(true)
            keysPanel()
            videoBox(Modifier.fillMaxWidth().weight(1f))
        }
    } else {
        Box(Modifier.fillMaxSize().background(Color.Black)) {
            videoBox(Modifier.fillMaxSize())
            Column(Modifier.align(Alignment.TopStart).fillMaxWidth()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = { showBar = !showBar }) { Text(if (showBar) "✕ ابزار" else "☰ ابزار", color = Color.White) }
                    RotateButton()
                }
                if (showBar) {
                    Column(Modifier.fillMaxWidth().background(Color.Black.copy(alpha = 0.7f))) {
                        toolbar(false)
                        keysPanel()
                    }
                }
            }
        }
    }
}
