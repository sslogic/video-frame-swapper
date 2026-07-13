$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Readme = Join-Path $Root "README.md"
$ReleaseNotes = Join-Path $Root "ANDROID_RELEASE.md"
$BuiltApk = Join-Path $Root "android\app\build\outputs\apk\debug\app-debug.apk"
$ReleaseApk = Join-Path $Root "releases\mayniak-subliminal-multimedia-studio.apk"

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

foreach ($Path in @($Readme, $ReleaseNotes, $ReleaseApk)) {
    if (!(Test-Path -LiteralPath $Path)) {
        throw "Missing expected file: $Path"
    }
    $Name = Split-Path -Leaf $Path
    Copy-Item -LiteralPath $Path -Destination (Join-Path $BackupDir "$Name.$Stamp.android-release-notes.bak") -Force
}

if (!(Test-Path -LiteralPath $BuiltApk)) {
    throw "Missing built APK: $BuiltApk"
}

function Replace-Once {
    param([string]$Text, [string]$Old, [string]$New, [string]$Label)
    $First = $Text.IndexOf($Old, [StringComparison]::Ordinal)
    if ($First -lt 0) { throw "Could not find expected block: $Label" }
    $Second = $Text.IndexOf($Old, $First + $Old.Length, [StringComparison]::Ordinal)
    if ($Second -ge 0) { throw "Expected block was not unique: $Label" }
    return $Text.Remove($First, $Old.Length).Insert($First, $New)
}

function Replace-Once-Or-Skip {
    param([string]$Text, [string]$Old, [string]$New, [string]$Already, [string]$Label)
    if ($Text.IndexOf($Old, [StringComparison]::Ordinal) -ge 0) {
        return Replace-Once $Text $Old $New $Label
    }
    if ($Text.IndexOf($Already, [StringComparison]::Ordinal) -ge 0) {
        return $Text
    }
    throw "Could not find expected or updated block: $Label"
}

$ReadmeText = (Get-Content -LiteralPath $Readme -Raw).Replace("`r`n", "`n")
$ReadmeFeatureNew = @'
- Edit a selected frame with an image/text editor.
- Keep imported images aspect-fit by default, then resize or rotate them on the canvas.
- Add movable text with size, rotation, opacity, optional border, and camouflage color matching.
- Remove image backgrounds by tapping the image layer or using auto background removal.
- Replace a frame every X output frames from the current timeline position.
'@
$ReadmeText = Replace-Once-Or-Skip $ReadmeText @'
- Add text to a selected frame with size, rotation, and X/Y placement controls.
'@ $ReadmeFeatureNew "- Edit a selected frame with an image/text editor." "README feature list"

$ReadmeUseNew = @'
5. Tap `Replace Frame` to choose an image for the selected output frame.
6. Tap `Edit Image/Text` to resize or rotate the image, remove its background, add movable text, and apply the edited frame.
7. Tap in the editor preview to place text. Drag selected text to move it, then use the sliders for size, rotation, opacity, and camouflage.
8. Tap `Replace Every X` to use one image every chosen number of output frames from the current timeline position.
9. Turn color blending on or off.
10. Set `Color Blend Strength` and `Image Frequency Blend`.
11. Tap `Add Music` if you want an extra track.
12. Set `Original Soundtrack Volume` and `Added Music Volume`.
13. Leave key matching enabled if you want the added music pitch-shifted to match the original audio.
14. Tap `Save Folder` and choose where the MP4 should be written.
15. Tap `Export To Chosen Folder`.
'@
$ReadmeText = Replace-Once-Or-Skip $ReadmeText @'
5. Tap `Replace Frame` to choose an image.
6. Tap `Edit Text` to add text to the selected frame.
7. Set text size, rotation, and X/Y placement, then apply it.
8. Turn color blending on or off.
9. Set `Color Blend Strength` and `Image Frequency Blend`.
10. Tap `Add Music` if you want an extra track.
11. Set `Original Soundtrack Volume` and `Added Music Volume`.
12. Leave key matching enabled if you want the added music pitch-shifted to match the original audio.
13. Tap `Save Folder` and choose where the MP4 should be written.
14. Tap `Export To Chosen Folder`.
'@ $ReadmeUseNew '6. Tap `Edit Image/Text`' "README Android use steps"

Set-Content -LiteralPath $Readme -Value $ReadmeText -NoNewline

$ReleaseText = (Get-Content -LiteralPath $ReleaseNotes -Raw).Replace("`r`n", "`n")
$ReleaseNew = @'
Use `Edit Image/Text` to work on the selected output frame. It can resize and rotate the imported image without stretching it, remove image backgrounds, place and move text, change text size, rotation, opacity, border, and camouflage color matching, then apply the edited image back to that frame.

Use `Replace Every X` when you want the same image placed every chosen number of output frames from the current timeline position.

This APK includes output-frame blending, so replacements are blended against the previous and next output frames instead of treating a four-frame source group as one block.
'@
$ReleaseText = Replace-Once-Or-Skip $ReleaseText @'
Use `Edit Text` to add text to the selected frame. The text tool has size, rotation, and X/Y placement controls.
'@ $ReleaseNew 'Use `Edit Image/Text` to work on the selected output frame.' "Android release feature note"

Set-Content -LiteralPath $ReleaseNotes -Value $ReleaseText -NoNewline

Copy-Item -LiteralPath $BuiltApk -Destination $ReleaseApk -Force

foreach ($Needle in @(
    "Edit Image/Text",
    "Replace Every X",
    "remove image backgrounds",
    "without stretching",
    "output-frame blending"
)) {
    $Combined = (Get-Content -LiteralPath $Readme -Raw) + "`n" + (Get-Content -LiteralPath $ReleaseNotes -Raw)
    if ($Combined.IndexOf($Needle, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "Verification failed. Missing text: $Needle"
    }
}

if ((Get-Item -LiteralPath $ReleaseApk).Length -ne (Get-Item -LiteralPath $BuiltApk).Length) {
    throw "Release APK size does not match built APK."
}

Write-Host "Android release notes and APK updated."
