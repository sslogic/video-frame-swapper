$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$MainPath = Join-Path $Root "android\app\src\main\java\com\mayniak\subliminalstudio\MainActivity.java"
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (!(Test-Path -LiteralPath $MainPath)) {
    throw "Missing target file: $MainPath"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -LiteralPath $MainPath -Destination (Join-Path $BackupDir "MainActivity.java.$Stamp.android-text-controls.bak") -Force

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
        Button autoRemove = button("Auto Remove Image BG");
        layout.addView(autoRemove, matchWrap());

        final Bitmap[] imageLayer = new Bitmap[]{initialLayer};
'@ @'
        Button autoRemove = button("Auto Remove Image BG");
        layout.addView(autoRemove, matchWrap());

        LinearLayout textActions = row();
        Button duplicateText = button("Duplicate Text");
        Button deleteText = button("Delete Text");
        textActions.addView(duplicateText, weight());
        textActions.addView(deleteText, weight());
        layout.addView(textActions);

        final Bitmap[] imageLayer = new Bitmap[]{initialLayer};
'@ "text action buttons"

$Text = Replace-Once $Text @'
        final TextOverlay[] selected = new TextOverlay[]{null};
        final boolean[] dragSelected = new boolean[]{false};

        Runnable refresh = () -> preview.setImageBitmap(renderEditorBitmap(
'@ @'
        final TextOverlay[] selected = new TextOverlay[]{null};
        final boolean[] dragSelected = new boolean[]{false};

        Runnable syncTextControls = () -> {
            TextOverlay active = selected[0];
            if (active == null) {
                return;
            }
            if (!textInput.getText().toString().equals(active.text)) {
                textInput.setText(active.text);
            }
            setSeekValue(sizeSeek, active.size);
            setSeekValue(rotationSeek, active.rotation);
            setSeekValue(opacitySeek, active.opacity);
            setSeekValue(camouflageSeek, active.camouflage);
            borderCheck.setChecked(active.border);
        };

        Runnable refresh = () -> preview.setImageBitmap(renderEditorBitmap(
'@ "sync controls runnable"

$Text = Replace-Once $Text @'
                if (hit != null) {
                    selected[0] = hit;
                    dragSelected[0] = true;
                } else {
'@ @'
                if (hit != null) {
                    selected[0] = hit;
                    syncTextControls.run();
                    dragSelected[0] = true;
                } else {
'@ "sync selected text"

$Text = Replace-Once $Text @'
        borderCheck.setOnClickListener(v -> textRefresh.onProgressChanged(sizeSeek, sizeSeek.getProgress(), true));
        imageSizeSeek.setOnSeekBarChangeListener(new SimpleSeekListener(refresh));
'@ @'
        borderCheck.setOnClickListener(v -> textRefresh.onProgressChanged(sizeSeek, sizeSeek.getProgress(), true));
        textInput.addTextChangedListener(new android.text.TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) {}
            @Override public void afterTextChanged(android.text.Editable editable) {
                if (selected[0] != null) {
                    selected[0].text = editable.toString();
                    refresh.run();
                }
            }
        });
        imageSizeSeek.setOnSeekBarChangeListener(new SimpleSeekListener(refresh));
'@ "text input watcher"

$Text = Replace-Once $Text @'
        autoRemove.setOnClickListener(v -> {
            if (imageLayer[0] != null) {
                imageLayer[0] = autoRemoveBackground(imageLayer[0], seekValue(bgToleranceSeek));
                refresh.run();
            }
        });

        refresh.run();
'@ @'
        autoRemove.setOnClickListener(v -> {
            if (imageLayer[0] != null) {
                imageLayer[0] = autoRemoveBackground(imageLayer[0], seekValue(bgToleranceSeek));
                refresh.run();
            }
        });
        duplicateText.setOnClickListener(v -> {
            if (selected[0] == null) {
                return;
            }
            TextOverlay source = selected[0];
            TextOverlay copy = new TextOverlay();
            copy.text = source.text;
            copy.x = Math.min(videoWidth - 1, source.x + 32);
            copy.y = Math.min(videoHeight - 1, source.y + 32);
            copy.size = source.size;
            copy.rotation = source.rotation;
            copy.opacity = source.opacity;
            copy.camouflage = source.camouflage;
            copy.border = source.border;
            texts.add(copy);
            selected[0] = copy;
            syncTextControls.run();
            refresh.run();
        });
        deleteText.setOnClickListener(v -> {
            if (selected[0] == null) {
                return;
            }
            texts.remove(selected[0]);
            selected[0] = null;
            refresh.run();
        });

        refresh.run();
'@ "duplicate delete behavior"

$Text = Replace-Once $Text @'
    private int seekValue(SeekBar seek) {
        Object tag = seek.getTag();
        int min = tag instanceof Integer ? (Integer) tag : 0;
        return min + seek.getProgress();
    }

    private Bitmap renderEditorBitmap(Bitmap sourceFrame, Bitmap imageLayer, List<TextOverlay> texts, int imageSizeProgress, int imageRotationProgress) {
'@ @'
    private int seekValue(SeekBar seek) {
        Object tag = seek.getTag();
        int min = tag instanceof Integer ? (Integer) tag : 0;
        return min + seek.getProgress();
    }

    private void setSeekValue(SeekBar seek, int value) {
        Object tag = seek.getTag();
        int min = tag instanceof Integer ? (Integer) tag : 0;
        int progress = Math.max(0, Math.min(seek.getMax(), value - min));
        seek.setProgress(progress);
    }

    private Bitmap renderEditorBitmap(Bitmap sourceFrame, Bitmap imageLayer, List<TextOverlay> texts, int imageSizeProgress, int imageRotationProgress) {
'@ "set seek helper"

Set-Content -LiteralPath $MainPath -Value $Text -NoNewline

$Repaired = Get-Content -LiteralPath $MainPath -Raw
foreach ($Needle in @(
    "Duplicate Text",
    "Delete Text",
    "syncTextControls",
    "addTextChangedListener",
    "setSeekValue"
)) {
    if ($Repaired.IndexOf($Needle, [StringComparison]::Ordinal) -lt 0) {
        throw "Verification failed. Missing repaired text: $Needle"
    }
}

Write-Host "Android text editor controls repair complete."
Write-Host "Backup written under $BackupDir with stamp $Stamp."
