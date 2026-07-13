# Android APK

Use this branch for the Android build of Video Frame Swapper.

Download the APK:

```text
releases/video-frame-swapper-debug.apk
```

Direct GitHub download:

```text
https://github.com/sslogic/video-frame-swapper/raw/android-fork/releases/video-frame-swapper-debug.apk
```

Install on Android:

1. Download the APK on the phone.
2. Open the file.
3. Allow installs from the browser or file manager if Android asks.
4. Install `Video Frame Swapper`.
5. Open the app.

The app lets you choose the export folder with Android's folder picker. If your phone shows the SD card in that picker, choose the SD card folder and the export will save there.

The app restores the last project when it opens again. It keeps the selected video, music, save folder, swapped frames, edited text-frame files, and slider settings as long as Android still allows access to those files.

Use `Edit Image/Text` to work on the selected output frame. It can resize and rotate the imported image without stretching it, remove image backgrounds, place and move text, duplicate or delete selected text, change text size, rotation, opacity, border, and camouflage color matching, then apply the edited image back to that frame.

Use `Replace Every X` when you want the same image placed every chosen number of output frames from the current timeline position.

This APK includes output-frame blending, so replacements are blended against the previous and next output frames instead of treating a four-frame source group as one block.
