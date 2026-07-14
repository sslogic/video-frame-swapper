$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$editorPath = Join-Path $repo 'movie_quad_editor.py'
$agentsPath = Join-Path $repo 'AGENTS.md'
$backupRoot = Join-Path $repo 'backups\20260714_restore_image_editor_and_stable_export'
$oldCommit = '21375fd^'

if (!(Test-Path -LiteralPath $editorPath)) {
    throw "Missing target file: $editorPath"
}
if (!(Test-Path -LiteralPath $agentsPath)) {
    throw "Missing target file: $agentsPath"
}

New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item -LiteralPath $editorPath -Destination (Join-Path $backupRoot "movie_quad_editor.py.$timestamp.bak") -Force
Copy-Item -LiteralPath $agentsPath -Destination (Join-Path $backupRoot "AGENTS.md.$timestamp.bak") -Force

function Get-Block {
    param(
        [Parameter(Mandatory=$true)][string]$Text,
        [Parameter(Mandatory=$true)][string]$StartMarker,
        [Parameter(Mandatory=$true)][string]$EndMarker
    )
    $start = $Text.IndexOf($StartMarker)
    if ($start -lt 0) {
        throw "Start marker not found: $StartMarker"
    }
    $end = $Text.IndexOf($EndMarker, $start)
    if ($end -lt 0) {
        throw "End marker not found after $StartMarker : $EndMarker"
    }
    return $Text.Substring($start, $end - $start)
}

function Replace-Block {
    param(
        [Parameter(Mandatory=$true)][string]$Text,
        [Parameter(Mandatory=$true)][string]$StartMarker,
        [Parameter(Mandatory=$true)][string]$EndMarker,
        [Parameter(Mandatory=$true)][string]$Replacement
    )
    $start = $Text.IndexOf($StartMarker)
    if ($start -lt 0) {
        throw "Start marker not found in current file: $StartMarker"
    }
    $end = $Text.IndexOf($EndMarker, $start)
    if ($end -lt 0) {
        throw "End marker not found in current file after $StartMarker : $EndMarker"
    }
    return $Text.Substring(0, $start) + $Replacement + $Text.Substring($end)
}

function Write-CleanUtf8 {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Text
    )
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, ($Text.TrimEnd("`r", "`n") + "`r`n"), $encoding)
}

Push-Location $repo
try {
    $oldEditor = (git show "${oldCommit}:movie_quad_editor.py") -join "`n"
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($oldEditor)) {
        throw "Could not read old editor source from git commit $oldCommit"
    }
}
finally {
    Pop-Location
}

