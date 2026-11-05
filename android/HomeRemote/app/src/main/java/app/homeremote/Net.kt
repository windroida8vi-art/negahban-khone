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
import android.content.Context
import android.content.SharedPreferences
import android.net.Uri
import android.provider.OpenableColumns
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import java.net.InetSocketAddress
import java.security.MessageDigest
import java.security.SecureRandom
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLHandshakeException
import javax.net.ssl.SSLSocket
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.BufferedSink
import org.json.JSONArray
import org.json.JSONObject




/** تنظیمات ذخیره‌شده (رمزنگاری‌شده با Keystore اگه گوشی پشتیبانی کنه) */
object Prefs {
    private lateinit var sp: SharedPreferences
    var encrypted = false
        private set

    fun init(ctx: Context) {
        sp = try {
            val key = MasterKey.Builder(ctx).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
            val s = EncryptedSharedPreferences.create(
                ctx, "secure_prefs", key,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
            )
            encrypted = true
            s
        } catch (e: Exception) {
            ctx.getSharedPreferences("plain_prefs", Context.MODE_PRIVATE)
        }
    }

    private fun s(k: String, d: String = ""): String = sp.getString(k, d) ?: d
    private fun p(k: String, v: String) { sp.edit().putString(k, v).apply() }
    private fun b(k: String, d: Boolean = false): Boolean = sp.getBoolean(k, d)
    private fun pb(k: String, v: Boolean) { sp.edit().putBoolean(k, v).apply() }

    var scheme: String
        get() = s("scheme", "https")
        set(v) = p("scheme", v)
    var host: String
        get() = s("host")
        set(v) = p("host", v)
    var port: String
        get() = s("port", "8080")
        set(v) = p("port", v)
    var user: String
        get() = s("user")
        set(v) = p("user", v)
    var pass: String
        get() = s("pass")
        set(v) = p("pass", v)
    var pin: String                       // اثر انگشت SHA-256 گواهی تاییدشده
        get() = s("pin")
        set(v) = p("pin", v)
    var pinFor: String                    // پین برای کدوم host:port ـه
        get() = s("pinFor")
        set(v) = p("pinFor", v)
    var cookies: String
        get() = s("cookies", "[]")
        set(v) = p("cookies", v)
    var lastEvent: String
        get() = s("lastEvent")
        set(v) = p("lastEvent", v)
    var appLock: Boolean
        get() = b("appLock")
        set(v) = pb("appLock", v)
    var watch: Boolean
        get() = b("watch")
        set(v) = pb("watch", v)
    var rememberPass: Boolean
        get() = b("rememberPass", true)
        set(v) = pb("rememberPass", v)

    val serverId: String get() = "$host:$port"
}

object Net {
    fun sha256Hex(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02X".format(it) }

    fun fingerprint(c: X509Certificate): String = sha256Hex(c.encoded)

    fun pretty(fp: String): String = fp.chunked(2).joinToString(":")

    /** فقط اگه گواهی دقیقا همونی باشه که کاربر تایید کرده (pinning) */
    private class PinTrust(private val pin: String) : X509TrustManager {
        override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {}
        override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
            val c = chain?.firstOrNull() ?: throw CertificateException("no certificate")
            if (pin.isEmpty() || Net.fingerprint(c) != pin) throw CertificateException("pin mismatch")
        }
        override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
    }

    /** گواهی سرور رو (بدون اعتماد) میگیره تا کاربر اثر انگشتش رو ببینه و تایید کنه */
    fun probeCert(host: String, port: Int): X509Certificate? {
        var captured: X509Certificate? = null
        val tm = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {}
            override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
                captured = chain?.firstOrNull()
            }
            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
        }
        val ctx = SSLContext.getInstance("TLS")
        ctx.init(null, arrayOf<TrustManager>(tm), SecureRandom())
        val sock = ctx.socketFactory.createSocket() as SSLSocket
        try {
            sock.connect(InetSocketAddress(host, port), 8000)
            sock.soTimeout = 8000
            sock.startHandshake()
        } finally {
            try { sock.close() } catch (e: Exception) { }
        }
        return captured
    }

    fun buildClient(): OkHttpClient {
        val b = OkHttpClient.Builder()
            .cookieJar(PersistentCookieJar())
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
        if (Prefs.scheme == "https") {
            val tm = PinTrust(if (Prefs.pinFor == Prefs.serverId) Prefs.pin else "")
            val ctx = SSLContext.getInstance("TLS")
            ctx.init(null, arrayOf<TrustManager>(tm), SecureRandom())
            b.sslSocketFactory(ctx.socketFactory, tm).hostnameVerifier { _, _ -> true }   // امن: گواهی دقیقا پین شده
        }
        return b.build()
    }
}

