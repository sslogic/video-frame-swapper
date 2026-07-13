$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Readme = Join-Path $Root "README.md"
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (!(Test-Path -LiteralPath $Readme)) {
    throw "Missing README: $Readme"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -LiteralPath $Readme -Destination (Join-Path $BackupDir "README.md.$Stamp.desktop-multitrack-audio.bak") -Force

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
- Open an Audio Editor popup for the main soundtrack and added audio tracks.
- Add multiple MP3/audio tracks.
- Set main-track volume and per-track volume.
- Set each added track start time, repeat timing, repeat count, and speed from `0.2x` to `5x`.
- Use track masking to compress peaks and limit loud spikes.
- Keep added tracks dynamically below the main track with below-main ducking.
- Detect the key of the original audio and added music, then pitch-shift added tracks to match.
'@ "feature audio list"

$Text = Replace-Once $Text @'
10. Click `Add Music` if you want a second track.
11. Use `Original Soundtrack Volume` to raise or lower the video audio.
12. Use `Added Music Volume` to raise or lower the added track.
13. Click `Tone Match + Half Volume` to set the added track to 50% and pitch-match it to the original audio.
14. Click `Export Video`.
'@ @'
10. Click `Audio Editor` to work on sound.
11. Set the main soundtrack volume.
12. Click `Add Audio Track` and choose an MP3 or other audio file.
13. Edit each added track's volume, movie start time, repeat timing, repeat count, and speed.
14. Use `Track masking` to compress peaks and keep that track from spiking.
15. Use `Keep this track dynamically below the main track` when the added track should duck under the original sound.
16. Turn on key matching if you want added tracks pitch-shifted to match the original audio.
17. Click `Export Video`.
'@ "windows audio steps"

Set-Content -LiteralPath $Readme -Value $Text -NoNewline

$Repaired = Get-Content -LiteralPath $Readme -Raw
foreach ($Needle in @(
    "Audio Editor popup",
    "multiple MP3/audio tracks",
    "0.2x",
    "Track masking",
    "dynamically below the main track",
    "Add Audio Track"
)) {
    if ($Repaired.IndexOf($Needle, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "Verification failed. Missing README text: $Needle"
    }
}

Write-Host "Desktop multi-track audio README repair complete."
Write-Host "Backup written under $BackupDir with stamp $Stamp."
