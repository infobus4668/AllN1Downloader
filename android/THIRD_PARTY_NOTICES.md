# Android APK third-party notices

The Android application/module is distributed under **GPL-3.0-only**. The
complete license text is in [`LICENSE`](LICENSE). APK recipients must be offered
the corresponding source for the Android module and the shared Python backend
included in the APK.

## Included libraries

- [youtubedl-android](https://github.com/yausername/youtubedl-android) 0.18.1:
  GPL-3.0; provides Android QuickJS, FFmpeg and shared Python support libraries.
  Chaquopy provides the Python 3.12 runtime used by the app.
- [Chaquopy](https://chaquo.com/chaquopy/) 17.2.0: open-source Android Python
  integration, released on Maven Central.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) 2026.11.23: Unlicense.
- [FastAPI](https://github.com/fastapi/fastapi), Starlette, Uvicorn and Pydantic:
  their respective MIT/BSD licenses; see their upstream package metadata.
- Android NDK `libc++_shared.so`: LLVM Project, Apache License 2.0 with LLVM
  Exceptions.

FFmpeg builds contain additional third-party codecs and components. Their exact
license set depends on the Android library build; consult the upstream
youtubedl-android FFmpeg notices before redistributing APKs.