/** کوکی نشست رو رمزنگاری‌شده نگه میداره تا با بستن اپ دوباره وارد نشی */
class PersistentCookieJar : CookieJar {
    private val store = LinkedHashMap<String, Cookie>()

    init {
        try {
            val arr = JSONArray(Prefs.cookies)
            for (i in 0 until arr.length()) {
                val o = arr.getJSONObject(i)
                val cb = Cookie.Builder().name(o.getString("n")).value(o.getString("v")).path(o.optString("p", "/"))
                    .expiresAt(o.optLong("e", System.currentTimeMillis() + 86_400_000L))
                    .hostOnlyDomain(o.getString("d"))
                if (o.optBoolean("s")) cb.secure()
                if (o.optBoolean("h")) cb.httpOnly()
                val c = cb.build()
                store[key(c)] = c
            }
        } catch (e: Exception) {
            store.clear()
        }
    }

    private fun key(c: Cookie) = c.domain + "|" + c.path + "|" + c.name

    @Synchronized
    private fun persist() {
        val arr = JSONArray()
        for (c in store.values) {
            if (c.expiresAt < System.currentTimeMillis()) continue
            arr.put(jsonOf("n" to c.name, "v" to c.value, "d" to c.domain, "p" to c.path, "e" to c.expiresAt, "s" to c.secure, "h" to c.httpOnly))
        }
        Prefs.cookies = arr.toString()
    }

    @Synchronized
    override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        for (c in cookies) {
            if (c.expiresAt < System.currentTimeMillis()) store.remove(key(c)) else store[key(c)] = c
        }
        persist()
    }

    @Synchronized
    override fun loadForRequest(url: HttpUrl): List<Cookie> =
        store.values.filter { it.expiresAt > System.currentTimeMillis() && it.matches(url) }

    @Synchronized
    fun clear() {
        store.clear()
        Prefs.cookies = "[]"
    }
}

class Resp(val code: Int, val text: String) {
    val ok: Boolean get() = code in 200..299
    val json: JSONObject by lazy { try { JSONObject(text) } catch (e: Exception) { JSONObject() } }
    val arr: JSONArray by lazy { try { JSONArray(text) } catch (e: Exception) { JSONArray() } }
    val error: String get() = if (code <= 0) text else json.optString("message", json.optString("error", "خطا ($code)"))
}

object Session {
    var loggedIn by mutableStateOf(false)
    var role by mutableStateOf("")
    var serviceMode by mutableStateOf(false)      // سرور تو حالت سرویس (قبل از ورود به ویندوز) کار میکنه
    val isViewer: Boolean get() = role == "viewer"
    fun drop() { loggedIn = false }

    /** برمیگردونه پیام خطا یا null اگه وارد شد */
    suspend fun login(user: String, pass: String, code: String): String? {
        val r = Api.rawLogin(user, pass, code)
        return when {
            r.code == 200 -> {
                role = if (r.json.optString("role") == "viewer") "viewer" else "admin"
                loggedIn = true
                null
            }
            r.code == 403 -> "نام کاربری، رمز یا کد دو مرحله‌ای اشتباهه"
            r.code == 429 -> "چند بار اشتباه زدی؛ ${r.json.optInt("wait", 60)} ثانیه صبر کن"
            r.code == -2 -> "گواهی سرور با اونی که تایید کرده بودی فرق داره (سرور عوض شده؟). تو «تنظیمات» دوباره تاییدش کن."
            r.code <= 0 -> "به سرور وصل نشد: ${r.text}"
            else -> "خطای سرور (${r.code})"
        }
    }

    /** باز کردن اپ: اگه نشست (یا رمز ذخیره‌شده) معتبره، بدون ورود دوباره برو تو */
    suspend fun resume() {
        if (Prefs.host.isEmpty() || Prefs.user.isEmpty()) return
        val r = Api.get("/api/state")
        if (r.code == 200) { if (role.isEmpty()) role = "admin"; loggedIn = true }
        else if (r.code == 403) { role = "viewer"; loggedIn = true }
    }

    suspend fun logout() {
        try { Api.post("/api/logout") } catch (e: Exception) { }
        (Api.jar as? PersistentCookieJar)?.clear()
        loggedIn = false
        role = ""
    }
}

object Api {
    @Volatile var client: OkHttpClient = OkHttpClient()
    @Volatile var stream: OkHttpClient = OkHttpClient()
    private val reloginLock = Mutex()
    val jar: CookieJar get() = client.cookieJar

    val base: String get() = Prefs.scheme + "://" + Prefs.host + ":" + Prefs.port

    fun rebuild() {
        client = Net.buildClient()
        stream = client.newBuilder()
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .callTimeout(0, TimeUnit.MILLISECONDS)
            .pingInterval(25, TimeUnit.SECONDS)
            .build()
    }

