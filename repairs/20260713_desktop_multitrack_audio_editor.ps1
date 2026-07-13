$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$MainPath = Join-Path $Root "movie_quad_editor.py"
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (!(Test-Path -LiteralPath $MainPath)) {
    throw "Missing target file: $MainPath"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -LiteralPath $MainPath -Destination (Join-Path $BackupDir "movie_quad_editor.py.$Stamp.desktop-multitrack-audio.bak") -Force

function Replace-Once {
    param([string]$Text, [string]$Old, [string]$New, [string]$Label)
    $First = $Text.IndexOf($Old, [StringComparison]::Ordinal)
    if ($First -lt 0) { throw "Could not find expected block: $Label" }
    $Second = $Text.IndexOf($Old, $First + $Old.Length, [StringComparison]::Ordinal)
    if ($Second -ge 0) { throw "Expected block was not unique: $Label" }
    return $Text.Remove($First, $Old.Length).Insert($First, $New)
}

function Replace-Range {
    param([string]$Text, [string]$Start, [string]$End, [string]$New, [string]$Label)
    $StartIndex = $Text.IndexOf($Start, [StringComparison]::Ordinal)
    if ($StartIndex -lt 0) { throw "Could not find range start: $Label" }
    $EndIndex = $Text.IndexOf($End, $StartIndex, [StringComparison]::Ordinal)
    if ($EndIndex -lt 0) { throw "Could not find range end: $Label" }
    return $Text.Remove($StartIndex, $EndIndex - $StartIndex).Insert($StartIndex, $New)
}

$Text = Get-Content -LiteralPath $MainPath -Raw

$AudioTrackClass = @'
@dataclass
class AudioTrack:
    path: str
    volume: float = 0.5
    start_time: float = 0.0
    repeat: bool = True
    repeat_every: float = 0.0
    repeat_count: int = 0
    speed: float = 1.0
    masking: bool = True
    duck_below_main: bool = True
    duration: float = 0.0

    @property
    def name(self):
        return Path(self.path).name

    def to_dict(self):
        return {
            "path": self.path,
            "volume": self.volume,
            "start_time": self.start_time,
            "repeat": self.repeat,
            "repeat_every": self.repeat_every,
            "repeat_count": self.repeat_count,
            "speed": self.speed,
            "masking": self.masking,
            "duck_below_main": self.duck_below_main,
            "duration": self.duration,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            path=str(data.get("path", "")),
            volume=float(data.get("volume", 0.5)),
            start_time=float(data.get("start_time", 0.0)),
            repeat=bool(data.get("repeat", True)),
            repeat_every=float(data.get("repeat_every", 0.0)),
            repeat_count=int(data.get("repeat_count", 0)),
            speed=float(data.get("speed", 1.0)),
            masking=bool(data.get("masking", True)),
            duck_below_main=bool(data.get("duck_below_main", True)),
            duration=float(data.get("duration", 0.0)),
        )


'@
$Text = Replace-Once $Text "@dataclass`nclass VideoState:" ($AudioTrackClass + "@dataclass`nclass VideoState:") "AudioTrack dataclass"

$Text = Replace-Once $Text @'
    music_path: str = ""
    music_volume: float = 0.5
    music_tone_match: bool = False
'@ @'
    music_path: str = ""
    music_volume: float = 0.5
    music_tone_match: bool = False
    audio_tracks: list = field(default_factory=list)
'@ "VideoState audio tracks"

$Text = Replace-Once $Text @'
        self.music_tone_var = tk.BooleanVar(value=False)
'@ @'
        self.music_tone_var = tk.BooleanVar(value=False)
        self.audio_editor_window = None
'@ "audio editor window field"

$Text = Replace-Once $Text @'
        ttk.Label(controls, text="Extra Music Track").grid(row=13, column=0, sticky="w")
        music_row = ttk.Frame(controls)
        music_row.grid(row=14, column=0, sticky="ew", pady=(4, 6))
        music_row.columnconfigure(0, weight=1)
        music_row.columnconfigure(1, weight=1)
        self.add_music_button = ttk.Button(music_row, text="Add Music", command=self.add_music_track)
        self.add_music_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.clear_music_button = ttk.Button(music_row, text="Clear Music", command=self.clear_music_track)
        self.clear_music_button.grid(row=0, column=1, sticky="ew")

        ttk.Label(controls, textvariable=self.music_label_var, wraplength=360).grid(row=15, column=0, sticky="ew")
        ttk.Label(controls, text="Original Soundtrack Volume").grid(row=16, column=0, sticky="w", pady=(8, 0))
        self.source_volume_slider = ttk.Scale(
            controls,
            from_=0,
            to=200,
            orient=tk.HORIZONTAL,
            variable=self.source_volume_var,
            command=self.on_source_volume_changed,
        )
        self.source_volume_slider.grid(row=17, column=0, sticky="ew", pady=(2, 6))
        ttk.Label(controls, text="Added Music Volume").grid(row=18, column=0, sticky="w", pady=(8, 0))
        self.music_volume_slider = ttk.Scale(
            controls,
            from_=0,
            to=200,
            orient=tk.HORIZONTAL,
            variable=self.music_volume_var,
            command=self.on_music_volume_changed,
        )
        self.music_volume_slider.grid(row=19, column=0, sticky="ew", pady=(2, 6))
        self.tone_match_button = ttk.Button(
            controls,
            text="Tone Match + Half Volume",
            command=self.apply_tone_match_preset,
        )
        self.tone_match_button.grid(row=20, column=0, sticky="ew", pady=(0, 10))
'@ @'
        ttk.Label(controls, text="Audio").grid(row=13, column=0, sticky="w")
        music_row = ttk.Frame(controls)
        music_row.grid(row=14, column=0, sticky="ew", pady=(4, 6))
        music_row.columnconfigure(0, weight=1)
        music_row.columnconfigure(1, weight=1)
        self.add_music_button = ttk.Button(music_row, text="Audio Editor", command=self.open_audio_editor)
        self.add_music_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.clear_music_button = ttk.Button(music_row, text="Clear Audio", command=self.clear_music_track)
        self.clear_music_button.grid(row=0, column=1, sticky="ew")

        ttk.Label(controls, textvariable=self.music_label_var, wraplength=360).grid(row=15, column=0, sticky="ew")
        self.source_volume_slider = ttk.Scale(controls, from_=0, to=200, orient=tk.HORIZONTAL, variable=self.source_volume_var, command=self.on_source_volume_changed)
        self.music_volume_slider = ttk.Scale(controls, from_=0, to=200, orient=tk.HORIZONTAL, variable=self.music_volume_var, command=self.on_music_volume_changed)
        self.tone_match_button = ttk.Button(controls, text="Tone Match + Half Volume", command=self.apply_tone_match_preset)
'@ "side panel audio controls"

$Text = Replace-Once $Text @'
            self.source_volume_slider,
            self.music_volume_slider,
            self.tone_match_button,
'@ "" "remove hidden audio controls from enabled list"

$Text = Replace-Once $Text @'
        self.state.music_path = data.get("music_path", "")
        self.state.music_volume = float(data.get("music_volume", 0.5))
        self.state.music_tone_match = bool(data.get("music_tone_match", False))
'@ @'
        self.state.music_path = data.get("music_path", "")
        self.state.music_volume = float(data.get("music_volume", 0.5))
        self.state.music_tone_match = bool(data.get("music_tone_match", False))
        tracks = data.get("audio_tracks")
        if isinstance(tracks, list):
            self.state.audio_tracks = [AudioTrack.from_dict(item) for item in tracks if item.get("path")]
        elif self.state.music_path:
            self.state.audio_tracks = [
                AudioTrack(
                    path=self.state.music_path,
                    volume=self.state.music_volume,
                    masking=self.state.music_tone_match,
                    duck_below_main=True,
                    duration=self.media_duration_seconds(self.state.music_path),
                )
            ]
        else:
            self.state.audio_tracks = []
'@ "load audio tracks"

$Text = Replace-Once $Text @'
            "music_path": self.state.music_path,
            "music_volume": self.state.music_volume,
            "music_tone_match": self.state.music_tone_match,
'@ @'
            "music_path": self.state.music_path,
            "music_volume": self.state.music_volume,
            "music_tone_match": self.state.music_tone_match,
            "audio_tracks": [track.to_dict() for track in self.state.audio_tracks],
'@ "save audio tracks"

$OldSync = @'
    def sync_music_controls(self):
        if not self.state:
            self.music_label_var.set("No music track")
            self.music_volume_var.set(50.0)
            self.source_volume_var.set(100.0)
            self.music_tone_var.set(False)
            return
        self.source_volume_var.set(round(self.state.source_volume * 100, 1))
        self.music_volume_var.set(round(self.state.music_volume * 100, 1))
        self.music_tone_var.set(self.state.music_tone_match)
        if self.state.music_path:
            name = Path(self.state.music_path).name
            suffix = "tone match on" if self.state.music_tone_match else "tone match off"
            self.music_label_var.set(f"{name} ({self.music_volume_var.get():.0f}%, {suffix})")
        else:
            self.music_label_var.set("No music track")
'@
$NewSync = @'
    def sync_music_controls(self):
        if not self.state:
            self.music_label_var.set("No added audio tracks")
            self.music_volume_var.set(50.0)
            self.source_volume_var.set(100.0)
            self.music_tone_var.set(False)
            return
        self.source_volume_var.set(round(self.state.source_volume * 100, 1))
        self.music_tone_var.set(self.state.music_tone_match)
        if self.state.audio_tracks:
            count = len(self.state.audio_tracks)
            masking_count = sum(1 for track in self.state.audio_tracks if track.masking)
            duck_count = sum(1 for track in self.state.audio_tracks if track.duck_below_main)
            self.music_label_var.set(
                f"{count} added audio track(s), main {self.source_volume_var.get():.0f}%, "
                f"masking {masking_count}, below-main {duck_count}"
            )
        else:
            self.music_label_var.set("No added audio tracks")
'@
$Text = Replace-Once $Text $OldSync $NewSync "sync music controls"

$Text = Replace-Once $Text @'
            f"Music track: {'yes' if self.state.music_path else 'no'}\n"
'@ @'
            f"Audio tracks: {len(self.state.audio_tracks)} added\n"
'@ "info audio track count"

$NewAudioMethods = @'
    def add_music_track(self):
        if not self.state:
            return
        path = filedialog.askopenfilename(
            title="Choose Audio Track",
            filetypes=[
                ("Audio files", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus"),
                ("Video/audio files", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        track = AudioTrack(path=str(Path(path)), duration=self.media_duration_seconds(path))
        self.state.audio_tracks.append(track)
        self.state.music_path = track.path
        self.state.music_volume = track.volume
        self.sync_music_controls()
        self.update_info()
        self.status_var.set("Audio track added. Click Save Edits to keep this change.")
        self.open_audio_editor()

    def clear_music_track(self):
        if not self.state:
            return
        self.state.audio_tracks.clear()
        self.state.music_path = ""
        self.state.music_tone_match = False
        self.sync_music_controls()
        self.update_info()
        self.status_var.set("Audio tracks cleared. Click Save Edits to keep this change.")

    def on_music_volume_changed(self, _value=None):
        if not self.state:
            return
        self.state.music_volume = clamp(self.music_volume_var.get() / 100.0, 0.0, 2.0)
        if self.state.audio_tracks:
            self.state.audio_tracks[-1].volume = self.state.music_volume
        self.sync_music_controls()

    def on_source_volume_changed(self, _value=None):
        if not self.state:
            return
        self.state.source_volume = clamp(self.source_volume_var.get() / 100.0, 0.0, 2.0)
        self.sync_music_controls()

    def open_audio_editor(self):
        if not self.state:
            return
        if self.audio_editor_window is not None and self.audio_editor_window.winfo_exists():
            self.audio_editor_window.destroy()
        window = tk.Toplevel(self)
        self.audio_editor_window = window
        window.title("Audio Editor")
        window.geometry("720x620")
        window.minsize(620, 460)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)

        canvas = tk.Canvas(window, highlightthickness=0)
        scrollbar = ttk.Scrollbar(window, orient=tk.VERTICAL, command=canvas.yview)
        body = ttk.Frame(canvas, padding=12)
        body.columnconfigure(0, weight=1)
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        ttk.Label(body, text="Main track audio", font=("", 11, "bold")).grid(row=0, column=0, sticky="w")
        main_volume = tk.DoubleVar(value=self.state.source_volume * 100.0)
        ttk.Label(body, text="Main track volume").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(
            body,
            from_=0,
            to=200,
            orient=tk.HORIZONTAL,
            variable=main_volume,
            command=lambda _value: self.set_main_audio_volume(main_volume.get()),
        ).grid(row=2, column=0, sticky="ew", pady=(2, 8))
        tone_match = tk.BooleanVar(value=self.state.music_tone_match)
        ttk.Checkbutton(
            body,
            text="Key-match added tracks to the main soundtrack at export",
            variable=tone_match,
            command=lambda: self.set_audio_tone_match(tone_match.get()),
        ).grid(row=3, column=0, sticky="w", pady=(0, 8))

        button_row = ttk.Frame(body)
        button_row.grid(row=4, column=0, sticky="ew", pady=(2, 10))
        button_row.columnconfigure(0, weight=1)
        button_row.columnconfigure(1, weight=1)
        ttk.Button(button_row, text="Add Audio Track", command=self.add_music_track).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(button_row, text="Clear All Tracks", command=self.clear_music_track).grid(row=0, column=1, sticky="ew")

        ttk.Separator(body).grid(row=5, column=0, sticky="ew", pady=8)
        if not self.state.audio_tracks:
            ttk.Label(body, text="No added audio tracks.").grid(row=6, column=0, sticky="w")
        else:
            for index, track in enumerate(self.state.audio_tracks):
                self.add_audio_track_row(body, index, track, 6 + index)

        ttk.Button(body, text="Close", command=window.destroy).grid(row=1000, column=0, sticky="ew", pady=(12, 0))

    def add_audio_track_row(self, parent, index, track, row):
        frame = ttk.LabelFrame(parent, text=f"Track {index + 1}: {track.name}", padding=8)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(0, weight=1)
        detail = (
            f"Length: {self.format_seconds(track.duration)} | Start: {self.format_seconds(track.start_time)} | "
            f"Volume: {track.volume * 100:.0f}% | Speed: {track.speed:.2f}x\n"
            f"Repeat: {'on' if track.repeat else 'off'} | Every: "
            f"{'track length' if track.repeat_every <= 0 else self.format_seconds(track.repeat_every)} | "
            f"Count: {'to end' if track.repeat_count <= 0 else track.repeat_count}\n"
            f"Track masking: {'on' if track.masking else 'off'} | Below main: {'on' if track.duck_below_main else 'off'}"
        )
        ttk.Label(frame, text=detail, justify=tk.LEFT).grid(row=0, column=0, sticky="w")
        actions = ttk.Frame(frame)
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(actions, text="Edit Track", command=lambda i=index: self.open_audio_track_settings(i)).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(actions, text="Remove Track", command=lambda i=index: self.remove_audio_track(i)).grid(row=0, column=1, sticky="ew")

    def open_audio_track_settings(self, index):
        if not self.state or index < 0 or index >= len(self.state.audio_tracks):
            return
        track = self.state.audio_tracks[index]
        window = tk.Toplevel(self)
        window.title(f"Audio Track {index + 1}")
        window.geometry("520x560")
        window.columnconfigure(0, weight=1)
        body = ttk.Frame(window, padding=12)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text=track.name, font=("", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(body, text=f"Length: {self.format_seconds(track.duration)}").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        volume_var = tk.DoubleVar(value=track.volume * 100.0)
        start_var = tk.StringVar(value=f"{track.start_time:.3f}")
        repeat_var = tk.BooleanVar(value=track.repeat)
        repeat_every_var = tk.StringVar(value="0" if track.repeat_every <= 0 else f"{track.repeat_every:.3f}")
        repeat_count_var = tk.StringVar(value=str(track.repeat_count))
        speed_var = tk.DoubleVar(value=track.speed * 100.0)
        masking_var = tk.BooleanVar(value=track.masking)
        duck_var = tk.BooleanVar(value=track.duck_below_main)
        speed_label_var = tk.StringVar(value=f"Track speed: {track.speed:.2f}x")

        ttk.Label(body, text="Track volume").grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Scale(body, from_=0, to=200, orient=tk.HORIZONTAL, variable=volume_var).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(2, 8))
        ttk.Label(body, text="Start time in movie seconds").grid(row=4, column=0, sticky="w")
        ttk.Entry(body, textvariable=start_var).grid(row=4, column=1, sticky="ew", pady=3)
        ttk.Checkbutton(body, text="Repeat this track", variable=repeat_var).grid(row=5, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Label(body, text="Repeat every seconds (0 = track length after speed)").grid(row=6, column=0, sticky="w")
        ttk.Entry(body, textvariable=repeat_every_var).grid(row=6, column=1, sticky="ew", pady=3)
        ttk.Label(body, text="Repeat count (0 = until movie ends)").grid(row=7, column=0, sticky="w")
        ttk.Entry(body, textvariable=repeat_count_var).grid(row=7, column=1, sticky="ew", pady=3)
        ttk.Label(body, textvariable=speed_label_var).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Scale(
            body,
            from_=20,
            to=500,
            orient=tk.HORIZONTAL,
            variable=speed_var,
            command=lambda value: speed_label_var.set(f"Track speed: {float(value) / 100.0:.2f}x"),
        ).grid(row=9, column=0, columnspan=2, sticky="ew", pady=(2, 8))
        ttk.Checkbutton(body, text="Track masking: compress peaks and limit loud spikes", variable=masking_var).grid(row=10, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Checkbutton(body, text="Keep this track dynamically below the main track", variable=duck_var).grid(row=11, column=0, columnspan=2, sticky="w", pady=3)

        buttons = ttk.Frame(body)
        buttons.grid(row=12, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text="Cancel", command=window.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(
            buttons,
            text="Apply",
            command=lambda: self.apply_audio_track_settings(
                window,
                index,
                volume_var,
                start_var,
                repeat_var,
                repeat_every_var,
                repeat_count_var,
                speed_var,
                masking_var,
                duck_var,
            ),
        ).grid(row=0, column=1, sticky="ew")

    def apply_audio_track_settings(self, window, index, volume_var, start_var, repeat_var, repeat_every_var, repeat_count_var, speed_var, masking_var, duck_var):
        if not self.state or index < 0 or index >= len(self.state.audio_tracks):
            return
        track = self.state.audio_tracks[index]
        try:
            track.volume = clamp(volume_var.get() / 100.0, 0.0, 2.0)
            track.start_time = max(0.0, float(start_var.get() or 0))
            track.repeat = bool(repeat_var.get())
            track.repeat_every = max(0.0, float(repeat_every_var.get() or 0))
            track.repeat_count = max(0, int(float(repeat_count_var.get() or 0)))
            track.speed = clamp(speed_var.get() / 100.0, 0.2, 5.0)
            track.masking = bool(masking_var.get())
            track.duck_below_main = bool(duck_var.get())
        except ValueError:
            messagebox.showerror("Audio Track", "Use numbers for start time, repeat timing, repeat count, and speed.")
            return
        self.state.music_path = track.path
        self.state.music_volume = track.volume
        self.sync_music_controls()
        self.update_info()
        window.destroy()
        self.open_audio_editor()
        self.status_var.set("Audio track updated. Click Save Edits to keep this change.")

    def remove_audio_track(self, index):
        if not self.state or index < 0 or index >= len(self.state.audio_tracks):
            return
        del self.state.audio_tracks[index]
        self.state.music_path = self.state.audio_tracks[-1].path if self.state.audio_tracks else ""
        self.sync_music_controls()
        self.update_info()
        self.open_audio_editor()
        self.status_var.set("Audio track removed. Click Save Edits to keep this change.")

    def set_main_audio_volume(self, value):
        if not self.state:
            return
        self.state.source_volume = clamp(float(value) / 100.0, 0.0, 2.0)
        self.source_volume_var.set(round(self.state.source_volume * 100.0, 1))
        self.sync_music_controls()

    def set_audio_tone_match(self, enabled):
        if not self.state:
            return
        self.state.music_tone_match = bool(enabled)
        self.music_tone_var.set(self.state.music_tone_match)
        self.sync_music_controls()

    def media_duration_seconds(self, path):
        try:
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            result = subprocess.run(
                [ffmpeg, "-hide_banner", "-i", str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=high_priority_subprocess_flags(),
            )
            for line in result.stderr.splitlines():
                if "Duration:" in line:
                    text = line.split("Duration:", 1)[1].split(",", 1)[0].strip()
                    hours, minutes, seconds = text.split(":")
                    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except Exception:
            pass
        return 0.0

    def format_seconds(self, seconds):
        seconds = max(0.0, float(seconds or 0.0))
        minutes = int(seconds // 60)
        remain = int(round(seconds - minutes * 60))
        return f"{minutes}:{remain:02d}"

'@

$Text = Replace-Range $Text "    def add_music_track(self):" "    def on_color_blend_changed(self, _value=None):" ($NewAudioMethods + "    def on_color_blend_changed(self, _value=None):") "audio editor methods"

$Text = Replace-Once $Text @'
        if not self.state.music_path:
            messagebox.showinfo("Tone Match", "Add a music track first.")
            return
        self.state.music_volume = 0.5
        self.state.music_tone_match = True
        self.sync_music_controls()
        self.status_var.set("Tone match preset enabled and music volume set to 50%. Click Save Edits to keep this change.")
'@ @'
        if not self.state.audio_tracks:
            messagebox.showinfo("Tone Match", "Add an audio track first.")
            return
        for track in self.state.audio_tracks:
            track.volume = 0.5
            track.masking = True
            track.duck_below_main = True
        self.state.music_volume = 0.5
        self.state.music_tone_match = True
        self.sync_music_controls()
        self.status_var.set("Tone match preset enabled, track masking enabled, and added tracks set to 50%. Click Save Edits to keep this change.")
'@ "tone match preset"

$BuildHelpers = @'
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
            semitone_shift = 0
            if source_key is not None:
                track_key = analyze_audio_key(ffmpeg, track.path)
                semitone_shift = shortest_semitone_shift(track_key["pc"], source_key["pc"])
                status_lines.append(
                    f"{track.name}: {key_label(track_key)} to {key_label(source_key)} ({semitone_shift:+d} semitones)"
                )
            labels = self.add_audio_track_filters(
                filter_parts,
                input_index=index + 2,
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

    def add_audio_track_filters(self, filter_parts, input_index, track, semitone_shift, label_offset):
        labels = []
        speed = clamp(track.speed, 0.2, 5.0)
        source_duration = track.duration or self.media_duration_seconds(track.path) or self.state.duration
        adjusted_duration = source_duration / speed if speed else source_duration
        repeat_every = track.repeat_every if track.repeat_every > 0 else adjusted_duration
        occurrences = 1
        if track.repeat:
            occurrences = track.repeat_count if track.repeat_count > 0 else int(np.ceil(max(0.0, self.state.duration - track.start_time) / max(0.1, repeat_every)))
        occurrences = clamp(occurrences, 1, 64)
        split_labels = []
        if occurrences > 1:
            split = f"[{input_index}:a:0]asplit={occurrences}"
            for repeat_index in range(occurrences):
                label = f"[atr{label_offset}_{repeat_index}_src]"
                split += label
                split_labels.append(label)
            filter_parts.append(split)
        for repeat_index in range(occurrences):
            delay = track.start_time + repeat_index * repeat_every
            if delay >= self.state.duration:
                break
            remaining = max(0.01, self.state.duration - delay)
            trim_seconds = max(0.01, min(source_duration, remaining * speed))
            input_label = split_labels[repeat_index] if occurrences > 1 else f"[{input_index}:a:0]"
            output_label = f"[atr{label_offset}_{repeat_index}]"
            chain = (
                f"{input_label}atrim=0:{trim_seconds:.6f},asetpts=PTS-STARTPTS,aresample=44100,"
                f"{self.ffmpeg_speed_filter(speed)}"
                f"{ffmpeg_pitch_filter(semitone_shift)}"
                f"volume={track.volume:.3f}"
            )
            if track.masking:
                chain += ",acompressor=threshold=0.18:ratio=6:attack=5:release=120,alimiter=limit=0.90"
            delay_ms = max(0, int(round(delay * 1000)))
            chain += f",adelay={delay_ms}|{delay_ms}{output_label}"
            filter_parts.append(chain)
            labels.append(output_label)
        return labels

    def mix_audio_labels(self, filter_parts, labels, output_name):
        labels = [label for label in labels if label]
        if not labels:
            return ""
        if len(labels) == 1:
            if output_name == "aout":
                filter_parts.append(f"{labels[0]}alimiter=limit=0.95[aout]")
                return "[aout]"
            return labels[0]
        joined = "".join(labels)
        filter_parts.append(
            f"{joined}amix=inputs={len(labels)}:duration=longest:dropout_transition=0,alimiter=limit=0.95[{output_name}]"
        )
        return f"[{output_name}]"

    def ffmpeg_speed_filter(self, speed):
        parts = []
        remaining = clamp(speed, 0.2, 5.0)
        while remaining > 2.0:
            parts.append("atempo=2.000000")
            remaining /= 2.0
        while remaining < 0.5:
            parts.append("atempo=0.500000")
            remaining /= 0.5
        if abs(remaining - 1.0) > 0.001:
            parts.append(f"atempo={remaining:.6f}")
        return ",".join(parts) + ("," if parts else "")
'@

$Text = Replace-Range $Text "    def build_ffmpeg_command(self, ffmpeg, output_path, encoder):" "    def source_has_audio(self, ffmpeg, media_path):" ($BuildHelpers + "    def source_has_audio(self, ffmpeg, media_path):") "multi-track ffmpeg command"

Set-Content -LiteralPath $MainPath -Value $Text -NoNewline

$Repaired = Get-Content -LiteralPath $MainPath -Raw
foreach ($Needle in @(
    "class AudioTrack",
    "audio_tracks",
    "open_audio_editor",
    "Add Audio Track",
    "Track masking",
    "duck_below_main",
    "sidechaincompress",
    "ffmpeg_speed_filter",
    "repeat_every",
    "add_audio_track_filters"
)) {
    if ($Repaired.IndexOf($Needle, [StringComparison]::Ordinal) -lt 0) {
        throw "Verification failed. Missing repaired text: $Needle"
    }
}

Write-Host "Desktop multi-track audio editor repair complete."
Write-Host "Backup written under $BackupDir with stamp $Stamp."
