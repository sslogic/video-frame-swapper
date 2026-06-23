# Video Frame Swapper

Video Frame Swapper is a small editor for making a four-frame version of a video.

For every frame in the source video, the editor creates four output frame slots. You can replace any one of those slots with an image. On export, the video writes all four slots for every source frame and raises the output FPS by 4x, so the finished video stays the same length.

Example:

```text
source:  1,000 frames at 30 FPS
export:  4,000 frames at 120 FPS
length:  about the same
```

The project has two versions:

- Windows desktop editor in Python
- Android app in `android/`

## Features

- Load a video.
- See all four generated slots for the current frame.
- Replace one slot with an image.
- Export a same-length MP4 with four frames for every original frame.
- Keep the original audio when possible.
- Add a second music track.
- Raise or lower the original soundtrack volume.
- Raise or lower the added music volume.
- Detect the key of the original audio and added music, then pitch-shift the added music to match.
- Color-match replacement images using the previous and next video frames.
- Blend image detail/frequency from nearby frames so replacements sit better in motion.
- Android output uses the system folder picker, so you can save to SD card folders when the phone exposes them.

## Get The Code

```powershell
git clone https://github.com/sslogic/video-frame-swapper.git
cd video-frame-swapper
```

## Windows Install

Requirements:

- Windows
- Python 3.11 or newer
- Internet connection for the first run

Run it:

```powershell
.\run_editor.bat
```

The first run creates a local `.venv` folder and installs:

- OpenCV
- Pillow
- imageio-ffmpeg

Nothing is installed globally.

## Windows Use

1. Click `Open Video`.
2. Move through the video with the frame slider or arrow buttons.
3. Pick `Slot 1`, `Slot 2`, `Slot 3`, or `Slot 4`.
4. Click `Replace Slot` to put an image into that slot.
5. Use `Color blend replacement images` if you want the replacement image matched to nearby frames.
6. Use `Color Blend Strength` for more or less color matching.
7. Use `Image Frequency Blend` for more or less detail/texture matching from nearby frames.
8. Click `Add Music` if you want a second track.
9. Use `Original Soundtrack Volume` to raise or lower the video audio.
10. Use `Added Music Volume` to raise or lower the added track.
11. Click `Tone Match + Half Volume` to set the added track to 50% and pitch-match it to the original audio.
12. Click `Export Video`.

The editor saves a `.quad_edits.json` file next to the video. That file stores the replacement slots and audio settings for that video.

## Android Install From Source

Requirements:

- Android Studio
- Android SDK
- JDK 17

On this machine, the SDK was found at:

```text
E:\androidsdk
```

Open the Android project:

1. Start Android Studio.
2. Choose `Open`.
3. Open this folder:

```text
video-frame-swapper\android
```

4. Let Gradle sync.
5. If Android Studio asks for an SDK location, use your Android SDK folder.
6. Build with `Build > Build Bundle(s) / APK(s) > Build APK(s)`.

The debug APK will be created at:

```text
android\app\build\outputs\apk\debug\app-debug.apk
```

## Android Command-Line Build

If you already have Java and Gradle installed:

```powershell
cd android
gradle :app:assembleDebug
```

If you are building on the original development machine from this folder, this command works:

```powershell
cd "E:\movie cutter\android"
$env:JAVA_HOME = "E:\movie cutter\android\jdk17b\jdk-17.0.19+10"
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"
.\gradle-8.10.2\bin\gradle.bat :app:assembleDebug
```

The local JDK and Gradle download folders are ignored by git. They are not part of the repository.

## Android Use

1. Install the APK on the phone.
2. Tap `Open Video`.
3. Pick a video.
4. Tap one of the four preview slots.
5. Tap `Replace Selected Slot` to choose an image.
6. Turn color blending on or off.
7. Set `Color Blend Strength` and `Image Frequency Blend`.
8. Tap `Add Music` if you want an extra track.
9. Set `Original Soundtrack Volume` and `Added Music Volume`.
10. Leave key matching enabled if you want the added music pitch-shifted to match the original audio.
11. Tap `Save Folder` and choose where the MP4 should be written.
12. Tap `Export To Chosen Folder`.

For SD cards, use the folder picker. If Android shows the SD card in that picker, the app can save there.

## Notes

- Large videos take time. The Android app renders frame images first, then encodes the final MP4.
- The key detector uses chroma analysis. It works best with music-heavy audio and may be less reliable on speech, noise, or very short clips.
- The Android build uses `com.mrljdx:ffmpeg-kit-full:6.1.4` because the original FFmpegKit packages were retired.
