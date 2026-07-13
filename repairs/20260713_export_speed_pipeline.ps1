$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$MoviePath = Join-Path $Root "movie_quad_editor.py"
$AgentsPath = Join-Path $Root "AGENTS.md"
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (!(Test-Path -LiteralPath $MoviePath)) {
    throw "Missing target file: $MoviePath"
}
if (!(Test-Path -LiteralPath $AgentsPath)) {
    throw "Missing target file: $AgentsPath"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -LiteralPath $MoviePath -Destination (Join-Path $BackupDir "movie_quad_editor.py.$Stamp.export-speed.bak") -Force
Copy-Item -LiteralPath $AgentsPath -Destination (Join-Path $BackupDir "AGENTS.md.$Stamp.export-speed.bak") -Force

function Replace-Once {
    param(
        [string]$Text,
        [string]$Old,
        [string]$New,
        [string]$Label
    )
    $First = $Text.IndexOf($Old, [StringComparison]::Ordinal)
    if ($First -lt 0) {
        throw "Could not find expected block: $Label"
    }
    $Second = $Text.IndexOf($Old, $First + $Old.Length, [StringComparison]::Ordinal)
    if ($Second -ge 0) {
        throw "Expected block was not unique: $Label"
    }
    return $Text.Remove($First, $Old.Length).Insert($First, $New)
}

function Replace-MethodRange {
    param(
        [string]$Text,
        [string]$StartMarker,
        [string]$EndMarker,
        [string]$New,
        [string]$Label
    )
    $Start = $Text.IndexOf($StartMarker, [StringComparison]::Ordinal)
    if ($Start -lt 0) {
        throw "Could not find start marker for $Label"
    }
    $End = $Text.IndexOf($EndMarker, $Start + $StartMarker.Length, [StringComparison]::Ordinal)
    if ($End -lt 0) {
        throw "Could not find end marker for $Label"
    }
    return $Text.Remove($Start, $End - $Start).Insert($Start, $New)
}

$Text = (Get-Content -LiteralPath $MoviePath -Raw).Replace("`r`n", "`n")

$OldPriority = @'
def high_priority_subprocess_flags():
    if os.name != "nt":
        return 0
    return getattr(subprocess, "ABOVE_NORMAL_PRIORITY_CLASS", 0)


class FixedValue:
'@

$NewPriority = @'
def high_priority_subprocess_flags():
    if os.name != "nt":
        return 0
    return getattr(subprocess, "ABOVE_NORMAL_PRIORITY_CLASS", 0)


def encoder_options(encoder):
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "21", "-pix_fmt", "yuv420p"]
    if encoder == "h264_qsv":
        return ["-c:v", "h264_qsv", "-global_quality", "23", "-pix_fmt", "nv12"]
    if encoder == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "balanced", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]


class FixedValue:
'@

$Text = Replace-Once $Text $OldPriority $NewPriority "encoder option helpers"

$OldFrameMethods = @'
    def get_output_frame(self, output_frame):
        source_frame = self.state.source_frame_for_output(output_frame)
        override = self.state.frame_override(output_frame)
        if override and Path(override).exists():
            return self.make_replacement_frame(source_frame, override)
        return self.read_frame(source_frame)

    def source_frame_cache_bytes(self, frame_count):
'@

$NewFrameMethods = @'
    def get_output_frame(self, output_frame):
        source_frame = self.state.source_frame_for_output(output_frame)
        override = self.state.frame_override(output_frame)
        if override and Path(override).exists():
            return self.make_replacement_frame(output_frame, override)
        return self.read_frame(source_frame)

    def source_frame_cache_bytes(self, frame_count):
'@

$Text = Replace-Once $Text $OldFrameMethods $NewFrameMethods "get_output_frame output-frame replacement"

$OldReplacement = @'
    def make_replacement_frame(self, frame_index, override_path, frame_reader=None):
        replacement = image_to_bgr(override_path, (self.state.width, self.state.height))
        if not self.state.frame_color_blend:
            return replacement
        frame_reader = frame_reader or self.read_frame_from_video
        previous_frame = frame_reader(max(0, frame_index - 1))
        next_frame = frame_reader(min(self.state.frame_count - 1, frame_index + 1))
        return blend_replacement_frame(
            replacement,
            previous_frame,
            next_frame,
            self.state.frame_color_blend_strength,
            self.state.frame_frequency_blend_strength,
        )

    def show_current_frame(self):
'@

