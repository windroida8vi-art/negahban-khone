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
import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject




@Composable
fun MoreScreen() {
    var tab by rememberSaveable { mutableStateOf("audio") }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
            Chips(listOf("audio" to "🎤 صدا", "tools" to "🧰 ابزار", "files" to "📁 فایل‌ها", "settings" to "⚙ تنظیمات"), tab) { tab = it }
        }
        Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
            when (tab) {
                "audio" -> AudioSection()
                "tools" -> ToolsSection()
                "files" -> FilesSection()
                else -> SettingsSection()
            }
        }
    }
}

@Composable
fun AudioSection() {
    val micLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) Talk.start() else toast("اجازه‌ی میکروفون داده نشد")
    }
    Section("🎤 صحبت با خونه (میکروفون گوشی ← اسپیکر سیستم)") {
        SwitchRow("روشن", Talk.on) { v ->
            if (v) { if (Talk.canStart()) Talk.start() else micLauncher.launch(Manifest.permission.RECORD_AUDIO) } else Talk.stop()
        }
        if (Talk.status.isNotEmpty()) Note(Talk.status)
        Note("وقتی صحبت میکنی صدای آهنگ خونه خودکار کم میشه.")
    }
    Section("👂 گوش دادن به خونه (میکروفون سیستم ← گوشی)") {
        SwitchRow("روشن", Listen.on) { v -> if (v) Listen.start() else Listen.stop() }
        if (Listen.status.isNotEmpty()) Note(Listen.status)
    }
    Section("🔊 صدای خود سیستم (آهنگ، فیلم، بازی ← گوشی)") {
        SwitchRow("کم‌حجم (برای اینترنت ضعیف)", SysAudio.lowQuality, enabled = !SysAudio.on) { SysAudio.lowQuality = it }
        SwitchRow("روشن", SysAudio.on) { v -> if (v) SysAudio.start() else SysAudio.stop() }
        if (SysAudio.status.isNotEmpty()) Note(SysAudio.status)
    }
}

@Composable
fun ToolsSection() {
    val scope = rememberCoroutineScope()
    val ctx = LocalContext.current
    var stats by remember { mutableStateOf(JSONObject()) }
    var info by remember { mutableStateOf(JSONObject()) }
    var speak by remember { mutableStateOf("") }
    var clip by remember { mutableStateOf("") }
    var run by remember { mutableStateOf("") }
    var confirm by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        val r = Api.get("/api/info")
        if (r.ok) info = r.json
        while (isActive) {
            val s = Api.get("/api/stats", poll = true)
            if (s.ok) stats = s.json
            delay(4000)
        }
    }

    Section("وضعیت سیستم") {
        Text("پردازنده: ${stats.num("cpu").toInt()}٪  ·  حافظه: ${stats.num("ram").toInt()}٪" + (if (stats.isNull("battery") || !stats.has("battery")) "" else "  ·  باتری: ${stats.optInt("battery")}٪"))
        info.optJSONArray("urls")?.strings()?.let { u -> if (u.isNotEmpty()) Note("آدرس‌های شبکه‌ی خونه: " + u.joinToString("  ")) }
    }
    Section("برق سیستم") {
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Btn("🔒 قفل") { scope.launch { val r = Api.post("/api/power", jsonOf("action" to "lock")); toast(if (r.ok) "انجام شد" else r.error) } }
            Btn("😴 خواب") { confirm = "sleep" }
            Btn("🔄 ری‌استارت") { confirm = "restart" }
            Btn("⏻ خاموش") { confirm = "shutdown" }
            Btn("↩ لغو") { scope.launch { Api.post("/api/power", jsonOf("action" to "cancel")); toast("لغو شد") } }
        }
    }
    Section("🗣 بلند بگو (متن به گفتار روی سیستم)") {
        OutlinedTextField(value = speak, onValueChange = { speak = it }, modifier = Modifier.fillMaxWidth(), placeholder = { Text("متن…") })
        Btn("بگو") { scope.launch { val r = Api.post("/api/speak", jsonOf("text" to speak)); toast(if (r.ok) "گفته شد" else r.error) } }
    }
    Section("📋 کلیپ‌بورد") {
        OutlinedTextField(value = clip, onValueChange = { clip = it }, modifier = Modifier.fillMaxWidth(), placeholder = { Text("متن کلیپ‌بورد") })
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Btn("⬇ از سیستم بگیر") { scope.launch { val r = Api.get("/api/clipboard"); if (r.ok) clip = r.json.str("text") else toast(r.error) } }
            Btn("⬆ به سیستم بفرست") { scope.launch { val r = Api.post("/api/clipboard", jsonOf("text" to clip)); toast(if (r.ok) "فرستاده شد" else r.error) } }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Btn("📥 از گوشی بچسبون") {
                val cm = ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clip = cm.primaryClip?.getItemAt(0)?.coerceToText(ctx)?.toString() ?: ""
            }
            Btn("📤 تو گوشی کپی کن") {
                val cm = ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                cm.setPrimaryClip(ClipData.newPlainText("home", clip))
                toast("کپی شد")
            }
        }
    }
    Section("▶ باز کردن برنامه/فایل/لینک روی سیستم") {
        OutlinedTextField(value = run, onValueChange = { run = it }, modifier = Modifier.fillMaxWidth(), singleLine = true, placeholder = { Text("مثلا notepad یا https://… یا C:\\file.pdf") })
        Btn("اجرا") { scope.launch { val r = Api.post("/api/run", jsonOf("target" to run)); toast(if (r.ok) "اجرا شد" else r.error) } }
    }
    Section("🖼 اسکرین‌شات") {
        Btn("ذخیره‌ی اسکرین‌شات سیستم تو گالری") {
            scope.launch {
                val b = Api.bytes("/api/screenshot.png")
                toast(if (b != null && saveBytes("screen-" + stamp() + ".png", "image/png", true, b)) "ذخیره شد" else "نشد")
            }
        }
    }

    confirm?.let { act ->
        val names = mapOf("sleep" to "خواب", "restart" to "ری‌استارت", "shutdown" to "خاموش شدن")
        Confirm("مطمئنی؟", "سیستم خونه " + (names[act] ?: act) + "؟ (اگه خاموش بشه از راه دور نمیتونی روشنش کنی)",
            { confirm = null; scope.launch { val r = Api.post("/api/power", jsonOf("action" to act)); toast(if (r.ok) "انجام میشه" else r.error) } },
            { confirm = null })
    }
}

