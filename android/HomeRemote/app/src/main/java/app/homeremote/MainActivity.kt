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
import android.content.Intent
import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch




class MainActivity : FragmentActivity() {
    private val locked = mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        locked.value = Prefs.appLock
        setContent {
            AppTheme {
                AppRoot(locked.value) { promptUnlock() }
            }
        }
        if (Prefs.appLock) promptUnlock()
    }

    override fun onStart() {
        super.onStart()
        if (Prefs.watch && Session.loggedIn && !Session.isViewer) {
            try { ContextCompat.startForegroundService(this, Intent(this, WatchService::class.java)) } catch (e: Exception) { }
        }
    }

    override fun onStop() {
        super.onStop()
        if (Prefs.appLock) locked.value = true
    }

    override fun onResume() {
        super.onResume()
        if (locked.value && Prefs.appLock) promptUnlock()
    }

    private fun promptUnlock() {
        val auth = BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL
        if (BiometricManager.from(this).canAuthenticate(auth) != BiometricManager.BIOMETRIC_SUCCESS) {
            locked.value = false          // گوشی قفل نداره: قفل اپ معنی نداره
            return
        }
        val prompt = BiometricPrompt(this, ContextCompat.getMainExecutor(this), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) { locked.value = false }
        })
        prompt.authenticate(
            BiometricPrompt.PromptInfo.Builder().setTitle("باز کردن کنترل خونه").setAllowedAuthenticators(auth).build()
        )
    }
}

@Composable
fun AppRoot(locked: Boolean, onUnlock: () -> Unit) {
    var checking by remember { mutableStateOf(Prefs.host.isNotEmpty() && Prefs.user.isNotEmpty()) }
    LaunchedEffect(Unit) {
        if (checking) {
            Session.resume()
            checking = false
        }
    }
    if (checking) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        return
    }
    // ping: تا سرور بدونه گوشی زنده‌ست (پخش‌های زنده بعد از ۴۵ ثانیه بی‌خبری بسته میشن)
    LaunchedEffect(Session.loggedIn) {
        while (Session.loggedIn && isActive) {
            Api.post("/api/ping")
            delay(8000)
        }
    }
    // حالت سرور (سرویس / کامل) رو هر ۱۵ ثانیه چک کن؛ بعد از ورود به ویندوز خودکار عوض میشه
    LaunchedEffect(Session.loggedIn) {
        while (Session.loggedIn && !Session.isViewer && isActive) {
            val r = Api.get("/api/info")
            if (r.ok) Session.serviceMode = r.json.optString("mode") == "service"
            delay(15000)
        }
        Session.serviceMode = false
    }
    when {
        !Session.loggedIn -> LoginScreen()
        locked -> LockScreen(onUnlock)
        Session.isViewer -> ViewerScreen()
        else -> MainScreen()
    }
}

/** دو دکمه‌ی 🏠 خونم / 🚪 رفتم بیرون برای کاربر بیننده (بالای دوربین‌ها) */
@Composable
fun ModeButtons() {
    val scope = rememberCoroutineScope()
    var away by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        while (isActive) {
            val r = Api.get("/api/mode", poll = true)
            if (r.ok) away = r.json.optBoolean("away")
            delay(5000)
        }
    }
    fun set(mode: String) {
        scope.launch {
            val r = Api.post("/api/mode", jsonOf("mode" to mode))
            if (r.ok) away = r.json.optBoolean("away") else toast(r.error)
        }
    }
    Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        val mod = Modifier.weight(1f).height(64.dp)
        if (!away) Button(onClick = { set("home") }, modifier = mod) { Text("🏠 خونم", fontSize = 18.sp) }
        else FilledTonalButton(onClick = { set("home") }, modifier = mod) { Text("🏠 خونم", fontSize = 18.sp) }
        if (away) Button(onClick = { set("away") }, modifier = mod) { Text("🚪 رفتم بیرون", fontSize = 18.sp) }
        else FilledTonalButton(onClick = { set("away") }, modifier = mod) { Text("🚪 رفتم بیرون", fontSize = 18.sp) }
    }
}

@Composable
fun ViewerScreen() {
    val scope = rememberCoroutineScope()
    val land = isLandscape()
    ImmersiveMode(land)
    RotateReset()
    if (land) {
        Box(Modifier.fillMaxSize().background(Color.Black)) {
            NvrView(viewer = true)
            RotateButton(Modifier.align(Alignment.TopStart))
        }
        return
    }
    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("📹 دوربین‌ها", fontWeight = FontWeight.Bold, fontSize = 18.sp, modifier = Modifier.weight(1f))
            TextButton(onClick = { scope.launch { Session.logout() } }) { Text("خروج") }
        }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).navigationBarsPadding()) {
            ModeButtons()
            Spacer(Modifier.height(10.dp))
            NvrView(viewer = true)
            Spacer(Modifier.height(24.dp))
        }
    }
}

private data class TabDef(val key: String, val icon: String, val label: String)

@Composable
fun MainScreen() {
    val tabs = remember {
        listOf(
            TabDef("music", "🎵", "موزیک"), TabDef("cam", "📷", "دوربین"), TabDef("sec", "🛡", "امنیت"),
            TabDef("desk", "🖥", "دسکتاپ"), TabDef("more", "☰", "بیشتر"),
        )
    }
    var tab by rememberSaveable { mutableStateOf("music") }
    // افقی روی دسکتاپ/دوربین: نوارها مخفی میشن و تصویر کل صفحه رو میگیره
    val immersive = isLandscape() && (tab == "desk" || tab == "cam")
    ImmersiveMode(immersive)
    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        bottomBar = {
            if (!immersive) NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
                for (t in tabs) {
                    NavigationBarItem(
                        selected = tab == t.key, onClick = { tab = t.key },
                        icon = { Text(t.icon, fontSize = 20.sp) }, label = { Text(t.label, fontSize = 11.sp) }
                    )
                }
            }
        }
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize().then(if (immersive) Modifier else Modifier.statusBarsPadding())) {
            if (Session.serviceMode && !immersive) {
                Surface(color = MaterialTheme.colorScheme.surfaceVariant, modifier = Modifier.fillMaxWidth()) {
                    Note("🛠 سرور تو حالت سرویس (قبل از ورود به ویندوز) کار میکنه: NVR، امنیت و فایل‌ها الان کار میکنن؛ موزیک، وب‌کم، دسکتاپ و صدا بعد از ورود به ویندوز فعال میشن.", Modifier.padding(10.dp))
                }
            }
            Box(Modifier.weight(1f).fillMaxWidth()) {
                when (tab) {
                    "music" -> MusicScreen()
                    "cam" -> CameraScreen()
                    "sec" -> SecurityScreen()
                    "desk" -> DesktopScreen()
                    else -> MoreScreen()
                }
            }
        }
    }
}
