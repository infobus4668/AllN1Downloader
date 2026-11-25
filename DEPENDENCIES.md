# Dependency update automation

## How updates are proposed

GitHub Dependabot checks the dependency manifests every Tuesday at 06:00 UTC
and opens grouped update pull requests. It covers:

| Ecosystem | Manifests / location | What it updates |
|---|---|---|
| Python / pip | `/requirements.txt` | Desktop app runtime: yt-dlp, FastAPI, Uvicorn. |
| Python / pip | `/android/app/requirements.txt` | Android-bundled Python runtime, including yt-dlp, FastAPI, Pydantic, Uvicorn and certifi. |
| Python / pip | `/packaging/requirements-build.txt` | Python packaging tools such as PyInstaller. |
| Gradle | `/android` | Android Gradle Plugin, Chaquopy, AndroidX, the Android yt-dlp integration, FFmpeg/QuickJS native library, and Gradle wrapper. |
| GitHub Actions | `/.github/workflows` | Versions of actions used by CI and packaging workflows. |

Updates are grouped by ecosystem/target to reduce review noise. GitHub can also
create Dependabot security update pull requests when security updates are
enabled in repository settings and an applicable vulnerability is detected.
The Android SDK build-tools and NDK pins are checked weekly by
`.github/workflows/update-android-sdk.yml`; when a newer stable package exists,
it updates the pins and runs the Android build and lint before opening a pull
request. Set the repository variable `ANDROID_EMULATOR_TESTS=true` on a runner
with emulator hardware acceleration to also run instrumentation. Updates are
**not auto-merged**: a maintainer reviews the changes and merges after the
required checks pass.

## Validation before merging

Dependency-related pull requests automatically run:

- `.github/workflows/release-check.yml`: Python dependency consistency, app
  tests, browser smoke checks, and JavaScript syntax.
- `.github/workflows/package-desktop.yml`: Windows frozen-app build and smoke
  test, plus the Ubuntu `.deb` build.
- `.github/workflows/android-apk.yml`: Android debug build and lint; optional
  API 36 emulator instrumentation when `ANDROID_EMULATOR_TESTS=true`.

The packaging and Android workflows run on pull requests that change their
respective manifests, source/assets, build scripts, or workflow files. CI does
not receive signing secrets for Dependabot pull requests, so those checks build
unsigned test artifacts. Signed release builds still require the publisher
credentials documented in `SIGNING.md`.

## What an accepted update changes for users

- **Source desktop install:** `start.bat` / `start.sh` fast-forward a clean Git
  checkout, then reinstall pinned requirements when the manifest changes and
  run `pip check`. Set `ALLN1_AUTO_UPDATE=0` to opt out.
- **Windows EXE:** checks the public GitHub Releases feed at startup. When a
  newer signed EXE is available and there are no active jobs, it downloads the
  file, verifies the pinned Authenticode identity, and replaces/restarts the
  app if the install directory is writable.
- **Android APK:** checks and downloads the newer signed APK on startup. Android
  verifies that it has the same application ID and signing certificate, then
  asks the user to confirm installation in the system package installer.
- **Debian `.deb`:** installs the signed APT source/keyring. The app can request
  an OS-authorized APT upgrade; users can also update with their normal package
  manager. The repository metadata is published with each GitHub release.

## Toolchains and externally managed components

Some components are intentionally updated outside Dependabot's package
manifests:

- The Windows packaging workflow uses Node.js 22 and downloads the current
  FFmpeg essentials archive when it builds. These are floating to newer patch
  releases at build time; review the resulting build and smoke-test output.
- The Ubuntu packaging job gets FFmpeg from the Ubuntu 22.04 package
  repository. Debian/Ubuntu users update this system dependency through their
  normal OS package manager.
- The Android build pins the compile/target platform to API 37, build-tools
  37.0.0, NDK 30.0.16248370, and the embedded Python runtime to 3.12. Build
  tools and NDK versions live in `android/build-tools-version.txt` and
  `android/ndk-version.txt`; the scheduled workflow proposes newer stable
  versions after Android tests pass. The compile/target API level remains a
  deliberate manual upgrade because it can change app behavior and platform
  requirements.
- Desktop source installs use the user's Python 3.11+ installation and local
  FFmpeg/JavaScript runtime. AllN1Downloader does not upgrade those system tools.

Python requirement files pin the direct dependencies. Pip resolves compatible
transitive dependencies during installation/build; the repository does not
currently maintain fully compiled lockfiles for every OS and Python runtime.
Dependabot security alerts and the platform build/test jobs are the safeguards
for those resolver updates.

## Current pins

- Desktop runtime: yt-dlp `2026.11.23`, FastAPI `0.165.0`, Uvicorn `0.54.0`
  in `requirements.txt`.
- Android Python runtime: yt-dlp `2026.11.23`, FastAPI `0.125.0` (Pydantic v1
  compatible), Pydantic `1.10.27`, Uvicorn `0.54.0`, certifi `2026.11.20` in
  `android/app/requirements.txt`.
- Build-time Python tool: PyInstaller `6.22.3` in
  `packaging/requirements-build.txt`.
- Android Gradle, native libraries, SDK and NDK: `android/build.gradle.kts`,
  `android/app/build.gradle.kts`, `android/gradle/wrapper/gradle-wrapper.properties`,
  `android/build-tools-version.txt`, `android/ndk-version.txt`, and
  `.github/workflows/android-apk.yml`