@Composable
fun FilesSection() {
    val scope = rememberCoroutineScope()
    var path by rememberSaveable { mutableStateOf("") }
    var data by remember { mutableStateOf(JSONObject()) }
    var busy by remember { mutableStateOf(false) }
    var err by remember { mutableStateOf("") }

    fun load(p: String) {
        scope.launch {
            busy = true
            val r = Api.get("/api/fs/list?path=" + java.net.URLEncoder.encode(p, "UTF-8"))
            busy = false
            if (r.ok) { data = r.json; path = r.json.str("path"); err = "" } else err = r.error
        }
    }
    LaunchedEffect(Unit) { load(path) }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty() && path.isNotEmpty()) {
            scope.launch {
                busy = true
                val r = Api.upload("/api/fs/upload", uris, "files", mapOf("path" to path))
                busy = false
                toast(if (r.ok) "${r.json.optInt("saved")} فایل آپلود شد" else r.error)
                load(path)
            }
        }
    }

    Section("فایل‌های سیستم") {
        Text(if (path.isEmpty()) "درایوها" else path, fontSize = 12.sp, color = MaterialTheme.colorScheme.secondary)
        if (err.isNotEmpty()) Note(err, error = true)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val parent = if (data.isNull("parent")) null else data.str("parent")
            Btn("⬆ بالا", enabled = parent != null) { parent?.let { load(it) } }
            Btn("💽 درایوها") { load("::drives") }
            Btn("⬆ آپلود اینجا", enabled = path.isNotEmpty() && !busy) { picker.launch(arrayOf("*/*")) }
            if (busy) CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp)
        }
        HorizontalDivider()
        val dirs = data.optJSONArray("dirs")?.objects() ?: emptyList()
        val files = data.optJSONArray("files")?.objects() ?: emptyList()
        for (d in dirs) {
            Text("📁 " + d.str("name"), Modifier.fillMaxWidth().clickable { load(d.str("path")) }.padding(vertical = 8.dp))
        }
        for (f in files) {
            Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("📄 " + f.str("name"), maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Note(fmtSize(f.optLong("size")))
                }
                TextButton(onClick = {
                    scope.launch {
                        toast("دانلود شروع شد…")
                        val ok = Api.download("/api/fs/download?path=" + java.net.URLEncoder.encode(f.str("path"), "UTF-8"), f.str("name"))
                        toast(if (ok) "تو Downloads/HomeRemote ذخیره شد" else "دانلود نشد")
                    }
                }) { Text("⬇") }
            }
        }
        if (dirs.isEmpty() && files.isEmpty() && !busy) Note("خالیه")
    }
}

