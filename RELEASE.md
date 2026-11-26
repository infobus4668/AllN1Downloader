# AllN1Downloader — release and update guide

## 1.1.1 changes

- Added support for numbered X photo links and verified the reported photo end to end.
- Fixed Instagram VP9 format selection and Windows media verification when metadata contains non-ASCII text.
- Original-file downloads now follow same-file EPUB handoffs, such as Standard Ebooks.
- Improved analysis messages for sign-in, rate limits, removed posts, protected streams, and server outages.
- Added a [repeatable live QA matrix](LIVE_SOURCE_QA.md) with verified examples and known provider limits.

## 1.1.0 changes

- Added original image and document downloads, plus a shared direct-file path
  for supported video and audio files. The link picker and batch queue include
  **Auto detect**, **Images** and **Documents**.
- Added Wikimedia Commons, Internet Archive and arXiv adapters, plus a bounded
  list of eligible files linked from a public page.
- See [verified sources and limits](DOWNLOAD_PLAN.md).
- Android opens the system file picker for `cookies.txt`. Original-file
  downloads now handle compressed responses, prefer recognized response types
  over mismatched filename extensions, and distinguish collection entries whose
  URLs differ by query parameters.
- Debian CI checks startup and loopback URL protection from the executable
  extracted from the actual package.

## 1.0.3 changes

- Instagram-style media formats stay selectable even if the source does not
  report the codec or resolution. Select **Best available** for unknown resolutions.
- **Connection settings → Cookies file** accepts a Netscape `cookies.txt` export
  on desktop and Android. Cookie contents are kept in memory, not in saved settings
  or job history. Select the file again after restarting the app.
- Browser-cookie load errors now explain how to retry or use a cookie file instead.

## 1.0.2 changes

- Update checks validate the expected repository, release tag and package name.
  Windows also requires a SHA-256 match before checking the pinned Authenticode
  signer. Android retains its package ID and signing identity and uses `versionCode` 5.
- Preferences distinguishes a missing release or package from an unavailable
  check and stops polling if a check does not complete.
- Pull requests always use the GitHub-hosted Android runner, even if a custom
  runner is configured for maintainer-triggered builds.

**Deployment:** one application process, one OS user, loopback only. Run from
a writable directory. Desktop actions use the user's file manager/player; the
Android build runs the same UI and backend on-device and uses Android intents
for exported/opened files.
The app doesn't provide accounts, per-user access control, or a shared queue
service. Don't expose it through a public proxy or run multiple workers on the
same history directory.

## What changed and why

| Perspective | Issue found | Release behavior |
|---|---|---|
| First launch | The old launcher installed into the system interpreter on every start and advertised an unsupported Python version. | Python 3.11+, project venv, exact direct dependency versions, `pip check` after installation. |
| Entering links | Batch submission silently discarded invalid lines and links beyond the limit. Cookies and proxy settings were hidden until analysis succeeded. | Batch preflight identifies the bad line or excessive count before creating jobs. Partial API failures retain unsubmitted links. Connection settings and inline analysis errors are available at the input. |
| Choosing a playlist | Selecting everything in a truncated preview could queue unseen entries. | Single-link downloads submit the checked indices, even when the preview is truncated. |
| Job reliability | Cancelling and immediately retrying a waiting job could leave two workers targeting its files. | Pending executor work is cancelled before retry. A still-running attempt cannot be retried. A nonzero downloader result is not treated as success just because a file exists. |
| Working with results | Open file picked the first output, even a subtitle or other sidecar. | Desktop playback selects a supported media file from a completed job; other outputs remain available via the folder. |
| Choosing quality | The picker couldn't show which resolution a container would actually select, and there was no check of the saved file. | Expected-stream preview reports the container, resolution and codec; ffprobe verification reports the actual streams after completion and notes requested-height or codec differences. |
| Managing history | Tidy-up actions deleted files, so clearing a list could destroy downloads. | **Remove from history** keeps files; **Delete files** and **Clear finished** explicitly remove them. |
| Re-downloading | Re-submitting the same link and settings created duplicate work and files; no-op precision flags could evade the guard. | A fingerprint of URL plus effective settings rejects active or completed duplicates; ineffective clip settings are normalized. **Add another copy** overrides. Batch mode skips duplicates. |
| Long recordings | Saving one segment required an external editor; a start beyond the media duration could create an empty failed job. | Optional start/end clipping with validated times and duration-bound checks. Stream copy is the default; frame-accurate video cuts re-encode. Single links only. |
| Unsupported output | A format absent from the analyzed source could still be submitted and fail later. | The UI disables Download when no compatible video variant is available for the selected container/codec/quality. |
| Queue actions | Open file could appear for sidecar-only output; Retry could race the worker's final return. | Open file is shown only when a playable file exists. Retry controls wait until the attempt future has completed. |
| Desktop distribution | Users needed Python and project setup to launch the app. | PyInstaller builds a Windows `.exe` and Debian/Ubuntu `.deb`; frozen assets are read from the bundle while history/downloads go to per-user writable storage. |
| Android distribution | The desktop server could not run unchanged on Android's storage and background-execution model. | A GPL-3.0 Android module embeds Chaquopy Python 3.12, the current yt-dlp package and the shared FastAPI UI, plus Android FFmpeg/QuickJS. A foreground data-sync service keeps active jobs alive. |
| Operations | There was no permanent release test and a damaged queue file could be overwritten. | Repeatable local fixture tests, CI workflow, configurable storage, and preservation of unreadable JSON. |

