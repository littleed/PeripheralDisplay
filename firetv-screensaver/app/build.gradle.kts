plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "io.github.littleed.peripheraldisplay.screensaver"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.littleed.peripheraldisplay.screensaver"
        minSdk = 22 // Fire OS 5 and later
        targetSdk = 35
        versionCode = 3
        versionName = "0.3"
    }

    buildTypes {
        release {
            // Sideloadable without a keystore, but unlike a debug build not
            // debuggable, so the saved token can't be read with `adb run-as`.
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}
