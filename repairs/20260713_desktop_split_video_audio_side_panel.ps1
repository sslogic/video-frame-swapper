$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$MainPath = Join-Path $Root "movie_quad_editor.py"
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (!(Test-Path -LiteralPath $MainPath)) {
    throw "Missing target file: $MainPath"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -LiteralPath $MainPath -Destination (Join-Path $BackupDir "movie_quad_editor.py.$Stamp.desktop-split-video-audio-side-panel.bak") -Force

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
        controls_outer = ttk.Frame(main)
        controls_outer.rowconfigure(0, weight=1)
        controls_outer.columnconfigure(0, weight=1)
        controls_canvas = tk.Canvas(controls_outer, highlightthickness=0, width=390)
        controls_scrollbar = ttk.Scrollbar(controls_outer, orient=tk.VERTICAL, command=controls_canvas.yview)
        controls = ttk.Frame(controls_canvas, padding=10)
        controls_window = controls_canvas.create_window((0, 0), window=controls, anchor="nw")
        controls.columnconfigure(0, weight=1)
        controls.bind("<Configure>", lambda _event: controls_canvas.configure(scrollregion=controls_canvas.bbox("all")))
        controls_canvas.bind("<Configure>", lambda event: controls_canvas.itemconfigure(controls_window, width=event.width))
        controls_canvas.configure(yscrollcommand=controls_scrollbar.set)
        controls_canvas.grid(row=0, column=0, sticky="nsew")
        controls_scrollbar.grid(row=0, column=1, sticky="ns")
        main.add(controls_outer, weight=2)
'@ @'
        controls_outer = ttk.Frame(main)
        controls_outer.rowconfigure(0, weight=1)
        controls_outer.rowconfigure(1, weight=1)
        controls_outer.columnconfigure(0, weight=1)

        controls = ttk.Frame(controls_outer, padding=10)
        controls.columnconfigure(0, weight=1)
        controls.grid(row=0, column=0, sticky="nsew")

        audio_outer = ttk.LabelFrame(controls_outer, text="Audio", padding=(0, 0, 0, 0))
        audio_outer.rowconfigure(0, weight=1)
        audio_outer.columnconfigure(0, weight=1)
        audio_canvas = tk.Canvas(audio_outer, highlightthickness=0, width=390)
        audio_scrollbar = ttk.Scrollbar(audio_outer, orient=tk.VERTICAL, command=audio_canvas.yview)
        audio_controls = ttk.Frame(audio_canvas, padding=10)
        audio_window = audio_canvas.create_window((0, 0), window=audio_controls, anchor="nw")
        audio_controls.columnconfigure(0, weight=1)
        audio_controls.bind("<Configure>", lambda _event: audio_canvas.configure(scrollregion=audio_canvas.bbox("all")))
        audio_canvas.bind("<Configure>", lambda event: audio_canvas.itemconfigure(audio_window, width=event.width))
        audio_canvas.configure(yscrollcommand=audio_scrollbar.set)
        audio_canvas.grid(row=0, column=0, sticky="nsew")
        audio_scrollbar.grid(row=0, column=1, sticky="ns")
        audio_outer.grid(row=1, column=0, sticky="nsew", padx=0, pady=(8, 0))
        main.add(controls_outer, weight=2)
'@ "split side panel container"

$Text = Replace-Once $Text @'
        ttk.Separator(controls).grid(row=12, column=0, sticky="ew", pady=8)

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

        self.status_var = tk.StringVar(value="")
        self.status_label = ttk.Label(controls, textvariable=self.status_var, wraplength=360, justify=tk.LEFT)
        self.status_label.grid(row=21, column=0, sticky="ew", pady=(0, 12))

        ttk.Separator(controls).grid(row=22, column=0, sticky="ew", pady=8)

        self.info_var = tk.StringVar(value="")
        ttk.Label(controls, textvariable=self.info_var, justify=tk.LEFT, wraplength=360).grid(row=23, column=0, sticky="ew")

        self.progress = ttk.Progressbar(controls, mode="determinate")
        self.progress.grid(row=24, column=0, sticky="ew", pady=(16, 4))
'@ @'
        ttk.Separator(controls).grid(row=12, column=0, sticky="ew", pady=8)

        music_row = ttk.Frame(audio_controls)
        music_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        music_row.columnconfigure(0, weight=1)
        music_row.columnconfigure(1, weight=1)
        self.add_music_button = ttk.Button(music_row, text="Audio Editor", command=self.open_audio_editor)
        self.add_music_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.clear_music_button = ttk.Button(music_row, text="Clear Audio", command=self.clear_music_track)
        self.clear_music_button.grid(row=0, column=1, sticky="ew")

        ttk.Label(audio_controls, textvariable=self.music_label_var, wraplength=360).grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.source_volume_slider = ttk.Scale(audio_controls, from_=0, to=200, orient=tk.HORIZONTAL, variable=self.source_volume_var, command=self.on_source_volume_changed)
        self.music_volume_slider = ttk.Scale(audio_controls, from_=0, to=200, orient=tk.HORIZONTAL, variable=self.music_volume_var, command=self.on_music_volume_changed)
        self.tone_match_button = ttk.Button(audio_controls, text="Tone Match + Half Volume", command=self.apply_tone_match_preset)

        self.status_var = tk.StringVar(value="")
        self.status_label = ttk.Label(audio_controls, textvariable=self.status_var, wraplength=360, justify=tk.LEFT)
        self.status_label.grid(row=2, column=0, sticky="ew", pady=(0, 12))

        ttk.Separator(audio_controls).grid(row=3, column=0, sticky="ew", pady=8)

        self.info_var = tk.StringVar(value="")
        ttk.Label(audio_controls, textvariable=self.info_var, justify=tk.LEFT, wraplength=360).grid(row=4, column=0, sticky="ew")

        self.progress = ttk.Progressbar(audio_controls, mode="determinate")
        self.progress.grid(row=5, column=0, sticky="ew", pady=(16, 4))
'@ "move audio section to lower scroll panel"

Set-Content -LiteralPath $MainPath -Value $Text -NoNewline

$Repaired = Get-Content -LiteralPath $MainPath -Raw
foreach ($Needle in @(
    "audio_outer = ttk.LabelFrame",
    "audio_canvas",
    "audio_scrollbar",
    "audio_controls",
    "controls.grid(row=0",
    "audio_outer.grid(row=1"
)) {
    if ($Repaired.IndexOf($Needle, [StringComparison]::Ordinal) -lt 0) {
        throw "Verification failed. Missing repaired text: $Needle"
    }
}

Write-Host "Desktop split video/audio side panel repair complete."
Write-Host "Backup written under $BackupDir with stamp $Stamp."