    private fun failResp(e: Exception): Resp {
        val ssl = e is SSLHandshakeException || e.cause is CertificateException || (e.message ?: "").contains("pin mismatch")
        return if (ssl) Resp(-2, "گواهی نامعتبر") else Resp(-1, e.message ?: "خطای شبکه")
    }

    suspend fun rawLogin(user: String, pass: String, code: String): Resp = withContext(Dispatchers.IO) {
        try {
            val body = jsonOf("username" to user, "password" to pass, "code" to code).toString().toRequestBody("application/json".toMediaType())
            val req = Request.Builder().url(base + "/api/login").post(body).build()
            client.newCall(req).execute().use { Resp(it.code, it.body?.string() ?: "") }
        } catch (e: Exception) {
            failResp(e)
        }
    }

    private suspend fun reLogin(): Boolean {
        return reloginLock.withLock {
            if (Prefs.pass.isEmpty() || Prefs.user.isEmpty()) {
                false
            } else {
                val r = rawLogin(Prefs.user, Prefs.pass, "")
                if (r.code == 200) {
                    Session.role = if (r.json.optString("role") == "viewer") "viewer" else "admin"
                    true
                } else {
                    false
                }
            }
        }
    }

    suspend fun call(method: String, path: String, body: JSONObject? = null, poll: Boolean = false, retry: Boolean = true): Resp {
        val r = withContext(Dispatchers.IO) {
            try {
                val rb: RequestBody? = if (method == "POST") (body ?: JSONObject()).toString().toRequestBody("application/json".toMediaType()) else null
                val rq = Request.Builder().url(base + path).method(method, rb)
                if (poll) rq.header("X-Poll", "1")
                client.newCall(rq.build()).execute().use { Resp(it.code, it.body?.string() ?: "") }
            } catch (e: Exception) {
                failResp(e)
            }
        }
        if (r.code == 401 && retry && path != "/api/login") {
            return if (reLogin()) call(method, path, body, poll, false) else { Session.drop(); r }
        }
        return r
    }

    suspend fun get(path: String, poll: Boolean = false) = call("GET", path, null, poll)
    suspend fun post(path: String, body: JSONObject? = null) = call("POST", path, body)

    suspend fun bytes(path: String): ByteArray? = withContext(Dispatchers.IO) {
        try {
            client.newCall(Request.Builder().url(base + path).build()).execute().use { if (it.isSuccessful) it.body?.bytes() else null }
        } catch (e: Exception) {
            null
        }
    }

    /** آپلود چند فایل از گوشی (multipart) */
    suspend fun upload(path: String, uris: List<Uri>, field: String, extra: Map<String, String> = emptyMap()): Resp = withContext(Dispatchers.IO) {
        try {
            val cr = App.ctx.contentResolver
            val mb = MultipartBody.Builder().setType(MultipartBody.FORM)
            for ((k, v) in extra) mb.addFormDataPart(k, v)
            for (u in uris) {
                var name = "file"
                var size = -1L
                cr.query(u, null, null, null, null)?.use { c ->
                    val i = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    val j = c.getColumnIndex(OpenableColumns.SIZE)
                    if (c.moveToFirst()) {
                        if (i >= 0) name = c.getString(i) ?: "file"
                        if (j >= 0 && !c.isNull(j)) size = c.getLong(j)
                    }
                }
                val fileSize = size
                val rb = object : RequestBody() {
                    override fun contentType() = "application/octet-stream".toMediaType()
                    override fun contentLength(): Long = fileSize
                    override fun writeTo(sink: BufferedSink) {
                        cr.openInputStream(u)?.use { ins ->
                            val buf = ByteArray(65536)
                            while (true) {
                                val n = ins.read(buf)
                                if (n < 0) break
                                sink.write(buf, 0, n)
                            }
                        }
                    }
                }
                mb.addFormDataPart(field, name, rb)
            }
            val req = Request.Builder().url(base + path).post(mb.build()).build()
            client.newBuilder().writeTimeout(0, TimeUnit.MILLISECONDS).readTimeout(300, TimeUnit.SECONDS).build()
                .newCall(req).execute().use { Resp(it.code, it.body?.string() ?: "") }
        } catch (e: Exception) {
            failResp(e)
        }
    }

    /** دانلود مستقیم به پوشه‌ی Downloads گوشی */
    suspend fun download(path: String, name: String): Boolean = withContext(Dispatchers.IO) {
        try {
            stream.newCall(Request.Builder().url(base + path).build()).execute().use { r ->
                if (!r.isSuccessful) return@withContext false
                saveStream(name, "application/octet-stream", false) { out -> r.body?.byteStream()?.copyTo(out) }
            }
        } catch (e: Exception) {
            false
        }
    }

    fun ws(path: String, listener: WebSocketListener): WebSocket {
        val u = base.replaceFirst("http", "ws") + path
        return stream.newWebSocket(Request.Builder().url(u).build(), listener)
    }
}
