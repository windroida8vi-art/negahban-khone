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
import org.json.JSONObject




private val OPT_LABELS = listOf(
    "human_only" to "فقط آدم (نه هر حرکتی)",
    "person_only" to "فقط آدم رو اعلان بده",
    "boxes" to "کادر دور آدم تو تصویر",
    "video" to "ضبط ویدیو از رویداد",
    "pcwatch" to "هشدار وقتی کسی با خود PC کار کرد",
    "noise" to "تشخیص صدای بلند",
    "lock" to "قفل کردن ویندوز با مسلح شدن",
)

@Composable
fun SecurityScreen() {
    val scope = rememberCoroutineScope()
    var st by remember { mutableStateOf(JSONObject()) }
    var loaded by remember { mutableStateOf(false) }
    var viewImage by remember { mutableStateOf<String?>(null) }
    var viewVideo by remember { mutableStateOf<String?>(null) }
    var log by remember { mutableStateOf<List<String>?>(null) }
    var askDeleteAll by remember { mutableStateOf(false) }

    fun send(body: JSONObject) {
        scope.launch {
            val r = Api.post("/api/security", body)
            if (r.ok) st = r.json else toast(r.error)
        }
    }

    LaunchedEffect(Unit) {
        while (isActive) {
            val r = Api.get("/api/security", poll = true)
            if (r.ok) { st = r.json; loaded = true }
            delay(3000)
        }
    }

    if (!loaded) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        return
    }

    val opts = st.obj("opts")
    val fun_ = st.obj("fun")
    val presence = st.obj("presence")
    val away = st.obj("autoaway")
    val events = st.optJSONArray("events")?.objects() ?: emptyList()
    val videos = st.optJSONArray("videos")?.strings() ?: emptyList()

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        Section("وضعیت") {
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                AssistChip(onClick = {}, label = { Text(if (st.flag("armed")) "🛡 مسلح" else "غیرمسلح") })
                AssistChip(onClick = {}, label = { Text(if (st.flag("camera_live")) "📷 زنده" else "📷 قطع") })
                AssistChip(onClick = {}, label = { Text(if (st.flag("notify")) "🔔 اعلان فعال" else "🔕 اعلان نداره") })
                AssistChip(onClick = {}, label = { Text(if (st.flag("locked")) "🔒 قفل" else "🔓 باز") })
                if (!st.isNull("disk_free_gb")) AssistChip(onClick = {}, label = { Text("💾 ${st.num("disk_free_gb")} GB") })
            }
            if (st.str("camera_err").isNotEmpty()) Note("دوربین: " + st.str("camera_err"), error = true)
            if (st.str("gate_err").isNotEmpty()) Note("تشخیص آدم: " + st.str("gate_err"), error = true)
            Note("تشخیص‌دهنده: " + st.str("detector", "-"))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { send(jsonOf("mode" to "away")) }, modifier = Modifier.weight(1f)) { Text("🚪 بیرونم") }
                FilledTonalButton(onClick = { send(jsonOf("mode" to "home")) }, modifier = Modifier.weight(1f)) { Text("🏠 رسیدم خونه") }
            }
            Note("«بیرونم» همه‌چیز رو روشن میکنه (وب‌کم، NVR، شبیه‌ساز حضور، قفل)؛ «رسیدم» همه رو خاموش.")
        }

        Section("📹 NVR (دوربین‌های اصلی)") {
            val nvr = st.obj("nvr")
            if (!nvr.flag("enabled")) {
                Note("NVR تنظیم نشده (NVR_IP تو start.bat) یا opencv نصب نیست", error = true)
            } else {
                SwitchRow("🛡 تشخیص آدم NVR (عکس، ویدیو، اعلان)", nvr.flag("on")) { send(jsonOf("nvr" to jsonOf("on" to it))) }
                SwitchRow("🎞 کیفیت HD (استریم اصلی)", nvr.flag("hd")) { send(jsonOf("nvr" to jsonOf("hd" to it))) }
                SwitchRow("✨ بهبود کیفیت", nvr.flag("enhance")) { send(jsonOf("nvr" to jsonOf("enhance" to it))) }
                for (c in nvr.optJSONArray("channels")?.objects() ?: emptyList()) {
                    val state = when (c.str("state")) {
                        "ok" -> "✅ وصله"
                        "connecting" -> "⏳ در حال اتصال"
                        "error" -> "❌ " + c.str("err", "خطا")
                        else -> "⏸ بی‌کار"
                    }
                    val person = if (c.isNull("person_ago")) "" else " · آدم " + (c.optInt("person_ago") / 60) + " دقیقه پیش"
                    Note("کانال " + c.optInt("ch") + ": " + state + " · " + c.optInt("events") + " رویداد" + person, error = c.str("state") == "error")
                }
                Note("تشخیص‌دهنده: " + nvr.str("detector", "-") + (if (nvr.flag("on")) "" else " · خاموشه؛ «بیرونم» روشنش میکنه و روشن میمونه"))
            }
        }

        Section("دوربین وب‌کم") {
            SwitchRow("مسلح بودن", st.flag("armed")) { send(jsonOf("armed" to it)) }
            Text("واکنش خودکار به رویداد")
            Chips(listOf("none" to "هیچ", "music" to "موزیک", "sounds" to "صدا افکت", "smart" to "هوشمند"), st.str("auto", "none")) { send(jsonOf("auto" to it)) }
            SliderRow("حساسیت (کمتر = حساس‌تر)", Math.log(st.num("sens", 1000.0)).toFloat(), Math.log(50.0).toFloat()..Math.log(20000.0).toFloat(),
                { Math.exp(it.toDouble()).toInt().toString() }) { send(jsonOf("sens" to Math.exp(it.toDouble()).toInt())) }
            SliderRow("حداکثر صدای واکنش خودکار", st.num("vmax", 0.8).toFloat(), 0.2f..1f, { "${(it * 100).toInt()}٪" }) { send(jsonOf("vmax" to it.toDouble())) }
            SwitchRow("🚨 آژیر", st.flag("siren")) { send(jsonOf("siren" to it)) }
        }

        Section("گزینه‌ها (برای وب‌کم و NVR)") {
            for ((k, label) in OPT_LABELS) {
                SwitchRow(label, opts.flag(k)) { send(jsonOf("opts" to jsonOf(k to it))) }
            }
        }

        Section("شبیه‌ساز حضور (انگار کسی خونه‌ست)") {
            SwitchRow("روشن", presence.flag("on")) { send(jsonOf("presence" to jsonOf("on" to it))) }
            Note("الان: " + when (presence.str("scene", "")) { "music" -> "🎵 موزیک"; "tv" -> "📺 تلویزیون"; "kitchen" -> "🍳 آشپزخونه"; "walk" -> "🚶 راه رفتن"; "chores" -> "🧹 کارهای خونه"; "phone" -> "📞 تلفن"; else -> "-" } + " · آهنگ‌ها: " + presence.optInt("tracks") + " · صداها: " + presence.optInt("sounds"))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("از ساعت")
                Btn("−") { send(jsonOf("presence" to jsonOf("start" to ((presence.optInt("start", 18) + 23) % 24)))) }
                Text("${presence.optInt("start", 18)}")
                Btn("+") { send(jsonOf("presence" to jsonOf("start" to ((presence.optInt("start", 18) + 1) % 24)))) }
                Text("تا")
                Btn("−") { send(jsonOf("presence" to jsonOf("end" to maxOf(1, presence.optInt("end", 23) - 1)))) }
                Text("${presence.optInt("end", 23)}")
                Btn("+") { send(jsonOf("presence" to jsonOf("end" to minOf(24, presence.optInt("end", 23) + 1)))) }
            }
        }

        Section("حالت سرگرمی (واکنش به آدمِ دیده‌شده)") {
            SwitchRow("روشن", fun_.flag("on")) { send(jsonOf("fun" to jsonOf("on" to it))) }
            Chips(listOf("1" to "ملایم", "2" to "بیشتر"), fun_.optInt("level", 1).toString()) { send(jsonOf("fun" to jsonOf("level" to it.toInt()))) }
            Btn("🧪 آزمایش یه واکنش") { send(jsonOf("test" to "random")) }
        }

        Section("خروج خودکار (وقتی گوشی وای‌فای خونه نیست)") {
            SwitchRow("روشن", away.flag("on")) { send(jsonOf("autoaway" to jsonOf("on" to it))) }
            Note("گوشی‌ها: " + (away.optJSONArray("phones")?.strings()?.joinToString(", ") ?: "-") + " · " + (if (away.flag("present")) "خونه‌ای" else "بیرونی") + " (" + away.str("state", "-") + ")")
            Btn("➕ همین گوشی رو اضافه کن (باید وای‌فای خونه باشی)") { send(jsonOf("autoaway" to jsonOf("add_me" to true))) }
        }

        Section("رویدادها (${events.size})") {
            if (events.isEmpty()) Note("هنوز رویدادی نیست")
            for (row in events.chunked(3)) {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (e in row) {
                        val name = e.str("name")
                        Box(Modifier.weight(1f).aspectRatio(1.3f).clip(RoundedCornerShape(8.dp)).clickable { viewImage = name }) {
                            RemoteImage("/api/capture/$name", Modifier.fillMaxSize())
                            if (e.flag("person")) Text("🧍", Modifier.align(Alignment.TopStart).padding(4.dp))
                        }
                    }
                    repeat(3 - row.size) { Spacer(Modifier.weight(1f)) }
                }
            }
            if (videos.isNotEmpty()) {
                Text("ویدیوها")
                for (v in videos) {
                    TextButton(onClick = { viewVideo = v }, modifier = Modifier.fillMaxWidth()) { Text("🎬 " + describeEvent(v), modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Start) }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Btn("🗑 پاک کردن همه") { askDeleteAll = true }
                Btn("🔔 تست اعلان") {
                    scope.launch {
                        val r = Api.post("/api/notify_test")
                        log = if (r.ok) (r.json.optJSONArray("lines")?.strings() ?: emptyList()) else listOf(r.error)
                    }
                }
                Btn("📜 لاگ ورود") {
                    scope.launch {
                        val r = Api.get("/api/access")
                        log = if (r.ok) (r.json.optJSONArray("lines")?.strings() ?: emptyList()) else listOf(r.error)
                    }
                }
            }
        }
    }

    viewImage?.let { name ->
        Dialog(onDismissRequest = { viewImage = null }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
            Surface(Modifier.fillMaxWidth().padding(8.dp), shape = RoundedCornerShape(12.dp), color = Color.Black) {
                Column {
                    RemoteImage("/api/capture/$name", Modifier.fillMaxWidth().heightIn(min = 200.dp, max = 460.dp), ContentScale.Fit, 1600)
                    Text(describeEvent(name), Modifier.padding(10.dp), color = Color.White, fontSize = 13.sp)
                    Row(Modifier.padding(8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Btn("💾 ذخیره") {
                            scope.launch {
                                val b = Api.bytes("/api/capture/$name")
                                toast(if (b != null && saveBytes(name, "image/jpeg", true, b)) "تو گالری ذخیره شد" else "نشد")
                            }
                        }
                        Btn("🗑 حذف") {
                            scope.launch { Api.post("/api/captures/delete", jsonOf("name" to name)); viewImage = null }
                        }
                        Btn("بستن") { viewImage = null }
                    }
                }
            }
        }
    }
    viewVideo?.let { v -> VideoDialog("/api/capture/$v", describeEvent(v)) { viewVideo = null } }
    log?.let { lines ->
        AlertDialog(
            onDismissRequest = { log = null },
            confirmButton = { TextButton(onClick = { log = null }) { Text("باشه") } },
            text = { Column(Modifier.verticalScroll(rememberScrollState())) { for (l in lines) Text(l, fontSize = 12.sp) } }
        )
    }
    if (askDeleteAll) {
        Confirm("پاک کردن همه", "همه‌ی عکس‌ها و ویدیوهای ضبط‌شده از سرور پاک بشن؟",
            { askDeleteAll = false; scope.launch { val r = Api.post("/api/captures/delete", jsonOf("name" to "all")); toast("${r.json.optInt("deleted")} فایل پاک شد") } },
            { askDeleteAll = false })
    }
}
