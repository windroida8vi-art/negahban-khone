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
import android.content.ContentValues
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.util.LruCache
import android.widget.Toast
import java.io.File
import java.io.FileOutputStream
import java.io.OutputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject




fun jsonOf(vararg p: Pair<String, Any?>): JSONObject {
    val o = JSONObject()
    for ((k, v) in p) o.put(k, v ?: JSONObject.NULL)
    return o
}

fun JSONObject.str(k: String, d: String = ""): String = if (has(k) && !isNull(k)) optString(k, d) else d
fun JSONObject.flag(k: String, d: Boolean = false): Boolean = if (has(k) && !isNull(k)) optBoolean(k, d) else d
fun JSONObject.num(k: String, d: Double = 0.0): Double = if (has(k) && !isNull(k)) optDouble(k, d) else d
fun JSONObject.obj(k: String): JSONObject = optJSONObject(k) ?: JSONObject()
fun JSONArray.objects(): List<JSONObject> = (0 until length()).mapNotNull { optJSONObject(it) }
fun JSONArray.strings(): List<String> = (0 until length()).map { optString(it) }

fun fmtTime(sec: Double): String {
    val s = sec.toInt().coerceAtLeast(0)
    return "%d:%02d".format(s / 60, s % 60)
}

fun toast(msg: String) {
    Handler(Looper.getMainLooper()).post { Toast.makeText(App.ctx, msg, Toast.LENGTH_SHORT).show() }
}

/** ذخیره‌ی فایل: عکس‌ها تو Pictures/HomeRemote، بقیه تو Downloads/HomeRemote */
fun saveStream(name: String, mime: String, image: Boolean, writer: (OutputStream) -> Unit): Boolean {
    return try {
        val ctx = App.ctx
        if (Build.VERSION.SDK_INT >= 29) {
            val cv = ContentValues()
            cv.put(MediaStore.MediaColumns.DISPLAY_NAME, name)
            cv.put(MediaStore.MediaColumns.MIME_TYPE, mime)
            val dir = if (image) Environment.DIRECTORY_PICTURES else Environment.DIRECTORY_DOWNLOADS
            cv.put(MediaStore.MediaColumns.RELATIVE_PATH, "$dir/HomeRemote")
            val col = if (image) MediaStore.Images.Media.EXTERNAL_CONTENT_URI else MediaStore.Downloads.EXTERNAL_CONTENT_URI
            val uri = ctx.contentResolver.insert(col, cv)
            if (uri == null) {
                false
            } else {
                ctx.contentResolver.openOutputStream(uri)?.use { writer(it) }
                true
            }
        } else {
            val d = File(ctx.getExternalFilesDir(null), "HomeRemote")
            d.mkdirs()
            FileOutputStream(File(d, name)).use { writer(it) }
            true
        }
    } catch (e: Exception) {
        false
    }
}

fun saveBytes(name: String, mime: String, image: Boolean, data: ByteArray): Boolean = saveStream(name, mime, image) { it.write(data) }

fun stamp(): String = java.text.SimpleDateFormat("yyyyMMdd-HHmmss", java.util.Locale.US).format(java.util.Date())

/** از اسم فایل رویداد (20261024-040701-n1-p.jpg) توضیح قابل خوندن میسازه */
fun describeEvent(name: String): String {
    val m = Regex("""(\d{8})-(\d{2})(\d{2})(\d{2})(-n(\d))?(-p)?\.""").find(name) ?: return name
    val src = if (m.groupValues[6].isNotEmpty()) "NVR کانال " + m.groupValues[6] else "وب‌کم"
    val who = if (m.groupValues[7].isNotEmpty()) "🧍 آدم" else "⚠ حرکت"
    return who + " · " + src + " · " + m.groupValues[2] + ":" + m.groupValues[3] + ":" + m.groupValues[4]
}

object Img {
    private val cache = object : LruCache<String, Bitmap>(40 * 1024 * 1024) {
        override fun sizeOf(key: String, value: Bitmap): Int = value.byteCount
    }

    fun decode(bytes: ByteArray, maxPx: Int): Bitmap? {
        val o = BitmapFactory.Options()
        o.inJustDecodeBounds = true
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, o)
        var s = 1
        while (o.outWidth / s > maxPx * 2) s *= 2
        val o2 = BitmapFactory.Options()
        o2.inSampleSize = s
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, o2)
    }

    suspend fun load(path: String, maxPx: Int = 480): Bitmap? {
        cache.get(path)?.let { return it }
        val bytes = Api.bytes(path) ?: return null
        val b = withContext(Dispatchers.Default) { decode(bytes, maxPx) }
        if (b != null) cache.put(path, b)
        return b
    }
}

@Composable
fun RemoteImage(path: String, modifier: Modifier = Modifier, scale: ContentScale = ContentScale.Crop, maxPx: Int = 480) {
    val bmp by produceState<Bitmap?>(null, path) { value = Img.load(path, maxPx) }
    Box(modifier.background(Color(0xFF1C2430)), contentAlignment = Alignment.Center) {
        val b = bmp
        if (b != null) {
            Image(b.asImageBitmap(), contentDescription = null, modifier = Modifier.fillMaxSize(), contentScale = scale)
        } else {
            CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp)
        }
    }
}
