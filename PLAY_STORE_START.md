# Google Play Store Start

Use this as the first checklist for selling the Android app.

## App Identity

- App name: Mayniak Subliminal Multimedia Studio
- Package id: com.mayniak.subliminalstudio
- Release APK in this branch: releases/mayniak-subliminal-multimedia-studio.apk

## Needed Before Sale

- A Google Play Developer account.
- A signed release build. The APK in this branch is a debug-signed test build and is good for sideload testing, not the final store upload.
- App icon, feature graphic, screenshots, short description, full description, privacy policy URL, and support email.
- Content rating questionnaire.
- Data safety answers.
- Pricing decision: free, paid, or in-app purchases.
- Closed testing track before production release.

## Store Build Notes

- Google Play normally expects an Android App Bundle (`.aab`) for production.
- Create a private upload key and keep it backed up.
- Build a release variant signed with that upload key.
- Test the signed build on a real phone before submitting.