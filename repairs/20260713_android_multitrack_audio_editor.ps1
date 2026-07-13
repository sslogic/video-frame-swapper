$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$MainPath = Join-Path $Root "android\app\src\main\java\com\mayniak\subliminalstudio\MainActivity.java"
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (!(Test-Path -LiteralPath $MainPath)) {
    throw "Missing target file: $MainPath"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -LiteralPath $MainPath -Destination (Join-Path $BackupDir "MainActivity.java.$Stamp.android-multitrack-audio.bak") -Force

function Replace-Once {
    param([string]$Text, [string]$Old, [string]$New, [string]$Label)
    $First = $Text.IndexOf($Old, [StringComparison]::Ordinal)
    if ($First -lt 0) { throw "Could not find expected block: $Label" }
    $Second = $Text.IndexOf($Old, $First + $Old.Length, [StringComparison]::Ordinal)
    if ($Second -ge 0) { throw "Expected block was not unique: $Label" }
    return $Text.Remove($First, $Old.Length).Insert($First, $New)
}

function Replace-Range {
    param([string]$Text, [string]$Start, [string]$End, [string]$New, [string]$Label)
    $StartIndex = $Text.IndexOf($Start, [StringComparison]::Ordinal)
    if ($StartIndex -lt 0) { throw "Could not find range start: $Label" }
    $EndIndex = $Text.IndexOf($End, $StartIndex, [StringComparison]::Ordinal)
    if ($EndIndex -lt 0) { throw "Could not find range end: $Label" }
    return $Text.Remove($StartIndex, $EndIndex - $StartIndex).Insert($StartIndex, $New)
}

$Text = Get-Content -LiteralPath $MainPath -Raw

$Text = Replace-Once $Text "import org.json.JSONObject;" "import org.json.JSONArray;`nimport org.json.JSONObject;" "JSONArray import"

$Text = Replace-Once $Text @'
    private Uri musicUri;
    private Uri outputTreeUri;
    private final Map<String, Uri> replacements = new HashMap<>();
'@ @'
    private Uri musicUri;
    private Uri outputTreeUri;
    private final List<AudioTrack> audioTracks = new ArrayList<>();
    private final Map<String, Uri> replacements = new HashMap<>();
'@ "audio track list field"

$Text = Replace-Once $Text @'
    private boolean exporting = false;
    private int pendingRepeatInterval = 0;
'@ @'
    private boolean exporting = false;
    private int pendingRepeatInterval = 0;
    private boolean reopenAudioEditorAfterPick = false;
'@ "audio picker reopen field"

$Text = Replace-Once $Text @'
        Button pickMusic = button("Add Music");
        pickMusic.setOnClickListener(v -> pick(PICK_MUSIC, "*/*"));
'@ @'
        Button pickMusic = button("Audio Editor");
        pickMusic.setOnClickListener(v -> openAudioEditor());
'@ "top audio editor button"

$Text = Replace-Once $Text @'
        TextView sourceVolumeLabel = label("Original Soundtrack Volume");
        root.addView(sourceVolumeLabel);
        sourceVolumeSeek = new SeekBar(this);
        sourceVolumeSeek.setMax(200);
        sourceVolumeSeek.setProgress(100);
        root.addView(sourceVolumeSeek, matchWrap());

        TextView musicLabel = label("Added Music Volume");
        root.addView(musicLabel);
        musicVolumeSeek = new SeekBar(this);
        musicVolumeSeek.setMax(200);
        musicVolumeSeek.setProgress(50);
        root.addView(musicVolumeSeek, matchWrap());

'@ @'
        sourceVolumeSeek = new SeekBar(this);
        sourceVolumeSeek.setMax(200);
        sourceVolumeSeek.setProgress(100);
        musicVolumeSeek = new SeekBar(this);
        musicVolumeSeek.setMax(200);
        musicVolumeSeek.setProgress(50);

'@ "move audio sliders into editor"

$Text = Replace-Once $Text @'
        } else if (requestCode == PICK_MUSIC) {
            musicUri = uri;
'@ @'
        } else if (requestCode == PICK_MUSIC) {
            addAudioTrack(uri);
'@ "audio picker handling"

$Text = Replace-Once $Text @'
        saveProject();
        refreshUi();
    }
'@ @'
        saveProject();
        refreshUi();
        if (requestCode == PICK_MUSIC && reopenAudioEditorAfterPick) {
            reopenAudioEditorAfterPick = false;
            runOnUiThread(this::openAudioEditor);
        }
    }
'@ "reopen audio editor after pick"

$Text = Replace-Once $Text @'
        String musicName = musicUri == null ? "none" : displayName(musicUri);
        String folder = outputTreeUri == null ? "none" : "chosen";
        info.setText(String.format(Locale.US,
                "Video: %s\nMusic: %s\nSave folder: %s\nOutput frame: %d / %d\nSource frame: %d / %d\nFPS: %.3f -> %.3f\nSwapped frames: %d",
                videoName, musicName, folder, currentOutputFrame, outputFrameCount() - 1,
                sourceFrameForOutput(currentOutputFrame), frameCount - 1, fps, fps * SLOT_COUNT, replacements.size()));
