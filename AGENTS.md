# Purpose

- Own the Movie Frame Quad Editor desktop application and its Android companion.

# Ownership

- The root owns `movie_quad_editor.py`, launch/dependency files, project-wide documentation, backups, and repair scripts.
- `android/` owns the Android application and its build tooling.

# Local Contracts

- Read the target code before editing it.
- Back up every existing file before changing it.
- Keep every lasting program repair reproducible through a one-shot script under `repairs/`.
- Preserve unrelated user changes in the working tree.
- Do not silently save or restore video edits.

# Work Guidance

- The desktop editor runs from `run_editor.bat` with the local `.venv`.
- The desktop editor supports multiple independent windows through the `New Window` button.
- The `Edit Frame` button opens the current video frame directly; image import stays on the separate `Import Image` button.
- When the selected frame already has a saved replacement, `Edit Frame` uses that replacement image as the editable base frame.
- Use the bundled `imageio-ffmpeg` executable for desktop export behavior.
- Desktop export writes a temporary silent MP4 first, then uses FFmpeg to mux source and added audio tracks into the final export.
- Exclude generated dependencies, build outputs, local JDK/Gradle distributions, backups, and media artifacts from source-structure decisions.

# Verification

- Verify Python syntax with the local virtual environment.
- For export changes, run a short end-to-end MP4 export and confirm FFmpeg returns zero and the result is readable.

# Child DOX Index

- `android/AGENTS.md` - Android application source, storage/export behavior, and Gradle verification.
- `repairs/AGENTS.md` - reusable one-shot repair scripts.
