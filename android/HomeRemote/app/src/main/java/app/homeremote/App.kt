package app.homeremote

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context




class App : Application() {
    override fun onCreate() {
        super.onCreate()
        ctx = applicationContext
        Prefs.init(this)
        Api.rebuild()
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel("stream", "پخش و صدا", NotificationManager.IMPORTANCE_LOW))
        nm.createNotificationChannel(NotificationChannel("watch", "سرویس هشدار زنده", NotificationManager.IMPORTANCE_MIN))
        nm.createNotificationChannel(NotificationChannel("alerts", "هشدار دوربین‌ها", NotificationManager.IMPORTANCE_HIGH))
    }

    companion object {
        lateinit var ctx: Context
    }
}
