[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
$target = Join-Path $ProjectRoot 'movie_quad_editor.py'
if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
    throw "Target file not found: $target"
}

$source = [IO.File]::ReadAllText($target)
$old = @'
                    if not ok:
                        break
                    current_source_frame = source_frame
                override = self.state.frame_override(output_frame)
                if override and Path(override).exists():
                    out_frame = self.make_replacement_frame(source_frame, override, cached_context_frame)
                else:
                    out_frame = frame
                writer.write(out_frame)
'@
$new = @'
                    if not ok:
                        raise RuntimeError(f"Could not read source frame {source_frame} while exporting output frame {output_frame}.")
                    current_source_frame = source_frame
                override = self.state.frame_override(output_frame)
                if override and Path(override).exists():
                    out_frame = self.make_replacement_frame(source_frame, override, cached_context_frame)
                else:
                    out_frame = frame
                writer.write(out_frame)
'@

$oldFinalize = @'
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            cmd = self.build_ffmpeg_command(ffmpeg, silent_path, output_path)
'@
$newFinalize = @'
            # Finalize the temporary MP4 before FFmpeg tries to read it.
            cap.release()
            cap = None
            context_cap.release()
            context_cap = None
            writer.release()
            writer = None

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            cmd = self.build_ffmpeg_command(ffmpeg, silent_path, output_path)
'@

$newline = if ($source.Contains("`r`n")) { "`r`n" } else { "`n" }
$old = $old.Replace("`r`n", "`n").Replace("`n", $newline)
$new = $new.Replace("`r`n", "`n").Replace("`n", $newline)
$oldFinalize = $oldFinalize.Replace("`r`n", "`n").Replace("`n", $newline)
$newFinalize = $newFinalize.Replace("`r`n", "`n").Replace("`n", $newline)

if ([regex]::Matches($source, [regex]::Escape($old)).Count -ne 1) {
    throw 'Expected exactly one source-frame failure block; no file was changed.'
}
if ([regex]::Matches($source, [regex]::Escape($oldFinalize)).Count -ne 1) {
    throw 'Expected exactly one FFmpeg finalization block; no file was changed.'
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupDir = Join-Path $ProjectRoot "backups\fix-export-nonzero-$stamp"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$backup = Join-Path $backupDir 'movie_quad_editor.py'
Copy-Item -LiteralPath $target -Destination $backup

$updated = $source.Replace($old, $new).Replace($oldFinalize, $newFinalize)
[IO.File]::WriteAllText($target, $updated, [Text.UTF8Encoding]::new($false))

$verified = [IO.File]::ReadAllText($target)
if (-not $verified.Contains($new) -or -not $verified.Contains($newFinalize)) {
    Copy-Item -LiteralPath $backup -Destination $target -Force
    throw "Repair verification failed. The original file was restored from $backup"
}

Write-Host "Export repair applied successfully."
Write-Host "Backup: $backup"
