$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$editorPath = Join-Path $repo 'movie_quad_editor.py'
$agentsPath = Join-Path $repo 'AGENTS.md'
$backupRoot = Join-Path $repo 'backups\20260714_edit_saved_replacement_as_base_frame'

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

$oldReadFrame = @'
    def read_frame(self, frame_index):
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = self.capture.read()
        if not ok:
            return None
        return frame

    def get_output_frame(self, output_frame):
'@

$newReadFrame = @'
    def read_frame(self, frame_index):
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = self.capture.read()
        if not ok:
            return None
        return frame

    def get_editor_base_frame(self, output_frame):
        override = self.state.frame_override(output_frame)
        if override and Path(override).exists():
            return image_to_bgr(override, (self.state.width, self.state.height))
        return self.read_frame(self.state.source_frame_for_output(output_frame))

    def get_output_frame(self, output_frame):
'@

$editor = Replace-Exact -Text $editor -Old $oldReadFrame -New $newReadFrame -Label 'editor base frame helper'

$oldOpenRead = @'
        editor_output_frame = self.state.current_output_frame
        original_frame = self.read_frame(self.state.source_frame_for_output(editor_output_frame))
        if original_frame is None:
            messagebox.showerror("Edit Frame", "Could not read the frame being edited.")
            return

        original = Image.fromarray(cv2.cvtColor(original_frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
'@

$newOpenRead = @'
        editor_output_frame = self.state.current_output_frame
        original_frame = self.get_editor_base_frame(editor_output_frame)
        if original_frame is None:
            messagebox.showerror("Edit Frame", "Could not read the frame being edited.")
            return

        original = Image.fromarray(cv2.cvtColor(original_frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
'@

$editor = Replace-Exact -Text $editor -Old $oldOpenRead -New $newOpenRead -Label 'edit frame uses saved replacement base'

Write-CleanUtf8 -Path $editorPath -Text $editor

$after = Get-Content -LiteralPath $editorPath -Raw
$required = @(
    'def get_editor_base_frame(self, output_frame):',
    'override = self.state.frame_override(output_frame)',
    'return image_to_bgr(override, (self.state.width, self.state.height))',
    'original_frame = self.get_editor_base_frame(editor_output_frame)'
)
foreach ($needle in $required) {
    if (!$after.Contains($needle)) {
        throw "Verification failed. Missing expected text: $needle"
    }
}
$forbidden = 'original_frame = self.read_frame(self.state.source_frame_for_output(editor_output_frame))'
if ($after.Contains($forbidden)) {
    throw "Verification failed. Edit Frame still reads the source video frame directly."
}

$agents = Get-Content -LiteralPath $agentsPath -Raw
$anchor = "- The ``Edit Frame`` button opens the current video frame directly; image import stays on the separate ``Import Image`` button."
$newLine = "- When the selected frame already has a saved replacement, ``Edit Frame`` uses that replacement image as the editable base frame."
if (!$agents.Contains($newLine)) {
    if (!$agents.Contains($anchor)) {
        throw "AGENTS.md anchor line not found."
    }
    $agents = $agents.Replace($anchor, "$anchor`r`n$newLine")
    Write-CleanUtf8 -Path $agentsPath -Text $agents
}

Write-Host "Edit Frame now uses an existing saved replacement image as the base frame."
Write-Host "Backups written to $backupRoot"
