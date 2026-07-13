$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Readme = Join-Path $Root "README.md"
$Release = Join-Path $Root "ANDROID_RELEASE.md"
$PlayStore = Join-Path $Root "PLAY_STORE_START.md"

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
foreach ($Path in @($Readme, $Release)) {
    if (!(Test-Path -LiteralPath $Path)) {
        throw "Missing file: $Path"
    }
    Copy-Item -LiteralPath $Path -Destination (Join-Path $BackupDir "$(Split-Path -Leaf $Path).$Stamp.android-audio-docs.bak") -Force
}

function Replace-Once {
    param([string]$Text, [string]$Old, [string]$New, [string]$Label)
    $First = $Text.IndexOf($Old, [StringComparison]::Ordinal)
    if ($First -lt 0) { throw "Could not find expected block: $Label" }
    $Second = $Text.IndexOf($Old, $First + $Old.Length, [StringComparison]::Ordinal)
    if ($Second -ge 0) { throw "Expected block was not unique: $Label" }
    return $Text.Remove($First, $Old.Length).Insert($First, $New)
}

$Text = (Get-Content -LiteralPath $Readme -Raw).Replace("`r`n", "`n")
$Text = Replace-Once $Text @'
- Add a second music track.
- Raise or lower the original soundtrack volume.
- Raise or lower the added music volume.
- Detect the key of the original audio and added music, then pitch-shift the added music to match.
'@ @'
- Open an Audio Editor popup for main audio and added tracks.
- Add multiple MP3/audio tracks.
- Set per-track volume, start time, repeat timing, repeat count, speed, masking, and below-main ducking.
- If the movie has no audio, use the first added track as the main masking track.
- Detect the key of the original audio or first masking track, then pitch-shift added tracks to match.
'@ "README feature audio list"

$Text = Replace-Once $Text @'
The local APK will be created at:

```text
android\app\build\outputs\apk\debug\app-debug.apk
```
'@ @'
The Gradle build writes the local APK under the app build output folder.
'@ "README local APK path"

$Text = Replace-Once $Text @'
11. Tap `Add Music` if you want an extra track.
12. Set `Original Soundtrack Volume` and `Added Music Volume`.
13. Leave key matching enabled if you want the added music pitch-shifted to match the original audio.
14. Tap `Save Folder` and choose where the MP4 should be written.
15. Tap `Export To Chosen Folder`.
'@ @'
11. Tap `Audio Editor` to add sound.
12. Tap `Add Audio Track` and choose an MP3 or other audio file.
13. Edit each track's volume, movie start time, repeat timing, repeat count, speed, masking, and below-main ducking.
14. If the video has no audio, turn on `If movie has no audio, use first added track as main masking track`.
15. Leave key matching enabled if you want added tracks pitch-shifted to match the main audio.
16. Tap `Save Folder` and choose where the MP4 should be written.
17. Tap `Export To Chosen Folder`.
'@ "README Android audio use"
Set-Content -LiteralPath $Readme -Value $Text -NoNewline

$ReleaseText = (Get-Content -LiteralPath $Release -Raw).Replace("`r`n", "`n")
if ($ReleaseText.IndexOf("Audio Editor", [StringComparison]::OrdinalIgnoreCase) -lt 0) {
    $ReleaseText += @'

Audio Editor adds multiple audio tracks with volume, start time, repeat timing, repeat count, speed, masking, below-main ducking, key matching, and the option to use the first added track as the main masking track when the video has no audio.
'@
}
Set-Content -LiteralPath $Release -Value $ReleaseText -NoNewline

Set-Content -LiteralPath $PlayStore -Value @'
# Google Play Store Start

Use this as the first checklist for selling the Android app.

## App Identity

- App name: Mayniak Subliminal Multimedia Studio
- Package id: com.mayniak.subliminalstudio
- Release APK in this branch: releases/mayniak-subliminal-multimedia-studio.apk

## Needed Before Sale

- A Google Play Developer account.
- A signed release build. The APK in this branch is a debug-signed test build and is good for sideload testing, not the final store upload.
- App icon, feature graphic, screenshots, short description, full description, privacy policy URL, and support email.
- Content rating questionnaire.
- Data safety answers.
- Pricing decision: free, paid, or in-app purchases.
- Closed testing track before production release.

## Store Build Notes

- Google Play normally expects an Android App Bundle (`.aab`) for production.
- Create a private upload key and keep it backed up.
- Build a release variant signed with that upload key.
- Test the signed build on a real phone before submitting.
'@ -NoNewline

$Combined = (Get-Content -LiteralPath $Readme -Raw) + "`n" + (Get-Content -LiteralPath $Release -Raw) + "`n" + (Get-Content -LiteralPath $PlayStore -Raw)
foreach ($Needle in @(
    "multiple MP3/audio tracks",
    "first added track as the main masking track",
    "Google Play Developer account",
    "signed release build",
    "com.mayniak.subliminalstudio"
)) {
    if ($Combined.IndexOf($Needle, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "Verification failed. Missing docs text: $Needle"
    }
}

Write-Host "Android audio docs and Play Store starter updated."
