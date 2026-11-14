package com.overwhelmedyy.esplisten

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaPlayer
import android.media.PlaybackParams
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import org.json.JSONObject

/**
 * 全局唯一的播放器。Activity 和通知栏服务都通过它控制播放，
 * 所以关掉界面（或锁屏）后音频照样继续。
 * 所有对 MediaPlayer 的操作都放到主线程执行。
 */
object AudioEngine {
    private lateinit var app: Context
    private val main = Handler(Looper.getMainLooper())

    private var mp: MediaPlayer? = null
    @Volatile private var prepared = false
    @Volatile var currentName: String? = null
        private set
    @Volatile var speed = 1f
        private set

    /** 播放状态变化 / 出错时通知界面（参数："state" / "completed" / "error:..."） */
    var listener: ((String) -> Unit)? = null

    private var focusRequest: AudioFocusRequest? = null
    private var resumeOnFocusGain = false

    fun init(ctx: Context) {
        if (!::app.isInitialized) app = ctx.applicationContext
    }

    private fun ui(block: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) block() else main.post(block)
    }

    fun load(uri: Uri, name: String, startMs: Int) = ui {
        releasePlayer()
        currentName = name
        val p = MediaPlayer()
        mp = p
        try {
            p.setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            p.setWakeMode(app, PowerManager.PARTIAL_WAKE_LOCK)
            p.setOnPreparedListener {
                prepared = true
                if (startMs > 0) seekTo(startMs)
                play()
            }
            p.setOnCompletionListener {
                notifyChange("completed")
            }
            p.setOnErrorListener { _, what, extra ->
                prepared = false
                notifyChange("error:播放器错误 $what/$extra")
                true
            }
            p.setDataSource(app, uri)
            p.prepareAsync()
        } catch (e: Exception) {
            prepared = false
            notifyChange("error:" + (e.message ?: "无法打开音频"))
        }
    }

    fun play() = ui {
        val p = mp ?: return@ui
        if (!prepared) return@ui
        if (!requestFocus()) return@ui
        try {
            p.start()
            applySpeed()
        } catch (_: IllegalStateException) {}
        notifyChange("state")
    }

    fun pause() = ui {
        val p = mp ?: return@ui
        if (prepared && p.isPlaying) p.pause()
        notifyChange("state")
    }

    fun toggle() = ui { if (isPlaying()) pause() else play() }

    fun seekTo(ms: Int) = ui {
        val p = mp ?: return@ui
        if (!prepared) return@ui
        val target = ms.coerceIn(0, maxOf(0, p.duration - 300))
        p.seekTo(target.toLong(), MediaPlayer.SEEK_CLOSEST)
        notifyChange("state")
    }

    fun seekBy(deltaMs: Int) = ui {
        val p = mp ?: return@ui
        if (!prepared) return@ui
        seekTo(p.currentPosition + deltaMs)
    }

    fun setSpeed(x: Float) = ui {
        speed = x.coerceIn(0.5f, 2f)
        // 注意：MediaPlayer 暂停时设置倍速会自动开始播放，所以暂停时只记下来，播放时再生效
        if (isPlaying()) applySpeed()
    }

    private fun applySpeed() {
        val p = mp ?: return
        try {
            p.playbackParams = (p.playbackParams ?: PlaybackParams()).setSpeed(speed).setPitch(1f)
        } catch (_: Exception) {}
    }

    fun isPlaying(): Boolean = try { prepared && mp?.isPlaying == true } catch (_: Exception) { false }

    fun position(): Int = try { if (prepared) mp?.currentPosition ?: 0 else 0 } catch (_: Exception) { 0 }

    fun duration(): Int = try { if (prepared) mp?.duration ?: 0 else 0 } catch (_: Exception) { 0 }

    fun stateJson(): String = JSONObject().apply {
        put("pos", position())
        put("dur", duration())
        put("playing", isPlaying())
        put("speed", speed.toDouble())
        put("name", currentName ?: "")
    }.toString()

    private fun notifyChange(ev: String) {
        main.post {
            listener?.invoke(ev)
            if (::app.isInitialized && currentName != null) PlaybackService.refresh(app)
        }
    }

    // ---- 音频焦点：来电、其他 App 播放时自动暂停 ----
    private val focusListener = AudioManager.OnAudioFocusChangeListener { change ->
        when (change) {
            AudioManager.AUDIOFOCUS_LOSS -> { resumeOnFocusGain = false; pause() }
            AudioManager.AUDIOFOCUS_LOSS_TRANSIENT,
            AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK -> {
                if (isPlaying()) { resumeOnFocusGain = true; pause() }
            }
            AudioManager.AUDIOFOCUS_GAIN -> {
                if (resumeOnFocusGain) { resumeOnFocusGain = false; play() }
            }
        }
    }

    private fun requestFocus(): Boolean {
        val am = app.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val req = focusRequest ?: AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            .setOnAudioFocusChangeListener(focusListener, main)
            .build().also { focusRequest = it }
        return am.requestAudioFocus(req) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
    }

    private fun releasePlayer() {
        prepared = false
        mp?.let {
            try { it.stop() } catch (_: Exception) {}
            it.release()
        }
        mp = null
    }
}
