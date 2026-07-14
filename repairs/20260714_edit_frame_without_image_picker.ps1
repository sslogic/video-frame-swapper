$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$editorPath = Join-Path $repo 'movie_quad_editor.py'
$agentsPath = Join-Path $repo 'AGENTS.md'
$backupRoot = Join-Path $repo 'backups\20260714_edit_frame_without_image_picker'

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

function Write-CleanUtf8 {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Text
    )
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, ($Text.TrimEnd("`r", "`n") + "`r`n"), $encoding)
}

function Replace-Exact {
    param(
        [Parameter(Mandatory=$true)][string]$Text,
        [Parameter(Mandatory=$true)][string]$Old,
        [Parameter(Mandatory=$true)][string]$New,
        [Parameter(Mandatory=$true)][string]$Label
    )
    $count = ([regex]::Matches($Text, [regex]::Escape($Old))).Count
    if ($count -ne 1) {
        throw "Expected one match for $Label, found $count."
    }
    return $Text.Replace($Old, $New)
}

$editor = Get-Content -LiteralPath $editorPath -Raw

$oldButton = 'self.edit_image_button = ttk.Button(edit_row, text="Edit Imported", command=self.open_import_editor)'
$newButton = 'self.edit_image_button = ttk.Button(edit_row, text="Edit Frame", command=self.open_import_editor)'
$editor = Replace-Exact -Text $editor -Old $oldButton -New $newButton -Label 'edit frame button label'

$oldOpen = @'
    def open_import_editor(self):
        if not self.state:
            return
        if self.imported_image is None:
            self.import_image()
            if self.imported_image is None:
                return

        editor_output_frame = self.state.current_output_frame
        original_frame = self.read_frame(self.state.source_frame_for_output(editor_output_frame))
        if original_frame is None:
            messagebox.showerror("Edit Imported", "Could not read the frame being replaced.")
            return

        original = Image.fromarray(cv2.cvtColor(original_frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
        imported_source = self.imported_image.copy().convert("RGBA")
        imported = self.fit_image_to_frame(imported_source, original.size)

        window = tk.Toplevel(self)
        window.title("Edit Imported Image")
'@

$newOpen = @'
    def open_import_editor(self):
        if not self.state:
            return

        editor_output_frame = self.state.current_output_frame
        original_frame = self.read_frame(self.state.source_frame_for_output(editor_output_frame))
        if original_frame is None:
            messagebox.showerror("Edit Frame", "Could not read the frame being edited.")
            return

        original = Image.fromarray(cv2.cvtColor(original_frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
        direct_frame_edit = self.imported_image is None
        if direct_frame_edit:
            imported_source = Image.new("RGBA", original.size, (0, 0, 0, 0))
            imported = imported_source.copy()
            frame_opacity = 100.0
            image_opacity = 0.0
        else:
            imported_source = self.imported_image.copy().convert("RGBA")
            imported = self.fit_image_to_frame(imported_source, original.size)
            frame_opacity = 35.0
            image_opacity = 100.0

        window = tk.Toplevel(self)
        window.title("Edit Frame")
'@

$editor = Replace-Exact -Text $editor -Old $oldOpen -New $newOpen -Label 'open_import_editor image picker removal'

$oldState = @'
            "imported": imported,
            "background_image": None,
'@
$newState = @'
            "imported": imported,
            "direct_frame_edit": direct_frame_edit,
            "background_image": None,
'@
$editor = Replace-Exact -Text $editor -Old $oldState -New $newState -Label 'direct frame edit state'

$oldOpacity = @'
            "frame_opacity": tk.DoubleVar(value=35.0),
            "image_opacity": tk.DoubleVar(value=100.0),
'@
$newOpacity = @'
            "frame_opacity": tk.DoubleVar(value=frame_opacity),
            "image_opacity": tk.DoubleVar(value=image_opacity),
'@
$editor = Replace-Exact -Text $editor -Old $oldOpacity -New $newOpacity -Label 'direct frame edit opacity defaults'

$oldLabels = @'
        ttk.Label(panel, text="Imported image").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=0, to=100, variable=state["image_opacity"], command=self.on_editor_layer_control_changed).grid(row=4, column=0, sticky="ew")
        ttk.Label(panel, text="Imported image size").grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=5, to=300, variable=state["image_size"], command=self.on_imported_image_size_changed).grid(row=6, column=0, sticky="ew")
        ttk.Label(panel, text="Imported image rotation").grid(row=7, column=0, sticky="w", pady=(8, 0))
'@
$newLabels = @'
        ttk.Label(panel, text="Image layer").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=0, to=100, variable=state["image_opacity"], command=self.on_editor_layer_control_changed).grid(row=4, column=0, sticky="ew")
        ttk.Label(panel, text="Image layer size").grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(panel, from_=5, to=300, variable=state["image_size"], command=self.on_imported_image_size_changed).grid(row=6, column=0, sticky="ew")
        ttk.Label(panel, text="Image layer rotation").grid(row=7, column=0, sticky="w", pady=(8, 0))
'@
$editor = Replace-Exact -Text $editor -Old $oldLabels -New $newLabels -Label 'image layer labels'

$oldClose = 'messagebox.askyesnocancel("Edit Imported Image", "Apply these changes to the selected video frame before closing?")'
$newClose = 'messagebox.askyesnocancel("Edit Frame", "Apply these changes to the selected video frame before closing?")'
$editor = Replace-Exact -Text $editor -Old $oldClose -New $newClose -Label 'editor close prompt'

Write-CleanUtf8 -Path $editorPath -Text $editor

$after = Get-Content -LiteralPath $editorPath -Raw
$required = @(
    'self.edit_image_button = ttk.Button(edit_row, text="Edit Frame", command=self.open_import_editor)',
    'direct_frame_edit = self.imported_image is None',
    'imported_source = Image.new("RGBA", original.size, (0, 0, 0, 0))',
    '"frame_opacity": tk.DoubleVar(value=frame_opacity)',
    'window.title("Edit Frame")'
)
foreach ($needle in $required) {
    if (!$after.Contains($needle)) {
        throw "Verification failed. Missing expected text: $needle"
    }
}
$forbidden = @(
    'if self.imported_image is None:' + "`r`n" + '            self.import_image()',
    'window.title("Edit Imported Image")'
)
foreach ($needle in $forbidden) {
    if ($after.Contains($needle)) {
        throw "Verification failed. Forbidden old behavior remains: $needle"
    }
}

$agents = Get-Content -LiteralPath $agentsPath -Raw
$anchor = "- The desktop editor supports multiple independent windows through the ``New Window`` button."
$newLine = "- The ``Edit Frame`` button opens the current video frame directly; image import stays on the separate ``Import Image`` button."
if (!$agents.Contains($newLine)) {
    if (!$agents.Contains($anchor)) {
        throw "AGENTS.md anchor line not found."
    }
    $agents = $agents.Replace($anchor, "$anchor`r`n$newLine")
    Write-CleanUtf8 -Path $agentsPath -Text $agents
}

Write-Host "Edit Frame now opens the current frame without launching the image picker."
Write-Host "Backups written to $backupRoot"
