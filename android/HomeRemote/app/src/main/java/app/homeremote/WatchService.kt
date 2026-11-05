package app.homeremote

import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch




/** هشدار زنده: هر چند ثانیه رویدادهای جدید سرور رو چک میکنه و اعلان (با عکس) میده */
class WatchService : Service() {
    private var job: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(this, "watch")
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("هشدار زنده فعاله")
            .setContentText("رویدادهای دوربین‌ها دنبال میشن")
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        try {
            ServiceCompat.startForeground(this, 2, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } catch (e: Exception) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (job == null) job = CoroutineScope(Dispatchers.IO + SupervisorJob()).launch { loop() }
        return START_STICKY
    }

    override fun onDestroy() {
        job?.cancel()
        job = null
        super.onDestroy()
    }

    private suspend fun loop() {
        var last = Prefs.lastEvent
        while (currentCoroutineContext().isActive) {
            try {
                if (Session.loggedIn && !Session.isViewer && Prefs.watch) {
                    val r = Api.get("/api/security")
                    if (r.ok) {
                        val names = (r.json.optJSONArray("events")?.objects() ?: emptyList()).map { it.str("name") }
                        if (names.isNotEmpty()) {
                            if (last.isEmpty()) {
                                last = names[0]                       // اولین بار: فقط نقطه‌ی شروع
                            } else {
                                val fresh = names.filter { it > last }
                                // از هر منبع (وب‌کم / NVR کانال N) فقط تازه‌ترین رو اعلان بده
                                val bySource = LinkedHashMap<String, String>()
                                for (nm in fresh) { if (!bySource.containsKey(tagOf(nm))) bySource[tagOf(nm)] = nm }
                                for ((tag, nm) in bySource) notifyEvent(nm, fresh.count { tagOf(it) == tag })
                                if (fresh.isNotEmpty()) last = names[0]
                            }
                            Prefs.lastEvent = last
                        }
                    }
                }
            } catch (e: Exception) {
            }
            delay(6000)
        }
    }

    private fun tagOf(n: String): String = Regex("-n\\d").find(n)?.value ?: "cam"

    private suspend fun notifyEvent(name: String, count: Int) {
        val bmp = try {
            val b = Api.bytes("/api/capture/$name")
            if (b != null) Img.decode(b, 720) else null
        } catch (e: Exception) { null }
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val person = name.contains("-p.")
        val b = NotificationCompat.Builder(this, "alerts")
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle(if (person) "🧍 آدم دیده شد" else "⚠ حرکت")
            .setContentText(describeEvent(name) + if (count > 1) " (+${count - 1})" else "")
            .setContentIntent(open)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
        if (bmp != null) b.setLargeIcon(bmp).setStyle(NotificationCompat.BigPictureStyle().bigPicture(bmp))
        try {
            NotificationManagerCompat.from(this).notify(tagOf(name).hashCode(), b.build())
        } catch (e: SecurityException) {
        }
    }
}
