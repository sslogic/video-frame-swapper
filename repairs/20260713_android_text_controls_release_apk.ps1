$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Readme = Join-Path $Root "README.md"
$ReleaseNotes = Join-Path $Root "ANDROID_RELEASE.md"
$BuiltApk = Join-Path $Root "android\app\build\outputs\apk\debug\app-debug.apk"
$ReleaseApk = Join-Path $Root "releases\video-frame-swapper-debug.apk"

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
foreach ($Path in @($Readme, $ReleaseNotes, $ReleaseApk)) {
    if (!(Test-Path -LiteralPath $Path)) {
        throw "Missing expected file: $Path"
    }
    $Name = Split-Path -Leaf $Path
    Copy-Item -LiteralPath $Path -Destination (Join-Path $BackupDir "$Name.$Stamp.android-text-controls-release.bak") -Force
}
if (!(Test-Path -LiteralPath $BuiltApk)) {
    throw "Missing built APK: $BuiltApk"
}

function Replace-Once {
    param([string]$Text, [string]$Old, [string]$New, [string]$Label)
    if ($Text.IndexOf($New, [StringComparison]::Ordinal) -ge 0) {
        return $Text
    }
    $First = $Text.IndexOf($Old, [StringComparison]::Ordinal)
    if ($First -lt 0) { throw "Could not find expected block: $Label" }
    $Second = $Text.IndexOf($Old, $First + $Old.Length, [StringComparison]::Ordinal)
    if ($Second -ge 0) { throw "Expected block was not unique: $Label" }
    return $Text.Remove($First, $Old.Length).Insert($First, $New)
}

$ReadmeText = (Get-Content -LiteralPath $Readme -Raw).Replace("`r`n", "`n")
$ReadmeText = Replace-Once $ReadmeText `
    '7. Tap in the editor preview to place text. Drag selected text to move it, then use the sliders for size, rotation, opacity, and camouflage.' `
    '7. Tap in the editor preview to place text. Drag selected text to move it, duplicate it, delete it, then use the sliders for size, rotation, opacity, and camouflage.' `
    "README text control step"
Set-Content -LiteralPath $Readme -Value $ReadmeText -NoNewline

$ReleaseText = (Get-Content -LiteralPath $ReleaseNotes -Raw).Replace("`r`n", "`n")
$ReleaseText = Replace-Once $ReleaseText `
    'Use `Edit Image/Text` to work on the selected output frame. It can resize and rotate the imported image without stretching it, remove image backgrounds, place and move text, change text size, rotation, opacity, border, and camouflage color matching, then apply the edited image back to that frame.' `
    'Use `Edit Image/Text` to work on the selected output frame. It can resize and rotate the imported image without stretching it, remove image backgrounds, place and move text, duplicate or delete selected text, change text size, rotation, opacity, border, and camouflage color matching, then apply the edited image back to that frame.' `
    "Android release text controls"
Set-Content -LiteralPath $ReleaseNotes -Value $ReleaseText -NoNewline

Copy-Item -LiteralPath $BuiltApk -Destination $ReleaseApk -Force

$BuiltLength = (Get-Item -LiteralPath $BuiltApk).Length
$ReleaseLength = (Get-Item -LiteralPath $ReleaseApk).Length
if ($BuiltLength -ne $ReleaseLength) {
    throw "Release APK size does not match built APK."
}

$Combined = (Get-Content -LiteralPath $Readme -Raw) + "`n" + (Get-Content -LiteralPath $ReleaseNotes -Raw)
foreach ($Needle in @("duplicate it, delete it", "duplicate or delete selected text")) {
    if ($Combined.IndexOf($Needle, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "Verification failed. Missing text: $Needle"
    }
}

Write-Host "Android text-control release notes and APK updated."
