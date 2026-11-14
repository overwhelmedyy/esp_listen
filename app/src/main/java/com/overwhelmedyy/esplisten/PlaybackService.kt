package com.overwhelmedyy.esplisten

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.graphics.drawable.Icon
import android.media.AudioManager
import android.media.MediaMetadata
import android.media.session.MediaSession
import android.media.session.PlaybackState
import android.os.Build
import android.os.IBinder
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat

/**
 * 前台服务：播放时保持进程存活（锁屏、切到别的 App 都不会被系统杀掉），
 * 并在通知栏/锁屏显示 快退10秒 · 播放/暂停 · 快进10秒。
 * 耳机线控按钮也通过 MediaSession 转到这里。
 */
class PlaybackService : Service() {

    private lateinit var session: MediaSession
    private var noisyRegistered = false

    // 拔耳机 / 蓝牙断开 → 暂停
    private val noisyReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == AudioManager.ACTION_AUDIO_BECOMING_NOISY) AudioEngine.pause()
        }
    }

    override fun onCreate() {
        super.onCreate()
        AudioEngine.init(this)
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, getString(R.string.channel_name), NotificationManager.IMPORTANCE_LOW).apply {
                setShowBadge(false)
            }
        )
        session = MediaSession(this, "esp_listen").apply {
            setCallback(object : MediaSession.Callback() {
                override fun onPlay() = AudioEngine.play()
                override fun onPause() = AudioEngine.pause()
                override fun onStop() = AudioEngine.pause()
                override fun onSkipToNext() = AudioEngine.seekBy(10_000)
                override fun onSkipToPrevious() = AudioEngine.seekBy(-10_000)
                override fun onFastForward() = AudioEngine.seekBy(10_000)
                override fun onRewind() = AudioEngine.seekBy(-10_000)
                override fun onSeekTo(pos: Long) = AudioEngine.seekTo(pos.toInt())
            })
            isActive = true
        }
        ContextCompat.registerReceiver(
            this, noisyReceiver, IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY),
            ContextCompat.RECEIVER_NOT_EXPORTED
        )
        noisyRegistered = true
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_TOGGLE -> AudioEngine.toggle()
            ACTION_BACK -> AudioEngine.seekBy(-10_000)
            ACTION_FWD -> AudioEngine.seekBy(10_000)
        }
        showNotification()
        return START_NOT_STICKY
    }

    private fun showNotification() {
        val playing = AudioEngine.isPlaying()
        val title = displayTitle(AudioEngine.currentName)

        session.setMetadata(
            MediaMetadata.Builder()
                .putString(MediaMetadata.METADATA_KEY_TITLE, title)
                .putString(MediaMetadata.METADATA_KEY_ARTIST, "Spanish for False Beginners")
                .putLong(MediaMetadata.METADATA_KEY_DURATION, AudioEngine.duration().toLong())
                .build()
        )
        session.setPlaybackState(
            PlaybackState.Builder()
                .setActions(
                    PlaybackState.ACTION_PLAY or PlaybackState.ACTION_PAUSE or PlaybackState.ACTION_PLAY_PAUSE or
                        PlaybackState.ACTION_SEEK_TO or PlaybackState.ACTION_SKIP_TO_NEXT or
                        PlaybackState.ACTION_SKIP_TO_PREVIOUS or PlaybackState.ACTION_FAST_FORWARD or
                        PlaybackState.ACTION_REWIND
                )
                .setState(
                    if (playing) PlaybackState.STATE_PLAYING else PlaybackState.STATE_PAUSED,
                    AudioEngine.position().toLong(),
                    if (playing) AudioEngine.speed else 0f
                )
                .build()
        )

        val openApp = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val n = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle(title)
            .setContentText("Spanish for False Beginners")
            .setContentIntent(openApp)
            .setOngoing(playing)
            .setShowWhen(false)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .addAction(action(R.drawable.ic_rewind, "-10秒", ACTION_BACK, 1))
            .addAction(
                if (playing) action(R.drawable.ic_pause, "暂停", ACTION_TOGGLE, 2)
                else action(R.drawable.ic_play, "播放", ACTION_TOGGLE, 2)
            )
            .addAction(action(R.drawable.ic_forward, "+10秒", ACTION_FWD, 3))
            .setStyle(Notification.MediaStyle().setMediaSession(session.sessionToken).setShowActionsInCompactView(0, 1, 2))
            .build()

        // 先进入前台（被 startForegroundService 启动时必须在 5 秒内调用），暂停时再退出前台但保留通知
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK else 0
        try {
            ServiceCompat.startForeground(this, NOTIF_ID, n, type)
        } catch (_: Exception) {
            getSystemService(NotificationManager::class.java).notify(NOTIF_ID, n)
        }
        if (!playing) ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_DETACH)
    }

    private fun action(icon: Int, label: String, act: String, req: Int): Notification.Action {
        val pi = PendingIntent.getService(
            this, req, Intent(this, PlaybackService::class.java).setAction(act),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return Notification.Action.Builder(Icon.createWithResource(this, icon), label, pi).build()
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        // 从最近任务里划掉 App：如果没在播放，就彻底退出
        if (!AudioEngine.isPlaying()) {
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    override fun onDestroy() {
        if (noisyRegistered) unregisterReceiver(noisyReceiver)
        session.release()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        private const val CHANNEL = "playback"
        private const val NOTIF_ID = 1
        const val ACTION_TOGGLE = "toggle"
        const val ACTION_BACK = "back10"
        const val ACTION_FWD = "fwd10"

        /** 播放状态变化时调用，刷新通知；播放中用前台服务方式启动 */
        fun refresh(ctx: Context) {
            val i = Intent(ctx, PlaybackService::class.java)
            try {
                if (AudioEngine.isPlaying()) ctx.startForegroundService(i) else ctx.startService(i)
            } catch (_: Exception) {
                // 后台不允许启动服务时（极少数情况）忽略，下次状态变化再刷新
            }
        }

        /** 音频文件名 → 通知栏标题：去掉 [YouTube ID] 和扩展名 */
        fun displayTitle(name: String?): String =
            (name ?: "").replace(Regex("""\s*\[[A-Za-z0-9_-]{11}]\.\w+$"""), "")
                .replace(Regex("""\.\w+$"""), "")
                .ifBlank { "西语听力" }
    }
}
