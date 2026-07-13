$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$MainPath = Join-Path $Root "android\app\src\main\java\com\mayniak\subliminalstudio\MainActivity.java"
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (!(Test-Path -LiteralPath $MainPath)) {
    throw "Missing target file: $MainPath"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -LiteralPath $MainPath -Destination (Join-Path $BackupDir "MainActivity.java.$Stamp.android-first-audio-mask.bak") -Force

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
    private int pendingRepeatInterval = 0;
    private boolean reopenAudioEditorAfterPick = false;
'@ @'
    private int pendingRepeatInterval = 0;
    private boolean reopenAudioEditorAfterPick = false;
    private boolean firstAudioAsMainMask = false;
'@ "first audio mask field"

$Text = Replace-Once $Text @'
            root.put("keyMatch", keyMatchCheck.isChecked());
            root.put("colorBlend", colorBlendCheck.isChecked());
'@ @'
            root.put("keyMatch", keyMatchCheck.isChecked());
            root.put("firstAudioAsMainMask", firstAudioAsMainMask);
            root.put("colorBlend", colorBlendCheck.isChecked());
'@ "save first audio mask"

$Text = Replace-Once $Text @'
            keyMatchCheck.setChecked(root.optBoolean("keyMatch", true));
            colorBlendCheck.setChecked(root.optBoolean("colorBlend", true));
'@ @'
            keyMatchCheck.setChecked(root.optBoolean("keyMatch", true));
            firstAudioAsMainMask = root.optBoolean("firstAudioAsMainMask", false);
            colorBlendCheck.setChecked(root.optBoolean("colorBlend", true));
'@ "restore first audio mask"

$Text = Replace-Once $Text @'
        content.addView(keyMatch, matchWrap());

        Button addTrack = button("Add Audio Track");
'@ @'
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
'@ "audio editor first mask checkbox"

$Text = Replace-Once $Text @'
                    keyMatchCheck.setChecked(keyMatch.isChecked());
                    saveProject();
'@ @'
                    keyMatchCheck.setChecked(keyMatch.isChecked());
                    firstAudioAsMainMask = firstMask.isChecked();
                    saveProject();
'@ "close first mask save"

$Text = Replace-Once $Text @'
        return audioTracks.size() + " added";
'@ @'
        return audioTracks.size() + " added" + (firstAudioAsMainMask ? ", first as main mask" : "");
'@ "summary first mask"

$Text = Replace-Once $Text @'
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
'@ @'
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
'@ "first audio main build setup"

$Text = Replace-Once $Text @'
            List<String> labels = addTrackFilters(filterParts, i + 2, track, videoDurationSeconds, semitoneShift, generated);
'@ @'
            List<String> labels = addTrackFilters(filterParts, i + 2, track, videoDurationSeconds, semitoneShift, generated);
'@ "keep input index stable"

$Text = Replace-Once $Text @'
            if (track.duckBelowMain && hasAudio) {
'@ @'
            if (track.duckBelowMain && mainLabel != null) {
'@ "duck against selected main"

$Text = Replace-Once $Text @'
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
'@ @'
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
'@ "split main sidechain"

Set-Content -LiteralPath $MainPath -Value $Text -NoNewline

$Repaired = Get-Content -LiteralPath $MainPath -Raw
foreach ($Needle in @(
    "firstAudioAsMainMask",
    "use first added track as main masking track",
    "useFirstAsMain",
    "Main masking track",
    "asplit=2[mainmix][mainside]"
)) {
    if ($Repaired.IndexOf($Needle, [StringComparison]::Ordinal) -lt 0) {
        throw "Verification failed. Missing repaired text: $Needle"
    }
}

Write-Host "Android first-audio masking and ducking repair complete."
Write-Host "Backup written under $BackupDir with stamp $Stamp."
