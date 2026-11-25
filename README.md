# AllN1Downloader

A local-first video and audio downloader for desktop and Android, with a
loopback web interface. See the
[release notes and verification guide](RELEASE.md) for the supported deployment,
checks and backup procedure.
Dependency update automation and its review/validation process are described
in [DEPENDENCIES.md](DEPENDENCIES.md).
Paste a link, pick a format, and download video, audio, playlists and subtitles
from YouTube, Instagram, TikTok, X, Reddit, SoundCloud, Vimeo, Twitch and
1,800+ other sites.

Built on the best open-source tools available:

- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** — the actively maintained,
  feature-complete downloader engine (supports 1,800+ extractors, DASH/HLS,
  playlists, subtitles, cookies and more).
- **[FFmpeg](https://ffmpeg.org/)** — muxing, audio extraction and subtitle
  conversion.
- **[FastAPI](https://fastapi.tiangolo.com/)** + vanilla JS — a tiny local
  backend and a dependency-free frontend.

## Latest release: 1.0.1

- [Windows x64](https://github.com/infobus4668/AllN1Downloader/releases/latest/download/AllN1Downloader-Windows-x64.exe)
- [Android APK](https://github.com/infobus4668/AllN1Downloader/releases/latest/download/AllN1Downloader-Android.apk)
- [Android App Bundle](https://github.com/infobus4668/AllN1Downloader/releases/latest/download/AllN1Downloader-Android.aab)
- [Debian/Ubuntu amd64 package](https://github.com/infobus4668/AllN1Downloader/releases/latest/download/alln1downloader_1.0.1_amd64.deb)

The Debian package configures the [signed APT repository](https://infobus4668.github.io/AllN1Downloader/apt).

## Features

- Video downloads up to 4K/8K, merged automatically with FFmpeg
- Codec-aware quality picker (H.264, VP9, AV1, HEVC) with size estimates
- Expected-stream preview shows the container, resolution and codec the app will
  target, and flags when a higher resolution is available in MKV
- Finished downloads are verified with ffprobe; each job card shows the actual
  resolution, codec, frame rate and audio bitrate that was written
- One-click presets for maximum quality, device compatibility, efficient video,
  and common audio formats
- Audio-only extraction to MP3, M4A, Opus, WAV or FLAC, with bitrate choice
- Container selection: MP4, MKV, WebM
- Clip a time range from a single video or audio file (seconds, `mm:ss` or
  `hh:mm:ss`) with a fast stream-copy cut or a frame-accurate video re-encode
- Full playlist support with per-item selection, search filter and ZIP export
- Subtitles (manual + auto-generated), converted to SRT
- Live progress: percentage, speed, ETA, current playlist item, per-job logs
- Persistent queue (survives app restarts) with retry, cancel, open file,
  open folder, copy path and clear-finished actions
- Duplicate guard: an identical URL and settings combination is refused while it
  is queued or after it completed; choose "Add another copy" to override
- Remove a job from history without deleting its files, or delete the files
  separately
- Batch mode: queue up to 50 links at once with shared settings
- Optional embed thumbnails, SponsorBlock, speed limits, proxies and browser
  cookies (Chrome, Edge, Firefox, Brave, …)
- Queue filters and search, retry-failed-all, desktop notifications, five accent
  themes and drag-and-drop links
- Keyboard shortcuts: `/` focuses the URL box, `Ctrl+Enter` analyzes/downloads,
  `Esc` closes panels
- Download processing and queue history stay on your device. Source sites,
  thumbnail hosts, the optional SponsorBlock service, and YouTube solver
  downloads still require network access.

## Quick start (Windows)

1. Install Python **3.11+** with `python` on PATH. Double-click **`start.bat`**.
2. Your browser opens at `http://127.0.0.1:8765`.
3. Paste a link and hit **Analyze**, choose your options, then **Download**.

The launcher creates a private `.venv`, fast-forwards a clean Git checkout on
startup when Git is installed, and installs the pinned dependencies when
`requirements.txt` changes. Source ZIP copies without `.git` cannot auto-update.
Set `ALLN1_AUTO_UPDATE=0` to disable source checkout updates. FFmpeg is required
for merging/conversion — install it with:

```powershell
winget install Gyan.FFmpeg
```

The app auto-detects FFmpeg from `PATH` or the WinGet package folder. The
engine badge in the header shows whether FFmpeg is ready.

For YouTube, yt-dlp also uses a JavaScript runtime to unlock all formats.
Install **Node.js** (already present on most dev machines) or **Deno**; the app
detects either automatically.

## Quick start (Linux / macOS)

```bash
bash start.sh
```

`start.sh` updates a clean Git checkout and its pinned Python environment before
launching. Git is required; source archives without `.git` do not auto-update.
Set `ALLN1_AUTO_UPDATE=0` to disable the Git update check.

Install FFmpeg with your package manager (`sudo apt install ffmpeg`,
`brew install ffmpeg`, …).

## Desktop packages

The desktop builds bundle Python and the application dependencies, then open the
local interface in the system browser. Download data is stored per OS user
outside the application bundle. The existing `AllInOne` data folder and
`ALLINONE_HOME` setting are retained for upgrade continuity.

- **Windows `.exe`:** from PowerShell, run `.\packaging\build_windows.ps1` with
  Python 3.11+. The output is `dist/AllN1Downloader.exe`. FFmpeg and ffprobe must be
  installed and available on `PATH`; to embed them at build time, set
  `FFMPEG_DIR` to a directory containing both executables. Node.js found on the
  build `PATH` is embedded for YouTube's JavaScript challenge solver.
- **Debian/Ubuntu `.deb`:** install Python 3.11+, `python3-venv`, FFmpeg,
  `xdg-utils`, and `dpkg-deb`, then build from the project root:

  ```bash
  python3 -m venv .venv
  PYTHON=.venv/bin/python bash packaging/build_linux.sh
  ```

  The build script installs its pinned requirements. The package installs a
  desktop-menu entry, configures the signed AllN1Downloader APT repository, and
  declares FFmpeg as a dependency.
- With the required publisher secrets configured, pushing a `v*` tag runs the
  signed Windows, Android and Debian release workflow and publishes the APT
  repository. The current `v1.0.1` release is available from the links above.
  Dependabot and the Android SDK updater open dependency-update PRs weekly.
- **Standalone Android APK:** uses an on-device Python 3.12 runtime and local
  loopback server; downloads and history stay on the phone. Build with Android
  SDK 37, JDK 21+, and Python 3.12:

  ```powershell
  $env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
  $env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
  .\android\gradlew.bat -p android assembleDebug assembleDebugAndroidTest lintDebug `
    -PchaquopyBuildPython='C:/path/to/python3.12.exe'
  ```

  With an emulator or Android device connected, append
  `connectedDebugAndroidTest` to run the embedded-server download smoke test.

  The debug APK is `android/app/build/outputs/apk/debug/app-debug.apk` and
  supports Android 10+ on 64-bit ARM or x86 devices. Downloads use the phone's
  app storage; tapping **Save file** or **Download ZIP** exports them to the
  system Downloads folder. Browser-cookie extraction is unavailable on Android.
  The Android module is GPL-3.0; its license and third-party notices are bundled
  in the APK. Release APKs need signing with the publisher's own key.
- The Android workflow builds a debug APK and compiles the instrumentation test.
  Set the repository variable `ANDROID_EMULATOR_TESTS=true` and use a runner with
  emulator hardware acceleration to run the API 36 smoke test; the current
  hosted runner could not boot its software-only emulator.

### Publisher signing

See [SIGNING.md](SIGNING.md) for the generated keys and fingerprints, secure
credential handling, GitHub Actions secret setup, verification commands, and
Windows trust limitations. Windows release builds use the pinned self-signed
certificate; the updater verifies that signer, although Windows may still warn
that it is an unknown publisher. Android and Debian update signatures are
verified using their persistent publisher keys.

### App updates

Source launches fast-forward a clean Git checkout and apply changed dependency
pins. Installed Windows and Android apps check the public GitHub Releases feed
at startup. Windows downloads and verifies the pinned-signer EXE, then replaces
and restarts when the install folder is writable and no downloads are active.
Android downloads a matching signed APK and the OS asks for install
confirmation. Debian/Ubuntu packages use the signed APT repository and system
authorization prompt. These updates use the latest published release at
`github.com/infobus4668/AllN1Downloader/releases/latest`.

For YouTube extraction, install Node.js or Deno on desktop; the Android APK
bundles QuickJS. These are local applications: media processing and downloaded
files stay on the device. The Android app uses a foreground service while
downloads are active and requires network access to the source sites and yt-dlp
JavaScript challenge components.

## Usage notes

- Downloads are stored in the `downloads/` folder, one subfolder per job.
- The queue is saved to `data/jobs.json` and restored on launch. Jobs that were
  running when the app stopped are marked failed — use **Retry** to resume.
- Job cards show per-file links, **Logs**, **Open file**, **Open folder** and
  **Copy path** actions once files exist. Use **Retry** on failed jobs.
- **Remove from history** clears the queue entry but leaves downloaded files on
  disk. **Delete files** removes both the entry and its files. **Clear finished**
  also deletes the output files of every finished job — save anything you need
  first.
- Use the queue search box to find a title, URL or job ID; **Retry failed**
  restarts every failed or cancelled job at once.
- **Batch links** queues every http(s) link (one per line) with the chosen
  type, quality and format. Playlist links in batch mode download in full.
  Links already queued or saved with the same settings are skipped.
- **Clip a section** accepts a start and optional end time. Leave the end blank
  to keep everything after the start. Fast cuts copy the streams; "frame-accurate
  video cut" re-encodes video for exact boundaries. Audio is stream-copied, and
  subtitles are not trimmed. Clipping is for single links, not playlists.
- Playlist jobs with multiple output files get a **Download ZIP** button.
  Single-link analysis previews up to 200 entries and downloads only checked
  items. Batch mode instead processes whole playlist links.
- Set the port with the `PORT` environment variable (default `8765`).
  Set `NO_BROWSER=1` to stop the app from opening a browser tab.
- YouTube sometimes asks for sign-in or bot verification. In **Connection settings →
  Cookies from browser**, pick the browser you are signed into YouTube with and
  analyze the link again.
- If cookie extraction fails on Chrome/Edge, close the browser first (the
  cookie database is locked while it runs).
- **Connection settings** is available before analysis. It accepts an optional
  HTTP/SOCKS proxy; invalid addresses produce an error. The download panel
  offers thumbnail embedding, SponsorBlock removal, and a speed limit.

## Quality notes

- **Best available** selects the highest resolution offered (verified up to
  2160p AV1). Resolution beats everything else, so 8K/4K is preferred when
  the site provides it.
- **Container matters.** Some sites only offer high resolutions in WebM/VP9 or
  AV1. `MP4` prefers native MP4 streams and can remux other streams into MP4;
  playback support depends on the device. `MKV` places no codec restrictions
  and is the safest choice for maximum quality. `WebM` is limited to
  WebM-compatible codecs and may not be available for every source.
- **Audio "Original"** downloads the best source audio (Opus/AAC) with no
  re-encoding — this is the highest-fidelity option. `MP3 320` and `M4A 256`
  are convenience conversions and always lose a generation of quality.
- Codec compatibility: AV1/VP9 files may not play on older TVs, phones or
  editors. If a device rejects the "best" file, download the 1080p MP4 preset.
- **Expected vs verified.** The preview uses the published format list to show
  the stream the app expects to select. After the download, ffprobe reports the
  file that was actually written; if the requested height or codec differs from
  the result, the job card says so. Multi-file jobs inspect the first playable
  output.
- YouTube extraction uses a JavaScript runtime (Node.js or Deno) plus yt-dlp's
  official EJS challenge-solver component, fetched automatically from GitHub,
  to unlock all available formats.

## Project layout

```
app.py              FastAPI backend + yt-dlp job manager
static/index.html   Web UI
static/style.css    Styles
static/app.js       Frontend logic
downloads/          Output files (created at runtime)
data/jobs.json      Persisted queue state (created at runtime)
start.bat           One-click Windows launcher
```

## Troubleshooting

- **"FFmpeg missing" badge** — install FFmpeg and restart the app.
- **"Sign in to confirm you're not a bot"** — select your signed-in browser in Connection settings.
- **Analysis fails for one site** — check the source URL and permissions.
  Extractors change; for a dependency update, change its release pin and run
  the checks in `RELEASE.md` before rolling it out.
- **Download stuck at 99%** — FFmpeg is merging/remuxing; large files can
  take a moment.

## Legal

This tool is intended for downloading content you own or have permission to
download (public domain, Creative Commons, your own uploads, etc.). Respect
the terms of service and copyright laws of the sites you use.
