$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$MainPath = Join-Path $Root "android\app\src\main\java\com\mayniak\subliminalstudio\MainActivity.java"
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (!(Test-Path -LiteralPath $MainPath)) {
    throw "Missing target file: $MainPath"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -LiteralPath $MainPath -Destination (Join-Path $BackupDir "MainActivity.java.$Stamp.android-editor-features.bak") -Force

function Replace-Once {
    param([string]$Text, [string]$Old, [string]$New, [string]$Label)
    $First = $Text.IndexOf($Old, [StringComparison]::Ordinal)
    if ($First -lt 0) { throw "Could not find expected block: $Label" }
    $Second = $Text.IndexOf($Old, $First + $Old.Length, [StringComparison]::Ordinal)
    if ($Second -ge 0) { throw "Expected block was not unique: $Label" }
    return $Text.Remove($First, $Old.Length).Insert($First, $New)
}

function Replace-Range {
    param([string]$Text, [string]$StartMarker, [string]$EndMarker, [string]$New, [string]$Label)
    $Start = $Text.IndexOf($StartMarker, [StringComparison]::Ordinal)
    if ($Start -lt 0) { throw "Could not find start marker for $Label" }
    $End = $Text.IndexOf($EndMarker, $Start + $StartMarker.Length, [StringComparison]::Ordinal)
    if ($End -lt 0) { throw "Could not find end marker for $Label" }
    return $Text.Remove($Start, $End - $Start).Insert($Start, $New)
}

$Text = (Get-Content -LiteralPath $MainPath -Raw).Replace("`r`n", "`n")

$Text = Replace-Once $Text "import android.graphics.Paint;`nimport android.media.MediaMetadataRetriever;" "import android.graphics.Paint;`nimport android.graphics.RectF;`nimport android.media.MediaMetadataRetriever;" "RectF import"
$Text = Replace-Once $Text "import android.view.Gravity;`nimport android.view.View;" "import android.view.Gravity;`nimport android.view.MotionEvent;`nimport android.view.View;" "MotionEvent import"
$Text = Replace-Once $Text "import java.util.HashMap;`nimport java.util.Locale;`nimport java.util.Map;" "import java.util.ArrayDeque;`nimport java.util.ArrayList;`nimport java.util.HashMap;`nimport java.util.List;`nimport java.util.Locale;`nimport java.util.Map;" "collection imports"

$Text = Replace-Once $Text "    private static final int PICK_OUTPUT_TREE = 13;" "    private static final int PICK_OUTPUT_TREE = 13;`n    private static final int PICK_REPEAT_REPLACEMENT = 14;" "repeat picker constant"
$Text = Replace-Once $Text "    private boolean exporting = false;" "    private boolean exporting = false;`n    private int pendingRepeatInterval = 0;" "pending repeat field"

$OldEditRow = @'
        LinearLayout editRow = row();
        Button replace = button("Replace Frame");
        replace.setOnClickListener(v -> pick(PICK_REPLACEMENT, "image/*"));
        Button editText = button("Edit Text");
        editText.setOnClickListener(v -> openTextEditor());
        Button clear = button("Clear Frame");
        clear.setOnClickListener(v -> {
            replacements.remove(key(currentOutputFrame));
            saveProject();
            refreshPreview();
        });
        editRow.addView(replace, weight());
        editRow.addView(editText, weight());
        editRow.addView(clear, weight());
        root.addView(editRow);
'@

$NewEditRow = @'
        LinearLayout editRow = row();
        Button replace = button("Replace Frame");
        replace.setOnClickListener(v -> pick(PICK_REPLACEMENT, "image/*"));
        Button editImage = button("Edit Image/Text");
        editImage.setOnClickListener(v -> openFrameImageEditor());
        Button repeatReplace = button("Replace Every X");
        repeatReplace.setOnClickListener(v -> replaceEveryXFrames());
        Button clear = button("Clear Frame");
        clear.setOnClickListener(v -> {
            replacements.remove(key(currentOutputFrame));
            saveProject();
            refreshPreview();
        });
        editRow.addView(replace, weight());
        editRow.addView(editImage, weight());
        editRow.addView(repeatReplace, weight());
        editRow.addView(clear, weight());
        root.addView(editRow);
'@

$Text = Replace-Once $Text $OldEditRow $NewEditRow "editor buttons"

$OldActivityResult = @'
        } else if (requestCode == PICK_REPLACEMENT) {
            replacements.put(key(currentOutputFrame), uri);
        } else if (requestCode == PICK_OUTPUT_TREE) {
            outputTreeUri = uri;
        }
