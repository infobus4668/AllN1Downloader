"""Smoke-test a frozen Windows build with isolated local storage."""

import json
import functools
import io
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from zipfile import ZipFile
from urllib.error import URLError
from urllib.request import Request, urlopen
import wave


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get_json(url: str) -> dict:
    with urlopen(url, timeout=4) as response:
        return json.load(response)


def post_json(url: str, body: dict) -> dict:
    request = Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python packaging/smoke_windows.py path\\to\\AllN1Downloader.exe")
    executable = Path(sys.argv[1]).resolve()
    if not executable.is_file():
        raise SystemExit(f"Executable not found: {executable}")
    if os.name == "nt" and os.environ.get("VERIFY_WINDOWS_SIGNATURE") == "1":
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from update_service import WINDOWS_SIGNER_THUMBPRINT, verify_windows_signature

        verify_windows_signature(executable, os.environ.get("WINDOWS_SIGN_CERT_THUMBPRINT", WINDOWS_SIGNER_THUMBPRINT))
    project_root = Path(__file__).resolve().parents[1]
    app_source = (project_root / "app.py").read_text(encoding="utf-8")
    version_match = re.search(r'^APP_VERSION = "([^"]+)"$', app_source, re.MULTILINE)
    if not version_match:
        raise RuntimeError("Could not find APP_VERSION in app.py")
    expected_version = version_match.group(1)
    requirements = project_root / "requirements.txt"
    yt_dlp_pins = [
        entry.partition("==")[2].strip()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if (entry := line.strip()).startswith("yt-dlp==")
    ]
    expected_yt_dlp = yt_dlp_pins[0] if yt_dlp_pins else None
    if not expected_yt_dlp:
        raise RuntimeError("Could not find the pinned yt-dlp version in requirements.txt")
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="alln1downloader-frozen-") as home:
        source_dir = Path(home) / "source"
        source_dir.mkdir()
        with wave.open(str(source_dir / "tone.wav"), "wb") as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            audio.writeframes(bytes(32000 * 2))
        source_server = ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(SimpleHTTPRequestHandler, directory=str(source_dir))
        )
        threading.Thread(target=source_server.serve_forever, daemon=True).start()
        env = dict(os.environ, ALLINONE_HOME=home, ALLN1_DISABLE_UPDATE_CHECK="1", NO_BROWSER="1", PORT=str(port))
        # Prove the frozen app uses bundled FFmpeg/Node rather than the build host PATH.
        env["PATH"] = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
        process = subprocess.Popen([str(executable)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            health = None
            for _ in range(180):
                if process.poll() is not None:
                    log = Path(home) / "allinone.log"
                    detail = log.read_text(encoding="utf-8", errors="replace") if log.exists() else "no app log"
                    raise RuntimeError(f"Frozen app exited with {process.returncode}: {detail}")
                try:
                    health = get_json(base + "/api/health")
                    update_status = get_json(base + "/api/update")
                    break
                except (URLError, TimeoutError, OSError):
                    time.sleep(0.5)
            if health is None:
                raise RuntimeError("Frozen app did not start its local API")
            if health.get("version") != expected_version:
                raise RuntimeError(f"Unexpected version: {health.get('version')}")
            if health.get("yt_dlp") != expected_yt_dlp:
                raise RuntimeError(f"Bundled yt-dlp is {health.get('yt_dlp')}, expected {expected_yt_dlp}")
            if update_status.get("status") != "disabled":
                raise RuntimeError("The local update-status endpoint did not report its test-only disabled state")
            if not health.get("ffmpeg") or health.get("js_runtime") != "node":
                raise RuntimeError("The bundle did not detect its FFmpeg and Node runtimes")
            if Path(health["download_dir"]) != Path(home) / "downloads":
                raise RuntimeError("Frozen app data was not written to the isolated user directory")
            with urlopen(base + "/", timeout=4) as response:
                if b"AllN1Downloader" not in response.read():
                    raise RuntimeError("Bundled home page is missing")
            with urlopen(base + "/static/app.js", timeout=4) as response:
                if b"startDownload" not in response.read():
                    raise RuntimeError("Bundled application script is missing")
            ffmpeg = Path(health["ffmpeg_path"])
            ffprobe = ffmpeg.with_name("ffprobe.exe")
            node = ffmpeg.with_name("node.exe")
            for binary in (ffmpeg, ffprobe, node):
                if not binary.is_file():
                    raise RuntimeError(f"Bundled runtime not found: {binary.name}")
                subprocess.run([str(binary), "-version" if binary != node else "--version"],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            source_url = f"http://127.0.0.1:{source_server.server_port}/tone.wav"
            job = post_json(base + "/api/download", {
                "url": source_url, "mode": "audio", "container": "mp3", "audio_quality": "320",
            })
            job_url = base + "/api/jobs/" + job["id"]
            for _ in range(300):
                job = get_json(job_url)
                if job["status"] in {"completed", "error", "cancelled"}:
                    break
                time.sleep(0.1)
            if job["status"] != "completed" or job.get("media", {}).get("audio", {}).get("codec") != "mp3":
                raise RuntimeError(f"Frozen media conversion failed: {job.get('error') or job['status']}")
            with urlopen(job_url + "/zip", timeout=20) as response, ZipFile(io.BytesIO(response.read())) as archive:
                if not any(name.lower().endswith(".mp3") for name in archive.namelist()):
                    raise RuntimeError("Frozen ZIP export did not contain the converted media")
            print(f"Frozen AllN1Downloader {expected_version}: yt-dlp {expected_yt_dlp}, local MP3 conversion, ffprobe, ZIP, static assets, isolated storage, FFmpeg and Node passed.")
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                else:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            source_server.shutdown()
            source_server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
