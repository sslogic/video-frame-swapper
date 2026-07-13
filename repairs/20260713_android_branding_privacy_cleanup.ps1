$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$oldVendor = "ss" + "logic"
$oldPackage = "com." + $oldVendor + ".videoframeswapper"
$oldName = "Video " + "Frame " + "Swapper"
$oldApk = "video-frame-swapper-" + "debug.apk"
$oldRepoHost = "github.com/" + $oldVendor + "/video-frame-swapper"
$oldSdkPath = "E" + ":" + "\android" + "sdk"
$oldWorkspacePath = "E" + ":" + "\movie " + "cutter"

$OldJava = Join-Path $Root "android\app\src\main\java\com\${oldVendor}\videoframeswapper\MainActivity.java"
$NewJavaDir = Join-Path $Root "android\app\src\main\java\com\mayniak\subliminalstudio"
$NewJava = Join-Path $NewJavaDir "MainActivity.java"
$Files = @(
    "README.md",
    "ANDROID_RELEASE.md",
    "android\app\build.gradle",
    "android\app\src\main\res\values\strings.xml",
    "android\app\src\main\AndroidManifest.xml",
    "repairs\20260713_android_editor_feature_update.ps1",
    "repairs\20260713_android_release_notes_and_apk.ps1",
    "repairs\20260713_android_text_controls_release_apk.ps1",
    "repairs\20260713_android_text_editor_controls.ps1",
    "repairs\20260713_android_multitrack_audio_editor.ps1",
    "repairs\20260713_android_multitrack_boundary_fix.ps1",
    "repairs\20260713_android_first_audio_mask_and_duck_fix.ps1"
)

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
foreach ($Rel in $Files) {
    $Path = Join-Path $Root $Rel
    if (Test-Path -LiteralPath $Path) {
        $Name = $Rel.Replace("\", "__")
        Copy-Item -LiteralPath $Path -Destination (Join-Path $BackupDir "$Name.$Stamp.android-branding.bak") -Force
    }
}
if (Test-Path -LiteralPath $OldJava) {
    Copy-Item -LiteralPath $OldJava -Destination (Join-Path $BackupDir "MainActivity.java.$Stamp.android-branding.bak") -Force
}

function Rewrite-File {
    param([string]$Rel)
    $Path = Join-Path $Root $Rel
    if (!(Test-Path -LiteralPath $Path)) {
        return
    }
    $Text = (Get-Content -LiteralPath $Path -Raw).Replace("`r`n", "`n")
    $Text = $Text.Replace("$oldName", "Mayniak Subliminal Multimedia Studio")
    $Text = $Text.Replace("$oldApk", "mayniak-subliminal-multimedia-studio.apk")
    $Text = $Text.Replace("releases/$oldApk", "releases/mayniak-subliminal-multimedia-studio.apk")
    $Text = $Text.Replace("https://github.com/$oldVendor/video-frame-swapper/raw/android-fork/releases/mayniak-subliminal-multimedia-studio.apk", "releases/mayniak-subliminal-multimedia-studio.apk")
    $Text = $Text.Replace("https://github.com/$oldVendor/video-frame-swapper/raw/android-fork/releases/$oldApk", "releases/mayniak-subliminal-multimedia-studio.apk")
    $Text = $Text.Replace("https://github.com/$oldVendor/video-frame-swapper.git", "<repository-url>")
    $Text = $Text.Replace("git clone https://github.com/$oldVendor/video-frame-swapper.git", "git clone <repository-url>")
    $Text = $Text.Replace("$oldSdkPath", "<your Android SDK folder>")
    $Text = $Text.Replace('cd "$oldWorkspacePath\android"', 'cd android')
    $Text = $Text.Replace('$oldWorkspacePath\android\jdk17b\jdk-17.0.19+10', '<your JDK 17 folder>')
    $Text = $Text.Replace('$oldWorkspacePath\android\jdk17\jdk-17.0.19+10', '<your JDK 17 folder>')
    $Text = $Text.Replace("$oldPackage", "com.mayniak.subliminalstudio")
    $Text = $Text.Replace("android\app\src\main\java\com\${oldVendor}\videoframeswapper\MainActivity.java", "android\app\src\main\java\com\mayniak\subliminalstudio\MainActivity.java")
    $Text = $Text.Replace("The debug APK will be created at:", "The local APK will be created at:")
    $Text = $Text.Replace("The debug APK", "The local APK")
    Set-Content -LiteralPath $Path -Value $Text -NoNewline
}

foreach ($Rel in $Files) {
    Rewrite-File $Rel
}

if (Test-Path -LiteralPath $OldJava) {
    New-Item -ItemType Directory -Force -Path $NewJavaDir | Out-Null
    Move-Item -LiteralPath $OldJava -Destination $NewJava -Force
}
if (!(Test-Path -LiteralPath $NewJava)) {
    throw "Missing renamed MainActivity: $NewJava"
}
$Java = (Get-Content -LiteralPath $NewJava -Raw).Replace("`r`n", "`n")
$Java = $Java.Replace("package $oldPackage;", "package com.mayniak.subliminalstudio;")
$Java = $Java.Replace('title.setText("$oldName");', 'title.setText("Mayniak Subliminal Multimedia Studio");')
Set-Content -LiteralPath $NewJava -Value $Java -NoNewline

foreach ($Dir in @(
    (Join-Path $Root "android\app\src\main\java\com\${oldVendor}\videoframeswapper"),
    (Join-Path $Root "android\app\src\main\java\com\${oldVendor}")
)) {
    if (Test-Path -LiteralPath $Dir) {
        try { Remove-Item -LiteralPath $Dir -Force } catch {}
    }
}

$AllTrackedText = @()
foreach ($Rel in $Files) {
    $Path = Join-Path $Root $Rel
    if (Test-Path -LiteralPath $Path) {
        $AllTrackedText += Get-Content -LiteralPath $Path -Raw
    }
}
$AllTrackedText += Get-Content -LiteralPath $NewJava -Raw
$Combined = [String]::Join("`n", $AllTrackedText)
foreach ($Bad in @("$oldName", "$oldPackage", "$oldSdkPath", "$oldWorkspacePath", "$oldApk", "github.com/$oldVendor/video-frame-swapper")) {
    if ($Combined.Contains($Bad)) {
        throw "Cleanup verification failed. Still found: $Bad"
    }
}

Write-Host "Android branding and privacy cleanup complete."
Write-Host "Backup written under $BackupDir with stamp $Stamp."
