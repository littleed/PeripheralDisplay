# Peripheral Display screensaver for Fire TV

A small Android TV app that shows a Peripheral Display `image` entity as the
Fire TV's screensaver. It talks to Home Assistant directly, without a
dashboard. Any button on the remote ends the screensaver.

Works on Fire OS 7 and older. Fire OS 8+ (since April 2026) and Fire TV
models with the Ambient Experience ignore third-party screensavers. Vega OS
can't install it at all.

## How it works

```
Fire OS ── idle ──▶ ArtDream (DreamService) ──▶ WebView running art.html
                                                   │
             ws://<HA>/api/websocket  ◀────────────┤ auth with the token,
             subscribe_entities [image.tv_art]     │ then wait for changes
                                                   │
             /api/image_proxy/image.tv_art?token=… ◀┘ load each new render
```

- `ArtDream` is the screensaver Fire OS starts after the idle timeout. It
  opens a full-screen WebView running `assets/art.html`.
- `art.html` connects to the Home Assistant WebSocket API with a long-lived
  access token. It subscribes to the image entity only. The entity's state
  is the time the art was last re-rendered, so a new state means new art. The
  page then loads the new SVG and swaps it in once it has loaded, so the
  screen never flashes. The token in the image URL rotates every 5 minutes;
  that changes only attributes, so the art isn't reloaded for it.
- If Home Assistant restarts or Wi-Fi drops, the last art stays on screen and
  the page reconnects, backing off up to a minute between attempts.
- `SettingsActivity` holds the Home Assistant address, the entity and the
  token. It's listed in the Fire TV app row and has a Preview button. The
  same settings can be passed over ADB, so you don't type a token with the
  remote.

## Home Assistant

1. Add a Peripheral Display entry for the TV with the aspect ratio set to
   16:9, e.g. named "TV art" (`image.tv_art`).
2. Create a user for the TV (Settings → People → Add person, allow login,
   not an administrator, "Can only log in from the local network").
3. Log in as that user, open its profile → Security, and create a long-lived
   access token.

## Build

Needs JDK 17 and the Android SDK (Android Studio has both).

```sh
./gradlew assembleRelease
# app/build/outputs/apk/release/app-release.apk
```

The release build is signed with the local debug key, so it sideloads without
a keystore, and isn't debuggable, so the saved token can't be read over ADB.

## Install on the Fire TV

On the Fire TV, show Developer Options (Settings → My Fire TV → About, select
the device name 7 times), then turn on ADB debugging. Find its IP under
About → Network.

```sh
adb connect <fire-tv-ip>
adb install -r app/build/outputs/apk/release/app-release.apk

adb shell am start -n io.github.littleed.peripheraldisplay.screensaver/.SettingsActivity \
  --es url http://<ha-ip>:8123 --es entity image.tv_art --es token <long-lived-token>

# Note the current screensaver first, so you can go back to it.
adb shell settings get secure screensaver_components

adb shell settings put secure screensaver_components \
  io.github.littleed.peripheraldisplay.screensaver/.ArtDream
adb shell settings put system screen_off_timeout 300000   # start after 5 minutes
```

Check with `adb shell settings get secure screensaver_components`. Use
Preview in the app to see the art straight away. ADB debugging can be turned
off afterwards; a Fire OS update may reset the screensaver, in which case run
the `settings put` lines again.

On a Fire TV Stick 4K Max (Fire OS 7.7.1.7):

- Fire OS won't start the screensaver sooner than 5 minutes; a shorter
  `screen_off_timeout` is treated as 300000.
- The stick goes to sleep, ending the screensaver, once the remote has been
  idle for `secure sleep_timeout` (840000, 14 minutes, on that device).

To go back to Amazon's screensaver, put back the value you noted. On the Fire
TV Stick 4K Max it was:

```sh
adb shell settings put secure screensaver_components \
  com.amazon.ftv.screensaver/.app.services.ScreensaverService
```
