# BrightSteps — Android app (APK)

A thin **Capacitor** shell that opens the live web app
(`https://exampulse.streamlit.app`) full-screen with your icon and splash —
no address bar. It is a window onto the real app, not a copy: it needs
internet, and the usual 12-hour cold-start still applies.

**Cost: $0** — built by GitHub Actions and sideloaded (shared as a file).
No Play Store, no developer account.

## Build the APK (recommended: GitHub Actions)

Every push that touches `mobile/` builds automatically:

1. Open the repo → **Actions** → **Build Android APK**
2. Wait for the green run (~4–6 min)
3. Open the run → **Artifacts** → download `brightsteps-apk`
   (a `.zip` containing `app-debug.apk`)
4. Or trigger manually: **Run workflow** on that screen

## Release signing (removes the "suspicious app" label)

Debug-keyed APKs trip Play Protect. CI therefore signs with a proper
**release keystore** stored as GitHub Actions secrets:

- `ANDROID_KEYSTORE_B64` — base64 of `release.keystore`
- `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` (`brightsteps`), `ANDROID_KEY_PASSWORD`

If the secrets are missing, the workflow falls back to a debug build and
prints a warning. **Back the keystore file up somewhere safe** — without it,
future updates can't install over existing ones (users would uninstall/reinstall).

## Build locally (optional)

Needs Node 20+, JDK 17, and the Android SDK (Android Studio is the easy way).

```bash
cd mobile
npm ci
npx cap add android
npx capacitor-assets generate
npx cap sync android
cd android && ./gradlew assembleDebug
# APK: android/app/build/outputs/apk/debug/app-debug.apk
```

## Install on a phone

1. Send the `.apk` to yourself (WhatsApp/Drive/USB)
2. Tap it → Android asks to allow **unknown sources** for your browser/file app → allow once
3. The **BrightSteps** icon appears in the launcher

## Updates

- **Web app changes** (scores, pages, styling) appear instantly — the APK loads the live site, so no rebuild is needed.
- **Icon / app name / config changes** → rebuild the APK (one Actions run).

## Removing it (back to pure v2)

```bash
git rm -r mobile .github/workflows/build-apk.yml
```

The web app and its Streamlit deploy are never affected by this folder —
`requirements.txt`, `app.py`, and the test suite are untouched (51/51).
