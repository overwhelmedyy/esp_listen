plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// 版本号：在 GitHub Actions 上用运行序号自动递增，本地编译时为 1
val buildNumber = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()

// 签名：用仓库里的 signing/release.jks（个人使用的 App，固定密钥保证新版本能直接覆盖安装）
val keystoreFile = rootProject.file("signing/release.jks").takeIf { it.exists() }

android {
    namespace = "com.overwhelmedyy.esplisten"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.overwhelmedyy.esplisten"
        minSdk = 26
        targetSdk = 35
        versionCode = buildNumber
        versionName = "1.0.$buildNumber"
    }

    signingConfigs {
        if (keystoreFile != null) {
            create("release") {
                storeFile = keystoreFile
                storePassword = "esplisten"
                keyAlias = "esplisten"
                keyPassword = "esplisten"
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = if (keystoreFile != null) signingConfigs.getByName("release")
                            else signingConfigs.getByName("debug")
        }
    }

    // 界面和文本数据都在仓库根目录的 web/ 里，直接作为 assets 打包，
    // 同一份网页也能在电脑浏览器里打开测试。
    sourceSets["main"].assets.srcDirs("../web")

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.webkit:webkit:1.12.1")
}
