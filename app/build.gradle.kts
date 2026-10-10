import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.devtools.ksp")
    id("com.google.dagger.hilt.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

// Токен приватных релизов — ТОЛЬКО из local.properties (в .gitignore, в git не попадает).
// В APK уезжает как BuildConfig.GITHUB_FILES_TOKEN; в исходниках его быть не должно.
val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}
val githubFilesToken: String = localProps.getProperty("githubFilesToken", "")
    .replace("\\", "\\\\").replace("\"", "\\\"")

android {
    namespace = "com.vedalibrary.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.vedalibrary.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 48
        versionName = "1.3"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField("String", "GITHUB_FILES_TOKEN", "\"$githubFilesToken\"")
    }
    signingConfigs {
        create("release") {
            storeFile = rootProject.file("debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            signingConfig = signingConfigs.getByName("release")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true; buildConfig = true }
    // Baseline Profiles + R8 уже включены через release above
}

dependencies {
    // Core
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.6")

    // Compose + M3
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.navigation:navigation-compose:2.8.9")
    implementation("androidx.compose.foundation:foundation")

    // Coil for illustrations
    implementation("io.coil-kt:coil-compose:2.6.0")

    // DI
    implementation("com.google.dagger:hilt-android:2.52")
    ksp("com.google.dagger:hilt-compiler:2.52")
    implementation("androidx.hilt:hilt-navigation-compose:1.2.0")
    ksp("androidx.hilt:hilt-compiler:1.2.0")

    // Room + FTS (поиск по всем книгам) + DataStore
    implementation("androidx.room:room-runtime:2.6.1")
    ksp("androidx.room:room-compiler:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    implementation("androidx.datastore:datastore-preferences:1.1.1")

    // PDF import: текст извлекаем через pdfbox-android
    implementation("com.tom-roush:pdfbox-android:2.0.4.0")

    // Аудио: ExoPlayer (MediaPlayer не умеет Opus-in-Ogg паки ШБ)
    implementation("androidx.media3:media3-exoplayer:1.5.0")

    // Backup/restore: SAF + kotlinx-serialization для JSON
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
}

// Схемы Room: пишутся при сборке в app/schemas/ — по ним проверяются миграции
// (MigrationTestHelper) и ловятся расхождения схем до релиза, а не на устройствах
ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
}
