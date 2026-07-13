$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$MainPath = Join-Path $Root "android\app\src\main\java\com\mayniak\subliminalstudio\MainActivity.java"
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (!(Test-Path -LiteralPath $MainPath)) {
    throw "Missing target file: $MainPath"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -LiteralPath $MainPath -Destination (Join-Path $BackupDir "MainActivity.java.$Stamp.android-multitrack-boundary.bak") -Force

$Text = Get-Content -LiteralPath $MainPath -Raw
$Text = $Text.Replace(
    "    private void openFrameImageEditor()    private void openFrameImageEditor() {",
    "    private void openFrameImageEditor() {"
)
Set-Content -LiteralPath $MainPath -Value $Text -NoNewline

$Repaired = Get-Content -LiteralPath $MainPath -Raw
if ($Repaired.Contains("private void openFrameImageEditor()    private void openFrameImageEditor()")) {
    throw "Duplicate openFrameImageEditor header still present."
}

Write-Host "Android multitrack boundary repair complete."
Write-Host "Backup written under $BackupDir with stamp $Stamp."