'@ @'
        String musicName = audioTrackSummary();
        String folder = outputTreeUri == null ? "none" : "chosen";
        info.setText(String.format(Locale.US,
                "Video: %s\nAudio tracks: %s\nSave folder: %s\nOutput frame: %d / %d\nSource frame: %d / %d\nFPS: %.3f -> %.3f\nSwapped frames: %d",
                videoName, musicName, folder, currentOutputFrame, outputFrameCount() - 1,
                sourceFrameForOutput(currentOutputFrame), frameCount - 1, fps, fps * SLOT_COUNT, replacements.size()));
'@ "audio summary info"

$Text = Replace-Once $Text @'
            if (musicUri != null) {
                root.put("musicUri", musicUri.toString());
            }
'@ @'
            JSONArray tracks = new JSONArray();
            for (AudioTrack track : audioTracks) {
                tracks.put(track.toJson());
            }
            root.put("audioTracks", tracks);
'@ "save audio tracks"

$Text = Replace-Once $Text @'
            if (root.has("musicUri")) {
                musicUri = Uri.parse(root.getString("musicUri"));
            }
'@ @'
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
'@ "restore audio tracks"

$AudioEditorBlock = @'
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
        return audioTracks.size() + " added";
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

'@

$Text = Replace-Range $Text "    private void openFrameImageEditor()" "    private void openFrameImageEditor()" ($AudioEditorBlock + "    private void openFrameImageEditor()") "insert audio editor before image editor"

$Text = Replace-Once $Text @'
        File sourceFile = copyUri(videoUri, new File(work, "source" + extensionFor(videoUri, ".mp4")));
        File musicFile = musicUri == null ? null : copyUri(musicUri, new File(work, "music" + extensionFor(musicUri, ".m4a")));
'@ @'
        File sourceFile = copyUri(videoUri, new File(work, "source" + extensionFor(videoUri, ".mp4")));
        List<AudioInput> audioInputs = new ArrayList<>();
        for (int i = 0; i < audioTracks.size(); i++) {
            AudioTrack track = audioTracks.get(i);
            File copied = copyUri(track.uri, new File(work, "audio_" + i + extensionFor(track.uri, ".mp3")));
            audioInputs.add(new AudioInput(track, copied));
        }
'@ "copy audio tracks"

$Text = Replace-Once $Text @'
        String command = buildEncodeCommand(framesDir, sourceFile, musicFile, encoded);
'@ @'
        String command = buildEncodeCommand(framesDir, sourceFile, audioInputs, encoded);
'@ "build command audio inputs"

$NewBuildBlock = @'
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

        int sourcePitchClass = -1;
        String sourceKeyLabel = "main";
        if (keyMatchCheck.isChecked() && hasAudio) {
            KeyResult sourceKey = analyzeKey(sourceFile);
            sourcePitchClass = sourceKey.pitchClass;
            sourceKeyLabel = sourceKey.label();
        }

        List<String> filterParts = new ArrayList<>();
        String mainLabel = null;
        if (hasAudio) {
            filterParts.add("[1:a:0]volume=" + String.format(Locale.US, "%.3f", sourceVolume) + ",alimiter=limit=0.95[maina]");
            mainLabel = "[maina]";
        }

        List<String> normalAdded = new ArrayList<>();
        List<String> duckedAdded = new ArrayList<>();
        int generated = 0;
        StringBuilder statusBuilder = new StringBuilder("Audio mix: ").append(audioInputs.size()).append(" added track(s)");
        for (int i = 0; i < audioInputs.size(); i++) {
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
            if (track.duckBelowMain && hasAudio) {
                duckedAdded.addAll(labels);
            } else {
                normalAdded.addAll(labels);
            }
        }
        String finalStatus = statusBuilder.toString();
        runOnUiThread(() -> setStatus(finalStatus));

        List<String> finalInputs = new ArrayList<>();
        if (mainLabel != null) {
            finalInputs.add(mainLabel);
        }
        if (!duckedAdded.isEmpty()) {
            String duckMix = mixLabels(filterParts, duckedAdded, "duckmix");
            if (mainLabel != null) {
                filterParts.add(duckMix + mainLabel + "sidechaincompress=threshold=0.08:ratio=8:attack=20:release=250[ducked]");
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

'@

$Text = Replace-Range $Text "    private String buildEncodeCommand(File framesDir," "    private String pitchFilter(int semitones)" $NewBuildBlock "multi-track build command"

$HelperClasses = @'
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

'@

$Text = Replace-Once $Text "    private static class TextOverlay {" ($HelperClasses + "    private static class TextOverlay {") "audio helper classes"

Set-Content -LiteralPath $MainPath -Value $Text -NoNewline

$Repaired = Get-Content -LiteralPath $MainPath -Raw
foreach ($Needle in @(
    "openAudioEditor",
    "Audio Editor",
    "Add Audio Track",
    "AudioTrack",
    "AudioInput",
    "track.repeatEveryMs",
    "sidechaincompress",
    "speedFilter",
    "addTrackFilters",
    "audioTracks"
)) {
    if ($Repaired.IndexOf($Needle, [StringComparison]::Ordinal) -lt 0) {
        throw "Verification failed. Missing repaired text: $Needle"
    }
}

Write-Host "Android multi-track audio editor repair complete."
Write-Host "Backup written under $BackupDir with stamp $Stamp."
