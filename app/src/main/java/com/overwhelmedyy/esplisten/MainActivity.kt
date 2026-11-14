package com.overwhelmedyy.esplisten

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.DocumentsContract
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.widget.FrameLayout
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewClientCompat
import org.json.JSONArray
import org.json.JSONObject

/**
 * 界面是打包在 assets 里的 web/index.html（WebView），
 * 播放用原生 MediaPlayer（AudioEngine），音频文件在手机上用户选择的文件夹里。
 */
class MainActivity : ComponentActivity() {

    private lateinit var web: WebView
    private val prefs by lazy { getSharedPreferences("esp_listen", MODE_PRIVATE) }

    /** 文件名 → content:// Uri（扫描所选文件夹得到） */
    @Volatile private var audioFiles: Map<String, Uri> = emptyMap()

    private val pickFolder = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri == null) return@registerForActivityResult
        try {
            contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
        } catch (_: SecurityException) {}
        prefs.edit().putString(KEY_TREE, uri.toString()).apply()
        scanInBackground { web.evaluateJavascript("window.onFolderPicked && window.onFolderPicked()", null) }
    }

    private val askNotif = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        AudioEngine.init(this)

        WindowCompat.setDecorFitsSystemWindows(window, false)
        val night = (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) ==
            Configuration.UI_MODE_NIGHT_YES
        WindowCompat.getInsetsController(window, window.decorView).apply {
            isAppearanceLightStatusBars = !night
            isAppearanceLightNavigationBars = !night
        }

        val root = FrameLayout(this).apply {
            setBackgroundColor(ContextCompat.getColor(this@MainActivity, R.color.page_bg))
        }
        ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            v.setPadding(bars.left, bars.top, bars.right, maxOf(bars.bottom, ime.bottom))
            WindowInsetsCompat.CONSUMED
        }

        val assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        web = WebView(this).apply {
            setBackgroundColor(ContextCompat.getColor(this@MainActivity, R.color.page_bg))
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true     // localStorage：收听进度、设置
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            webViewClient = object : WebViewClientCompat() {
                override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest) =
                    assetLoader.shouldInterceptRequest(request.url)

                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    val url = request.url
                    if (url.host == APP_HOST) return false
                    try { startActivity(Intent(Intent.ACTION_VIEW, url)) } catch (_: ActivityNotFoundException) {}
                    return true
                }
            }
            addJavascriptInterface(Bridge(), "Android")
        }
        root.addView(web, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(root)

        // 先扫描音频文件夹再加载网页，这样网页一打开就能拿到文件列表
        scanInBackground {
            if (savedInstanceState != null) web.restoreState(savedInstanceState)
            else web.loadUrl("https://$APP_HOST/assets/index.html")
        }

        AudioEngine.listener = { ev ->
            if (ev != "state") web.evaluateJavascript("window.onPlayerEvent && window.onPlayerEvent(${JSONObject.quote(ev)})", null)
        }

        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED &&
            !prefs.getBoolean(KEY_ASKED_NOTIF, false)
        ) {
            prefs.edit().putBoolean(KEY_ASKED_NOTIF, true).apply()
            askNotif.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                web.evaluateJavascript("(window.appBack && window.appBack()) === true") { handled ->
                    if (handled != "true") moveTaskToBack(true)   // 不退出，保持后台播放
                }
            }
        })
    }

    // ---------------- 音频文件夹 ----------------

    private fun treeUri(): Uri? {
        val s = prefs.getString(KEY_TREE, null) ?: return null
        val uri = Uri.parse(s)
        val ok = contentResolver.persistedUriPermissions.any { it.uri == uri && it.isReadPermission }
        return if (ok) uri else null
    }

    private fun scanInBackground(then: () -> Unit) {
        Thread {
            audioFiles = try { scan() } catch (_: Exception) { emptyMap() }
            runOnUiThread(then)
        }.start()
    }

    /** 列出所选文件夹（以及下两级子文件夹）里的音频文件 */
    private fun scan(): Map<String, Uri> {
        val tree = treeUri() ?: return emptyMap()
        val result = LinkedHashMap<String, Uri>()
        fun walk(docId: String, depth: Int) {
            val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, docId)
            contentResolver.query(
                children,
                arrayOf(
                    DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                    DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                    DocumentsContract.Document.COLUMN_MIME_TYPE
                ), null, null, null
            )?.use { c ->
                while (c.moveToNext()) {
                    val id = c.getString(0) ?: continue
                    val name = c.getString(1) ?: continue
                    val mime = c.getString(2) ?: ""
                    if (mime == DocumentsContract.Document.MIME_TYPE_DIR) {
                        if (depth < 2) walk(id, depth + 1)
                    } else if (AUDIO_EXT.containsMatchIn(name)) {
                        result[name] = DocumentsContract.buildDocumentUriUsingTree(tree, id)
                    }
                }
            }
        }
        walk(DocumentsContract.getTreeDocumentId(tree), 0)
        return result
    }

    private fun folderName(): String {
        val tree = treeUri() ?: return ""
        return try {
            val doc = DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
            contentResolver.query(doc, arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME), null, null, null)
                ?.use { if (it.moveToFirst()) it.getString(0) else null } ?: ""
        } catch (_: Exception) {
            DocumentsContract.getTreeDocumentId(tree).substringAfterLast(':').substringAfterLast('/')
        }
    }

    // ---------------- 给网页调用的接口：window.Android ----------------

    inner class Bridge {
        @JavascriptInterface
        fun pickFolder() = runOnUiThread {
            try {
                pickFolder.launch(null)
            } catch (_: ActivityNotFoundException) {
                Toast.makeText(this@MainActivity, "系统没有可用的文件管理器", Toast.LENGTH_LONG).show()
            }
        }

        @JavascriptInterface
        fun listAudio(): String = JSONArray().apply {
            for (name in audioFiles.keys) put(JSONObject().put("name", name))
        }.toString()

        @JavascriptInterface
        fun folderName(): String = this@MainActivity.folderName()

        @JavascriptInterface
        fun load(name: String, startMs: Int) {
            val uri = audioFiles[name]
            if (uri == null) {
                runOnUiThread { Toast.makeText(this@MainActivity, "找不到音频：$name", Toast.LENGTH_LONG).show() }
                return
            }
            AudioEngine.load(uri, name, startMs)
        }

        @JavascriptInterface fun play() = AudioEngine.play()
        @JavascriptInterface fun pause() = AudioEngine.pause()
        @JavascriptInterface fun toggle() = AudioEngine.toggle()
        @JavascriptInterface fun seekTo(ms: Int) = AudioEngine.seekTo(ms)
        @JavascriptInterface fun seekBy(ms: Int) = AudioEngine.seekBy(ms)
        @JavascriptInterface fun setSpeed(x: Float) = AudioEngine.setSpeed(x)
        @JavascriptInterface fun state(): String = AudioEngine.stateJson()

        @JavascriptInterface
        fun appVersion(): String = try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: ""
        } catch (_: Exception) { "" }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    override fun onDestroy() {
        AudioEngine.listener = null
        web.destroy()
        super.onDestroy()
    }

    companion object {
        private const val APP_HOST = "appassets.androidplatform.net"
        private const val KEY_TREE = "audio_tree"
        private const val KEY_ASKED_NOTIF = "asked_notif"
        private val AUDIO_EXT = Regex("""\.(mp3|m4a|aac|ogg|opus|wav|flac)$""", RegexOption.IGNORE_CASE)
    }
}
