$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BuiltApk = Join-Path $Root "android\app\build\outputs\apk\debug\app-debug.apk"
$OldRelease = Join-Path $Root ("releases\" + "video-frame-swapper-" + "debug.apk")
$NewRelease = Join-Path $Root "releases\mayniak-subliminal-multimedia-studio.apk"
$BrandingScript = Join-Path $Root "repairs\20260713_android_branding_privacy_cleanup.ps1"

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
foreach ($Path in @($OldRelease, $NewRelease, $BrandingScript)) {
    if (Test-Path -LiteralPath $Path) {
        $Name = Split-Path -Leaf $Path
        Copy-Item -LiteralPath $Path -Destination (Join-Path $BackupDir "$Name.$Stamp.release-rename.bak") -Force
    }
}
if (!(Test-Path -LiteralPath $BuiltApk)) {
    throw "Missing built APK: $BuiltApk"
}

Copy-Item -LiteralPath $BuiltApk -Destination $NewRelease -Force
if (Test-Path -LiteralPath $OldRelease) {
    Remove-Item -LiteralPath $OldRelease -Force
}

if ((Get-Item -LiteralPath $NewRelease).Length -ne (Get-Item -LiteralPath $BuiltApk).Length) {
    throw "Release APK size does not match built APK."
}

Write-Host "Android release APK renamed."