$NewReplacement = @'
    def preload_replacement_images(self):
        cache = {}
        for override in sorted({str(path) for path in self.state.edits.values()}):
            path = Path(override)
            if path.exists():
                cache[str(path)] = image_to_bgr(path, (self.state.width, self.state.height))
        if cache:
            self.after(0, self.status_var.set, f"Cached {len(cache)} replacement images for export...")
        return cache

    def make_replacement_frame(self, output_frame, override_path, frame_reader=None, replacement_cache=None):
        path_key = str(Path(override_path))
        replacement = replacement_cache.get(path_key) if replacement_cache is not None else None
        if replacement is None:
            replacement = image_to_bgr(override_path, (self.state.width, self.state.height))
        if not self.state.frame_color_blend:
            return replacement
        frame_reader = frame_reader or self.read_frame_from_video
        previous_output = max(0, output_frame - 1)
        next_output = min(self.state.output_frame_count - 1, output_frame + 1)
        previous_frame = frame_reader(self.state.source_frame_for_output(previous_output))
        next_frame = frame_reader(self.state.source_frame_for_output(next_output))
        return blend_replacement_frame(
            replacement,
            previous_frame,
            next_frame,
            self.state.frame_color_blend_strength,
            self.state.frame_frequency_blend_strength,
        )

    def show_current_frame(self):
'@

$Text = Replace-Once $Text $OldReplacement $NewReplacement "replacement image cache and output-frame blending"

$NewExportWorker = @'
    def select_video_encoder(self, ffmpeg):
        for encoder in ("h264_nvenc", "h264_qsv", "h264_amf"):
            if self.test_video_encoder(ffmpeg, encoder):
                return encoder
        return "libx264"

    def test_video_encoder(self, ffmpeg, encoder):
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=64x64:rate=1",
            "-frames:v",
            "1",
            *encoder_options(encoder),
            "-f",
            "null",
            "-",
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=high_priority_subprocess_flags(),
            )
            return True
        except Exception:
            return False

    def _export_worker(self, output_path):
        best_effort_raise_process_priority()
        cap = None
        context_cap = None
        process = None
        try:
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            encoder = self.select_video_encoder(ffmpeg)
            self.after(0, self.status_var.set, f"Exporting with {encoder} encoder...")
            cmd = self.build_ffmpeg_command(ffmpeg, output_path, encoder)
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                creationflags=high_priority_subprocess_flags(),
            )

            replacement_cache = self.preload_replacement_images()
            source_cache = None
            if self.source_frame_cache_bytes(self.state.frame_count) <= SOURCE_FRAME_CACHE_LIMIT_BYTES:
                source_cache = self.preload_source_frames(range(self.state.frame_count), "Export")

            context_preload = None
            if source_cache is None and self.state.frame_color_blend:
                context_indices = []
                for output_frame_text in self.state.edits:
                    try:
                        output_frame = int(output_frame_text)
                    except ValueError:
                        continue
                    previous_output = max(0, output_frame - 1)
                    next_output = min(self.state.output_frame_count - 1, output_frame + 1)
                    context_indices.extend(
                        (
                            self.state.source_frame_for_output(previous_output),
                            self.state.source_frame_for_output(next_output),
                        )
                    )
                context_preload = self.preload_source_frames(context_indices, "Export replacements")

            cap = cv2.VideoCapture(str(self.state.video_path))
            context_cap = cv2.VideoCapture(str(self.state.video_path))
            context_cache = {}
            current_source_frame = None
            frame = None

            def cached_context_frame(frame_index):
                frame_index = clamp(frame_index, 0, self.state.frame_count - 1)
                if source_cache is not None and frame_index in source_cache:
                    return source_cache[frame_index]
                if context_preload is not None and frame_index in context_preload:
                    return context_preload[frame_index]
                cached = context_cache.get(frame_index)
                if cached is None:
                    cached = self.read_frame_from_video(frame_index, context_cap)
                    context_cache[frame_index] = cached
                    if len(context_cache) > 256:
                        context_cache.pop(next(iter(context_cache)))
                return cached

            for output_frame in range(self.state.output_frame_count):
                source_frame = self.state.source_frame_for_output(output_frame)
                if source_frame != current_source_frame:
                    if source_cache is not None and source_frame in source_cache:
                        frame = source_cache[source_frame]
                        ok = True
                    elif current_source_frame is not None and source_frame == current_source_frame + 1:
                        ok, frame = cap.read()
                    else:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, source_frame)
                        ok, frame = cap.read()
                    if not ok:
                        raise RuntimeError(f"Could not read source frame {source_frame} while exporting output frame {output_frame}.")
                    current_source_frame = source_frame
                override = self.state.frame_override(output_frame)
                if override and Path(override).exists():
                    out_frame = self.make_replacement_frame(output_frame, override, cached_context_frame, replacement_cache)
                else:
                    out_frame = frame
                process.stdin.write(np.ascontiguousarray(out_frame).tobytes())
                if output_frame % 20 == 0:
                    self.after(0, self.progress.configure, {"value": output_frame + 1})
                    self.after(
                        0,
                        self.status_var.set,
                        f"Exporting frame {output_frame + 1} of {self.state.output_frame_count} with {encoder}...",
                    )

            process.stdin.close()
            process.stdin = None
            stdout, stderr = process.communicate()
            if process.returncode != 0:
                error_text = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else str(stderr)
                raise RuntimeError(error_text.strip() or f"FFmpeg failed with exit code {process.returncode}.")
            self.after(0, self._export_done, output_path, None)
        except Exception as exc:
            self.after(0, self._export_done, output_path, exc)
        finally:
            if cap is not None:
                cap.release()
            if context_cap is not None:
                context_cap.release()
            if process is not None and process.stdin:
                try:
                    process.stdin.close()
                except Exception:
                    pass

