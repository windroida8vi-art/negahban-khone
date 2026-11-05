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
import android.content.Intent
import androidx.core.content.ContextCompat
import androidx.media3.common.MediaItem
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import org.json.JSONObject




/** نگه‌دار پروسه تا وقتی صدا (گوش دادن / صحبت / شنیدن همزمان) فعاله، حتی با خاموش شدن صفحه */
object Streams {
    fun update() {
        val any = Talk.on || Listen.on || SysAudio.on || Mirror.on
        val ctx = App.ctx
        val i = Intent(ctx, StreamService::class.java)
        if (any) ContextCompat.startForegroundService(ctx, i) else ctx.stopService(i)
    }
}

@OptIn(UnstableApi::class)
fun newExo(ctx: Context): ExoPlayer =
    ExoPlayer.Builder(ctx).setMediaSourceFactory(DefaultMediaSourceFactory(OkHttpDataSource.Factory(Api.stream))).build()

/** «شنیدن همزمان»: آهنگی که رو سیستم خونه پخشه، همزمان رو گوشی هم پخش میشه (صدای خونه سر جاشه) */
object Mirror {
    var on by mutableStateOf(false)
    private var player: ExoPlayer? = null
    private var curId = -1

    fun start() {
        if (player == null) player = newExo(App.ctx)
        curId = -1
        on = true
        Streams.update()
    }

    fun stop() {
        player?.release()
        player = null
        curId = -1
        on = false
        Streams.update()
    }

    /** با هر state جدیدِ سرور صدا کن (روی main thread) */
    fun sync(s: JSONObject) {
        if (!on) return
        val p = player ?: return
        val id = if (s.isNull("current")) -1 else s.optInt("current", -1)
        val playing = s.optBoolean("playing", false)
        val pos = s.optDouble("position", 0.0)
        if (id < 0) {
            p.pause()
            return
        }
        if (id != curId) {
            curId = id
            p.setMediaItem(MediaItem.fromUri(Api.base + "/api/stream/" + id))
            p.prepare()
            p.seekTo((pos * 1000).toLong())
        }
        if (playing) {
            if (!p.isPlaying) p.play()
            val drift = Math.abs(p.currentPosition / 1000.0 - pos)
            if (drift > 1.5) p.seekTo(((pos + 0.3) * 1000).toLong())
        } else if (p.isPlaying) {
            p.pause()
        }
    }
}

/** پخش‌کننده‌ی ویدیوهای ضبط‌شده‌ی سرور (با کوکی نشست) */
@Composable
fun VideoDialog(path: String, title: String, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val exo = remember { newExo(ctx) }
    DisposableEffect(path) {
        exo.setMediaItem(MediaItem.fromUri(Api.base + path))
        exo.prepare()
        exo.playWhenReady = true
        onDispose { exo.release() }
    }
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxWidth().padding(8.dp), shape = RoundedCornerShape(12.dp), color = Color.Black) {
            Column {
                Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(title, Modifier.weight(1f), color = Color.White, fontSize = 14.sp)
                    TextButton(onClick = onClose) { Text("بستن") }
                }
                AndroidView(
                    factory = { c -> PlayerView(c).apply { player = exo } },
                    modifier = Modifier.fillMaxWidth().height(260.dp)
                )
            }
        }
    }
}
