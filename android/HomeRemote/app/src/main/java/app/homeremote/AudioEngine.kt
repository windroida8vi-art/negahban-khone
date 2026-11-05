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
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONObject




private fun hasMic(): Boolean =
    ContextCompat.checkSelfPermission(App.ctx, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

private fun newTrack(rate: Int, channels: Int): AudioTrack {
    val mask = if (channels >= 2) AudioFormat.CHANNEL_OUT_STEREO else AudioFormat.CHANNEL_OUT_MONO
    val min = AudioTrack.getMinBufferSize(rate, mask, AudioFormat.ENCODING_PCM_16BIT)
    val size = maxOf(min * 4, rate * channels * 2 / 2)       // حدود نیم ثانیه بافر (پرش کمتر)
    val t = AudioTrack.Builder()
        .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
        .setAudioFormat(AudioFormat.Builder().setSampleRate(rate).setEncoding(AudioFormat.ENCODING_PCM_16BIT).setChannelMask(mask).build())
        .setBufferSizeInBytes(size)
        .setTransferMode(AudioTrack.MODE_STREAM)
        .build()
    t.play()
    return t
}

/** 👂 صدای میکروفون/وب‌کم خونه -> گوشی (PCM 16kHz مونو) */
object Listen {
    var on by mutableStateOf(false)
    var status by mutableStateOf("")
    private var ws: WebSocket? = null
    private var track: AudioTrack? = null

    fun start() {
        if (on) return
        on = true
        status = "در حال اتصال…"
        track = newTrack(16000, 1)
        ws = Api.ws("/ws/listen", object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) { status = "🔴 زنده" }
            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                try { track?.write(bytes.toByteArray(), 0, bytes.size) } catch (e: Exception) { }
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { fail("قطع شد: " + (t.message ?: "")) }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { fail("بسته شد (شاید سرور میکروفون نداره)") }
        })
        Streams.update()
    }

    private fun fail(msg: String) {
        if (!on) return
        status = msg
        stop(false)
    }

    fun stop(clear: Boolean = true) {
        ws?.cancel()
        ws = null
        try { track?.stop(); track?.release() } catch (e: Exception) { }
        track = null
        on = false
        if (clear) status = ""
        Streams.update()
    }
}

/** 🔊 صدای خود سیستم (آهنگ، فیلم، بازی...) -> گوشی. فریم اول JSON {rate, ch} ـه */
object SysAudio {
    var on by mutableStateOf(false)
    var status by mutableStateOf("")
    var lowQuality by mutableStateOf(false)
    private var ws: WebSocket? = null
    private var track: AudioTrack? = null

    fun start() {
        if (on) return
        on = true
        status = "در حال اتصال…"
        ws = Api.ws("/ws/sysaudio" + if (lowQuality) "?q=lo" else "", object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    val j = JSONObject(text)
                    if (j.has("error")) { fail(j.optString("error")); return }
                    if (track == null) {
                        track = newTrack(j.optInt("rate", 32000), j.optInt("ch", 2))
                        status = "🔴 زنده"
                    }
                } catch (e: Exception) { }
            }
            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                try { track?.write(bytes.toByteArray(), 0, bytes.size) } catch (e: Exception) { }
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { fail("قطع شد: " + (t.message ?: "")) }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { fail("بسته شد") }
        })
        Streams.update()
    }

    private fun fail(msg: String) {
        if (!on) return
        status = msg
        stop(false)
    }

    fun stop(clear: Boolean = true) {
        ws?.cancel()
        ws = null
        try { track?.stop(); track?.release() } catch (e: Exception) { }
        track = null
        on = false
        if (clear) status = ""
        Streams.update()
    }
}

/** 🎤 میکروفون گوشی -> اسپیکر سیستم خونه (فریم اول JSON {rate}، بعد PCM مونو 16-bit).
 *  باگ قبلی: فریم‌های صوتی بعد از ۳۰۰ms فرستاده میشدن حتی اگه اتصال هنوز باز نشده بود (اینترنت کند) و قبل از JSON به سرور میرسیدن
 *  -> سرور قطع میکرد -> «Connection reset». حالا ارسال صدا فقط بعد از onOpen شروع میشه و قطع شدن غیرارادی تا ۳ بار خودکار دوباره وصل میشه. */
object Talk {
    var on by mutableStateOf(false)
    var status by mutableStateOf("")
    private var ws: WebSocket? = null
    private var job: Job? = null
    @Volatile private var opened = false
    @Volatile private var retrying = false
    private var retries = 0

    fun canStart(): Boolean = hasMic()

    @SuppressLint("MissingPermission")
    fun start() {
        if (on || !hasMic()) return
        retries = 0
        begin()
    }

    @SuppressLint("MissingPermission")
    private fun begin() {
        on = true
        opened = false
        status = "در حال اتصال…"
        val rate = 16000
        val min = AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = try {
            AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION, rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(min * 2, 4096))
        } catch (e: Exception) {
            on = false; status = "میکروفون گوشی باز نشد"; Streams.update(); return
        }
        if (rec.state != AudioRecord.STATE_INITIALIZED) {
            try { rec.release() } catch (e: Exception) { }
            on = false; status = "میکروفون گوشی باز نشد (شاید برنامه‌ی دیگه‌ای ازش استفاده میکنه)"; Streams.update(); return
        }
        val socket = Api.ws("/ws/talk", object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                webSocket.send("{\"rate\":$rate}")      // اول JSON، بعد صدا
                opened = true
                status = "🎤 داری حرف میزنی"
            }
            override fun onMessage(webSocket: WebSocket, text: String) {
                if (webSocket !== ws) return
                try {
                    val j = JSONObject(text)
                    if (j.has("error")) giveUp("سرور: " + j.optString("error"))
                } catch (e: Exception) { }
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { if (webSocket === ws) retryOrFail("قطع شد: " + (t.message ?: "")) }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { if (webSocket === ws) retryOrFail("بسته شد") }
        })
        ws = socket
        job = CoroutineScope(Dispatchers.IO).launch {
            val buf = ByteArray(1280)                 // ۴۰ میلی‌ثانیه
            try {
                rec.startRecording()
                var waited = 0
                while (isActive && on && !opened && waited < 10000) { delay(20); waited += 20 }   // صبر تا اتصال واقعا باز بشه
                while (isActive && on && opened) {
                    val n = rec.read(buf, 0, buf.size)
                    if (n > 0) socket.send(ByteString.of(*buf.copyOf(n)))
                    else if (n < 0) break
                }
            } catch (e: Exception) {
            } finally {
                try { rec.stop() } catch (e: Exception) { }
                rec.release()
            }
        }
        Streams.update()
    }

    private fun retryOrFail(msg: String) {
        if (!on) return
        if (retries < 3) {
            retries++
            status = "اتصال دوباره ($retries)…"
            retrying = true
            stop(false)
            CoroutineScope(Dispatchers.Main).launch {
                delay(1000)
                if (retrying) { retrying = false; begin() }
            }
            return
        }
        giveUp(msg)
    }

    private fun giveUp(msg: String) {
        if (!on) return
        status = msg
        stop(false)
    }

    fun stop(clear: Boolean = true) {
        if (clear) retrying = false          // خودت قطع کردی: دوباره وصل نشو
        on = false
        opened = false
        job?.cancel()
        job = null
        ws?.cancel()
        ws = null
        if (clear) status = ""
        Streams.update()
    }
}
