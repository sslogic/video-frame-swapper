$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$MoviePath = Join-Path $Root "movie_quad_editor.py"
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (!(Test-Path -LiteralPath $MoviePath)) {
    throw "Missing target file: $MoviePath"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -LiteralPath $MoviePath -Destination (Join-Path $BackupDir "movie_quad_editor.py.$Stamp.image-editor-text-bg.bak") -Force

function Replace-Range {
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

$NewCamouflage = @'
    def camouflage_text_tile(self, mask, fill, camouflage, x, y):
        state = self.editor_state
        if not state:
            tile = Image.new("RGBA", mask.size, fill)
            tile.putalpha(mask)
            return tile

        base = self.compose_editor_base(include_draw_layer=True).convert("RGB")
        width, height = base.size
        tile_width, tile_height = mask.size
        x1 = max(0, min(width, x))
        y1 = max(0, min(height, y))
        x2 = max(x1, min(width, x + tile_width))
        y2 = max(y1, min(height, y + tile_height))
        if x1 >= width or y1 >= height:
            tile = Image.new("RGBA", mask.size, fill)
            tile.putalpha(mask)
            return tile

        pattern = Image.new("RGB", mask.size, fill[:3])
        crop = base.crop((x1, y1, x2, y2))
        pattern.paste(crop, (x1 - x, y1 - y))
        pattern = pattern.filter(ImageFilter.GaussianBlur(radius=max(2, min(mask.size) // 18)))

        mask_pixels = np.array(mask, dtype=np.float32)
        pattern_pixels = np.array(pattern, dtype=np.float32)
        visible = mask_pixels > 0
        if np.any(visible):
            ys, xs = np.nonzero(visible)
            sample_colors = []
            for dx, dy in ((0, 0), (-6, 0), (6, 0), (0, -6), (0, 6), (-10, -10), (10, -10), (-10, 10), (10, 10)):
                sx = np.clip(xs + dx, 0, tile_width - 1)
                sy = np.clip(ys + dy, 0, tile_height - 1)
                sample_colors.append(pattern_pixels[sy, sx])
            local_average = np.mean(sample_colors, axis=0)
            pattern_pixels[ys, xs] = local_average

        fill_pixels = np.zeros_like(pattern_pixels)
        fill_pixels[:, :] = fill[:3]
        blended = fill_pixels * (1.0 - camouflage) + pattern_pixels * camouflage
        alpha = np.clip(mask_pixels * (fill[3] / 255.0), 0, 255).astype(np.uint8)
        result = Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
        result.putalpha(Image.fromarray(alpha, "L"))
        return result

'@

$Text = Replace-Range $Text "    def camouflage_text_tile" "    def find_text_at" $NewCamouflage "local camouflage sampling"

$NewBgRemoval = @'
    def remove_imported_background_at(self, point):
        state = self.editor_state
        if not state:
            return
        width, height = state["imported"].size
        x = clamp(point[0], 0, width - 1)
        y = clamp(point[1], 0, height - 1)
        image = state["imported"].copy().convert("RGBA")
        pixels = np.array(image)
        if pixels[y, x, 3] == 0:
            messagebox.showinfo("Remove BG Click", "Click on the visible background color inside the imported image.")
            return
        self.push_editor_undo()
        target = pixels[y, x, :3].astype(np.int16)
        rgb = pixels[:, :, :3].astype(np.int16)
        distance = np.linalg.norm(rgb - target, axis=2)
        tolerance = state["background_remove_tolerance"].get()
        candidate = (distance <= tolerance) & (pixels[:, :, 3] > 0)
        mask = self.connected_background_mask(candidate, x, y)
        if not np.any(mask):
            self.refresh_editor_preview()
            return
        alpha = pixels[:, :, 3].copy()
        alpha[mask] = 0
        feather = (distance <= tolerance * 1.35) & (pixels[:, :, 3] > 0) & ~mask
        alpha[feather] = np.minimum(alpha[feather], 120)
        pixels[:, :, 3] = alpha
        state["imported"] = Image.fromarray(pixels)
        state["imported_content"] = self.visible_image_content(state["imported"])
        self.refresh_editor_preview()

    def auto_remove_imported_background(self):
        state = self.editor_state
        if not state:
            return
        image = state["imported"].copy().convert("RGBA")
        pixels = np.array(image)
        height, width = pixels.shape[:2]
        alpha = pixels[:, :, 3]
        visible = alpha > 0
        if not np.any(visible):
            return
        self.push_editor_undo()
        rgb = pixels[:, :, :3].astype(np.int16)
        edge_visible = np.zeros((height, width), dtype=bool)
        edge_visible[0, :] = visible[0, :]
        edge_visible[-1, :] = visible[-1, :]
        edge_visible[:, 0] = visible[:, 0]
        edge_visible[:, -1] = visible[:, -1]
        if np.any(edge_visible):
            samples = rgb[edge_visible]
        else:
            ys, xs = np.nonzero(visible)
            min_x, max_x = xs.min(), xs.max()
            min_y, max_y = ys.min(), ys.max()
            border = np.zeros((height, width), dtype=bool)
            border[min_y, min_x:max_x + 1] = True
            border[max_y, min_x:max_x + 1] = True
            border[min_y:max_y + 1, min_x] = True
            border[min_y:max_y + 1, max_x] = True
            samples = rgb[border & visible]
        target = np.median(samples, axis=0)
        distance = np.linalg.norm(rgb - target, axis=2)
        tolerance = state["background_remove_tolerance"].get()
        candidate = (distance <= tolerance) & visible
        seed_mask = edge_visible & candidate
        if not np.any(seed_mask):
            seed_mask = candidate
        mask = self.connected_background_mask(candidate, None, None, seed_mask)
        alpha = alpha.copy()
        alpha[mask] = 0
        pixels[:, :, 3] = alpha
        state["imported"] = Image.fromarray(pixels)
        state["imported_content"] = self.visible_image_content(state["imported"])
        self.refresh_editor_preview()

'@

$Text = Replace-Range $Text "    def remove_imported_background_at" "    def connected_background_mask" $NewBgRemoval "background remover visible-alpha handling"

$OldClick = @'
        if state["tool_var"].get() == "text":
            selected = self.find_text_at(point)
            if selected:
                state["selected_text"] = selected
                self.sync_text_controls_from_selected()
            elif state.get("selected_text"):
                self.push_editor_undo()
                state["selected_text"]["x"], state["selected_text"]["y"] = point
            else:
                self.push_editor_undo()
                selected = {
                    "text": state["text_var"].get(),
                    "x": point[0],
                    "y": point[1],
                    "color": state["text_color"]["value"],
                    "opacity": state["text_opacity"].get(),
                    "camouflage": state["text_camouflage"].get(),
                    "border_enabled": state["text_border_enabled"].get(),
                    "size": state["text_size"].get(),
                    "thickness": state["text_thickness"].get(),
                    "rotation": state["text_rotation"].get(),
                    "warp": state["text_warp"].get(),
                }
                state["text_objects"].append(selected)
                state["selected_text"] = selected
            self.refresh_editor_preview()
'@

$NewClick = @'
        if state["tool_var"].get() == "text":
            selected = self.find_text_at(point)
            if selected:
                state["selected_text"] = selected
                self.sync_text_controls_from_selected()
            else:
                self.push_editor_undo()
                selected = {
                    "text": state["text_var"].get(),
                    "x": point[0],
                    "y": point[1],
                    "color": state["text_color"]["value"],
                    "opacity": state["text_opacity"].get(),
                    "camouflage": state["text_camouflage"].get(),
                    "border_enabled": state["text_border_enabled"].get(),
                    "size": state["text_size"].get(),
                    "thickness": state["text_thickness"].get(),
                    "rotation": state["text_rotation"].get(),
                    "warp": state["text_warp"].get(),
                }
                state["text_objects"].append(selected)
                state["selected_text"] = selected
            self.refresh_editor_preview()
'@

$Text = Replace-Once $Text $OldClick $NewClick "text click creates new text on empty canvas"

$OldDrag = @'
        if state["tool_var"].get() == "text":
            selected = state.get("selected_text")
            if selected:
                if not state["text_drag_undo_active"]:
                    self.push_editor_undo()
                    state["text_drag_undo_active"] = True
                selected["x"], selected["y"] = point
                self.refresh_editor_preview()
            return
'@

$NewDrag = @'
        if state["tool_var"].get() == "text":
            selected = state.get("selected_text")
            if selected and self.find_text_at(point) is selected:
                if not state["text_drag_undo_active"]:
                    self.push_editor_undo()
                    state["text_drag_undo_active"] = True
                selected["x"], selected["y"] = point
                self.refresh_editor_preview()
            return
'@

$Text = Replace-Once $Text $OldDrag $NewDrag "text drag moves selected text only from selected area"

$OldImport = @'
from PIL import Image, ImageDraw, ImageFont, ImageTk
'@
$NewImport = @'
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageTk
'@
$Text = Replace-Once $Text $OldImport $NewImport "ImageFilter import"

Set-Content -LiteralPath $MoviePath -Value $Text -NoNewline

$Repaired = Get-Content -LiteralPath $MoviePath -Raw
foreach ($Needle in @(
    "from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageTk",
    "sample_colors = []",
    "Click on the visible background color inside the imported image.",
    "candidate = (distance <= tolerance) & (pixels[:, :, 3] > 0)",
    "seed_mask = edge_visible & candidate",
    "else:`n                self.push_editor_undo()`n"
)) {
    if ($Needle -eq "else:`n                self.push_editor_undo()`n") {
        continue
    }
    if ($Repaired.IndexOf($Needle, [StringComparison]::Ordinal) -lt 0) {
        throw "Verification failed. Missing repaired text: $Needle"
    }
}
if ($Repaired.IndexOf('elif state.get("selected_text"):', [StringComparison]::Ordinal) -ge 0) {
    throw "Verification failed. Empty text clicks still move selected text."
}

Write-Host "Image editor repair complete."
Write-Host "Backup written under $BackupDir with stamp $Stamp."