'@

$NewActivityResult = @'
        } else if (requestCode == PICK_REPLACEMENT) {
            replacements.put(key(currentOutputFrame), uri);
        } else if (requestCode == PICK_REPEAT_REPLACEMENT) {
            applyRepeatedReplacement(uri);
        } else if (requestCode == PICK_OUTPUT_TREE) {
            outputTreeUri = uri;
        }
'@

$Text = Replace-Once $Text $OldActivityResult $NewActivityResult "activity result repeated replacement"

$NewEditorBlock = @'
    private void openFrameImageEditor() {
        if (videoUri == null) {
            setStatus("Open a video first.");
            return;
        }
        try {
            MediaMetadataRetriever retriever = new MediaMetadataRetriever();
            Bitmap source;
            try {
                retriever.setDataSource(this, videoUri);
                source = frameAt(retriever, sourceFrameForOutput(currentOutputFrame)).copy(Bitmap.Config.ARGB_8888, true);
            } finally {
                safeRelease(retriever);
            }
            Uri replacementUri = replacements.get(key(currentOutputFrame));
            Bitmap imageLayer = replacementUri == null ? null : loadBitmap(replacementUri, videoWidth, videoHeight).copy(Bitmap.Config.ARGB_8888, true);
            showImageEditorDialog(source, imageLayer);
        } catch (Exception exc) {
            setStatus("Image editor failed: " + exc.getMessage());
        }
    }

    private void showImageEditorDialog(Bitmap sourceFrame, Bitmap initialLayer) {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(18, 12, 18, 0);

        ImageView preview = new ImageView(this);
        preview.setBackgroundColor(Color.rgb(24, 24, 24));
        preview.setScaleType(ImageView.ScaleType.FIT_XY);
        layout.addView(preview, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 620));

        RadioGroup mode = new RadioGroup(this);
        mode.setOrientation(RadioGroup.HORIZONTAL);
        RadioButton textMode = new RadioButton(this);
        textMode.setText("Text");
        textMode.setId(1);
        RadioButton removeMode = new RadioButton(this);
        removeMode.setText("Remove BG");
        removeMode.setId(2);
        mode.addView(textMode);
        mode.addView(removeMode);
        mode.check(1);
        layout.addView(mode, matchWrap());

        EditText textInput = new EditText(this);
        textInput.setHint("Text");
        textInput.setText("Text");
        layout.addView(textInput, matchWrap());

        SeekBar sizeSeek = seek(layout, "Text Size", 8, 300, 64);
        SeekBar rotationSeek = seek(layout, "Text Rotation", 0, 360, 0);
        SeekBar opacitySeek = seek(layout, "Text Opacity", 0, 100, 100);
        SeekBar camouflageSeek = seek(layout, "Text Camouflage", 0, 100, 0);
        CheckBox borderCheck = new CheckBox(this);
        borderCheck.setText("Text border");
        layout.addView(borderCheck, matchWrap());
        SeekBar imageSizeSeek = seek(layout, "Image Size", 5, 300, 100);
        SeekBar imageRotationSeek = seek(layout, "Image Rotation", 0, 360, 0);
        SeekBar bgToleranceSeek = seek(layout, "BG Remove Tolerance", 5, 140, 38);

        Button autoRemove = button("Auto Remove Image BG");
        layout.addView(autoRemove, matchWrap());

        final Bitmap[] imageLayer = new Bitmap[]{initialLayer};
        final List<TextOverlay> texts = new ArrayList<>();
        final TextOverlay[] selected = new TextOverlay[]{null};
        final boolean[] dragSelected = new boolean[]{false};

        Runnable refresh = () -> preview.setImageBitmap(renderEditorBitmap(
                sourceFrame,
                imageLayer[0],
                texts,
                seekValue(imageSizeSeek),
                seekValue(imageRotationSeek)));

        preview.setOnTouchListener((view, event) -> {
            if (event.getAction() == MotionEvent.ACTION_DOWN) {
                float x = event.getX() / Math.max(1, view.getWidth()) * videoWidth;
                float y = event.getY() / Math.max(1, view.getHeight()) * videoHeight;
                if (mode.getCheckedRadioButtonId() == 2) {
                    if (imageLayer[0] != null) {
                        imageLayer[0] = removeBackgroundAt(imageLayer[0], (int) x, (int) y, seekValue(bgToleranceSeek));
                        refresh.run();
                    }
                    return true;
                }
                TextOverlay hit = findTextOverlay(texts, x, y);
                if (hit != null) {
                    selected[0] = hit;
                    dragSelected[0] = true;
                } else {
                    TextOverlay overlay = new TextOverlay();
                    overlay.text = textInput.getText().toString();
                    overlay.x = x;
                    overlay.y = y;
                    texts.add(overlay);
                    selected[0] = overlay;
                    dragSelected[0] = true;
                }
                refresh.run();
                return true;
            }
            if (event.getAction() == MotionEvent.ACTION_MOVE && dragSelected[0] && selected[0] != null) {
                selected[0].x = event.getX() / Math.max(1, view.getWidth()) * videoWidth;
                selected[0].y = event.getY() / Math.max(1, view.getHeight()) * videoHeight;
                refresh.run();
                return true;
            }
            if (event.getAction() == MotionEvent.ACTION_UP) {
                dragSelected[0] = false;
                return true;
            }
            return true;
        });

        SeekBar.OnSeekBarChangeListener textRefresh = new SimpleSeekListener(() -> {
            if (selected[0] != null) {
                selected[0].text = textInput.getText().toString();
                selected[0].size = Math.max(8, seekValue(sizeSeek));
                selected[0].rotation = seekValue(rotationSeek);
                selected[0].opacity = seekValue(opacitySeek);
                selected[0].camouflage = seekValue(camouflageSeek);
                selected[0].border = borderCheck.isChecked();
            }
            refresh.run();
        });
        sizeSeek.setOnSeekBarChangeListener(textRefresh);
        rotationSeek.setOnSeekBarChangeListener(textRefresh);
        opacitySeek.setOnSeekBarChangeListener(textRefresh);
        camouflageSeek.setOnSeekBarChangeListener(textRefresh);
        borderCheck.setOnClickListener(v -> textRefresh.onProgressChanged(sizeSeek, sizeSeek.getProgress(), true));
        imageSizeSeek.setOnSeekBarChangeListener(new SimpleSeekListener(refresh));
        imageRotationSeek.setOnSeekBarChangeListener(new SimpleSeekListener(refresh));
        autoRemove.setOnClickListener(v -> {
            if (imageLayer[0] != null) {
                imageLayer[0] = autoRemoveBackground(imageLayer[0], seekValue(bgToleranceSeek));
                refresh.run();
            }
        });

        refresh.run();
        new AlertDialog.Builder(this)
                .setTitle("Edit Image/Text")
                .setView(layout)
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Apply Changes", (dialog, which) -> {
                    try {
                        Bitmap edited = renderEditorBitmap(sourceFrame, imageLayer[0], texts, seekValue(imageSizeSeek), seekValue(imageRotationSeek));
                        File editedDir = new File(getFilesDir(), "edited_frames");
                        if (!editedDir.exists() && !editedDir.mkdirs()) {
                            throw new IOException("Could not create edited frame folder.");
                        }
                        File output = new File(editedDir, "frame_" + currentOutputFrame + ".png");
                        writePng(edited, output);
                        replacements.put(key(currentOutputFrame), Uri.fromFile(output));
                        saveProject();
                        refreshUi();
                        setStatus("Applied edited image to frame " + currentOutputFrame + ".");
                    } catch (Exception exc) {
                        setStatus("Image edit failed: " + exc.getMessage());
                    }
                })
                .show();
    }

    private SeekBar seek(LinearLayout layout, String label, int min, int max, int value) {
        layout.addView(label(label));
        SeekBar seek = new SeekBar(this);
        seek.setMax(max - min);
        seek.setProgress(Math.max(0, Math.min(max - min, value - min)));
        seek.setTag(min);
        layout.addView(seek, matchWrap());
        return seek;
    }

    private int seekValue(SeekBar seek) {
        Object tag = seek.getTag();
        int min = tag instanceof Integer ? (Integer) tag : 0;
        return min + seek.getProgress();
    }

    private Bitmap renderEditorBitmap(Bitmap sourceFrame, Bitmap imageLayer, List<TextOverlay> texts, int imageSizeProgress, int imageRotationProgress) {
        Bitmap edited = sourceFrame.copy(Bitmap.Config.ARGB_8888, true);
        Canvas canvas = new Canvas(edited);
        if (imageLayer != null) {
            Bitmap scaled = fitBitmapToFrame(imageLayer, videoWidth, videoHeight, Math.max(5, imageSizeProgress));
            canvas.save();
            canvas.rotate(imageRotationProgress, videoWidth / 2f, videoHeight / 2f);
            canvas.drawBitmap(scaled, 0, 0, null);
            canvas.restore();
        }
        for (TextOverlay overlay : texts) {
            drawTextOverlay(canvas, edited, overlay);
        }
        return edited;
    }

    private void drawTextOverlay(Canvas canvas, Bitmap base, TextOverlay overlay) {
        Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        paint.setTextSize(Math.max(8, overlay.size));
        int alpha = Math.max(0, Math.min(255, overlay.opacity * 255 / 100));
        int color = Color.argb(alpha, 255, 255, 255);
        if (overlay.camouflage > 0) {
            int sampled = sampleTextColor(base, overlay);
            color = blendColor(color, sampled, overlay.camouflage / 100.0);
            color = Color.argb(alpha, Color.red(color), Color.green(color), Color.blue(color));
        }
        paint.setColor(color);
        paint.setStyle(Paint.Style.FILL);
        if (overlay.border) {
            paint.setShadowLayer(4f, 2f, 2f, Color.argb(alpha, 0, 0, 0));
        } else {
            paint.clearShadowLayer();
        }
        canvas.save();
        canvas.rotate(overlay.rotation, overlay.x, overlay.y);
        canvas.drawText(overlay.text, overlay.x, overlay.y, paint);
        canvas.restore();
    }

    private TextOverlay findTextOverlay(List<TextOverlay> texts, float x, float y) {
        for (int i = texts.size() - 1; i >= 0; i--) {
            TextOverlay overlay = texts.get(i);
            RectF bounds = textBounds(overlay);
            if (bounds.contains(x, y)) {
                return overlay;
            }
        }
        return null;
    }

    private RectF textBounds(TextOverlay overlay) {
        Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        paint.setTextSize(Math.max(8, overlay.size));
        float width = Math.max(48, paint.measureText(overlay.text));
        Paint.FontMetrics metrics = paint.getFontMetrics();
        float height = Math.max(24, metrics.descent - metrics.ascent);
        return new RectF(overlay.x, overlay.y - height, overlay.x + width, overlay.y + height * 0.35f);
    }

    private int sampleTextColor(Bitmap bitmap, TextOverlay overlay) {
        RectF bounds = textBounds(overlay);
        int left = Math.max(0, (int) bounds.left - 12);
        int top = Math.max(0, (int) bounds.top - 12);
        int right = Math.min(bitmap.getWidth() - 1, (int) bounds.right + 12);
        int bottom = Math.min(bitmap.getHeight() - 1, (int) bounds.bottom + 12);
        long r = 0, g = 0, b = 0, count = 0;
        int step = Math.max(1, Math.min(right - left + 1, bottom - top + 1) / 12);
        for (int yy = top; yy <= bottom; yy += step) {
            for (int xx = left; xx <= right; xx += step) {
                int color = bitmap.getPixel(xx, yy);
                r += Color.red(color);
                g += Color.green(color);
                b += Color.blue(color);
                count++;
            }
        }
        if (count == 0) {
            return Color.WHITE;
        }
        return Color.rgb((int) (r / count), (int) (g / count), (int) (b / count));
    }

    private int blendColor(int foreground, int sample, double amount) {
        double keep = 1.0 - amount;
        return Color.rgb(
                clampChannel((int) Math.round(Color.red(foreground) * keep + Color.red(sample) * amount)),
                clampChannel((int) Math.round(Color.green(foreground) * keep + Color.green(sample) * amount)),
                clampChannel((int) Math.round(Color.blue(foreground) * keep + Color.blue(sample) * amount)));
    }

    private Bitmap removeBackgroundAt(Bitmap source, int x, int y, int tolerance) {
        Bitmap bitmap = source.copy(Bitmap.Config.ARGB_8888, true);
        int width = bitmap.getWidth();
        int height = bitmap.getHeight();
        x = Math.max(0, Math.min(width - 1, x));
        y = Math.max(0, Math.min(height - 1, y));
        int target = bitmap.getPixel(x, y);
        boolean[] visited = new boolean[width * height];
        ArrayDeque<Integer> stack = new ArrayDeque<>();
        stack.push(y * width + x);
        while (!stack.isEmpty()) {
            int index = stack.pop();
            if (index < 0 || index >= visited.length || visited[index]) {
                continue;
            }
            visited[index] = true;
            int px = index % width;
            int py = index / width;
            int color = bitmap.getPixel(px, py);
            if (Color.alpha(color) == 0 || colorDistance(color, target) > tolerance) {
                continue;
            }
            bitmap.setPixel(px, py, Color.TRANSPARENT);
            if (px > 0) stack.push(index - 1);
            if (px < width - 1) stack.push(index + 1);
            if (py > 0) stack.push(index - width);
            if (py < height - 1) stack.push(index + width);
        }
        return bitmap;
    }

    private Bitmap autoRemoveBackground(Bitmap source, int tolerance) {
        Bitmap bitmap = source.copy(Bitmap.Config.ARGB_8888, true);
        int width = bitmap.getWidth();
        int height = bitmap.getHeight();
        int target = medianEdgeColor(bitmap);
        boolean[] candidate = new boolean[width * height];
        ArrayDeque<Integer> stack = new ArrayDeque<>();
        for (int x = 0; x < width; x++) {
            seedBackground(bitmap, candidate, stack, x, 0, target, tolerance);
            seedBackground(bitmap, candidate, stack, x, height - 1, target, tolerance);
        }
        for (int y = 0; y < height; y++) {
            seedBackground(bitmap, candidate, stack, 0, y, target, tolerance);
            seedBackground(bitmap, candidate, stack, width - 1, y, target, tolerance);
        }
        while (!stack.isEmpty()) {
            int index = stack.pop();
            if (index < 0 || index >= candidate.length || candidate[index]) {
                continue;
            }
            int px = index % width;
            int py = index / width;
            int color = bitmap.getPixel(px, py);
            if (Color.alpha(color) == 0 || colorDistance(color, target) > tolerance) {
                continue;
            }
            candidate[index] = true;
            bitmap.setPixel(px, py, Color.TRANSPARENT);
            if (px > 0) stack.push(index - 1);
            if (px < width - 1) stack.push(index + 1);
            if (py > 0) stack.push(index - width);
            if (py < height - 1) stack.push(index + width);
        }
        return bitmap;
    }

    private void seedBackground(Bitmap bitmap, boolean[] seen, ArrayDeque<Integer> stack, int x, int y, int target, int tolerance) {
        int width = bitmap.getWidth();
        int index = y * width + x;
        if (!seen[index] && colorDistance(bitmap.getPixel(x, y), target) <= tolerance) {
            stack.push(index);
        }
    }

    private int medianEdgeColor(Bitmap bitmap) {
        int width = bitmap.getWidth();
        int height = bitmap.getHeight();
        long r = 0, g = 0, b = 0, count = 0;
        for (int x = 0; x < width; x++) {
            int top = bitmap.getPixel(x, 0);
            int bottom = bitmap.getPixel(x, height - 1);
            r += Color.red(top) + Color.red(bottom);
            g += Color.green(top) + Color.green(bottom);
            b += Color.blue(top) + Color.blue(bottom);
            count += 2;
        }
        for (int y = 0; y < height; y++) {
            int left = bitmap.getPixel(0, y);
            int right = bitmap.getPixel(width - 1, y);
            r += Color.red(left) + Color.red(right);
            g += Color.green(left) + Color.green(right);
            b += Color.blue(left) + Color.blue(right);
            count += 2;
        }
        return Color.rgb((int) (r / count), (int) (g / count), (int) (b / count));
    }

    private double colorDistance(int a, int b) {
        int dr = Color.red(a) - Color.red(b);
        int dg = Color.green(a) - Color.green(b);
        int db = Color.blue(a) - Color.blue(b);
        return Math.sqrt(dr * dr + dg * dg + db * db);
    }

    private void replaceEveryXFrames() {
        if (videoUri == null) {
            setStatus("Open a video first.");
            return;
        }
        EditText input = new EditText(this);
        input.setInputType(android.text.InputType.TYPE_CLASS_NUMBER);
        input.setHint("Frame interval");
        input.setText("10");
        new AlertDialog.Builder(this)
                .setTitle("Replace Every X Frames")
                .setView(input)
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Choose Image", (dialog, which) -> {
                    try {
                        pendingRepeatInterval = Math.max(1, Integer.parseInt(input.getText().toString()));
                        pick(PICK_REPEAT_REPLACEMENT, "image/*");
                    } catch (Exception exc) {
                        setStatus("Enter a valid frame interval.");
                    }
                })
                .show();
    }

    private void applyRepeatedReplacement(Uri uri) {
        if (pendingRepeatInterval <= 0) {
            return;
        }
        int count = 0;
        for (int outputFrame = currentOutputFrame; outputFrame < outputFrameCount(); outputFrame += pendingRepeatInterval) {
            replacements.put(key(outputFrame), uri);
            count++;
        }
        pendingRepeatInterval = 0;
        saveProject();
        refreshUi();
        setStatus("Replaced " + count + " frames from frame " + currentOutputFrame + ".");
    }