$current = Get-Content -LiteralPath $editorPath -Raw
$oldImageEditorBlock = Get-Block `
    -Text $oldEditor `
    -StartMarker "    def replace_every_x_frames(self):" `
    -EndMarker "    def clear_frame(self):"

$stableExportBlock = @'
    def _export_worker(self, output_path):
        best_effort_raise_process_priority()
        temp_dir = Path(tempfile.mkdtemp(prefix="quad_editor_"))
        silent_path = temp_dir / "video_no_audio.mp4"
        cap = None
        writer = None
        try:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(
                str(silent_path),
                fourcc,
                self.state.export_fps,
                (self.state.width, self.state.height),
            )
            if not writer.isOpened():
                raise RuntimeError("Could not start MP4 writer.")

            cap = cv2.VideoCapture(str(self.state.video_path))
            current_source_frame = None
            frame = None
            for output_frame in range(self.state.output_frame_count):
                source_frame = self.state.source_frame_for_output(output_frame)
                if source_frame != current_source_frame:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, source_frame)
                    ok, frame = cap.read()
                    if not ok:
                        raise RuntimeError(f"Could not read source frame {source_frame} while exporting output frame {output_frame}.")
                    current_source_frame = source_frame
                override = self.state.frame_override(output_frame)
                if override and Path(override).exists():
                    out_frame = self.make_replacement_frame(output_frame, override)
                else:
                    out_frame = frame
                writer.write(out_frame)
                if output_frame % 20 == 0:
                    self.after(0, self.progress.configure, {"value": output_frame + 1})
                    self.after(
                        0,
                        self.status_var.set,
                        f"Exporting frame {output_frame + 1} of {self.state.output_frame_count}...",
                    )

            writer.release()
            writer = None
            cap.release()
            cap = None

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            cmd = self.build_ffmpeg_command(ffmpeg, silent_path, output_path)
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=high_priority_subprocess_flags(),
            )
            self.after(0, self._export_done, output_path, None)
        except Exception as exc:
            self.after(0, self._export_done, output_path, exc)
        finally:
            if writer is not None:
                writer.release()
            if cap is not None:
                cap.release()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def build_ffmpeg_command(self, ffmpeg, silent_path, output_path):
        video_input = [ffmpeg, "-y", "-i", str(silent_path)]
        video_output = ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        audio_tracks = [track for track in self.state.audio_tracks if track.path and Path(track.path).exists()]
        has_source_audio = self.source_has_audio(ffmpeg, self.state.video_path)
        if not audio_tracks:
            if has_source_audio and abs(self.state.source_volume - 1.0) > 0.001:
                return [
                    *video_input,
                    "-i",
                    str(self.state.video_path),
                    "-filter_complex",
                    f"[1:a:0]volume={self.state.source_volume:.3f},alimiter=limit=0.95[aout]",
                    "-map",
                    "0:v:0",
                    "-map",
                    "[aout]",
                    *video_output,
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(output_path),
                ]
            return [
                *video_input,
                "-i",
                str(self.state.video_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a?",
                *video_output,
                "-c:a",
                "aac",
                "-shortest",
                str(output_path),
            ]

        cmd = [*video_input, "-i", str(self.state.video_path)]
        for track in audio_tracks:
            cmd.extend(["-i", track.path])

        use_first_track_as_main = (not has_source_audio) and self.state.first_audio_as_main_mask and bool(audio_tracks)
        main_track = audio_tracks[0] if use_first_track_as_main else None
        export_tracks = audio_tracks[1:] if use_first_track_as_main else audio_tracks

        source_key = None
        if self.state.music_tone_match:
            if has_source_audio:
                self.after(0, self.status_var.set, "Analyzing audio keys...")
                source_key = analyze_audio_key(ffmpeg, self.state.video_path)
            elif main_track is not None:
                self.after(0, self.status_var.set, "Analyzing first audio track key...")
                source_key = analyze_audio_key(ffmpeg, main_track.path)

        filter_parts = []
        main_label = None
        generated_offset = 0
        if has_source_audio:
            filter_parts.append(f"[1:a:0]volume={self.state.source_volume:.3f},alimiter=limit=0.95[maina]")
            main_label = "[maina]"
        elif main_track is not None:
            main_labels = self.add_audio_track_filters(
                filter_parts,
                input_index=2,
                track=main_track,
                semitone_shift=0,
                label_offset=generated_offset,
            )
            generated_offset += max(1, len(main_labels))
            main_label = self.mix_audio_labels(filter_parts, main_labels, "firstmain")

        normal_added = []
        ducked_added = []
        status_lines = [f"Audio mix: {len(audio_tracks)} added track(s)"]
        if main_track is not None:
            status_lines.append(f"Main masking track: {main_track.name}")
        for index, track in enumerate(export_tracks):
            semitone_shift = 0
            if source_key is not None:
                track_key = analyze_audio_key(ffmpeg, track.path)
                semitone_shift = shortest_semitone_shift(track_key["pc"], source_key["pc"])
                status_lines.append(
                    f"{track.name}: {key_label(track_key)} to {key_label(source_key)} ({semitone_shift:+d} semitones)"
                )
            labels = self.add_audio_track_filters(
                filter_parts,
                input_index=index + (3 if main_track is not None else 2),
                track=track,
                semitone_shift=semitone_shift,
                label_offset=generated_offset,
            )
            generated_offset += max(1, len(labels))
            if track.duck_below_main and has_source_audio:
                ducked_added.extend(labels)
            else:
                normal_added.extend(labels)

        self.after(0, self.status_var.set, "\n".join(status_lines))
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
        audio_out = self.mix_audio_labels(filter_parts, final_inputs, "aout")
        if audio_out != "[aout]":
            filter_parts.append(f"{audio_out}anull[aout]")

        return [
            *cmd,
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            *video_output,
            "-c:a",
            "aac",
            "-t",
            f"{self.state.duration:.6f}",
            str(output_path),
        ]

'@

$updated = Replace-Block `
    -Text $current `
    -StartMarker "    def replace_every_x_frames(self):" `
    -EndMarker "    def clear_frame(self):" `
    -Replacement $oldImageEditorBlock

$updated = Replace-Block `
    -Text $updated `
    -StartMarker "    def select_video_encoder(self, ffmpeg):" `
    -EndMarker "    def add_audio_track_filters(self, filter_parts, input_index, track, semitone_shift, label_offset):" `
    -Replacement $stableExportBlock

$updated = $updated.Replace(
    'self.edit_image_button = ttk.Button(edit_row, text="Edit Frame/Image", command=self.open_import_editor)',
    'self.edit_image_button = ttk.Button(edit_row, text="Edit Imported", command=self.open_import_editor)'
)

Write-CleanUtf8 -Path $editorPath -Text $updated

$after = Get-Content -LiteralPath $editorPath -Raw
$required = @(
    'window.title("Edit Imported Image")',
    'self.edit_image_button = ttk.Button(edit_row, text="Edit Imported", command=self.open_import_editor)',
    'ttk.Label(panel, text="Imported image").grid',
    'def _export_worker(self, output_path):',
    'temp_dir = Path(tempfile.mkdtemp(prefix="quad_editor_"))',
    'cmd = self.build_ffmpeg_command(ffmpeg, silent_path, output_path)',
    'def build_ffmpeg_command(self, ffmpeg, silent_path, output_path):'
)
foreach ($needle in $required) {
    if (!$after.Contains($needle)) {
        throw "Verification failed. Missing expected editor/export text: $needle"
    }
}
$forbidden = @(
    'def select_video_encoder(self, ffmpeg):',
    '"pipe:0"',
    'Exporting with {encoder} encoder'
)
foreach ($needle in $forbidden) {
    if ($after.Contains($needle)) {
        throw "Verification failed. Old raw-pipe/GPU export text still present: $needle"
    }
}

$agents = Get-Content -LiteralPath $agentsPath -Raw
$oldLine = '- Desktop export streams raw frames directly into FFmpeg, tests GPU H.264 encoders first, and falls back to CPU `libx264`.'
$newLine = '- Desktop export writes a temporary silent MP4 first, then uses FFmpeg to mux source and added audio tracks into the final export.'
if ($agents.Contains($oldLine)) {
    $agents = $agents.Replace($oldLine, $newLine)
} elseif (!$agents.Contains($newLine)) {
    throw "AGENTS.md did not contain the expected export contract line."
}
Write-CleanUtf8 -Path $agentsPath -Text $agents

$agentsAfter = Get-Content -LiteralPath $agentsPath -Raw
if (!$agentsAfter.Contains($newLine)) {
    throw "AGENTS.md verification failed."
}

Write-Host "Restored older image editor block and stable temp-video export path."
Write-Host "Backups written to $backupRoot"
