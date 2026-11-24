"""Bootstrap the desktop FastAPI app inside the Android process."""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

_server = None
_thread: Optional[threading.Thread] = None


def start(home: str, static_dir: str, ffmpeg: str, ffprobe: str, quickjs: str,
          python_lib_dir: str, ffmpeg_lib_dir: str, port: int) -> bool:
    global _server, _thread
    if _thread and _thread.is_alive():
        return True
    os.environ.update({
        "ALLINONE_ANDROID": "1",
        "ALLINONE_HOME": home,
        "ALLINONE_STATIC_DIR": static_dir,
        "HOME": home,
    })
    if ffmpeg:
        os.environ["ALLINONE_FFMPEG"] = ffmpeg
    if ffprobe:
        os.environ["ALLINONE_FFPROBE"] = ffprobe
    if quickjs:
        os.environ["ALLINONE_JS_RUNTIME_NAME"] = "quickjs"
        os.environ["ALLINONE_JS_RUNTIME_PATH"] = quickjs
    if python_lib_dir:
        os.environ["SSL_CERT_FILE"] = str(__import__("pathlib").Path(python_lib_dir).parent / "etc" / "tls" / "cert.pem")
    if ffmpeg_lib_dir or python_lib_dir:
        native_lib_dir = os.path.dirname(ffmpeg) if ffmpeg else ""
        paths = [path for path in (native_lib_dir, python_lib_dir, ffmpeg_lib_dir,
                                   os.environ.get("LD_LIBRARY_PATH", "")) if path]
        os.environ["LD_LIBRARY_PATH"] = ":".join(paths)

    import app
    import uvicorn

    _server = uvicorn.Server(uvicorn.Config(
        app.app, host="127.0.0.1", port=int(port), log_level="warning", access_log=False
    ))
    _thread = threading.Thread(target=_server.run, name="alln1downloader-api", daemon=True)
    _thread.start()
    deadline = time.time() + 20
    while time.time() < deadline:
        if _server.started:
            return True
        if not _thread.is_alive():
            raise RuntimeError("AllN1Downloader's embedded server stopped during startup")
        time.sleep(0.1)
    raise TimeoutError("AllN1Downloader's embedded server timed out")


def stop() -> None:
    if _server:
        _server.should_exit = True
