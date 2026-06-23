package com.sslogic.videoframeswapper;

import android.app.Activity;
import android.content.Intent;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.ImageDecoder;
import android.media.MediaMetadataRetriever;
import android.net.Uri;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.GridLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.TextView;

import androidx.documentfile.provider.DocumentFile;

import com.arthenica.ffmpegkit.FFmpegKit;
import com.arthenica.ffmpegkit.ReturnCode;
import com.arthenica.ffmpegkit.Session;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

public class MainActivity extends Activity {
    private static final int PICK_VIDEO = 10;
    private static final int PICK_MUSIC = 11;
    private static final int PICK_REPLACEMENT = 12;
    private static final int PICK_OUTPUT_TREE = 13;
    private static final int SLOT_COUNT = 4;
    private static final int ANALYSIS_SAMPLE_RATE = 22050;
    private static final int ANALYSIS_SECONDS = 90;
    private static final String[] KEY_NAMES = {"C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"};
    private static final double[] MAJOR_PROFILE = {6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88};
    private static final double[] MINOR_PROFILE = {6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17};

    private Uri videoUri;
    private Uri musicUri;
    private Uri outputTreeUri;
    private final Map<String, Uri> replacements = new HashMap<>();
    private final ImageView[] slotViews = new ImageView[SLOT_COUNT];
    private final Button[] slotButtons = new Button[SLOT_COUNT];
    private TextView status;
    private TextView info;
    private SeekBar frameSeek;
    private ProgressBar progress;
    private EditText outputName;
    private CheckBox keyMatchCheck;
    private CheckBox colorBlendCheck;
    private SeekBar musicVolumeSeek;
    private SeekBar colorBlendSeek;
    private int currentFrame = 0;
    private int selectedSlot = 0;
    private int frameCount = 1;
    private double fps = 30.0;
    private long durationMs = 0;
    private int videoWidth = 1280;
    private int videoHeight = 720;
    private boolean exporting = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(buildUi());
        refreshUi();
    }

    private View buildUi() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(24, 24, 24, 24);
        scroll.addView(root);

        TextView title = new TextView(this);
        title.setText("Video Frame Swapper");
        title.setTextSize(24);
        title.setTextColor(Color.BLACK);
        title.setGravity(Gravity.CENTER_VERTICAL);
        root.addView(title, matchWrap());

        LinearLayout top = row();
        Button pickVideo = button("Open Video");
        pickVideo.setOnClickListener(v -> pick(PICK_VIDEO, "video/*"));
        Button pickMusic = button("Add Music");
        pickMusic.setOnClickListener(v -> pick(PICK_MUSIC, "*/*"));
        Button pickFolder = button("Save Folder");
        pickFolder.setOnClickListener(v -> chooseOutputTree());
        top.addView(pickVideo, weight());
        top.addView(pickMusic, weight());
        top.addView(pickFolder, weight());
        root.addView(top);

        GridLayout grid = new GridLayout(this);
        grid.setColumnCount(2);
        grid.setPadding(0, 20, 0, 12);
        for (int i = 0; i < SLOT_COUNT; i++) {
            final int slot = i;
            ImageView view = new ImageView(this);
            view.setBackgroundColor(Color.rgb(24, 24, 24));
            view.setScaleType(ImageView.ScaleType.FIT_CENTER);
            view.setAdjustViewBounds(true);
            view.setMinimumHeight(360);
            view.setPadding(6, 6, 6, 6);
            view.setOnClickListener(v -> selectSlot(slot));
            slotViews[i] = view;
            GridLayout.LayoutParams params = new GridLayout.LayoutParams(GridLayout.spec(i / 2), GridLayout.spec(i % 2));
            params.width = getResources().getDisplayMetrics().widthPixels / 2 - 36;
            params.height = Math.max(260, params.width * 9 / 16);
            params.setMargins(4, 4, 4, 4);
            grid.addView(view, params);
        }
        root.addView(grid, matchWrap());

        LinearLayout slots = row();
        for (int i = 0; i < SLOT_COUNT; i++) {
            final int slot = i;
            Button slotButton = button("Slot " + (i + 1));
            slotButton.setOnClickListener(v -> selectSlot(slot));
            slotButtons[i] = slotButton;
            slots.addView(slotButton, weight());
        }
        root.addView(slots);

        LinearLayout editRow = row();
        Button replace = button("Replace Selected Slot");
        replace.setOnClickListener(v -> pick(PICK_REPLACEMENT, "image/*"));
        Button clear = button("Clear Slot");
        clear.setOnClickListener(v -> {
            replacements.remove(key(currentFrame, selectedSlot));
            refreshPreview();
        });
        editRow.addView(replace, weight());
        editRow.addView(clear, weight());
        root.addView(editRow);

        TextView frameLabel = label("Frame");
        root.addView(frameLabel);
        frameSeek = new SeekBar(this);
        frameSeek.setMax(0);
        frameSeek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar seekBar, int progressValue, boolean fromUser) {
                if (fromUser) {
                    currentFrame = progressValue;
                    refreshPreview();
                }
            }
            @Override public void onStartTrackingTouch(SeekBar seekBar) {}
            @Override public void onStopTrackingTouch(SeekBar seekBar) {}
        });
        root.addView(frameSeek, matchWrap());

        TextView musicLabel = label("Music Volume");
        root.addView(musicLabel);
        musicVolumeSeek = new SeekBar(this);
        musicVolumeSeek.setMax(100);
        musicVolumeSeek.setProgress(50);
        root.addView(musicVolumeSeek, matchWrap());

        keyMatchCheck = new CheckBox(this);
        keyMatchCheck.setText("Detect keys and pitch-match added music to original audio at export");
        keyMatchCheck.setChecked(true);
        root.addView(keyMatchCheck, matchWrap());

        colorBlendCheck = new CheckBox(this);
        colorBlendCheck.setText("Color blend replacement images using previous and next frames");
        colorBlendCheck.setChecked(true);
        root.addView(colorBlendCheck, matchWrap());

        TextView blendLabel = label("Color Blend Strength");
        root.addView(blendLabel);
        colorBlendSeek = new SeekBar(this);
        colorBlendSeek.setMax(100);
        colorBlendSeek.setProgress(65);
        root.addView(colorBlendSeek, matchWrap());

        outputName = new EditText(this);
        outputName.setHint("output_quad.mp4");
        outputName.setSingleLine(true);
        root.addView(outputName, matchWrap());

        Button export = button("Export To Chosen Folder");
        export.setOnClickListener(v -> exportVideo());
        root.addView(export, matchWrap());

        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(1);
        root.addView(progress, matchWrap());

        status = label("");
        root.addView(status, matchWrap());
        info = label("");
        root.addView(info, matchWrap());
        return scroll;
    }

    private LinearLayout row() {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setPadding(0, 10, 0, 10);
        return row;
    }

    private Button button(String text) {
        Button button = new Button(this);
        button.setText(text);
        return button;
    }

    private TextView label(String text) {
        TextView textView = new TextView(this);
        textView.setText(text);
        textView.setTextSize(15);
        textView.setTextColor(Color.rgb(35, 35, 35));
        textView.setPadding(0, 8, 0, 8);
        return textView;
    }

    private LinearLayout.LayoutParams weight() {
        return new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private void pick(int request, String mimeType) {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType(mimeType);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(intent, request);
    }

    private void chooseOutputTree() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(intent, PICK_OUTPUT_TREE);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null || data.getData() == null) {
            return;
        }
        Uri uri = data.getData();
        int flags = data.getFlags() & (Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        try {
            getContentResolver().takePersistableUriPermission(uri, flags);
        } catch (Exception ignored) {
        }

        if (requestCode == PICK_VIDEO) {
            videoUri = uri;
            replacements.clear();
            loadVideoMetadata();
            currentFrame = 0;
            selectedSlot = 0;
        } else if (requestCode == PICK_MUSIC) {
            musicUri = uri;
        } else if (requestCode == PICK_REPLACEMENT) {
            replacements.put(key(currentFrame, selectedSlot), uri);
        } else if (requestCode == PICK_OUTPUT_TREE) {
            outputTreeUri = uri;
        }
        refreshUi();
    }

    private void loadVideoMetadata() {
        MediaMetadataRetriever retriever = new MediaMetadataRetriever();
        try {
            retriever.setDataSource(this, videoUri);
            durationMs = parseLong(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION), 0);
            String fpsText = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_CAPTURE_FRAMERATE);
            fps = fpsText == null ? 30.0 : Math.max(1.0, Double.parseDouble(fpsText));
            frameCount = (int) parseLong(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_FRAME_COUNT), 0);
            if (frameCount <= 0) {
                frameCount = Math.max(1, (int) Math.round(durationMs / 1000.0 * fps));
            }
            videoWidth = (int) parseLong(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH), 1280);
            videoHeight = (int) parseLong(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT), 720);
            frameSeek.setMax(Math.max(0, frameCount - 1));
        } catch (Exception exc) {
            setStatus("Could not read video metadata: " + exc.getMessage());
        } finally {
            safeRelease(retriever);
        }
    }

    private long parseLong(String value, long fallback) {
        try {
            return value == null ? fallback : Long.parseLong(value);
        } catch (Exception ignored) {
            return fallback;
        }
    }

    private void refreshUi() {
        refreshPreview();
        String videoName = videoUri == null ? "none" : displayName(videoUri);
        String musicName = musicUri == null ? "none" : displayName(musicUri);
        String folder = outputTreeUri == null ? "none" : "chosen";
        info.setText(String.format(Locale.US,
                "Video: %s\nMusic: %s\nSave folder: %s\nFrame: %d / %d\nSelected slot: %d\nFPS: %.3f -> %.3f\nReplaced slots: %d",
                videoName, musicName, folder, currentFrame, frameCount, selectedSlot + 1, fps, fps * SLOT_COUNT, replacements.size()));
    }

    private void refreshPreview() {
        if (videoUri == null) {
            for (int i = 0; i < SLOT_COUNT; i++) {
                slotViews[i].setImageBitmap(null);
                slotViews[i].setBackgroundColor(i == selectedSlot ? Color.rgb(37, 99, 235) : Color.rgb(24, 24, 24));
            }
            return;
        }
        MediaMetadataRetriever retriever = new MediaMetadataRetriever();
        try {
            retriever.setDataSource(this, videoUri);
            Bitmap source = frameAt(retriever, currentFrame);
            Bitmap previous = frameAt(retriever, Math.max(0, currentFrame - 1));
            Bitmap next = frameAt(retriever, Math.min(frameCount - 1, currentFrame + 1));
            for (int i = 0; i < SLOT_COUNT; i++) {
                Bitmap preview = source;
                Uri replacement = replacements.get(key(currentFrame, i));
                if (replacement != null) {
                    preview = loadBitmap(replacement, videoWidth, videoHeight);
                    if (colorBlendCheck != null && colorBlendCheck.isChecked()) {
                        preview = colorBlend(preview, previous, next, colorBlendSeek.getProgress() / 100.0);
                    }
                }
                slotViews[i].setImageBitmap(preview);
                slotViews[i].setBackgroundColor(i == selectedSlot ? Color.rgb(37, 99, 235) : Color.rgb(24, 24, 24));
                slotButtons[i].setEnabled(true);
            }
        } catch (Exception exc) {
            setStatus("Preview failed: " + exc.getMessage());
        } finally {
            safeRelease(retriever);
        }
    }

    private Bitmap frameAt(MediaMetadataRetriever retriever, int frame) {
        long timeUs = Math.max(0, Math.round(frame * 1_000_000.0 / fps));
        Bitmap bitmap = retriever.getFrameAtTime(timeUs, MediaMetadataRetriever.OPTION_CLOSEST);
        if (bitmap == null) {
            bitmap = Bitmap.createBitmap(videoWidth, videoHeight, Bitmap.Config.ARGB_8888);
            bitmap.eraseColor(Color.BLACK);
        }
        return Bitmap.createScaledBitmap(bitmap, videoWidth, videoHeight, true);
    }

    private Bitmap loadBitmap(Uri uri, int width, int height) throws IOException {
        ImageDecoder.Source source = ImageDecoder.createSource(getContentResolver(), uri);
        Bitmap bitmap = ImageDecoder.decodeBitmap(source, (decoder, info, src) -> decoder.setAllocator(ImageDecoder.ALLOCATOR_SOFTWARE));
        return Bitmap.createScaledBitmap(bitmap, width, height, true);
    }

    private void selectSlot(int slot) {
        selectedSlot = slot;
        refreshUi();
    }

    private String key(int frame, int slot) {
        return frame + ":" + slot;
    }

    private void exportVideo() {
        if (exporting) {
            return;
        }
        if (videoUri == null || outputTreeUri == null) {
            setStatus("Choose a video and a save folder first.");
            return;
        }
        exporting = true;
        progress.setMax(frameCount);
        progress.setProgress(0);
        setStatus("Export started...");
        new Thread(() -> {
            try {
                File exportFile = renderAndEncode();
                writeToChosenFolder(exportFile);
                runOnUiThread(() -> setStatus("Export saved to chosen folder."));
            } catch (Exception exc) {
                runOnUiThread(() -> setStatus("Export failed: " + exc.getMessage()));
            } finally {
                exporting = false;
            }
        }).start();
    }

    private File renderAndEncode() throws Exception {
        File work = new File(getCacheDir(), "android_quad_export");
        deleteTree(work);
        File framesDir = new File(work, "frames");
        if (!framesDir.mkdirs()) {
            throw new IOException("Could not create export cache.");
        }

        File sourceFile = copyUri(videoUri, new File(work, "source" + extensionFor(videoUri, ".mp4")));
        File musicFile = musicUri == null ? null : copyUri(musicUri, new File(work, "music" + extensionFor(musicUri, ".m4a")));

        MediaMetadataRetriever retriever = new MediaMetadataRetriever();
        retriever.setDataSource(this, videoUri);
        int outputIndex = 0;
        try {
            for (int frame = 0; frame < frameCount; frame++) {
                Bitmap source = frameAt(retriever, frame);
                Bitmap previous = frameAt(retriever, Math.max(0, frame - 1));
                Bitmap next = frameAt(retriever, Math.min(frameCount - 1, frame + 1));
                for (int slot = 0; slot < SLOT_COUNT; slot++) {
                    Bitmap out = source;
                    Uri replacement = replacements.get(key(frame, slot));
                    if (replacement != null) {
                        out = loadBitmap(replacement, videoWidth, videoHeight);
                        if (colorBlendCheck.isChecked()) {
                            out = colorBlend(out, previous, next, colorBlendSeek.getProgress() / 100.0);
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

        File encoded = new File(work, "export.mp4");
        String command = buildEncodeCommand(framesDir, sourceFile, musicFile, encoded);
        Session session = FFmpegKit.execute(command);
        if (!ReturnCode.isSuccess(session.getReturnCode())) {
            throw new RuntimeException("FFmpeg failed: " + session.getFailStackTrace());
        }
        return encoded;
    }

    private String buildEncodeCommand(File framesDir, File sourceFile, File musicFile, File outputFile) throws Exception {
        double exportFps = fps * SLOT_COUNT;
        String framePattern = new File(framesDir, "frame_%08d.png").getAbsolutePath();
        String duration = String.format(Locale.US, "%.6f", frameCount / fps);
        String video = "-y -framerate " + q(String.format(Locale.US, "%.6f", exportFps))
                + " -i " + q(framePattern);

        if (musicFile == null) {
            return video + " -i " + q(sourceFile.getAbsolutePath())
                    + " -map 0:v:0 -map 1:a? -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "
                    + q(outputFile.getAbsolutePath());
        }

        boolean hasAudio = sourceHasAudio(sourceFile);
        double volume = musicVolumeSeek.getProgress() / 100.0;
        int semitoneShift = 0;
        String statusText = "Music mix: " + Math.round(volume * 100) + "%";
        if (keyMatchCheck.isChecked() && hasAudio) {
            KeyResult sourceKey = analyzeKey(sourceFile);
            KeyResult musicKey = analyzeKey(musicFile);
            semitoneShift = shortestShift(musicKey.pitchClass, sourceKey.pitchClass);
            statusText = String.format(Locale.US, "Key match: music %s -> video %s (%+d semitones), music %.0f%%",
                    musicKey.label(), sourceKey.label(), semitoneShift, volume * 100.0);
        }
        String finalStatusText = statusText;
        runOnUiThread(() -> setStatus(finalStatusText));

        String musicFilter = pitchFilter(semitoneShift) + "volume=" + String.format(Locale.US, "%.3f", volume)
                + ",highpass=f=80,lowpass=f=12000,acompressor=threshold=0.25:ratio=2.5:attack=20:release=250";

        if (hasAudio) {
            return video + " -i " + q(sourceFile.getAbsolutePath()) + " -stream_loop -1 -i " + q(musicFile.getAbsolutePath())
                    + " -filter_complex " + q("[1:a:0]volume=1.0[maina];[2:a:0]" + musicFilter
                    + "[musica];[maina][musica]amix=inputs=2:duration=first:dropout_transition=0,alimiter=limit=0.95[aout]")
                    + " -map 0:v:0 -map [aout] -c:v libx264 -pix_fmt yuv420p -c:a aac -t "
                    + q(duration) + " " + q(outputFile.getAbsolutePath());
        }

        return video + " -stream_loop -1 -i " + q(musicFile.getAbsolutePath())
                + " -filter_complex " + q("[1:a:0]" + musicFilter + ",alimiter=limit=0.95[aout]")
                + " -map 0:v:0 -map [aout] -c:v libx264 -pix_fmt yuv420p -c:a aac -t "
                + q(duration) + " " + q(outputFile.getAbsolutePath());
    }

    private String pitchFilter(int semitones) {
        if (semitones == 0) {
            return "aresample=44100,";
        }
        double factor = Math.pow(2.0, semitones / 12.0);
        double tempo = 1.0 / factor;
        return String.format(Locale.US, "aresample=44100,asetrate=44100*%.8f,aresample=44100,atempo=%.8f,", factor, tempo);
    }

    private boolean sourceHasAudio(File sourceFile) {
        MediaMetadataRetriever retriever = new MediaMetadataRetriever();
        try {
            retriever.setDataSource(sourceFile.getAbsolutePath());
            return retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_AUDIO) != null;
        } catch (Exception ignored) {
            return true;
        } finally {
            safeRelease(retriever);
        }
    }

    private void safeRelease(MediaMetadataRetriever retriever) {
        try {
            retriever.release();
        } catch (Exception ignored) {
        }
    }

    private KeyResult analyzeKey(File mediaFile) throws Exception {
        File pcm = new File(getCacheDir(), "key_" + Math.abs(mediaFile.getAbsolutePath().hashCode()) + ".f32");
        String decode = "-y -i " + q(mediaFile.getAbsolutePath()) + " -vn -ac 1 -ar " + ANALYSIS_SAMPLE_RATE
                + " -t " + ANALYSIS_SECONDS + " -f f32le " + q(pcm.getAbsolutePath());
        Session decodeSession = FFmpegKit.execute(decode);
        if (!ReturnCode.isSuccess(decodeSession.getReturnCode())) {
            throw new RuntimeException("Could not decode audio for key detection.");
        }
        byte[] bytes = readAllBytes(pcm);
        FloatArray audio = new FloatArray(bytes.length / 4);
        ByteBuffer buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
        for (int i = 0; i < audio.size; i++) {
            audio.data[i] = buffer.getFloat();
        }
        pcm.delete();
        return scoreKey(audio);
    }

    private KeyResult scoreKey(FloatArray audio) {
        int window = 4096;
        int hop = 2048;
        double[] chroma = new double[12];
        for (int start = 0; start + window < audio.size; start += hop) {
            for (int midi = 33; midi <= 96; midi++) {
                double freq = 440.0 * Math.pow(2.0, (midi - 69) / 12.0);
                double energy = goertzel(audio.data, start, window, freq, ANALYSIS_SAMPLE_RATE);
                chroma[midi % 12] += Math.log1p(energy);
            }
        }
        normalize(chroma);
        double best = -1;
        double second = -1;
        int bestPc = 0;
        boolean bestMajor = true;
        for (int pc = 0; pc < 12; pc++) {
            double maj = dotRotated(chroma, MAJOR_PROFILE, pc);
            double min = dotRotated(chroma, MINOR_PROFILE, pc);
            if (maj > best) {
                second = best;
                best = maj;
                bestPc = pc;
                bestMajor = true;
            } else if (maj > second) {
                second = maj;
            }
            if (min > best) {
                second = best;
                best = min;
                bestPc = pc;
                bestMajor = false;
            } else if (min > second) {
                second = min;
            }
        }
        double confidence = Math.max(0.0, Math.min(1.0, (best - second) * 10.0));
        return new KeyResult(bestPc, bestMajor ? "major" : "minor", confidence);
    }

    private double goertzel(float[] samples, int start, int count, double freq, double sampleRate) {
        double normalized = freq / sampleRate;
        double coeff = 2.0 * Math.cos(2.0 * Math.PI * normalized);
        double q0 = 0;
        double q1 = 0;
        double q2 = 0;
        for (int i = 0; i < count; i++) {
            double window = 0.5 - 0.5 * Math.cos(2.0 * Math.PI * i / (count - 1));
            q0 = coeff * q1 - q2 + samples[start + i] * window;
            q2 = q1;
            q1 = q0;
        }
        return q1 * q1 + q2 * q2 - coeff * q1 * q2;
    }

    private double dotRotated(double[] chroma, double[] profile, int rotation) {
        double[] copy = profile.clone();
        normalize(copy);
        double value = 0;
        for (int i = 0; i < 12; i++) {
            value += chroma[i] * copy[(i - rotation + 12) % 12];
        }
        return value;
    }

    private void normalize(double[] values) {
        double sum = 0;
        for (double value : values) {
            sum += value * value;
        }
        double norm = Math.sqrt(sum);
        if (norm <= 0.000001) {
            return;
        }
        for (int i = 0; i < values.length; i++) {
            values[i] /= norm;
        }
    }

    private int shortestShift(int sourcePc, int targetPc) {
        int shift = (targetPc - sourcePc) % 12;
        if (shift > 6) {
            shift -= 12;
        }
        if (shift < -6) {
            shift += 12;
        }
        return shift;
    }

    private Bitmap colorBlend(Bitmap replacement, Bitmap previous, Bitmap next, double strength) {
        Bitmap repl = replacement.copy(Bitmap.Config.ARGB_8888, true);
        Bitmap prev = Bitmap.createScaledBitmap(previous, repl.getWidth(), repl.getHeight(), true);
        Bitmap nxt = Bitmap.createScaledBitmap(next, repl.getWidth(), repl.getHeight(), true);
        int width = repl.getWidth();
        int height = repl.getHeight();
        int[] rp = new int[width * height];
        int[] pp = new int[width * height];
        int[] np = new int[width * height];
        repl.getPixels(rp, 0, width, 0, 0, width, height);
        prev.getPixels(pp, 0, width, 0, 0, width, height);
        nxt.getPixels(np, 0, width, 0, 0, width, height);

        double[] rm = mean(rp);
        double[] rs = std(rp, rm);
        double[] cm = contextMean(pp, np);
        double[] cs = contextStd(pp, np, cm);
        double edgeMix = Math.min(0.35, strength * 0.5);
        for (int i = 0; i < rp.length; i++) {
            int r = Color.red(rp[i]);
            int g = Color.green(rp[i]);
            int b = Color.blue(rp[i]);
            int cr = (Color.red(pp[i]) + Color.red(np[i])) / 2;
            int cg = (Color.green(pp[i]) + Color.green(np[i])) / 2;
            int cb = (Color.blue(pp[i]) + Color.blue(np[i])) / 2;
            int nr = channelBlend(r, cr, rm[0], rs[0], cm[0], cs[0], strength, edgeMix);
            int ng = channelBlend(g, cg, rm[1], rs[1], cm[1], cs[1], strength, edgeMix);
            int nb = channelBlend(b, cb, rm[2], rs[2], cm[2], cs[2], strength, edgeMix);
            rp[i] = Color.argb(Color.alpha(rp[i]), nr, ng, nb);
        }
        repl.setPixels(rp, 0, width, 0, 0, width, height);
        return repl;
    }

    private int channelBlend(int src, int context, double srcMean, double srcStd, double ctxMean, double ctxStd, double strength, double edgeMix) {
        double matched = (src - srcMean) * (ctxStd / Math.max(1.0, srcStd)) + ctxMean;
        double colored = src * (1.0 - strength) + matched * strength;
        double blended = colored * (1.0 - edgeMix) + context * edgeMix;
        return (int) Math.max(0, Math.min(255, Math.round(blended)));
    }

    private double[] mean(int[] pixels) {
        double[] mean = new double[3];
        for (int pixel : pixels) {
            mean[0] += Color.red(pixel);
            mean[1] += Color.green(pixel);
            mean[2] += Color.blue(pixel);
        }
        for (int i = 0; i < 3; i++) {
            mean[i] /= pixels.length;
        }
        return mean;
    }

    private double[] std(int[] pixels, double[] mean) {
        double[] std = new double[3];
        for (int pixel : pixels) {
            std[0] += Math.pow(Color.red(pixel) - mean[0], 2);
            std[1] += Math.pow(Color.green(pixel) - mean[1], 2);
            std[2] += Math.pow(Color.blue(pixel) - mean[2], 2);
        }
        for (int i = 0; i < 3; i++) {
            std[i] = Math.sqrt(std[i] / pixels.length);
        }
        return std;
    }

    private double[] contextMean(int[] previous, int[] next) {
        double[] mean = new double[3];
        for (int i = 0; i < previous.length; i++) {
            mean[0] += (Color.red(previous[i]) + Color.red(next[i])) / 2.0;
            mean[1] += (Color.green(previous[i]) + Color.green(next[i])) / 2.0;
            mean[2] += (Color.blue(previous[i]) + Color.blue(next[i])) / 2.0;
        }
        for (int i = 0; i < 3; i++) {
            mean[i] /= previous.length;
        }
        return mean;
    }

    private double[] contextStd(int[] previous, int[] next, double[] mean) {
        double[] std = new double[3];
        for (int i = 0; i < previous.length; i++) {
            double r = (Color.red(previous[i]) + Color.red(next[i])) / 2.0;
            double g = (Color.green(previous[i]) + Color.green(next[i])) / 2.0;
            double b = (Color.blue(previous[i]) + Color.blue(next[i])) / 2.0;
            std[0] += Math.pow(r - mean[0], 2);
            std[1] += Math.pow(g - mean[1], 2);
            std[2] += Math.pow(b - mean[2], 2);
        }
        for (int i = 0; i < 3; i++) {
            std[i] = Math.sqrt(std[i] / previous.length);
        }
        return std;
    }

    private void writePng(Bitmap bitmap, File file) throws IOException {
        try (FileOutputStream out = new FileOutputStream(file)) {
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, out);
        }
    }

    private File copyUri(Uri uri, File target) throws IOException {
        try (InputStream in = getContentResolver().openInputStream(uri);
             OutputStream out = new FileOutputStream(target)) {
            if (in == null) {
                throw new IOException("Could not open " + uri);
            }
            byte[] buffer = new byte[1024 * 1024];
            int read;
            while ((read = in.read(buffer)) >= 0) {
                out.write(buffer, 0, read);
            }
        }
        return target;
    }

    private void writeToChosenFolder(File exportFile) throws IOException {
        DocumentFile folder = DocumentFile.fromTreeUri(this, outputTreeUri);
        if (folder == null || !folder.canWrite()) {
            throw new IOException("Chosen folder is not writable.");
        }
        String name = outputName.getText().toString().trim();
        if (name.isEmpty()) {
            name = "video_frame_swapper_quad.mp4";
        }
        if (!name.toLowerCase(Locale.US).endsWith(".mp4")) {
            name += ".mp4";
        }
        DocumentFile existing = folder.findFile(name);
        if (existing != null) {
            existing.delete();
        }
        DocumentFile output = folder.createFile("video/mp4", name);
        if (output == null) {
            throw new IOException("Could not create output file.");
        }
        try (InputStream in = new FileInputStream(exportFile);
             OutputStream out = getContentResolver().openOutputStream(output.getUri())) {
            if (out == null) {
                throw new IOException("Could not open output stream.");
            }
            byte[] buffer = new byte[1024 * 1024];
            int read;
            while ((read = in.read(buffer)) >= 0) {
                out.write(buffer, 0, read);
            }
        }
    }

    private String displayName(Uri uri) {
        try (Cursor cursor = getContentResolver().query(uri, null, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                int index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (index >= 0) {
                    return cursor.getString(index);
                }
            }
        } catch (Exception ignored) {
        }
        return uri.getLastPathSegment() == null ? "selected" : uri.getLastPathSegment();
    }

    private String extensionFor(Uri uri, String fallback) {
        String name = displayName(uri);
        int dot = name.lastIndexOf('.');
        if (dot >= 0 && dot < name.length() - 1) {
            return name.substring(dot);
        }
        return fallback;
    }

    private byte[] readAllBytes(File file) throws IOException {
        try (FileInputStream in = new FileInputStream(file);
             ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[1024 * 1024];
            int read;
            while ((read = in.read(buffer)) >= 0) {
                out.write(buffer, 0, read);
            }
            return out.toByteArray();
        }
    }

    private String q(String value) {
        return "\"" + value.replace("\"", "\\\"") + "\"";
    }

    private void setStatus(String value) {
        status.setText(value);
    }

    private void deleteTree(File file) {
        if (!file.exists()) {
            return;
        }
        if (file.isDirectory()) {
            File[] children = file.listFiles();
            if (children != null) {
                for (File child : children) {
                    deleteTree(child);
                }
            }
        }
        file.delete();
    }

    private static class FloatArray {
        final float[] data;
        final int size;
        FloatArray(int size) {
            this.size = size;
            this.data = new float[size];
        }
    }

    private static class KeyResult {
        final int pitchClass;
        final String mode;
        final double confidence;
        KeyResult(int pitchClass, String mode, double confidence) {
            this.pitchClass = pitchClass;
            this.mode = mode;
            this.confidence = confidence;
        }
        String label() {
            return String.format(Locale.US, "%s %s %.2f", KEY_NAMES[pitchClass], mode, confidence);
        }
    }
}
