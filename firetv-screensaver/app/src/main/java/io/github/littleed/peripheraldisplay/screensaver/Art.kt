package io.github.littleed.peripheraldisplay.screensaver

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.webkit.WebView
import org.json.JSONObject

/** Where the art comes from: the Home Assistant address, an access token and the image entity. */
class ArtSettings(context: Context) {
    private val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)

    var url: String
        get() = prefs.getString("url", "")!!
        set(value) = prefs.edit().putString("url", value.trim().trimEnd('/')).apply()

    var token: String
        get() = prefs.getString("token", "")!!
        set(value) = prefs.edit().putString("token", value.trim()).apply()

    var entity: String
        get() = prefs.getString("entity", "")!!
        set(value) = prefs.edit().putString("entity", value.trim()).apply()

    val isComplete: Boolean
        get() = url.isNotEmpty() && token.isNotEmpty() && entity.isNotEmpty()
}

/** A WebView running art.html, used by both the screensaver and the preview. */
@SuppressLint("SetJavaScriptEnabled")
fun artView(context: Context, art: ArtSettings): WebView = WebView(context).apply {
    settings.javaScriptEnabled = true
    setBackgroundColor(Color.BLACK)
    val config = JSONObject()
        .put("url", art.url)
        .put("token", art.token)
        .put("entity", art.entity)
    val html = context.assets.open("art.html").bufferedReader().use { it.readText() }
        .replace("/*CONFIG*/null", config.toString())
    // With Home Assistant's address as the page's origin, the relative image
    // URLs Home Assistant sends resolve against it.
    loadDataWithBaseURL("${art.url}/", html, "text/html", "utf-8", null)
}
