$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$MainPath = Join-Path $Root "movie_quad_editor.py"
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (!(Test-Path -LiteralPath $MainPath)) {
    throw "Missing target file: $MainPath"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -LiteralPath $MainPath -Destination (Join-Path $BackupDir "movie_quad_editor.py.$Stamp.first-audio-main-mask.bak") -Force

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
    music_tone_match: bool = False
    audio_tracks: list = field(default_factory=list)
'@ @'
    music_tone_match: bool = False
    first_audio_as_main_mask: bool = False
    audio_tracks: list = field(default_factory=list)
'@ "VideoState first audio mask field"

$Text = Replace-Once $Text @'
        self.music_tone_var = tk.BooleanVar(value=False)
        self.audio_editor_window = None
'@ @'
        self.music_tone_var = tk.BooleanVar(value=False)
        self.first_audio_mask_var = tk.BooleanVar(value=False)
        self.audio_editor_window = None
'@ "first audio mask tk var"

$Text = Replace-Once $Text @'
        self.state.music_tone_match = bool(data.get("music_tone_match", False))
        tracks = data.get("audio_tracks")
'@ @'
        self.state.music_tone_match = bool(data.get("music_tone_match", False))
        self.state.first_audio_as_main_mask = bool(data.get("first_audio_as_main_mask", False))
        tracks = data.get("audio_tracks")
'@ "load first audio mask"

$Text = Replace-Once $Text @'
            "music_tone_match": self.state.music_tone_match,
            "audio_tracks": [track.to_dict() for track in self.state.audio_tracks],
'@ @'
            "music_tone_match": self.state.music_tone_match,
            "first_audio_as_main_mask": self.state.first_audio_as_main_mask,
            "audio_tracks": [track.to_dict() for track in self.state.audio_tracks],
'@ "save first audio mask"

$Text = Replace-Once $Text @'
            self.music_tone_var.set(False)
            return
        self.source_volume_var.set(round(self.state.source_volume * 100, 1))
        self.music_tone_var.set(self.state.music_tone_match)
'@ @'
            self.music_tone_var.set(False)
            self.first_audio_mask_var.set(False)
            return
        self.source_volume_var.set(round(self.state.source_volume * 100, 1))
        self.music_tone_var.set(self.state.music_tone_match)
        self.first_audio_mask_var.set(self.state.first_audio_as_main_mask)
'@ "sync first audio mask"

$Text = Replace-Once $Text @'
            self.music_label_var.set(
                f"{count} added audio track(s), main {self.source_volume_var.get():.0f}%, "
                f"masking {masking_count}, below-main {duck_count}"
            )
'@ @'
            first_mask = ", first track as main mask" if self.state.first_audio_as_main_mask else ""
            self.music_label_var.set(
                f"{count} added audio track(s), main {self.source_volume_var.get():.0f}%, "
                f"masking {masking_count}, below-main {duck_count}{first_mask}"
            )
'@ "summary first audio mask"

$Text = Replace-Once $Text @'
        tone_match = tk.BooleanVar(value=self.state.music_tone_match)
        ttk.Checkbutton(
            body,
            text="Key-match added tracks to the main soundtrack at export",
            variable=tone_match,
            command=lambda: self.set_audio_tone_match(tone_match.get()),
        ).grid(row=3, column=0, sticky="w", pady=(0, 8))

        button_row = ttk.Frame(body)
        button_row.grid(row=4, column=0, sticky="ew", pady=(2, 10))
'@ @'
        tone_match = tk.BooleanVar(value=self.state.music_tone_match)
        ttk.Checkbutton(
            body,
            text="Key-match added tracks to the main soundtrack at export",
            variable=tone_match,
            command=lambda: self.set_audio_tone_match(tone_match.get()),
        ).grid(row=3, column=0, sticky="w", pady=(0, 4))
        first_audio_mask = tk.BooleanVar(value=self.state.first_audio_as_main_mask)
        ttk.Checkbutton(
            body,
            text="If movie has no audio, use first added track as the main masking track",
            variable=first_audio_mask,
            command=lambda: self.set_first_audio_as_main_mask(first_audio_mask.get()),
        ).grid(row=4, column=0, sticky="w", pady=(0, 8))

        button_row = ttk.Frame(body)
        button_row.grid(row=5, column=0, sticky="ew", pady=(2, 10))
'@ "audio editor checkbox"

$Text = Replace-Once $Text @'
        ttk.Separator(body).grid(row=5, column=0, sticky="ew", pady=8)
        if not self.state.audio_tracks:
            ttk.Label(body, text="No added audio tracks.").grid(row=6, column=0, sticky="w")
        else:
            for index, track in enumerate(self.state.audio_tracks):
                self.add_audio_track_row(body, index, track, 6 + index)
'@ @'
        ttk.Separator(body).grid(row=6, column=0, sticky="ew", pady=8)
        if not self.state.audio_tracks:
            ttk.Label(body, text="No added audio tracks.").grid(row=7, column=0, sticky="w")
        else:
            for index, track in enumerate(self.state.audio_tracks):
                self.add_audio_track_row(body, index, track, 7 + index)
'@ "audio editor row shift"

$Text = Replace-Once $Text @'
    def set_audio_tone_match(self, enabled):
        if not self.state:
            return
        self.state.music_tone_match = bool(enabled)
        self.music_tone_var.set(self.state.music_tone_match)
        self.sync_music_controls()

    def media_duration_seconds(self, path):
'@ @'
    def set_audio_tone_match(self, enabled):
        if not self.state:
            return
        self.state.music_tone_match = bool(enabled)
        self.music_tone_var.set(self.state.music_tone_match)
        self.sync_music_controls()

    def set_first_audio_as_main_mask(self, enabled):
        if not self.state:
            return
        self.state.first_audio_as_main_mask = bool(enabled)
        self.first_audio_mask_var.set(self.state.first_audio_as_main_mask)
        self.sync_music_controls()

    def media_duration_seconds(self, path):
'@ "first audio mask setter"

$Text = Replace-Once $Text @'
        source_key = None
        if self.state.music_tone_match and has_source_audio:
            self.after(0, self.status_var.set, "Analyzing audio keys...")
            source_key = analyze_audio_key(ffmpeg, self.state.video_path)

        filter_parts = []
        main_label = None
        if has_source_audio:
            filter_parts.append(f"[1:a:0]volume={self.state.source_volume:.3f},alimiter=limit=0.95[maina]")
            main_label = "[maina]"

        normal_added = []
        ducked_added = []
        status_lines = [f"Audio mix: {len(audio_tracks)} added track(s)"]
        generated_offset = 0
        for index, track in enumerate(audio_tracks):
'@ @'
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
'@ "main track selection"

$Text = Replace-Once $Text @'
                input_index=index + 2,
'@ @'
                input_index=index + (3 if main_track is not None else 2),
'@ "audio input offset"

Set-Content -LiteralPath $MainPath -Value $Text -NoNewline

$Repaired = Get-Content -LiteralPath $MainPath -Raw
foreach ($Needle in @(
    "first_audio_as_main_mask",
    "first_audio_mask_var",
    "use first added track as the main masking track",
    "set_first_audio_as_main_mask",
    "use_first_track_as_main",
    "Main masking track"
)) {
    if ($Repaired.IndexOf($Needle, [StringComparison]::Ordinal) -lt 0) {
        throw "Verification failed. Missing repaired text: $Needle"
    }
}

Write-Host "Desktop first-audio main masking repair complete."
Write-Host "Backup written under $BackupDir with stamp $Stamp."