fun fmtSize(b: Long): String = when {
    b >= 1L shl 30 -> "%.1f GB".format(b / (1L shl 30).toDouble())
    b >= 1L shl 20 -> "%.1f MB".format(b / (1L shl 20).toDouble())
    b >= 1L shl 10 -> "%.0f KB".format(b / 1024.0)
    else -> "$b B"
}

@Composable
fun SettingsSection() {
    val scope = rememberCoroutineScope()
    val ctx = LocalContext.current
    var lock by remember { mutableStateOf(Prefs.appLock) }
    var watch by remember { mutableStateOf(Prefs.watch) }
    var askAll by remember { mutableStateOf(false) }
    var rePin by remember { mutableStateOf<String?>(null) }
    var rePinInfo by remember { mutableStateOf("") }

    val notifLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { _ ->
        Prefs.watch = true
        watch = true
        ContextCompat.startForegroundService(ctx, Intent(ctx, WatchService::class.java))
    }

    Section("اتصال") {
        Text("سرور: ${Prefs.scheme}://${Prefs.host}:${Prefs.port}")
        val roleName = if (Session.isViewer) "فقط تماشا" else "ادمین"
        Note("کاربر: " + Prefs.user + " (" + roleName + ")")
        if (Prefs.scheme == "https") {
            Note("اثر انگشت گواهی تاییدشده:")
            Text(Net.pretty(Prefs.pin), fontSize = 10.sp, color = MaterialTheme.colorScheme.secondary)
            Btn("🔄 تایید دوباره‌ی گواهی سرور") {
                scope.launch {
                    val c = withContext(Dispatchers.IO) { try { Net.probeCert(Prefs.host, Prefs.port.toInt()) } catch (e: Exception) { null } }
                    if (c == null) toast("به سرور وصل نشد") else { rePin = Net.fingerprint(c); rePinInfo = c.subjectDN.name }
                }
            }
        }
    }
    Section("امنیت اپ") {
        SwitchRow("قفل برنامه (اثر انگشت / قفل گوشی)", lock) { Prefs.appLock = it; lock = it }
        SwitchRow("هشدار زنده‌ی رویدادها (اعلان گوشی)", watch) { v ->
            if (v) {
                if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                    notifLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                } else {
                    Prefs.watch = true
                    watch = true
                    ContextCompat.startForegroundService(ctx, Intent(ctx, WatchService::class.java))
                }
            } else {
                Prefs.watch = false
                watch = false
                ctx.stopService(Intent(ctx, WatchService::class.java))
            }
        }
        Note("وقتی روشنه، اپ هر چند ثانیه سرور رو چک میکنه و تا آدم دیده شد اعلان (با عکس) میده. کمی باتری مصرف میکنه.")
        if (!Prefs.encrypted) Note("⚠ این گوشی ذخیره‌ی رمزنگاری‌شده رو پشتیبانی نمیکنه؛ رمز ذخیره نمیشه.", error = true)
    }
    Section("حساب") {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Btn("خروج") { scope.launch { ctx.stopService(Intent(ctx, WatchService::class.java)); Session.logout() } }
            Btn("خروج همه‌ی دستگاه‌ها") { askAll = true }
        }
    }
    Section("درباره") { Note("کنترل خونه 1.0 · ارتباط رمزنگاری‌شده با سرور خودت (گواهی پین‌شده)") }

    if (askAll) {
        Confirm("خروج همه‌ی دستگاه‌ها", "همه‌ی گوشی‌ها و مرورگرها (از جمله کاربر فقط‌تماشا) از حساب خارج میشن. ادامه؟",
            { askAll = false; scope.launch { Api.post("/api/logout_all"); Session.logout() } }, { askAll = false })
    }
    rePin?.let { fp ->
        AlertDialog(
            onDismissRequest = { rePin = null },
            title = { Text("گواهی جدید سرور") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("اگه خودت گواهی سرور رو عوض کردی (یا IP عوض شده) و اثر انگشت زیر با سرور یکیه، تایید کن:", fontSize = 13.sp)
                    Text(Net.pretty(fp), fontSize = 11.sp, color = MaterialTheme.colorScheme.secondary)
                    Note(rePinInfo)
                }
            },
            confirmButton = { TextButton(onClick = { Prefs.pin = fp; Prefs.pinFor = Prefs.serverId; Api.rebuild(); rePin = null; toast("ذخیره شد") }) { Text("تایید") } },
            dismissButton = { TextButton(onClick = { rePin = null }) { Text("نه") } }
        )
    }
}