'@

$Text = Replace-Range $Text "    private void openTextEditor()" "    private int outputFrameCount()" $NewEditorBlock "image/text editor block"

$OldLoadBitmap = @'
    private Bitmap loadBitmap(Uri uri, int width, int height) throws IOException {
        if ("file".equals(uri.getScheme())) {
            Bitmap bitmap = BitmapFactory.decodeFile(uri.getPath());
            if (bitmap == null) {
                throw new IOException("Could not read image file.");
            }
            return Bitmap.createScaledBitmap(bitmap, width, height, true);
        }
        ImageDecoder.Source source = ImageDecoder.createSource(getContentResolver(), uri);
        Bitmap bitmap = ImageDecoder.decodeBitmap(source, (decoder, info, src) -> decoder.setAllocator(ImageDecoder.ALLOCATOR_SOFTWARE));
        return Bitmap.createScaledBitmap(bitmap, width, height, true);
    }
'@

$NewLoadBitmap = @'
    private Bitmap loadBitmap(Uri uri, int width, int height) throws IOException {
        Bitmap bitmap;
        if ("file".equals(uri.getScheme())) {
            bitmap = BitmapFactory.decodeFile(uri.getPath());
            if (bitmap == null) {
                throw new IOException("Could not read image file.");
            }
        } else {
            ImageDecoder.Source source = ImageDecoder.createSource(getContentResolver(), uri);
            bitmap = ImageDecoder.decodeBitmap(source, (decoder, info, src) -> decoder.setAllocator(ImageDecoder.ALLOCATOR_SOFTWARE));
        }
        return fitBitmapToFrame(bitmap, width, height, 100);
    }

    private Bitmap fitBitmapToFrame(Bitmap bitmap, int width, int height, int scalePercent) {
        Bitmap source = bitmap.copy(Bitmap.Config.ARGB_8888, false);
        double fitScale = Math.min(width / (double) source.getWidth(), height / (double) source.getHeight());
        double scale = fitScale * Math.max(5, Math.min(300, scalePercent)) / 100.0;
        int fittedWidth = Math.max(1, (int) Math.round(source.getWidth() * scale));
        int fittedHeight = Math.max(1, (int) Math.round(source.getHeight() * scale));
        Bitmap fitted = Bitmap.createScaledBitmap(source, fittedWidth, fittedHeight, true);
        Bitmap layer = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(layer);
        canvas.drawColor(Color.TRANSPARENT);
        canvas.drawBitmap(fitted, (width - fittedWidth) / 2f, (height - fittedHeight) / 2f, null);
        return layer;
    }
