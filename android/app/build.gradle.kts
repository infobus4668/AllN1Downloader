import org.gradle.api.GradleException
import org.gradle.api.tasks.Copy
import org.gradle.api.tasks.Sync

plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

val syncDesktopBackend = tasks.register<Copy>("syncDesktopBackend") {
    from(rootProject.file("../app.py"))
    from(rootProject.file("../file_downloads.py"))
    from(rootProject.file("../update_service.py"))
    into(layout.buildDirectory.dir("generated/chaquopy/main"))
}
val syncAndroidAssets = tasks.register<Sync>("syncAndroidAssets") {
    from(rootProject.file("../static")) { into("static") }
    into(layout.buildDirectory.dir("generated/android-assets"))
}

val ndkVersionForRuntime = rootProject.file("ndk-version.txt").readText().trim()
val sdkRootForRuntime = System.getenv("ANDROID_SDK_ROOT") ?: System.getenv("ANDROID_HOME")
    ?: error("Set ANDROID_SDK_ROOT or ANDROID_HOME to package Android native runtimes")
val hostTag = when {
    System.getProperty("os.name").lowercase().contains("windows") -> "windows-x86_64"
    System.getProperty("os.name").lowercase().contains("mac") -> "darwin-x86_64"
    else -> "linux-x86_64"
}
val copyCppRuntime = tasks.register<Copy>("copyAndroidCppRuntime") {
    val ndkLibs = file("$sdkRootForRuntime/ndk/$ndkVersionForRuntime/toolchains/llvm/prebuilt/$hostTag/sysroot/usr/lib")
    from(file("$ndkLibs/aarch64-linux-android/libc++_shared.so")) { into("arm64-v8a") }
    from(file("$ndkLibs/x86_64-linux-android/libc++_shared.so")) { into("x86_64") }
    into(layout.buildDirectory.dir("generated/android-jniLibs"))
}

val signAndroidRelease = providers.gradleProperty("signRelease").orNull == "true"
val androidKeystorePath = System.getenv("ANDROID_KEYSTORE_PATH")
val androidKeystorePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
val androidKeyAlias = System.getenv("ANDROID_KEY_ALIAS")
val androidKeyPassword = System.getenv("ANDROID_KEY_PASSWORD")
if (signAndroidRelease && listOf(androidKeystorePath, androidKeystorePassword, androidKeyAlias, androidKeyPassword).any { it.isNullOrBlank() }) {
    throw GradleException("Set ANDROID_KEYSTORE_PATH, ANDROID_KEYSTORE_PASSWORD, ANDROID_KEY_ALIAS and ANDROID_KEY_PASSWORD to sign the Android release.")
}

android {
    namespace = "com.allinone.android"
    compileSdk = 37
    ndkVersion = ndkVersionForRuntime

    defaultConfig {
        applicationId = "com.allinone.android"
        minSdk = 29
        targetSdk = 37
        // Keep the existing applicationId/signing key so users can update their installation.
        versionCode = 9
        versionName = "1.1.2"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk { abiFilters += setOf("arm64-v8a", "x86_64") }
    }

    signingConfigs {
        if (signAndroidRelease) {
            create("release") {
                storeFile = file(androidKeystorePath!!)
                storePassword = androidKeystorePassword!!
                keyAlias = androidKeyAlias!!
                keyPassword = androidKeyPassword!!
            }
        }
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
            if (signAndroidRelease) signingConfig = signingConfigs.getByName("release")
        }
    }

    sourceSets.getByName("main").assets.directories.add(
        layout.buildDirectory.dir("generated/android-assets").get().asFile.absolutePath
    )
    sourceSets.getByName("main").jniLibs.directories.add(
        layout.buildDirectory.dir("generated/android-jniLibs").get().asFile.absolutePath
    )

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        jniLibs {
            useLegacyPackaging = true
            excludes += setOf("**/libpython.so")
        }
    }
}

chaquopy {
    defaultConfig {
        version = "3.12"
        buildPython(providers.gradleProperty("chaquopyBuildPython").orElse("python").get())
        pip { install("-r", "requirements.txt") }
    }
    sourceSets { getByName("main") { srcDir(syncDesktopBackend) } }
}

tasks.named("preBuild").configure { dependsOn(syncDesktopBackend) }
tasks.matching { it.name.endsWith("PythonSources") }.configureEach { dependsOn(syncDesktopBackend) }
tasks.matching { it.name.startsWith("merge") && it.name.endsWith("Assets") }.configureEach { dependsOn(syncAndroidAssets) }
tasks.matching { it.name.lowercase().contains("lint") }.configureEach { dependsOn(syncAndroidAssets) }
tasks.matching { it.name.startsWith("merge") && it.name.endsWith("JniLibFolders") }.configureEach { dependsOn(copyCppRuntime) }
tasks.matching { it.name == "preReleaseBuild" }.configureEach {
    doFirst {
        if (!signAndroidRelease) throw GradleException("Release APK/AAB builds require -PsignRelease=true and the Android keystore environment variables.")
    }
}

dependencies {
    implementation("androidx.activity:activity:1.13.0")
    implementation("androidx.core:core:1.19.1")
    // This library is used for its packaged QuickJS and FFmpeg native runtimes.
    implementation("io.github.junkfood02.youtubedl-android:library:0.18.1")
    implementation("io.github.junkfood02.youtubedl-android:ffmpeg:0.18.1")
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test:rules:1.7.0")
}
