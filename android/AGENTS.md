# Purpose

- Own the Android version of Movie Frame Quad Editor.

# Ownership

- Own Android source, resources, Gradle configuration, and device-facing export behavior under `android/`.
- Generated build output and bundled tool distributions are not source contracts.

# Local Contracts

- Keep folder selection and persisted URI permissions compatible with Android's Storage Access Framework.
- Preserve the existing FFmpegKit integration unless a requested repair requires changing it.

# Work Guidance

- Use the repository's configured Android SDK and JDK paths when building.

# Verification

- Run the existing Gradle assemble task when Android source or build configuration changes.

# Child DOX Index
