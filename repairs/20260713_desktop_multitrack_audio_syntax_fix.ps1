$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$MainPath = Join-Path $Root "movie_quad_editor.py"
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (!(Test-Path -LiteralPath $MainPath)) {
    throw "Missing target file: $MainPath"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -LiteralPath $MainPath -Destination (Join-Path $BackupDir "movie_quad_editor.py.$Stamp.desktop-multitrack-audio-syntax.bak") -Force

$Text = Get-Content -LiteralPath $MainPath -Raw
$Text = $Text.Replace(
    "    def on_color_blend_changed(self, _value=None):    def on_color_blend_changed(self, _value=None):",
    "    def on_color_blend_changed(self, _value=None):"
)
$Text = $Text.Replace(
    "        return "","".join(parts) + ("","" if parts else """")    def source_has_audio(self, ffmpeg, media_path):    def source_has_audio(self, ffmpeg, media_path):",
    "        return "","".join(parts) + ("","" if parts else """")`n`n    def source_has_audio(self, ffmpeg, media_path):"
)
Set-Content -LiteralPath $MainPath -Value $Text -NoNewline

$Repaired = Get-Content -LiteralPath $MainPath -Raw
if ($Repaired.Contains("def on_color_blend_changed(self, _value=None):    def on_color_blend_changed")) {
    throw "Duplicate on_color_blend_changed header still present."
}
if ($Repaired.Contains("def source_has_audio(self, ffmpeg, media_path):    def source_has_audio")) {
    throw "Duplicate source_has_audio header still present."
}

Write-Host "Desktop multi-track audio syntax repair complete."
Write-Host "Backup written under $BackupDir with stamp $Stamp."
