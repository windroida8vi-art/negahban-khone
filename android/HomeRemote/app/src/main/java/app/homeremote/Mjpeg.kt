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
import kotlin.coroutines.coroutineContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import okhttp3.Request




/** آخرین فریم یه پخش زنده (برای ذخیره‌ی عکس) */
class FrameHolder {
    @Volatile var last: Bitmap? = null
}

private fun indexOf2(a: ByteArray, len: Int, b1: Int, b2: Int, from: Int): Int {
    var i = from
    while (i < len - 1) {
        if (a[i] == b1.toByte() && a[i + 1] == b2.toByte()) return i
        i++
    }
    return -1
}

/** یه اتصال MJPEG رو تا وقتی کنسل نشه میخونه؛ از فریم‌های عقب‌افتاده فقط آخری رو دیکد میکنه (تاخیر جمع نمیشه) */
private suspend fun readMjpeg(url: String, onFrame: (Bitmap) -> Unit, onState: (String) -> Unit) {
    withContext(Dispatchers.IO) {
        val call = Api.stream.newCall(Request.Builder().url(url).build())
        val canceller = coroutineContext[Job]?.invokeOnCompletion { call.cancel() }
        try {
            call.execute().use { resp ->
                if (!resp.isSuccessful) {
                    onState(if (resp.code == 401) "نشست تموم شده" else if (resp.code == 503) "بعد از ورود به ویندوز فعال میشه" else "خطا ${resp.code}")
                    return@use
                }
                val src = resp.body?.source() ?: return@use
                var acc = ByteArray(1 shl 20)
                var len = 0
                val tmp = ByteArray(32768)
                onState("")
                while (isActive) {
                    val n = src.read(tmp)
                    if (n < 0) break
                    if (len + n > acc.size) acc = acc.copyOf(maxOf(acc.size * 2, len + n))
                    System.arraycopy(tmp, 0, acc, len, n)
                    len += n
                    var pos = 0
                    var ls = -1
                    var le = -1
                    while (true) {
                        val s = indexOf2(acc, len, 0xFF, 0xD8, pos)
                        if (s < 0) break
                        val e = indexOf2(acc, len, 0xFF, 0xD9, s + 2)
                        if (e < 0) { pos = s; break }
                        ls = s
                        le = e + 2
                        pos = le
                    }
                    if (ls >= 0) {
                        val bmp = BitmapFactory.decodeByteArray(acc, ls, le - ls)
                        if (bmp != null) onFrame(bmp)
                    }
                    if (pos > 0) {
                        System.arraycopy(acc, pos, acc, 0, len - pos)
                        len -= pos
                    } else if (len > 0 && indexOf2(acc, len, 0xFF, 0xD8, 0) < 0) {
                        val keep = if (acc[len - 1] == 0xFF.toByte()) 1 else 0
                        if (keep == 1) acc[0] = acc[len - 1]
                        len = keep
                    }
                    if (len > 12_000_000) len = 0
                }
            }
        } catch (e: Exception) {
            if (isActive) onState("قطع شد؛ دوباره وصل میشم…")
        } finally {
            canceller?.dispose()
        }
    }
}

/** پخش زنده‌ی MJPEG (وب‌کم / NVR / دسکتاپ) با اتصال دوباره‌ی خودکار */
@Composable
fun MjpegView(
    url: String,
    modifier: Modifier = Modifier,
    holder: FrameHolder? = null,
    scale: ContentScale = ContentScale.FillWidth,
    onClick: (() -> Unit)? = null,
) {
    var frame by remember(url) { mutableStateOf<Bitmap?>(null) }
    var status by remember(url) { mutableStateOf("در حال اتصال…") }
    LaunchedEffect(url) {
        while (isActive) {
            readMjpeg(url, { b -> frame = b; holder?.last = b; status = "" }, { s -> status = s })
            if (!isActive) break
            delay(2000)
        }
    }
    val base = modifier.background(Color.Black)
    Box(if (onClick != null) base.clickable { onClick() } else base, contentAlignment = Alignment.Center) {
        val f = frame
        if (f != null) {
            Image(f.asImageBitmap(), contentDescription = null, modifier = if (scale == ContentScale.Fit) Modifier.fillMaxSize() else Modifier.fillMaxWidth(), contentScale = scale, filterQuality = FilterQuality.High)
        } else {
            Box(Modifier.fillMaxWidth().height(160.dp))
        }
        if (status.isNotEmpty()) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                if (f == null) CircularProgressIndicator(Modifier.size(28.dp), strokeWidth = 3.dp)
                Text(status, color = Color.White, fontSize = 12.sp, modifier = Modifier.padding(6.dp))
            }
        }
    }
}
