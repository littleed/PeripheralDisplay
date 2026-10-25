package io.github.littleed.peripheraldisplay.screensaver

import android.app.Activity
import android.os.Bundle
import android.webkit.WebView
import android.widget.Button
import android.widget.EditText
import android.widget.Toast

/**
 * Settings screen, opened from the Fire TV app list. It also takes its
 * settings as extras, so they can be set over ADB instead of typed:
 * adb shell am start -n <package>/.SettingsActivity --es url ... --es entity ... --es token ...
 */
class SettingsActivity : Activity() {
    private lateinit var settings: ArtSettings
    private var preview: WebView? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        settings = ArtSettings(this)
        intent.getStringExtra("url")?.let { settings.url = it }
        intent.getStringExtra("entity")?.let { settings.entity = it }
        intent.getStringExtra("token")?.let { settings.token = it }
        showForm()
    }

    private fun showForm() {
        setContentView(R.layout.settings)
        val url = findViewById<EditText>(R.id.url).apply { setText(settings.url) }
        val entity = findViewById<EditText>(R.id.entity).apply { setText(settings.entity) }
        val token = findViewById<EditText>(R.id.token).apply { setText(settings.token) }
        fun save() {
            settings.url = url.text.toString()
            settings.entity = entity.text.toString()
            settings.token = token.text.toString()
        }
        findViewById<Button>(R.id.save).setOnClickListener {
            save()
            Toast.makeText(this, R.string.saved, Toast.LENGTH_SHORT).show()
        }
        findViewById<Button>(R.id.preview).setOnClickListener {
            save()
            preview = artView(this, settings).also { setContentView(it) }
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        val shown = preview ?: return super.onBackPressed()
        preview = null
        showForm()
        shown.destroy()
    }
}
