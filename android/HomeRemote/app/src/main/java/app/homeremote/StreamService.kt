package app.homeremote

import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat




class StreamService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(this, "stream")
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("کنترل خونه")
            .setContentText("صدا یا پخش زنده فعاله")
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        var type = ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
        if (Talk.on && Talk.canStart()) type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
        try {
            ServiceCompat.startForeground(this, 1, n, type)
        } catch (e: Exception) {
            try { ServiceCompat.startForeground(this, 1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK) } catch (e2: Exception) { }
        }
        return START_NOT_STICKY
    }
}
