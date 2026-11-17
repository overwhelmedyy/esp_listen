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

    // 两个版本，包名不同，可以同时安装：
    //   plain：西语听力（只有音频 + 双语文本），界面在 web_plain/
    //   study：西语听力·注释（点词注释、性数颜色、手动对齐），界面在 web/
    // 两者共用 web_shared/transcripts.json
    flavorDimensions += "edition"
    productFlavors {
        create("plain") {
            dimension = "edition"
            resValue("string", "app_name", "西语听力")
        }
        create("study") {
            dimension = "edition"
            applicationIdSuffix = ".study"
            resValue("string", "app_name", "西语听力·注释")
        }
    }
    sourceSets["plain"].assets.srcDirs("../web_plain", "../web_shared")
    sourceSets["study"].assets.srcDirs("../web", "../web_shared")

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