'@

$Text = Replace-Once $Text $OldLoadBitmap $NewLoadBitmap "aspect fit bitmap loading"

$OldExportLoop = @'
        MediaMetadataRetriever retriever = new MediaMetadataRetriever();
        retriever.setDataSource(this, videoUri);
        int outputIndex = 0;
        try {
            for (int frame = 0; frame < frameCount; frame++) {
                Bitmap source = frameAt(retriever, frame);
                Bitmap previous = frameAt(retriever, Math.max(0, frame - 1));
                Bitmap next = frameAt(retriever, Math.min(frameCount - 1, frame + 1));
                for (int slot = 0; slot < SLOT_COUNT; slot++) {
                    int outputFrame = frame * SLOT_COUNT + slot;
                    Bitmap out = source;
                    Uri replacement = replacements.get(key(outputFrame));
                    if (replacement != null) {
                        out = loadBitmap(replacement, videoWidth, videoHeight);
                        if (colorBlendCheck.isChecked()) {
                            out = colorBlend(
                                    out,
                                    previous,
                                    next,
                                    colorBlendSeek.getProgress() / 100.0,
                                    frequencyBlendSeek.getProgress() / 100.0);
                        }
                    }
                    File frameFile = new File(framesDir, String.format(Locale.US, "frame_%08d.png", outputIndex++));
                    writePng(out, frameFile);
                }
                int done = frame + 1;
                runOnUiThread(() -> {
                    progress.setProgress(done);
                    setStatus("Rendered frame " + done + " of " + frameCount);
                });
            }
        } finally {
            safeRelease(retriever);
        }
