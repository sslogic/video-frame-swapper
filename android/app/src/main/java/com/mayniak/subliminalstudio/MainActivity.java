package com.mayniak.subliminalstudio;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.ImageDecoder;
import android.graphics.Paint;
import android.graphics.RectF;
import android.media.MediaMetadataRetriever;
import android.net.Uri;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.view.Gravity;
import android.view.MotionEvent;
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
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import org.json.JSONArray;
import org.json.JSONObject;

public class MainActivity extends Activity {
    private static final int PICK_VIDEO = 10;
    private static final int PICK_MUSIC = 11;
    private static final int PICK_REPLACEMENT = 12;
    private static final int PICK_OUTPUT_TREE = 13;
    private static final int PICK_REPEAT_REPLACEMENT = 14;
    private static final String PREFS = "video_frame_swapper_project";
    private static final String PREF_PROJECT = "last_project";
    private static final int SLOT_COUNT = 4;
    private static final int ANALYSIS_SAMPLE_RATE = 22050;
    private static final int ANALYSIS_SECONDS = 90;
    private static final String[] KEY_NAMES = {"C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"};
    private static final double[] MAJOR_PROFILE = {6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88};
    private static final double[] MINOR_PROFILE = {6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17};

    private Uri videoUri;
    private Uri musicUri;
    private Uri outputTreeUri;
    private final List<AudioTrack> audioTracks = new ArrayList<>();
    private final Map<String, Uri> replacements = new HashMap<>();
    private ImageView previewView;
    private TextView status;
    private TextView info;
    private SeekBar frameSeek;
    private SeekBar timelineZoomSeek;
    private ProgressBar progress;
    private EditText outputName;
    private CheckBox keyMatchCheck;
    private CheckBox colorBlendCheck;
    private SeekBar sourceVolumeSeek;
    private SeekBar musicVolumeSeek;
    private SeekBar colorBlendSeek;
    private SeekBar frequencyBlendSeek;
    private int currentOutputFrame = 0;
    private int frameCount = 1;
    private double fps = 30.0;
    private long durationMs = 0;
    private int videoWidth = 1280;
    private int videoHeight = 720;
    private boolean exporting = false;
    private int pendingRepeatInterval = 0;
    private boolean reopenAudioEditorAfterPick = false;
    private boolean firstAudioAsMainMask = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(buildUi());
        restoreProject();
        refreshUi();
    }

    private View buildUi() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(24, 24, 24, 24);
        scroll.addView(root);

        TextView title = new TextView(this);
        title.setText("Mayniak Subliminal Multimedia Studio");
        title.setTextSize(24);
        title.setTextColor(Color.BLACK);
        title.setGravity(Gravity.CENTER_VERTICAL);
        root.addView(title, matchWrap());

        LinearLayout top = row();
        Button pickVideo = button("Open Video");
        pickVideo.setOnClickListener(v -> pick(PICK_VIDEO, "video/*"));
        Button pickMusic = button("Audio Editor");
        pickMusic.setOnClickListener(v -> openAudioEditor());
        Button pickFolder = button("Save Folder");
        pickFolder.setOnClickListener(v -> chooseOutputTree());
        top.addView(pickVideo, weight());
        top.addView(pickMusic, weight());
        top.addView(pickFolder, weight());
        root.addView(top);

        previewView = new ImageView(this);
        previewView.setBackgroundColor(Color.rgb(24, 24, 24));
        previewView.setScaleType(ImageView.ScaleType.FIT_CENTER);
        previewView.setAdjustViewBounds(true);
        previewView.setMinimumHeight(520);
        previewView.setPadding(6, 6, 6, 6);
        root.addView(previewView, matchWrap());

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

        TextView frameLabel = label("Output Frame Timeline");
        root.addView(frameLabel);
        frameSeek = new SeekBar(this);
        frameSeek.setMax(0);
        frameSeek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar seekBar, int progressValue, boolean fromUser) {
                if (fromUser) {
                    currentOutputFrame = progressValue;
                    refreshPreview();
                }
            }
            @Override public void onStartTrackingTouch(SeekBar seekBar) {}
            @Override public void onStopTrackingTouch(SeekBar seekBar) {}
        });
        root.addView(frameSeek, matchWrap());

        TextView zoomLabel = label("Timeline Zoom");
        root.addView(zoomLabel);
        timelineZoomSeek = new SeekBar(this);
        timelineZoomSeek.setMax(79);
        timelineZoomSeek.setProgress(0);
        root.addView(timelineZoomSeek, matchWrap());

        sourceVolumeSeek = new SeekBar(this);
        sourceVolumeSeek.setMax(200);
        sourceVolumeSeek.setProgress(100);
        musicVolumeSeek = new SeekBar(this);
        musicVolumeSeek.setMax(200);
        musicVolumeSeek.setProgress(50);

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

        TextView frequencyLabel = label("Image Frequency Blend");
        root.addView(frequencyLabel);
        frequencyBlendSeek = new SeekBar(this);
        frequencyBlendSeek.setMax(100);
        frequencyBlendSeek.setProgress(35);
        root.addView(frequencyBlendSeek, matchWrap());

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
            currentOutputFrame = 0;
        } else if (requestCode == PICK_MUSIC) {
            addAudioTrack(uri);
        } else if (requestCode == PICK_REPLACEMENT) {
            replacements.put(key(currentOutputFrame), uri);
        } else if (requestCode == PICK_REPEAT_REPLACEMENT) {
            applyRepeatedReplacement(uri);
        } else if (requestCode == PICK_OUTPUT_TREE) {
            outputTreeUri = uri;
        }
        saveProject();
        refreshUi();
        if (requestCode == PICK_MUSIC && reopenAudioEditorAfterPick) {
            reopenAudioEditorAfterPick = false;
            runOnUiThread(this::openAudioEditor);
        }
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
            frameSeek.setMax(Math.max(0, outputFrameCount() - 1));
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
        String musicName = audioTrackSummary();
        String folder = outputTreeUri == null ? "none" : "chosen";
        info.setText(String.format(Locale.US,
                "Video: %s\nAudio tracks: %s\nSave folder: %s\nOutput frame: %d / %d\nSource frame: %d / %d\nFPS: %.3f -> %.3f\nSwapped frames: %d",
                videoName, musicName, folder, currentOutputFrame, outputFrameCount() - 1,
                sourceFrameForOutput(currentOutputFrame), frameCount - 1, fps, fps * SLOT_COUNT, replacements.size()));
    }

    private void refreshPreview() {
        if (videoUri == null) {
            previewView.setImageBitmap(null);
            previewView.setBackgroundColor(Color.rgb(24, 24, 24));
            return;
        }
        MediaMetadataRetriever retriever = new MediaMetadataRetriever();
        try {
            retriever.setDataSource(this, videoUri);
            int sourceFrame = sourceFrameForOutput(currentOutputFrame);
            Bitmap preview = frameAt(retriever, sourceFrame);
            Bitmap previous = frameAt(retriever, Math.max(0, sourceFrame - 1));
            Bitmap next = frameAt(retriever, Math.min(frameCount - 1, sourceFrame + 1));
            Uri replacement = replacements.get(key(currentOutputFrame));
            if (replacement != null) {
                preview = loadBitmap(replacement, videoWidth, videoHeight);
                if (colorBlendCheck != null && colorBlendCheck.isChecked()) {
                    preview = colorBlend(
                            preview,
                            previous,
                            next,
                            colorBlendSeek.getProgress() / 100.0,
                            frequencyBlendSeek.getProgress() / 100.0);
                }
            }
            previewView.setImageBitmap(preview);
            frameSeek.setProgress(currentOutputFrame);
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

    private void saveProject() {
        try {
            JSONObject root = new JSONObject();
            if (videoUri != null) {
                root.put("videoUri", videoUri.toString());
            }
            JSONArray tracks = new JSONArray();
            for (AudioTrack track : audioTracks) {
                tracks.put(track.toJson());
            }
            root.put("audioTracks", tracks);
            if (outputTreeUri != null) {
                root.put("outputTreeUri", outputTreeUri.toString());
            }
            root.put("currentOutputFrame", currentOutputFrame);
            root.put("sourceVolume", sourceVolumeSeek.getProgress());
            root.put("musicVolume", musicVolumeSeek.getProgress());
            root.put("keyMatch", keyMatchCheck.isChecked());
            root.put("firstAudioAsMainMask", firstAudioAsMainMask);
            root.put("colorBlend", colorBlendCheck.isChecked());
            root.put("colorBlendStrength", colorBlendSeek.getProgress());
            root.put("frequencyBlendStrength", frequencyBlendSeek.getProgress());
            JSONObject edits = new JSONObject();
            for (Map.Entry<String, Uri> entry : replacements.entrySet()) {
                edits.put(entry.getKey(), entry.getValue().toString());
            }
            root.put("replacements", edits);
            getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(PREF_PROJECT, root.toString()).apply();
        } catch (Exception exc) {
            setStatus("Project save failed: " + exc.getMessage());
        }
    }

    private void restoreProject() {
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        String raw = prefs.getString(PREF_PROJECT, null);
        if (raw == null) {
            return;
        }
        try {
            JSONObject root = new JSONObject(raw);
            if (root.has("videoUri")) {
                videoUri = Uri.parse(root.getString("videoUri"));
                loadVideoMetadata();
            }
            audioTracks.clear();
            JSONArray tracks = root.optJSONArray("audioTracks");
            if (tracks != null) {
                for (int i = 0; i < tracks.length(); i++) {
                    audioTracks.add(AudioTrack.fromJson(tracks.getJSONObject(i)));
                }
            } else if (root.has("musicUri")) {
                Uri legacyMusic = Uri.parse(root.getString("musicUri"));
                AudioTrack legacyTrack = createAudioTrack(legacyMusic);
                legacyTrack.volume = root.optInt("musicVolume", 50);
                audioTracks.add(legacyTrack);
            }
            if (root.has("outputTreeUri")) {
                outputTreeUri = Uri.parse(root.getString("outputTreeUri"));
            }
            currentOutputFrame = Math.max(0, Math.min(outputFrameCount() - 1, root.optInt("currentOutputFrame", 0)));
            sourceVolumeSeek.setProgress(root.optInt("sourceVolume", 100));
            musicVolumeSeek.setProgress(root.optInt("musicVolume", 50));
            keyMatchCheck.setChecked(root.optBoolean("keyMatch", true));
            firstAudioAsMainMask = root.optBoolean("firstAudioAsMainMask", false);
            colorBlendCheck.setChecked(root.optBoolean("colorBlend", true));
            colorBlendSeek.setProgress(root.optInt("colorBlendStrength", 65));
            frequencyBlendSeek.setProgress(root.optInt("frequencyBlendStrength", 35));
            replacements.clear();
            JSONObject edits = root.optJSONObject("replacements");
            if (edits != null) {
                java.util.Iterator<String> keys = edits.keys();
                while (keys.hasNext()) {
                    String key = keys.next();
                    replacements.put(key, Uri.parse(edits.getString(key)));
                }
            }
            setStatus("Restored last project.");
        } catch (Exception exc) {
            setStatus("Project restore failed: " + exc.getMessage());
        }
    }

    private void addAudioTrack(Uri uri) {
        AudioTrack track = createAudioTrack(uri);
        audioTracks.add(track);
        musicUri = uri;
        setStatus("Added audio track: " + track.name);
    }

    private AudioTrack createAudioTrack(Uri uri) {
        AudioTrack track = new AudioTrack();
        track.uri = uri;
        track.name = displayName(uri);
        track.durationMs = mediaDurationMs(uri);
        track.volume = Math.max(1, musicVolumeSeek == null ? 50 : musicVolumeSeek.getProgress());
        track.repeat = true;
        track.repeatEveryMs = 0;
        track.repeatCount = 0;
        track.speedPercent = 100;
        track.masking = true;
        track.duckBelowMain = true;
        return track;
    }

    private void openAudioEditor() {
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(18, 12, 18, 0);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(content);

        TextView mainLabel = label("Main track audio volume");
        content.addView(mainLabel);
        SeekBar mainVolume = seek(content, "Main Volume", 0, 200, sourceVolumeSeek.getProgress());
        mainVolume.setOnSeekBarChangeListener(new SimpleSeekListener(() -> {
            sourceVolumeSeek.setProgress(seekValue(mainVolume));
            saveProject();
        }));

        CheckBox keyMatch = new CheckBox(this);
        keyMatch.setText("Key-match added tracks to main audio at export");
        keyMatch.setChecked(keyMatchCheck.isChecked());
        keyMatch.setOnClickListener(v -> {
            keyMatchCheck.setChecked(keyMatch.isChecked());
            saveProject();
        });
        content.addView(keyMatch, matchWrap());

        CheckBox firstMask = new CheckBox(this);
        firstMask.setText("If movie has no audio, use first added track as main masking track");
        firstMask.setChecked(firstAudioAsMainMask);
        firstMask.setOnClickListener(v -> {
            firstAudioAsMainMask = firstMask.isChecked();
            saveProject();
        });
        content.addView(firstMask, matchWrap());

        Button addTrack = button("Add Audio Track");
        addTrack.setOnClickListener(v -> {
            reopenAudioEditorAfterPick = true;
            pick(PICK_MUSIC, "audio/*");
        });
        content.addView(addTrack, matchWrap());

        if (audioTracks.isEmpty()) {
            TextView empty = label("No added audio tracks yet.");
            content.addView(empty, matchWrap());
        } else {
            for (int i = 0; i < audioTracks.size(); i++) {
                AudioTrack track = audioTracks.get(i);
                TextView trackInfo = label(trackSummary(i, track));
                content.addView(trackInfo, matchWrap());
                LinearLayout actions = row();
                Button edit = button("Edit");
                final int index = i;
                edit.setOnClickListener(v -> openAudioTrackSettings(index));
                Button remove = button("Remove");
                remove.setOnClickListener(v -> {
                    if (index >= 0 && index < audioTracks.size()) {
                        audioTracks.remove(index);
                        saveProject();
                        refreshUi();
                        openAudioEditor();
                    }
                });
                actions.addView(edit, weight());
                actions.addView(remove, weight());
                content.addView(actions);
            }
        }

        new AlertDialog.Builder(this)
                .setTitle("Audio Editor")
                .setView(scroll)
                .setNegativeButton("Close", (dialog, which) -> {
                    sourceVolumeSeek.setProgress(seekValue(mainVolume));
                    keyMatchCheck.setChecked(keyMatch.isChecked());
                    firstAudioAsMainMask = firstMask.isChecked();
                    saveProject();
                    refreshUi();
                })
                .show();
    }

    private void openAudioTrackSettings(int index) {
        if (index < 0 || index >= audioTracks.size()) {
            return;
        }
        AudioTrack track = audioTracks.get(index);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(18, 12, 18, 0);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(layout);

        layout.addView(label(track.name + "\nLength: " + formatTime(track.durationMs)), matchWrap());
        SeekBar volume = seek(layout, "Track Volume", 0, 200, track.volume);
        EditText start = numberInput("Start time in movie seconds", millisToSecondsText(track.startMs));
        layout.addView(start, matchWrap());
        CheckBox repeat = new CheckBox(this);
        repeat.setText("Repeat this track");
        repeat.setChecked(track.repeat);
        layout.addView(repeat, matchWrap());
        EditText repeatEvery = numberInput("Repeat every seconds (0 = track length after speed)", millisToSecondsText(track.repeatEveryMs));
        layout.addView(repeatEvery, matchWrap());
        EditText repeatCount = numberInput("Repeat count (0 = until movie ends)", String.valueOf(track.repeatCount));
        layout.addView(repeatCount, matchWrap());
        SeekBar speed = seek(layout, "Track Speed", 20, 500, track.speedPercent);
        TextView speedInfo = label(String.format(Locale.US, "Speed: %.2fx", track.speedPercent / 100.0));
        layout.addView(speedInfo, matchWrap());
        speed.setOnSeekBarChangeListener(new SimpleSeekListener(() ->
                speedInfo.setText(String.format(Locale.US, "Speed: %.2fx", seekValue(speed) / 100.0))));
        CheckBox masking = new CheckBox(this);
        masking.setText("Track masking: compress peaks and limit loud spikes");
        masking.setChecked(track.masking);
        layout.addView(masking, matchWrap());
        CheckBox duck = new CheckBox(this);
        duck.setText("Keep this track dynamically below the main track");
        duck.setChecked(track.duckBelowMain);
        layout.addView(duck, matchWrap());

        new AlertDialog.Builder(this)
                .setTitle("Audio Track")
                .setView(scroll)
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Apply", (dialog, which) -> {
                    track.volume = seekValue(volume);
                    track.startMs = secondsTextToMillis(start.getText().toString(), 0);
                    track.repeat = repeat.isChecked();
                    track.repeatEveryMs = secondsTextToMillis(repeatEvery.getText().toString(), 0);
                    track.repeatCount = Math.max(0, parseInt(repeatCount.getText().toString(), 0));
                    track.speedPercent = Math.max(20, Math.min(500, seekValue(speed)));
                    track.masking = masking.isChecked();
                    track.duckBelowMain = duck.isChecked();
                    saveProject();
                    refreshUi();
                    openAudioEditor();
                })
                .show();
    }

    private EditText numberInput(String hint, String value) {
        EditText input = new EditText(this);
        input.setHint(hint);
        input.setSingleLine(true);
        input.setInputType(android.text.InputType.TYPE_CLASS_NUMBER | android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL);
        input.setText(value);
        return input;
    }

    private String audioTrackSummary() {
        if (audioTracks.isEmpty()) {
            return "none";
        }
        return audioTracks.size() + " added" + (firstAudioAsMainMask ? ", first as main mask" : "");
    }

    private String trackSummary(int index, AudioTrack track) {
        return String.format(Locale.US,
                "%d. %s\nLength: %s  Start: %s  Volume: %d%%  Speed: %.2fx\nRepeat: %s  Every: %s  Count: %s\nMasking: %s  Below main: %s",
                index + 1,
                track.name,
                formatTime(track.durationMs),
                formatTime(track.startMs),
                track.volume,
                track.speedPercent / 100.0,
                track.repeat ? "on" : "off",
                track.repeatEveryMs <= 0 ? "track length" : formatTime(track.repeatEveryMs),
                track.repeatCount <= 0 ? "to end" : String.valueOf(track.repeatCount),
                track.masking ? "on" : "off",
                track.duckBelowMain ? "on" : "off");
    }

    private long mediaDurationMs(Uri uri) {
        MediaMetadataRetriever retriever = new MediaMetadataRetriever();
        try {
            retriever.setDataSource(this, uri);
            return parseLong(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION), 0);
        } catch (Exception ignored) {
            return 0;
        } finally {
            safeRelease(retriever);
        }
    }

    private String formatTime(long millis) {
        long totalSeconds = Math.max(0, Math.round(millis / 1000.0));
        long minutes = totalSeconds / 60;
        long seconds = totalSeconds % 60;
        return String.format(Locale.US, "%d:%02d", minutes, seconds);
    }

    private String millisToSecondsText(long millis) {
        if (millis <= 0) {
            return "0";
        }
        return String.format(Locale.US, "%.3f", millis / 1000.0);
    }

    private long secondsTextToMillis(String text, long fallback) {
        try {
            return Math.max(0, Math.round(Double.parseDouble(text.trim()) * 1000.0));
        } catch (Exception ignored) {
            return fallback;
        }
    }

    private int parseInt(String text, int fallback) {
        try {
            return Integer.parseInt(text.trim());
        } catch (Exception ignored) {
            return fallback;
        }
    }
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

        LinearLayout textActions = row();
        Button duplicateText = button("Duplicate Text");
        Button deleteText = button("Delete Text");
        textActions.addView(duplicateText, weight());
        textActions.addView(deleteText, weight());
        layout.addView(textActions);

        final Bitmap[] imageLayer = new Bitmap[]{initialLayer};
        final List<TextOverlay> texts = new ArrayList<>();
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
                    syncTextControls.run();
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
        imageRotationSeek.setOnSeekBarChangeListener(new SimpleSeekListener(refresh));
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

    private void setSeekValue(SeekBar seek, int value) {
        Object tag = seek.getTag();
        int min = tag instanceof Integer ? (Integer) tag : 0;
        int progress = Math.max(0, Math.min(seek.getMax(), value - min));
        seek.setProgress(progress);
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
    private int outputFrameCount() {
        return Math.max(1, frameCount * SLOT_COUNT);
    }

    private int sourceFrameForOutput(int outputFrame) {
        return Math.max(0, Math.min(frameCount - 1, outputFrame / SLOT_COUNT));
    }

    private String key(int outputFrame) {
        return String.valueOf(outputFrame);
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
        progress.setMax(outputFrameCount());
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
        List<AudioInput> audioInputs = new ArrayList<>();
        for (int i = 0; i < audioTracks.size(); i++) {
            AudioTrack track = audioTracks.get(i);
            File copied = copyUri(track.uri, new File(work, "audio_" + i + extensionFor(track.uri, ".mp3")));
            audioInputs.add(new AudioInput(track, copied));
        }

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

        File encoded = new File(work, "export.mp4");
        String command = buildEncodeCommand(framesDir, sourceFile, audioInputs, encoded);
        Session session = FFmpegKit.execute(command);
        if (!ReturnCode.isSuccess(session.getReturnCode())) {
            throw new RuntimeException("FFmpeg failed: " + session.getFailStackTrace());
        }
        return encoded;
    }

    private String buildEncodeCommand(File framesDir, File sourceFile, List<AudioInput> audioInputs, File outputFile) throws Exception {
        double exportFps = fps * SLOT_COUNT;
        String framePattern = new File(framesDir, "frame_%08d.png").getAbsolutePath();
        double videoDurationSeconds = frameCount / fps;
        String duration = String.format(Locale.US, "%.6f", videoDurationSeconds);
        StringBuilder command = new StringBuilder("-y -framerate ")
                .append(q(String.format(Locale.US, "%.6f", exportFps)))
                .append(" -i ").append(q(framePattern))
                .append(" -i ").append(q(sourceFile.getAbsolutePath()));
        for (AudioInput input : audioInputs) {
            command.append(" -i ").append(q(input.file.getAbsolutePath()));
        }

        boolean hasAudio = sourceHasAudio(sourceFile);
        double sourceVolume = sourceVolumeSeek.getProgress() / 100.0;
        if (audioInputs.isEmpty()) {
            if (hasAudio && Math.abs(sourceVolume - 1.0) > 0.001) {
                return command
                        + " -filter_complex " + q("[1:a:0]volume=" + String.format(Locale.US, "%.3f", sourceVolume)
                        + ",alimiter=limit=0.95[aout]")
                        + " -map 0:v:0 -map [aout] -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "
                        + q(outputFile.getAbsolutePath());
            }
            return command + " -map 0:v:0 -map 1:a? -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "
                    + q(outputFile.getAbsolutePath());
        }

        boolean useFirstAsMain = !hasAudio && firstAudioAsMainMask && !audioInputs.isEmpty();
        AudioInput mainInput = useFirstAsMain ? audioInputs.get(0) : null;
        int sourcePitchClass = -1;
        String sourceKeyLabel = "main";
        if (keyMatchCheck.isChecked()) {
            if (hasAudio) {
                KeyResult sourceKey = analyzeKey(sourceFile);
                sourcePitchClass = sourceKey.pitchClass;
                sourceKeyLabel = sourceKey.label();
            } else if (mainInput != null) {
                KeyResult sourceKey = analyzeKey(mainInput.file);
                sourcePitchClass = sourceKey.pitchClass;
                sourceKeyLabel = sourceKey.label();
            }
        }

        List<String> filterParts = new ArrayList<>();
        String mainLabel = null;
        int generated = 0;
        if (hasAudio) {
            filterParts.add("[1:a:0]volume=" + String.format(Locale.US, "%.3f", sourceVolume) + ",alimiter=limit=0.95[maina]");
            mainLabel = "[maina]";
        } else if (mainInput != null) {
            List<String> mainLabels = addTrackFilters(filterParts, 2, mainInput.track, videoDurationSeconds, 0, generated);
            generated += mainLabels.size();
            mainLabel = mixLabels(filterParts, mainLabels, "firstmain");
        }

        List<String> normalAdded = new ArrayList<>();
        List<String> duckedAdded = new ArrayList<>();
        StringBuilder statusBuilder = new StringBuilder("Audio mix: ").append(audioInputs.size()).append(" added track(s)");
        if (mainInput != null) {
            statusBuilder.append("\nMain masking track: ").append(mainInput.track.name);
        }
        for (int i = mainInput == null ? 0 : 1; i < audioInputs.size(); i++) {
            AudioInput input = audioInputs.get(i);
            AudioTrack track = input.track;
            int semitoneShift = 0;
            if (sourcePitchClass >= 0) {
                KeyResult trackKey = analyzeKey(input.file);
                semitoneShift = shortestShift(trackKey.pitchClass, sourcePitchClass);
                statusBuilder.append("\n").append(track.name).append(": ").append(trackKey.label())
                        .append(" -> ").append(sourceKeyLabel)
                        .append(String.format(Locale.US, " (%+d)", semitoneShift));
            }
            List<String> labels = addTrackFilters(filterParts, i + 2, track, videoDurationSeconds, semitoneShift, generated);
            generated += labels.size();
            if (track.duckBelowMain && mainLabel != null) {
                duckedAdded.addAll(labels);
            } else {
                normalAdded.addAll(labels);
            }
        }
        String finalStatus = statusBuilder.toString();
        runOnUiThread(() -> setStatus(finalStatus));

        List<String> finalInputs = new ArrayList<>();
        String mainMixLabel = mainLabel;
        String mainSideLabel = mainLabel;
        if (!duckedAdded.isEmpty() && mainLabel != null) {
            filterParts.add(mainLabel + "asplit=2[mainmix][mainside]");
            mainMixLabel = "[mainmix]";
            mainSideLabel = "[mainside]";
        }
        if (mainMixLabel != null) {
            finalInputs.add(mainMixLabel);
        }
        if (!duckedAdded.isEmpty()) {
            String duckMix = mixLabels(filterParts, duckedAdded, "duckmix");
            if (mainSideLabel != null) {
                filterParts.add(duckMix + mainSideLabel + "sidechaincompress=threshold=0.08:ratio=8:attack=20:release=250[ducked]");
                finalInputs.add("[ducked]");
            } else {
                finalInputs.add(duckMix);
            }
        }
        finalInputs.addAll(normalAdded);

        String audioOut = mixLabels(filterParts, finalInputs, "aout");
        if (!"[aout]".equals(audioOut)) {
            filterParts.add(audioOut + "anull[aout]");
        }
        String filter = String.join(";", filterParts);
        return command + " -filter_complex " + q(filter)
                + " -map 0:v:0 -map [aout] -c:v libx264 -pix_fmt yuv420p -c:a aac -t "
                + q(duration) + " " + q(outputFile.getAbsolutePath());
    }

    private List<String> addTrackFilters(List<String> filterParts, int inputIndex, AudioTrack track, double videoDurationSeconds, int semitoneShift, int labelOffset) {
        List<String> labels = new ArrayList<>();
        double speed = Math.max(0.2, Math.min(5.0, track.speedPercent / 100.0));
        double sourceDurationSeconds = track.durationMs > 0 ? track.durationMs / 1000.0 : videoDurationSeconds;
        double adjustedDurationSeconds = sourceDurationSeconds / speed;
        double repeatEverySeconds = track.repeatEveryMs > 0 ? track.repeatEveryMs / 1000.0 : adjustedDurationSeconds;
        int occurrences = track.repeat ? occurrenceCount(track.startMs / 1000.0, repeatEverySeconds, track.repeatCount, videoDurationSeconds) : 1;
        occurrences = Math.max(1, Math.min(64, occurrences));
        List<String> splitLabels = new ArrayList<>();
        if (occurrences > 1) {
            StringBuilder split = new StringBuilder("[").append(inputIndex).append(":a:0]asplit=").append(occurrences);
            for (int i = 0; i < occurrences; i++) {
                split.append("[trk").append(labelOffset).append("_src").append(i).append("]");
                splitLabels.add("[trk" + labelOffset + "_src" + i + "]");
            }
            filterParts.add(split.toString());
        }
        for (int i = 0; i < occurrences; i++) {
            double delaySeconds = track.startMs / 1000.0 + i * repeatEverySeconds;
            if (delaySeconds >= videoDurationSeconds) {
                break;
            }
            double remainingAfterSpeed = Math.max(0.01, videoDurationSeconds - delaySeconds);
            double trimSeconds = Math.max(0.01, Math.min(sourceDurationSeconds, remainingAfterSpeed * speed));
            String inLabel = occurrences > 1 ? splitLabels.get(i) : "[" + inputIndex + ":a:0]";
            String outLabel = "[trk" + labelOffset + "_" + i + "]";
            StringBuilder chain = new StringBuilder(inLabel)
                    .append("atrim=0:").append(String.format(Locale.US, "%.6f", trimSeconds))
                    .append(",asetpts=PTS-STARTPTS,aresample=44100,")
                    .append(speedFilter(speed))
                    .append(pitchFilter(semitoneShift))
                    .append("volume=").append(String.format(Locale.US, "%.3f", track.volume / 100.0));
            if (track.masking) {
                chain.append(",acompressor=threshold=0.18:ratio=6:attack=5:release=120,alimiter=limit=0.90");
            }
            long delayMs = Math.max(0, Math.round(delaySeconds * 1000.0));
            chain.append(",adelay=").append(delayMs).append("|").append(delayMs).append(outLabel);
            filterParts.add(chain.toString());
            labels.add(outLabel);
        }
        return labels;
    }

    private int occurrenceCount(double startSeconds, double repeatEverySeconds, int repeatCount, double videoDurationSeconds) {
        if (startSeconds >= videoDurationSeconds) {
            return 1;
        }
        if (repeatCount > 0) {
            return repeatCount;
        }
        double every = Math.max(0.1, repeatEverySeconds);
        return Math.max(1, (int) Math.ceil((videoDurationSeconds - startSeconds) / every));
    }

    private String mixLabels(List<String> filterParts, List<String> labels, String outputName) {
        if (labels.isEmpty()) {
            return "";
        }
        if (labels.size() == 1) {
            if ("aout".equals(outputName)) {
                filterParts.add(labels.get(0) + "alimiter=limit=0.95[aout]");
                return "[aout]";
            }
            return labels.get(0);
        }
        StringBuilder mix = new StringBuilder();
        for (String label : labels) {
            mix.append(label);
        }
        mix.append("amix=inputs=").append(labels.size()).append(":duration=first:dropout_transition=0,alimiter=limit=0.95[").append(outputName).append("]");
        filterParts.add(mix.toString());
        return "[" + outputName + "]";
    }

    private String speedFilter(double speed) {
        StringBuilder chain = new StringBuilder();
        double remaining = speed;
        while (remaining > 2.0) {
            chain.append("atempo=2.000000,");
            remaining /= 2.0;
        }
        while (remaining < 0.5) {
            chain.append("atempo=0.500000,");
            remaining /= 0.5;
        }
        if (Math.abs(remaining - 1.0) > 0.001) {
            chain.append(String.format(Locale.US, "atempo=%.6f,", remaining));
        }
        return chain.toString();
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

    private Bitmap colorBlend(Bitmap replacement, Bitmap previous, Bitmap next, double colorStrength, double frequencyStrength) {
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
        double edgeMix = Math.min(0.35, colorStrength * 0.5);
        for (int i = 0; i < rp.length; i++) {
            int r = Color.red(rp[i]);
            int g = Color.green(rp[i]);
            int b = Color.blue(rp[i]);
            int cr = (Color.red(pp[i]) + Color.red(np[i])) / 2;
            int cg = (Color.green(pp[i]) + Color.green(np[i])) / 2;
            int cb = (Color.blue(pp[i]) + Color.blue(np[i])) / 2;
            int nr = channelBlend(r, cr, rm[0], rs[0], cm[0], cs[0], colorStrength, edgeMix);
            int ng = channelBlend(g, cg, rm[1], rs[1], cm[1], cs[1], colorStrength, edgeMix);
            int nb = channelBlend(b, cb, rm[2], rs[2], cm[2], cs[2], colorStrength, edgeMix);
            rp[i] = Color.argb(Color.alpha(rp[i]), nr, ng, nb);
        }
        if (frequencyStrength > 0.0) {
            applyFrequencyBlend(rp, pp, np, width, height, frequencyStrength);
        }
        repl.setPixels(rp, 0, width, 0, 0, width, height);
        return repl;
    }

    private void applyFrequencyBlend(int[] replacement, int[] previous, int[] next, int width, int height, double strength) {
        int[] original = replacement.clone();
        for (int y = 1; y < height - 1; y++) {
            for (int x = 1; x < width - 1; x++) {
                int index = y * width + x;
                int replLowR = neighborhoodAverage(original, width, x, y, 0);
                int replLowG = neighborhoodAverage(original, width, x, y, 1);
                int replLowB = neighborhoodAverage(original, width, x, y, 2);
                int ctxLowR = (neighborhoodAverage(previous, width, x, y, 0) + neighborhoodAverage(next, width, x, y, 0)) / 2;
                int ctxLowG = (neighborhoodAverage(previous, width, x, y, 1) + neighborhoodAverage(next, width, x, y, 1)) / 2;
                int ctxLowB = (neighborhoodAverage(previous, width, x, y, 2) + neighborhoodAverage(next, width, x, y, 2)) / 2;

                int replDetailR = Color.red(original[index]) - replLowR;
                int replDetailG = Color.green(original[index]) - replLowG;
                int replDetailB = Color.blue(original[index]) - replLowB;
                int ctxR = (Color.red(previous[index]) + Color.red(next[index])) / 2;
                int ctxG = (Color.green(previous[index]) + Color.green(next[index])) / 2;
                int ctxB = (Color.blue(previous[index]) + Color.blue(next[index])) / 2;
                int ctxDetailR = ctxR - ctxLowR;
                int ctxDetailG = ctxG - ctxLowG;
                int ctxDetailB = ctxB - ctxLowB;

                int r = clampChannel(Color.red(replacement[index]) + (int) Math.round((ctxDetailR - replDetailR) * strength));
                int g = clampChannel(Color.green(replacement[index]) + (int) Math.round((ctxDetailG - replDetailG) * strength));
                int b = clampChannel(Color.blue(replacement[index]) + (int) Math.round((ctxDetailB - replDetailB) * strength));
                replacement[index] = Color.argb(Color.alpha(replacement[index]), r, g, b);
            }
        }
    }

    private int neighborhoodAverage(int[] pixels, int width, int x, int y, int channel) {
        int sum = 0;
        for (int yy = y - 1; yy <= y + 1; yy++) {
            for (int xx = x - 1; xx <= x + 1; xx++) {
                int color = pixels[yy * width + xx];
                if (channel == 0) {
                    sum += Color.red(color);
                } else if (channel == 1) {
                    sum += Color.green(color);
                } else {
                    sum += Color.blue(color);
                }
            }
        }
        return sum / 9;
    }

    private int clampChannel(int value) {
        return Math.max(0, Math.min(255, value));
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

    private static class AudioTrack {
        Uri uri;
        String name = "audio";
        long durationMs = 0;
        int volume = 50;
        long startMs = 0;
        boolean repeat = true;
        long repeatEveryMs = 0;
        int repeatCount = 0;
        int speedPercent = 100;
        boolean masking = true;
        boolean duckBelowMain = true;

        JSONObject toJson() throws Exception {
            JSONObject json = new JSONObject();
            json.put("uri", uri.toString());
            json.put("name", name);
            json.put("durationMs", durationMs);
            json.put("volume", volume);
            json.put("startMs", startMs);
            json.put("repeat", repeat);
            json.put("repeatEveryMs", repeatEveryMs);
            json.put("repeatCount", repeatCount);
            json.put("speedPercent", speedPercent);
            json.put("masking", masking);
            json.put("duckBelowMain", duckBelowMain);
            return json;
        }

        static AudioTrack fromJson(JSONObject json) throws Exception {
            AudioTrack track = new AudioTrack();
            track.uri = Uri.parse(json.getString("uri"));
            track.name = json.optString("name", "audio");
            track.durationMs = json.optLong("durationMs", 0);
            track.volume = json.optInt("volume", 50);
            track.startMs = json.optLong("startMs", 0);
            track.repeat = json.optBoolean("repeat", true);
            track.repeatEveryMs = json.optLong("repeatEveryMs", 0);
            track.repeatCount = json.optInt("repeatCount", 0);
            track.speedPercent = json.optInt("speedPercent", 100);
            track.masking = json.optBoolean("masking", true);
            track.duckBelowMain = json.optBoolean("duckBelowMain", true);
            return track;
        }
    }

    private static class AudioInput {
        final AudioTrack track;
        final File file;
        AudioInput(AudioTrack track, File file) {
            this.track = track;
            this.file = file;
        }
    }
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