'@

$Text = Replace-MethodRange $Text "    def _export_worker(self, output_path):" "    def build_ffmpeg_command" $NewExportWorker "direct FFmpeg pipe export worker"

$NewBuildCommand = @'
    def build_ffmpeg_command(self, ffmpeg, output_path, encoder):
        video_input = [
            ffmpeg,
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s:v",
            f"{self.state.width}x{self.state.height}",
            "-r",
            f"{self.state.export_fps:.6f}",
            "-i",
            "pipe:0",
        ]
        video_output = encoder_options(encoder)
        music_path = Path(self.state.music_path) if self.state.music_path else None
        has_music = music_path and music_path.exists()
        if not has_music:
            has_source_audio = self.source_has_audio(ffmpeg, self.state.video_path)
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

        has_source_audio = self.source_has_audio(ffmpeg, self.state.video_path)
        semitone_shift = 0
        if self.state.music_tone_match and has_source_audio:
            self.after(0, self.status_var.set, "Analyzing audio keys...")
            source_key = analyze_audio_key(ffmpeg, self.state.video_path)
            music_key = analyze_audio_key(ffmpeg, music_path)
            semitone_shift = shortest_semitone_shift(music_key["pc"], source_key["pc"])
            self.after(
                0,
                self.status_var.set,
                f"Key match: music {key_label(music_key)} to video {key_label(source_key)} ({semitone_shift:+d} semitones).",
            )

        music_filter = f"{ffmpeg_pitch_filter(semitone_shift)}volume={self.state.music_volume:.3f}"
        if self.state.music_tone_match:
            music_filter += ",highpass=f=80,lowpass=f=12000,acompressor=threshold=0.25:ratio=2.5:attack=20:release=250"
        export_duration = f"{self.state.duration:.6f}"

        if has_source_audio:
            return [
                *video_input,
                "-i",
                str(self.state.video_path),
                "-stream_loop",
                "-1",
                "-i",
                str(music_path),
                "-filter_complex",
                f"[1:a:0]volume={self.state.source_volume:.3f}[maina];[2:a:0]{music_filter}[musica];"
                "[maina][musica]amix=inputs=2:duration=first:dropout_transition=0,alimiter=limit=0.95[aout]",
                "-map",
                "0:v:0",
                "-map",
                "[aout]",
                *video_output,
                "-c:a",
                "aac",
                "-t",
                export_duration,
                str(output_path),
            ]

        return [
            *video_input,
            "-stream_loop",
            "-1",
            "-i",
            str(music_path),
            "-filter_complex",
            f"[1:a:0]{music_filter},alimiter=limit=0.95[aout]",
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            *video_output,
            "-c:a",
            "aac",
            "-t",
            export_duration,
            str(output_path),
        ]

'@

$Text = Replace-MethodRange $Text "    def build_ffmpeg_command" "    def source_has_audio" $NewBuildCommand "raw pipe FFmpeg command builder"

Set-Content -LiteralPath $MoviePath -Value $Text -NoNewline

$Agents = (Get-Content -LiteralPath $AgentsPath -Raw).Replace("`r`n", "`n")
$OldGuidance = @'
- Use the bundled `imageio-ffmpeg` executable for desktop export behavior.
'@
$NewGuidance = @'
- Use the bundled `imageio-ffmpeg` executable for desktop export behavior.
- Desktop export streams raw frames directly into FFmpeg, tests GPU H.264 encoders first, and falls back to CPU `libx264`.
'@
if ($Agents.IndexOf($NewGuidance, [StringComparison]::Ordinal) -lt 0) {
    $Agents = Replace-Once $Agents $OldGuidance $NewGuidance "AGENTS export workflow guidance"
    Set-Content -LiteralPath $AgentsPath -Value $Agents -NoNewline
}

$Repaired = Get-Content -LiteralPath $MoviePath -Raw
foreach ($Needle in @(
    "def select_video_encoder",
    "def test_video_encoder",
    "def preload_replacement_images",
    "pipe:0",
    "np.ascontiguousarray(out_frame).tobytes()",
    "previous_output = max(0, output_frame - 1)",
    "encoder_options(encoder)"
)) {
    if ($Repaired.IndexOf($Needle, [StringComparison]::Ordinal) -lt 0) {
        throw "Verification failed. Missing repaired text: $Needle"
    }
}

$AgentsRepaired = Get-Content -LiteralPath $AgentsPath -Raw
if ($AgentsRepaired.IndexOf("streams raw frames directly into FFmpeg", [StringComparison]::Ordinal) -lt 0) {
    throw "Verification failed. AGENTS.md export guidance was not updated."
}

Write-Host "Repair complete."
Write-Host "Backups written under $BackupDir with stamp $Stamp."
