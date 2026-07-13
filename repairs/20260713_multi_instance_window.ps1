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
Copy-Item -LiteralPath $MoviePath -Destination (Join-Path $BackupDir "movie_quad_editor.py.$Stamp.multi-instance.bak") -Force
Copy-Item -LiteralPath $AgentsPath -Destination (Join-Path $BackupDir "AGENTS.md.$Stamp.multi-instance.bak") -Force

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

$Text = (Get-Content -LiteralPath $MoviePath -Raw).Replace("`r`n", "`n")

$Text = Replace-Once $Text "import subprocess`nimport tempfile" "import subprocess`nimport sys`nimport tempfile" "sys import"

$OldTopbar = @'
        topbar = ttk.Frame(self, padding=(10, 10, 10, 6))
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.columnconfigure(7, weight=1)

        self.open_button = ttk.Button(topbar, text="Open Video", command=self.open_video)
        self.open_button.grid(row=0, column=0, padx=(0, 8))
        self.save_button = ttk.Button(topbar, text="Save Edits", command=self.save_edits)
        self.save_button.grid(row=0, column=1, padx=(0, 8))
        self.open_project_button = ttk.Button(topbar, text="Open Project", command=self.open_project)
        self.open_project_button.grid(row=0, column=2, padx=(0, 8))
        self.recent_project_button = ttk.Button(topbar, text="Recent Project", command=self.open_recent_project)
        self.recent_project_button.grid(row=0, column=3, padx=(0, 8))
        self.export_button = ttk.Button(topbar, text="Export Video", command=self.export_video)
        self.export_button.grid(row=0, column=4, padx=(0, 12))
        self.play_button = ttk.Button(topbar, text="Play Preview", command=self.toggle_playback)
        self.play_button.grid(row=0, column=5, padx=(0, 12))

        self.video_label = ttk.Label(topbar, text="No video loaded")
        self.video_label.grid(row=0, column=6, columnspan=2, sticky="w")
'@

$NewTopbar = @'
        topbar = ttk.Frame(self, padding=(10, 10, 10, 6))
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.columnconfigure(8, weight=1)

        self.open_button = ttk.Button(topbar, text="Open Video", command=self.open_video)
        self.open_button.grid(row=0, column=0, padx=(0, 8))
        self.save_button = ttk.Button(topbar, text="Save Edits", command=self.save_edits)
        self.save_button.grid(row=0, column=1, padx=(0, 8))
        self.open_project_button = ttk.Button(topbar, text="Open Project", command=self.open_project)
        self.open_project_button.grid(row=0, column=2, padx=(0, 8))
        self.recent_project_button = ttk.Button(topbar, text="Recent Project", command=self.open_recent_project)
        self.recent_project_button.grid(row=0, column=3, padx=(0, 8))
        self.export_button = ttk.Button(topbar, text="Export Video", command=self.export_video)
        self.export_button.grid(row=0, column=4, padx=(0, 12))
        self.play_button = ttk.Button(topbar, text="Play Preview", command=self.toggle_playback)
        self.play_button.grid(row=0, column=5, padx=(0, 12))
        self.new_window_button = ttk.Button(topbar, text="New Window", command=self.launch_new_instance)
        self.new_window_button.grid(row=0, column=6, padx=(0, 12))

        self.video_label = ttk.Label(topbar, text="No video loaded")
        self.video_label.grid(row=0, column=7, columnspan=2, sticky="w")
'@

$Text = Replace-Once $Text $OldTopbar $NewTopbar "topbar new window button"

$OldControlsEnd = @'
    def _set_controls_enabled(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        for child in self.video_controls:
            try:
                child.configure(state=state)
            except tk.TclError:
                pass

    def open_video(self):
'@

$NewControlsEnd = @'
    def _set_controls_enabled(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        for child in self.video_controls:
            try:
                child.configure(state=state)
            except tk.TclError:
                pass

    def launch_new_instance(self):
        try:
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve())],
                cwd=str(APP_DIR),
                close_fds=True,
                creationflags=high_priority_subprocess_flags(),
            )
            self.status_var.set("Opened another editor window.")
        except Exception as exc:
            messagebox.showerror("New Window", f"Could not open another editor window:\n{exc}")

    def open_video(self):
'@

$Text = Replace-Once $Text $OldControlsEnd $NewControlsEnd "launch_new_instance method"

Set-Content -LiteralPath $MoviePath -Value $Text -NoNewline

$Agents = (Get-Content -LiteralPath $AgentsPath -Raw).Replace("`r`n", "`n")
$OldGuidance = @'
- The desktop editor runs from `run_editor.bat` with the local `.venv`.
'@
$NewGuidance = @'
- The desktop editor runs from `run_editor.bat` with the local `.venv`.
- The desktop editor supports multiple independent windows through the `New Window` button.
'@
if ($Agents.IndexOf($NewGuidance, [StringComparison]::Ordinal) -lt 0) {
    $Agents = Replace-Once $Agents $OldGuidance $NewGuidance "AGENTS multi-instance guidance"
    Set-Content -LiteralPath $AgentsPath -Value $Agents -NoNewline
}

$Repaired = Get-Content -LiteralPath $MoviePath -Raw
foreach ($Needle in @(
    "import sys",
    "text=`"New Window`"",
    "def launch_new_instance",
    "[sys.executable, str(Path(__file__).resolve())]",
    "Opened another editor window."
)) {
    if ($Repaired.IndexOf($Needle, [StringComparison]::Ordinal) -lt 0) {
        throw "Verification failed. Missing repaired text: $Needle"
    }
}
if ($Repaired.IndexOf("self.new_window_button", [StringComparison]::Ordinal) -lt 0) {
    throw "Verification failed. New Window button not present."
}
if ($Repaired.IndexOf("self.new_window_button,") -ge 0) {
    throw "Verification failed. New Window button was added to disabled video controls."
}

$AgentsRepaired = Get-Content -LiteralPath $AgentsPath -Raw
if ($AgentsRepaired.IndexOf("multiple independent windows", [StringComparison]::Ordinal) -lt 0) {
    throw "Verification failed. AGENTS.md multi-instance guidance was not updated."
}

Write-Host "Multi-instance repair complete."
Write-Host "Backups written under $BackupDir with stamp $Stamp."