'@

$NewExportLoop = @'
        MediaMetadataRetriever retriever = new MediaMetadataRetriever();
        retriever.setDataSource(this, videoUri);
        int outputIndex = 0;
        int totalOutputFrames = outputFrameCount();
        runOnUiThread(() -> progress.setMax(totalOutputFrames));
        try {
            for (int outputFrame = 0; outputFrame < totalOutputFrames; outputFrame++) {
                int sourceFrame = sourceFrameForOutput(outputFrame);
                Bitmap source = frameAt(retriever, sourceFrame);
                Bitmap out = source;
                Uri replacement = replacements.get(key(outputFrame));
                if (replacement != null) {
                    out = loadBitmap(replacement, videoWidth, videoHeight);
                    if (colorBlendCheck.isChecked()) {
                        Bitmap previous = frameAt(retriever, sourceFrameForOutput(Math.max(0, outputFrame - 1)));
                        Bitmap next = frameAt(retriever, sourceFrameForOutput(Math.min(totalOutputFrames - 1, outputFrame + 1)));
                        out = colorBlend(
                                out,
                                previous,
                                next,
                                colorBlendSeek.getProgress() / 100.0,
                                frequencyBlendSeek.getProgress() / 100.0);
                    }
                }
                File frameFile = new File(framesDir, String.format(Locale.US, "frame_%08d.png", outputIndex++));
                writePng(out, frameFile);
                int done = outputFrame + 1;
                if (done % 10 == 0 || done == totalOutputFrames) {
                    runOnUiThread(() -> {
                        progress.setProgress(done);
                        setStatus("Rendered output frame " + done + " of " + totalOutputFrames);
                    });
                }
            }
        } finally {
            safeRelease(retriever);
        }
