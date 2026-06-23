# Video Frame Swapper

Video Frame Swapper is a small editor for replacing exact frames in a video.

For every frame in the source video, the editor still creates four output frames and raises the output FPS by 4x. That keeps the finished video the same length. You do not edit slots. You move through the output timeline and swap one exact frame with an image.

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
- Move through an output-frame timeline.
- Replace one frame with an image.
- Restore the last Android project when the app opens.
- Add text to a selected frame with size, rotation, and X/Y placement controls.
- Export a same-length MP4 with four frames for every original frame.
- Keep the original audio when possible.
- Add a second music track.
- Raise or lower the original soundtrack volume.
- Raise or lower the added music volume.
- Detect the key of the original audio and added music, then pitch-shift the added music to match.
- Color-match replacement images using the previous and next video frames.
- Blend image detail/frequency from nearby frames so replacements sit better in motion.
- Android output uses the system folder picker, so you can save to SD card folders when the phone exposes them.

## Android APK Download

Download the compiled APK here:

```text
https://github.com/sslogic/video-frame-swapper/raw/android-fork/releases/video-frame-swapper-debug.apk
```

Install on Android:

1. Download the APK on the phone.
2. Open the downloaded file.
3. If Android blocks it, allow installs from that browser or file manager.
4. Install `Video Frame Swapper`.
5. Open the app.

The source for this Android build is in the `android/` folder on this branch.
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
3. Use the timeline or frame box to choose the exact frame.
4. Click `Replace Frame` and pick an image.
5. Use `Color blend replacement images` if you want the replacement image matched to nearby frames.
6. Use `Color Blend Strength` for more or less color matching.
7. Use `Image Frequency Blend` for more or less detail/texture matching from nearby frames.
8. Click `Add Music` if you want a second track.
9. Use `Original Soundtrack Volume` to raise or lower the video audio.
10. Use `Added Music Volume` to raise or lower the added track.
11. Click `Tone Match + Half Volume` to set the added track to 50% and pitch-match it to the original audio.
12. Click `Export Video`.

The editor saves a `.quad_edits.json` file next to the video. That file stores the swapped frame numbers and audio settings for that video.

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
4. Use the output-frame timeline to choose the exact frame.
5. Tap `Replace Frame` to choose an image.
6. Tap `Edit Text` to add text to the selected frame.
7. Set text size, rotation, and X/Y placement, then apply it.
8. Turn color blending on or off.
9. Set `Color Blend Strength` and `Image Frequency Blend`.
10. Tap `Add Music` if you want an extra track.
11. Set `Original Soundtrack Volume` and `Added Music Volume`.
12. Leave key matching enabled if you want the added music pitch-shifted to match the original audio.
13. Tap `Save Folder` and choose where the MP4 should be written.
14. Tap `Export To Chosen Folder`.

The Android app saves the current project locally. When you open the app again it restores the last video, music track, save folder, swapped frames, edited text frames, and slider settings when Android still has access to those files.

For SD cards, use the folder picker. If Android shows the SD card in that picker, the app can save there.

## Notes

- Large videos take time. The Android app renders frame images first, then encodes the final MP4.
- The key detector uses chroma analysis. It works best with music-heavy audio and may be less reliable on speech, noise, or very short clips.
- The Android build uses `com.mrljdx:ffmpeg-kit-full:6.1.4` because the original FFmpegKit packages were retired.