SponsorBlock now registers both lookup and chapter-removal processors. Whether
there are segments to remove still depends on the source and remote service.

Dependency update automation, CI validation, and toolchain update policy are
documented in [DEPENDENCIES.md](DEPENDENCIES.md).

## AllN1Downloader 1.0.1 clean build

- Updated yt-dlp to `2026.11.23` on desktop and Android. Android uses FastAPI
  `0.125.0` with Pydantic `1.10.27`; desktop uses FastAPI `0.165.0`. Both use
  Uvicorn `0.54.0`.
- Updated Android Gradle Plugin to `9.5.2`, build-tools to `37.0.0`, and NDK to
  `30.0.16248370`; the target API remains 37. The app version is `1.0.1` and
  Android `versionCode` is `4` so existing installs can upgrade. Its historical
  application ID is retained for signing and data continuity.
- Built and signed `android/app/build/outputs/apk/release/app-release.apk` and
  `android/app/build/outputs/bundle/release/app-release.aab` with the persistent
  Android keystore; APK/AAB signature verification and Android Lint passed. The
  API 36 instrumentation test compiles, but the GitHub-hosted runner could not
  boot its software-only emulator, so the 1.0.1 instrumentation run is unverified.
- Rebuilt and signed `dist/AllN1Downloader.exe` using Python 3.12.16, PyInstaller
  `6.22.3`, yt-dlp `2026.11.23`, FFmpeg `9.1`, and Node `26.8.1`. The Windows
  frozen-app smoke test passed. Its self-signed Authenticode certificate is
  timestamped but is not publicly trusted.
- Built `alln1downloader_1.0.1_amd64.deb` in the Ubuntu 22.04 package workflow.
  Its detached signature and signed APT `InRelease` metadata were verified with
  the committed public archive key; the repository is published on GitHub Pages.

## Runtime updates

Source checkouts launched through `start.bat` or `bash start.sh` fast-forward a
clean Git branch at startup, then install the repository's pinned dependencies
if they changed. Set `ALLN1_AUTO_UPDATE=0` to opt out; dirty checkouts are left
alone.

Installed Windows and Android clients check the public GitHub Releases feed for
`infobus4668/AllN1Downloader` at startup. Windows downloads the newer
timestamped EXE, verifies the pinned signer identity, and replaces/restarts if
the executable directory is writable and no downloads are active. Android
downloads an APK signed with the existing app key and asks Android's package
installer for confirmation. Debian packages configure a signed APT repository;
the app can start an APT upgrade through the system's authorization prompt, and
standard OS update tools can also apply it. Client auto-updates require a
published signed release (and the signed APT repository for Debian). The
GitHub Actions tag-publishing workflow additionally requires the signing secrets
documented in `SIGNING.md`; the 1.0.1 release was signed locally and published
with its verified assets.

ZIP exports use an independent temporary archive per request. Sending or
interrupting an export closes that archive without removing the downloaded
media. Preferences uses a native dialog with keyboard focus restoration; the
downloads-folder action is in the queue toolbar.

Clipping is limited to single links because applying one time range to every
item in a playlist is ambiguous. Fast cuts stream-copy and can include a partial
keyframe at the boundary; the precise option re-encodes video. Audio is always
stream-copied so **Original** audio keeps its codec. Clipping needs FFmpeg.
Duplicate detection compares normalized effective settings, not title or
thumbnail, so changing the resolution, codec, clip or other option is a new job.

## Startup, backup and rollback

- Windows: `start.bat --setup-only` installs/checks dependencies without starting
  the server. `start.bat` runs the app. See `/api/health` or Preferences for
  the actual application version, FFmpeg availability, free disk and storage path.
- Use `ALLINONE_HOME` to choose a different writable location for **both**
  `data/` and `downloads/`. Existing files aren't automatically migrated.
  Keep one process per location. Source runs default next to `app.py`; frozen
  Windows/Linux/macOS builds use the current user's application-data directory.
- Before upgrading, finish active downloads, stop the app, then copy `data/`
  and `downloads/` together. These may contain private titles, links, paths,
  logs and proxy settings. Protect the backup as you would the files themselves.
- To roll back, stop the app, restore the previous application files and that
  backup, and recreate the project's `.venv` using the previous requirements.
  Don't remove `downloads/` when repairing the environment.