'@

$Text = Replace-Once $Text $OldExportLoop $NewExportLoop "output-frame export loop"

$Text = Replace-Once $Text "        progress.setMax(frameCount);" "        progress.setMax(outputFrameCount());" "export progress max"

$InsertBefore = @'
    private static class FloatArray {
'@

$HelperClasses = @'
    private static class TextOverlay {
        String text = "Text";
        float x;
        float y;
        int size = 64;
        int rotation = 0;
        int opacity = 100;
        int camouflage = 0;
        boolean border = false;
    }

    private static class SimpleSeekListener implements SeekBar.OnSeekBarChangeListener {
        private final Runnable callback;
        SimpleSeekListener(Runnable callback) {
            this.callback = callback;
        }
        @Override public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
            callback.run();
        }
        @Override public void onStartTrackingTouch(SeekBar seekBar) {}
        @Override public void onStopTrackingTouch(SeekBar seekBar) {}
    }

'@

$Text = Replace-Once $Text $InsertBefore ($HelperClasses + $InsertBefore) "editor helper classes"

Set-Content -LiteralPath $MainPath -Value $Text -NoNewline

$Repaired = Get-Content -LiteralPath $MainPath -Raw
foreach ($Needle in @(
    "PICK_REPEAT_REPLACEMENT",
    "Edit Image/Text",
    "Replace Every X",
    "showImageEditorDialog",
    "removeBackgroundAt",
    "autoRemoveBackground",
    "fitBitmapToFrame",
    "sourceFrameForOutput(Math.max(0, outputFrame - 1))",
    "TextOverlay",
    "SimpleSeekListener"
)) {
    if ($Repaired.IndexOf($Needle, [StringComparison]::Ordinal) -lt 0) {
        throw "Verification failed. Missing repaired text: $Needle"
    }
}

Write-Host "Android editor feature repair complete."
Write-Host "Backup written under $BackupDir with stamp $Stamp."
