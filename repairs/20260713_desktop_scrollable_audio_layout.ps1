$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$MainPath = Join-Path $Root "movie_quad_editor.py"
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (!(Test-Path -LiteralPath $MainPath)) {
    throw "Missing target file: $MainPath"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -LiteralPath $MainPath -Destination (Join-Path $BackupDir "movie_quad_editor.py.$Stamp.desktop-scrollable-audio-layout.bak") -Force

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
        controls = ttk.Frame(main, padding=10)
        controls.columnconfigure(0, weight=1)
        main.add(controls, weight=2)
'@ @'
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
'@ "main scrollable controls panel"

$Text = Replace-Once $Text @'
        window.geometry("520x560")
        window.columnconfigure(0, weight=1)
        body = ttk.Frame(window, padding=12)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
'@ @'
        window.geometry("560x600")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        canvas = tk.Canvas(window, highlightthickness=0)
        scrollbar = ttk.Scrollbar(window, orient=tk.VERTICAL, command=canvas.yview)
        body = ttk.Frame(canvas, padding=12)
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_window, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        body.columnconfigure(1, weight=1)
'@ "audio track settings scrollable panel"

Set-Content -LiteralPath $MainPath -Value $Text -NoNewline

$Repaired = Get-Content -LiteralPath $MainPath -Raw
foreach ($Needle in @(
    "controls_outer",
    "controls_scrollbar",
    "controls_canvas",
    "body_window = canvas.create_window",
    "audio track settings scrollable"
)) {
    if ($Needle -eq "audio track settings scrollable") {
        continue
    }
    if ($Repaired.IndexOf($Needle, [StringComparison]::Ordinal) -lt 0) {
        throw "Verification failed. Missing repaired text: $Needle"
    }
}

Write-Host "Desktop scrollable audio layout repair complete."
Write-Host "Backup written under $BackupDir with stamp $Stamp."
