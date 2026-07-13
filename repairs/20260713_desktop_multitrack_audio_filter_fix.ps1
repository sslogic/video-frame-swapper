$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$MainPath = Join-Path $Root "movie_quad_editor.py"
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (!(Test-Path -LiteralPath $MainPath)) {
    throw "Missing target file: $MainPath"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -LiteralPath $MainPath -Destination (Join-Path $BackupDir "movie_quad_editor.py.$Stamp.desktop-multitrack-audio-filter.bak") -Force

function Replace-Once {
    param([string]$Text, [string]$Old, [string]$New, [string]$Label)
    $First = $Text.IndexOf($Old, [StringComparison]::Ordinal)
    if ($First -lt 0) { throw "Could not find expected block: $Label" }
    $Second = $Text.IndexOf($Old, $First + $Old.Length, [StringComparison]::Ordinal)
    if ($Second -ge 0) { throw "Expected block was not unique: $Label" }
    return $Text.Remove($First, $Old.Length).Insert($First, $New)
}

$Text = Get-Content -LiteralPath $MainPath -Raw

$Text = Replace-Once $Text @'
        final_inputs = []
        if main_label:
            final_inputs.append(main_label)
        if ducked_added:
            duck_mix = self.mix_audio_labels(filter_parts, ducked_added, "duckmix")
            if main_label:
                filter_parts.append(f"{duck_mix}{main_label}sidechaincompress=threshold=0.08:ratio=8:attack=20:release=250[ducked]")
                final_inputs.append("[ducked]")
            else:
                final_inputs.append(duck_mix)
        final_inputs.extend(normal_added)

        if not final_inputs:
            return [*video_input, *video_output, "-t", f"{self.state.duration:.6f}", str(output_path)]
'@ @'
        final_inputs = []
        main_mix_label = main_label
        main_sidechain_label = main_label
        if ducked_added and main_label:
            filter_parts.append(f"{main_label}asplit=2[mainmix][mainside]")
            main_mix_label = "[mainmix]"
            main_sidechain_label = "[mainside]"
        if main_mix_label:
            final_inputs.append(main_mix_label)
        if ducked_added:
            duck_mix = self.mix_audio_labels(filter_parts, ducked_added, "duckmix")
            if main_sidechain_label:
                filter_parts.append(f"{duck_mix}{main_sidechain_label}sidechaincompress=threshold=0.08:ratio=8:attack=20:release=250[ducked]")
                final_inputs.append("[ducked]")
            else:
                final_inputs.append(duck_mix)
        final_inputs.extend(normal_added)

        if not final_inputs:
            return [*video_input, "-map", "0:v:0", *video_output, "-t", f"{self.state.duration:.6f}", str(output_path)]
'@ "split main audio for ducking"

$Text = Replace-Once $Text @'
        return f"{minutes}:{remain:02d}"
    def on_color_blend_changed(self, _value=None):
'@ @'
        return f"{minutes}:{remain:02d}"

    def on_color_blend_changed(self, _value=None):
'@ "method spacing after format_seconds"

Set-Content -LiteralPath $MainPath -Value $Text -NoNewline

$Repaired = Get-Content -LiteralPath $MainPath -Raw
foreach ($Needle in @(
    "asplit=2[mainmix][mainside]",
    "main_sidechain_label",
    '"-map", "0:v:0"',
    "def on_color_blend_changed"
)) {
    if ($Repaired.IndexOf($Needle, [StringComparison]::Ordinal) -lt 0) {
        throw "Verification failed. Missing repaired text: $Needle"
    }
}

Write-Host "Desktop multi-track audio filter repair complete."
Write-Host "Backup written under $BackupDir with stamp $Stamp."
