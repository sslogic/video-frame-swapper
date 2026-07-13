$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$PlayStore = Join-Path $Root "PLAY_STORE_START.md"
$BackupDir = Join-Path $Root "backups"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (!(Test-Path -LiteralPath $PlayStore)) {
    throw "Missing file: $PlayStore"
}
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
Copy-Item -LiteralPath $PlayStore -Destination (Join-Path $BackupDir "PLAY_STORE_START.md.$Stamp.requirements.bak") -Force

Set-Content -LiteralPath $PlayStore -Value @'
# Google Play Store Start

Use this as the first checklist for selling the Android app.

## App Identity

- App name: Mayniak Subliminal Multimedia Studio
- Package id: com.mayniak.subliminalstudio
- Test APK in this branch: releases/mayniak-subliminal-multimedia-studio.apk

## Account

- Create a Google Play Console developer account.
- Pay the one-time Google Play developer registration fee.
- Choose personal or organization account type.
- Complete identity verification.

## Store Build

- The APK in this branch is for sideload testing.
- Google Play production should use a signed Android App Bundle (`.aab`).
- Create a private upload key and keep it backed up.
- Enable Play App Signing in Play Console.
- Build a release variant signed with the upload key.
- Test the signed release build on a real phone before submitting.

## Store Listing

- App icon.
- Feature graphic.
- Phone screenshots.
- Short description.
- Full description.
- Privacy policy URL.
- Support email.
- App category.
- Content rating questionnaire.
- Data safety form.
- Target countries and pricing.

## Testing Before Production

- Start with internal testing.
- Use closed testing before production.
- New personal developer accounts may need at least 12 opted-in testers for 14 continuous days before production access.
- Keep a tester list and notes about crashes, export tests, install tests, and device models.

## Selling

- Decide whether the app is paid up front, free, or uses in-app purchases.
- If selling digital goods or subscriptions inside the app, plan for Google Play Billing and service fees.
- If charging up front only, set the app price in Play Console pricing.
'@ -NoNewline

$Text = Get-Content -LiteralPath $PlayStore -Raw
foreach ($Needle in @("signed Android App Bundle", "12 opted-in testers", "14 continuous days", "Google Play Billing", "one-time Google Play developer registration fee")) {
    if ($Text.IndexOf($Needle, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "Verification failed. Missing Play Store requirement: $Needle"
    }
}

Write-Host "Play Store requirements starter updated."
