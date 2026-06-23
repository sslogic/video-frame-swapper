# Video Frame Swapper

Video Frame Swapper is a small editor for replacing exact frames in a video.

For every frame in the source video, the editor still creates four output frames and raises the output FPS by 4x. That keeps the finished video the same length. You do not edit “slots” anymore. You move through the output timeline and swap one exact frame with an image.

Example:

```text
source:  1,000 frames at 30 FPS
export:  4,000 frames at 120 FPS
length:  about the same
```

The project has two parts:

- Windows desktop editor in Python
- Android app in the `android-fork` branch

## Features

- Load a video.
- Zoom in and out on a video timeline.
- Move to an exact output frame.
- Replace one frame with an image.
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

## Android APK Download

The Android app is on its own branch:

```text
https://github.com/sslogic/video-frame-swapper/tree/android-fork
```

Download the compiled APK here:

```text
https://github.com/sslogic/video-frame-swapper/raw/android-fork/releases/video-frame-swapper-debug.apk
```

## Android Install

1. Download the APK on the phone.
2. Open the downloaded file.
3. If Android blocks it, allow installs from that browser or file manager.
4. Install `Video Frame Swapper`.
5. Open the app.

For SD cards, use the folder picker. If Android shows the SD card in that picker, the app can save there.

## Android Use

1. Tap `Open Video`.
2. Pick a video.
3. Use the timeline to pick a frame.
4. Tap `Replace Frame` to choose an image.
5. Turn color blending on or off.
6. Set `Color Blend Strength` and `Image Frequency Blend`.
7. Tap `Add Music` if you want an extra track.
8. Set `Original Soundtrack Volume` and `Added Music Volume`.
9. Leave key matching enabled if you want the added music pitch-shifted to match the original audio.
10. Tap `Save Folder` and choose where the MP4 should be written.
11. Tap `Export To Chosen Folder`.

## Android Source Build

If you want to build the Android app yourself, switch to the Android branch:

```powershell
git fetch origin
git checkout android-fork
```

Open the `android` folder in Android Studio and build the APK from there.

## Notes

- Large videos take time. The Android app renders frame images first, then encodes the final MP4.
- The key detector uses chroma analysis. It works best with music-heavy audio and may be less reliable on speech, noise, or very short clips.
- The Android build uses `com.mrljdx:ffmpeg-kit-full:6.1.4` because the original FFmpegKit packages were retired.