- Corrupt JSON is renamed to `data/jobs-unreadable-*.json` before starting
  with an empty history. Download files aren't deleted. A history write
  failure is logged to the process console; check disk space and permissions.
- History is bounded to 300 jobs. At capacity, new submissions are rejected
  rather than silently dropping more history at the next launch.

## Repeat the release checks

Requires FFmpeg and ffprobe. Windows PowerShell from the project folder:

```powershell
.\start.bat --setup-only
.\.venv\Scripts\python.exe -m pip check
node --check static/app.js
$env:SMOKE_BROWSER = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Build the Windows package with
`.\packaging\build_windows.ps1`; optionally set `FFMPEG_DIR` to bundle FFmpeg
and ffprobe. The build automatically bundles Node
when it is on `PATH`. Verify the result with
   `python packaging/smoke_windows.py dist/AllN1Downloader.exe`. Debian package creation
is Linux-only: `PYTHON=.venv/bin/python bash packaging/build_linux.sh`; the
Ubuntu 22.04 CI job builds and uploads that artifact.

## Publisher signing

See [SIGNING.md](SIGNING.md) for the generated key inventory, secret-copy
commands, local build verification and the status of the self-signed Windows
certificate.

Release-tag workflows require signing credentials. Store them as GitHub
repository secrets; never add them to the repository:

| Platform | Secrets | Result |
|---|---|---|
| Android | `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD` | Release APK and AAB signed with the persistent publisher keystore. Back up this keystore securely; Android updates must retain the same signing identity. |
| Windows | `WINDOWS_SIGN_PFX_BASE64`, `WINDOWS_SIGN_PASSWORD` | Authenticode-signed EXE. The current updater pins the self-signed certificate; Windows may still show an unknown-publisher warning. |
| Debian | `DEB_SIGNING_KEY_BASE64`, `DEB_SIGNING_KEY_ID`, `DEB_SIGNING_PASSPHRASE` | `.deb.asc` detached signature plus signed `SHA256SUMS` for artifact verification. |

For Android, Base64-encode the existing release `.jks` or `.keystore` into
`ANDROID_KEYSTORE_BASE64`; set the remaining values to its passwords and alias.
The workflow decodes it into the ephemeral runner temp directory. A local
release build uses the same environment variables:

```powershell
$env:ANDROID_KEYSTORE_PATH = 'C:\secure\android-release.p12'
$env:ANDROID_KEYSTORE_PASSWORD = '...'
$env:ANDROID_KEY_ALIAS = '...'
$env:ANDROID_KEY_PASSWORD = '...'
.\android\gradlew.bat -p android assembleRelease bundleRelease -PsignRelease=true `
  -PchaquopyBuildPython='C:/path/to/python3.12.exe'
```

For Windows release builds, configure the existing PFX and password as
repository secrets. The updater pins this self-signed signer for integrity, but
Windows may still show an unknown-publisher warning. See `SIGNING.md` before
replacing it with a CA-issued certificate or cloud/HSM signer.

For Debian, Base64-encode an ASCII-armored GPG private-key export into
`DEB_SIGNING_KEY_BASE64`, and set the matching key ID and passphrase. On Linux,
run `bash packaging/build_linux.sh`; verify results with
`gpg --verify dist/SHA256SUMS.asc dist/SHA256SUMS` and
`(cd dist && sha256sum --check SHA256SUMS)`. Detached signatures let recipients verify
downloaded artifacts using the publisher's separately obtained public key.

`SMOKE_BROWSER` is optional; setting it adds a headless Chromium-family browser
check (Node 22+). Tests create a temporary storage root, isolated browser
profile, local WAV source and loopback ports. They don't clear the live queue
or depend on YouTube. `.github/workflows/release-check.yml` runs the suite on
Ubuntu when enabled in a GitHub repository.

**Evidence on this release:** all twenty tests passed on Python 3.12.16;
`pip check`, JavaScript syntax, and Edge browser checks passed. Browser coverage
includes input, preferences, presets, playlist selection, filters, batch
submission, duplicate handling, queue controls and job actions, including the
390px layout. The frozen Windows 1.0.1 executable smoke passed with the updated
yt-dlp, bundled FFmpeg/ffprobe and Node; it verified MP3 conversion and ZIP
export. The Android 1.0.1 APK/AAB were signed with the persistent Android
keystore and signature-verified. Android Lint passed with the updated
yt-dlp/FastAPI/Uvicorn stack. The API 36 instrumentation test compiled, but its
GitHub-hosted software emulator did not boot, so that test is not confirmed for
1.0.1. The Debian package and signed APT repository were built in Ubuntu CI and
verified against the publisher's public key.
Before broad distribution,
verify real-site features (including subtitles, signed-in sources, SponsorBlock
and precise video cuts), and check keyboard/screen-reader usability on the
intended desktop platforms.
