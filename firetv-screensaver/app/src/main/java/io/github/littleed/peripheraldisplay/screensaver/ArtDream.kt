package io.github.littleed.peripheraldisplay.screensaver

import android.graphics.Color
import android.service.dreams.DreamService
import android.view.Gravity
import android.webkit.WebView
import android.widget.TextView

/** The screensaver Fire OS starts when the TV has been idle. */
class ArtDream : DreamService() {
    private var webView: WebView? = null

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        isInteractive = false // any remote button ends the screensaver
        isFullscreen = true
        isScreenBright = true
        val settings = ArtSettings(this)
        if (settings.isComplete) {
            setContentView(artView(this, settings).also { webView = it })
        } else {
            setContentView(TextView(this).apply {
                setText(R.string.not_set_up)
                gravity = Gravity.CENTER
                textSize = 24f
                setTextColor(Color.GRAY)
            })
        }
    }

    override fun onDetachedFromWindow() {
        webView?.destroy()
        webView = null
        super.onDetachedFromWindow()
    }
}
