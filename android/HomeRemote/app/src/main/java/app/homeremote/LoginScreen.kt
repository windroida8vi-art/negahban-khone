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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext




@Composable
fun LoginScreen() {
    val scope = rememberCoroutineScope()
    var scheme by remember { mutableStateOf(Prefs.scheme) }
    var host by remember { mutableStateOf(Prefs.host) }
    var port by remember { mutableStateOf(Prefs.port) }
    var user by remember { mutableStateOf(Prefs.user) }
    var pass by remember { mutableStateOf(if (Prefs.rememberPass) Prefs.pass else "") }
    var code by remember { mutableStateOf("") }
    var keepPass by remember { mutableStateOf(Prefs.rememberPass) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf("") }
    var certFp by remember { mutableStateOf<String?>(null) }
    var certInfo by remember { mutableStateOf("") }

    fun applyServer() {
        Prefs.scheme = scheme
        Prefs.host = host.trim()
        Prefs.port = port.trim()
    }

    suspend fun doLogin() {
        applyServer()
        Api.rebuild()
        val err = Session.login(user.trim(), pass, code.trim())
        if (err == null) {
            Prefs.user = user.trim()
            Prefs.rememberPass = keepPass
            Prefs.pass = if (keepPass && Prefs.encrypted) pass else ""
        } else {
            error = err
        }
    }

    fun connect() {
        error = ""
        if (host.isBlank() || port.isBlank() || user.isBlank() || pass.isEmpty()) {
            error = "آدرس، پورت، نام کاربری و رمز رو پر کن"
            return
        }
        busy = true
        scope.launch {
            try {
                val sid = host.trim() + ":" + port.trim()
                if (scheme == "https" && (Prefs.pin.isEmpty() || Prefs.pinFor != sid)) {
                    // اولین اتصال به این سرور: گواهی رو بگیر و از کاربر تایید بخواه (TOFU)
                    val c = withContext(Dispatchers.IO) {
                        try { Net.probeCert(host.trim(), port.trim().toInt()) } catch (e: Exception) { null }
                    }
                    if (c == null) {
                        error = "به سرور وصل نشد (آدرس/پورت یا اینترنت رو چک کن)"
                    } else {
                        certFp = Net.fingerprint(c)
                        certInfo = c.subjectDN.name
                    }
                } else {
                    doLogin()
                }
            } finally {
                busy = false
            }
        }
    }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp).imePadding(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Spacer(Modifier.height(24.dp))
        Text("🏠 کنترل خونه", fontSize = 26.sp, fontWeight = FontWeight.Bold)
        Note("به سرور خونه وصل شو (آدرس همون که تو مرورگر میزنی)")
        Chips(listOf("https" to "https (امن)", "http" to "http"), scheme) { scheme = it }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = host, onValueChange = { host = it }, label = { Text("آدرس / IP") }, singleLine = true,
                modifier = Modifier.weight(2f), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri)
            )
            OutlinedTextField(
                value = port, onValueChange = { port = it.filter { c -> c.isDigit() } }, label = { Text("پورت") }, singleLine = true,
                modifier = Modifier.weight(1f), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
            )
        }
        OutlinedTextField(value = user, onValueChange = { user = it }, label = { Text("نام کاربری") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(
            value = pass, onValueChange = { pass = it }, label = { Text("رمز") }, singleLine = true, modifier = Modifier.fillMaxWidth(),
            visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password)
        )
        OutlinedTextField(
            value = code, onValueChange = { code = it.filter { c -> c.isDigit() }.take(8) }, label = { Text("کد دو مرحله‌ای (فقط اگه فعاله)") },
            singleLine = true, modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
        )
        if (Prefs.encrypted) {
            SwitchRow("ذخیره‌ی رمز (رمزنگاری‌شده تو گوشی)", keepPass) { keepPass = it }
        }
        if (error.isNotEmpty()) Note(error, error = true)
        Button(onClick = { connect() }, enabled = !busy, modifier = Modifier.fillMaxWidth()) {
            if (busy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp) else Text("ورود")
        }
    }

    val fp = certFp
    if (fp != null) {
        AlertDialog(
            onDismissRequest = { certFp = null },
            title = { Text("تایید گواهی سرور") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("این اولین باره به این سرور وصل میشی. اثر انگشت (SHA-256) رو با پنجره‌ی سیاه سرور یا فایل certs/cert.pem مقایسه کن؛ اگه یکیه تایید کن.", fontSize = 13.sp)
                    Text(Net.pretty(fp), fontSize = 11.sp, modifier = Modifier.fillMaxWidth(), color = MaterialTheme.colorScheme.secondary)
                    Note(certInfo)
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    Prefs.pin = fp
                    Prefs.pinFor = host.trim() + ":" + port.trim()
                    certFp = null
                    busy = true
                    scope.launch { try { doLogin() } finally { busy = false } }
                }) { Text("تایید و ورود") }
            },
            dismissButton = { TextButton(onClick = { certFp = null }) { Text("نه") } }
        )
    }
}

@Composable
fun LockScreen(onUnlock: () -> Unit) {
    Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Text("🔒", fontSize = 56.sp)
        Spacer(Modifier.height(12.dp))
        Text("برنامه قفله")
        Spacer(Modifier.height(16.dp))
        Button(onClick = onUnlock) { Text("باز کردن") }
    }
}
