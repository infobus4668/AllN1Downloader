#!/usr/bin/env python3
"""AllN1Downloader - a local web app powered by yt-dlp and FFmpeg."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

import yt_dlp
import update_service
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

APP_VERSION = "1.0.0"
UPDATE_REPOSITORY = os.environ.get("ALLN1_UPDATE_REPOSITORY", "infobus4668/AllN1Downloader")
UPDATE_LOCK = threading.Lock()
UPDATE_STATE: Dict[str, Any] = {
    "status": "idle",
    "platform": "windows" if os.name == "nt" else "linux",
    "current_version": APP_VERSION,
    "latest_version": "",
    "available": False,
    "release_url": "",
    "asset_name": "",
    "asset_url": "",
    "asset_digest": "",
    "downloaded": False,
    "pending_path": "",
}
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)).resolve()


def default_work_dir() -> Path:
    configured = os.environ.get("ALLINONE_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    # Keep the legacy data directory so the renamed app retains existing jobs/files.
    return (root / "AllInOne").resolve()


WORK_DIR = default_work_dir()
DOWNLOAD_DIR = WORK_DIR / "downloads"
STATIC_DIR = Path(os.environ.get("ALLINONE_STATIC_DIR") or (BASE_DIR / "static")).expanduser().resolve()
DATA_DIR = WORK_DIR / "data"
ANDROID_MODE = os.environ.get("ALLINONE_ANDROID") == "1"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
STATE_FILE = DATA_DIR / "jobs.json"
if getattr(sys, "frozen", False):
    logging.basicConfig(
        filename=str(WORK_DIR / "allinone.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
SKIP_SUFFIXES = (".part", ".ytdl", ".temp", ".tmp")

QUALITY_MIN = 144
QUALITY_MAX = 4320
VIDEO_CONTAINERS = {"mp4", "mkv", "webm"}
AUDIO_CONTAINERS = {"original", "mp3", "m4a", "opus", "wav", "flac"}
AUDIO_QUALITIES = {"320", "256", "192", "128"}
COOKIE_BROWSERS = {"chrome", "edge", "firefox", "brave", "opera", "vivaldi", "chromium", "safari"}
CODEC_FILTERS = {"h264": "avc1", "vp9": "vp9", "av1": "av01", "h265": "hev"}
CODEC_ORDER = {"av1": 0, "vp9": 1, "h264": 2, "h265": 3}
EMBED_THUMBNAIL_CONTAINERS = {"mp3", "m4a", "flac", "mp4", "mkv"}
PROXY_SCHEMES = {"http", "https", "socks4", "socks4a", "socks5", "socks5h"}
SPONSORBLOCK_CATEGORIES = ["sponsor", "selfpromo", "interaction"]
MAX_STATE_JOBS = 300
ACTIVE_STATUSES = {"queued", "downloading", "processing"}
TERMINAL_STATUSES = {"completed", "error", "cancelled"}
PLAYABLE_EXTENSIONS = {".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav"}
VIDEO_CODEC_LABELS = {"h264": "H.264", "h265": "H.265", "vp9": "VP9", "av1": "AV1"}
AUDIO_CODEC_LABELS = {"aac": "AAC", "mp3": "MP3", "opus": "Opus", "vorbis": "Vorbis", "flac": "FLAC", "wav": "PCM", "alac": "ALAC"}

jobs: Dict[str, "Job"] = {}
jobs_lock = threading.Lock()
state_lock = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="download")


def clean_text(value: Any, limit: int = 500) -> str:
    text = ANSI_RE.sub("", str(value or ""))
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text.strip()[:limit]


def clean_thumbnail(value: Any) -> str:
    text = clean_text(value, 1000)
    return text if text.startswith(("http://", "https://")) else ""


def clean_proxy(value: Any) -> Optional[str]:
    text = clean_text(value, 500)
    if not text:
        return None
    try:
        parsed = urlparse(text)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return None
    if parsed.scheme not in PROXY_SCHEMES or not hostname:
        return None
    return text


def clean_ratelimit(value: Any) -> Optional[int]:
    try:
        rate = int(value)
    except (TypeError, ValueError):
        return None
    return rate if 0 < rate <= 104_857_600 else None


def requested_proxy(value: Optional[str]) -> Optional[str]:
    proxy = clean_proxy(value)
    if value and value.strip() and not proxy:
        raise HTTPException(status_code=400, detail="Invalid proxy. Enter an HTTP(S) or SOCKS URL, or clear the field to connect directly.")
    return proxy


def normalize_quality(value: Any) -> str:
    text = str(value or "best").strip().lower()
    if text == "best":
        return "best"
    try:
        height = int(text)
    except ValueError:
        return "best"
    return str(height) if QUALITY_MIN <= height <= QUALITY_MAX else "best"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def find_ffmpeg() -> Optional[str]:
    override = os.environ.get("ALLINONE_FFMPEG")
    if override and Path(override).is_file():
        return str(Path(override).resolve())
    bundled = BASE_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if getattr(sys, "frozen", False) and bundled.is_file():
        return str(bundled)
    found = shutil.which("ffmpeg")
    if found:
        return found
    candidates: List[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        winget = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if winget.exists():
            try:
                candidates.extend(winget.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"))
            except OSError:
                pass
    for path in (
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
        Path("/usr/local/bin/ffmpeg"),
        Path("/opt/homebrew/bin/ffmpeg"),
        Path("/usr/bin/ffmpeg"),
    ):
        if path.exists():
            candidates.append(path)
    return str(candidates[0]) if candidates else None


def find_ffprobe() -> Optional[str]:
    override = os.environ.get("ALLINONE_FFPROBE")
    if override and Path(override).is_file():
        return str(Path(override).resolve())
    if FFMPEG:
        sibling = Path(FFMPEG).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if sibling.exists():
            return str(sibling)
    return shutil.which("ffprobe")


FFMPEG = find_ffmpeg()
if FFMPEG:
    os.environ["PATH"] = str(Path(FFMPEG).parent) + os.pathsep + os.environ.get("PATH", "")
FFPROBE = find_ffprobe()

JS_RUNTIMES: Dict[str, Dict[str, str]] = {}
configured_runtime = os.environ.get("ALLINONE_JS_RUNTIME_NAME")
configured_runtime_path = os.environ.get("ALLINONE_JS_RUNTIME_PATH")
if configured_runtime in {"deno", "node", "bun", "quickjs"} and configured_runtime_path:
    JS_RUNTIMES[configured_runtime] = {"path": configured_runtime_path}
else:
    for runtime_name in ("deno", "node", "bun"):
        bundled_runtime = BASE_DIR / ("node.exe" if os.name == "nt" else "node") if runtime_name == "node" else None
        executable = (
            str(bundled_runtime)
            if getattr(sys, "frozen", False) and bundled_runtime and bundled_runtime.is_file()
            else shutil.which(runtime_name)
        )
        if executable:
            JS_RUNTIMES[runtime_name] = {"path": executable}
            break


def validate_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Paste a link first")
    if len(raw) > 4096:
        raise HTTPException(status_code=400, detail="That link is too long")
    try:
        parsed = urlparse(raw)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        raise HTTPException(status_code=400, detail="Enter a valid http(s) link")
    if parsed.scheme not in ("http", "https") or not hostname:
        raise HTTPException(status_code=400, detail="Enter a valid http(s) link")
    return raw


def collect_files(folder: Path) -> List[Path]:
    if not folder.exists():
        return []
    files = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and not path.name.endswith(SKIP_SUFFIXES):
            files.append(path)
    return files


def open_path(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def codec_family(vcodec: Any) -> str:
    value = str(vcodec or "").lower()
    if value.startswith("av01"):
        return "av1"
    if value.startswith("vp9"):
        return "vp9"
    if value.startswith("avc"):
        return "h264"
    if value.startswith(("hev", "hvc")):
        return "h265"
    return ""


def audio_codec_family(acodec: Any) -> str:
    value = str(acodec or "").lower()
    if value.startswith("opus"):
        return "opus"
    if value.startswith("mp4a"):
        return "aac"
    if value.startswith("mp3"):
        return "mp3"
    if value.startswith("vorbis"):
        return "vorbis"
    if value.startswith("flac"):
        return "flac"
    if value.startswith("pcm"):
        return "wav"
    return value.split(".")[0][:20] or "audio"


def describe_qualities(formats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_height: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for fmt in formats:
        height = fmt.get("height")
        family = codec_family(fmt.get("vcodec"))
        if not height or not family or family not in CODEC_ORDER:
            continue
        size = fmt.get("filesize") or fmt.get("filesize_approx")
        tbr = fmt.get("tbr")
        entry = {
            "codec": family,
            "vcodec": clean_text(fmt.get("vcodec"), 60),
            "ext": fmt.get("ext"),
            "fps": fmt.get("fps"),
            "filesize": size,
            "tbr": tbr,
            "hdr": bool(fmt.get("dynamic_range") and str(fmt.get("dynamic_range")).upper() != "SDR"),
        }
        existing = by_height.setdefault(height, {}).get(family)
        score = (size or 0, tbr or 0)
        if existing is None or score > ((existing.get("filesize") or 0), (existing.get("tbr") or 0)):
            by_height[height][family] = entry
    qualities = []
    for height in sorted(by_height, reverse=True):
        variants = sorted(
            by_height[height].values(),
            key=lambda item: (CODEC_ORDER.get(item["codec"], 9), -(item.get("tbr") or 0)),
        )
        qualities.append({"height": height, "formats": variants})
    return qualities


def describe_audio(formats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    seen = set()
    for fmt in formats:
        if fmt.get("vcodec") not in (None, "none"):
            continue
        acodec = fmt.get("acodec")
        if not acodec or acodec == "none":
            continue
        abr = fmt.get("abr") or fmt.get("tbr")
        key = (audio_codec_family(acodec), round(abr) if abr else None)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "codec": audio_codec_family(acodec),
            "acodec": clean_text(acodec, 60),
            "abr": abr,
            "ext": fmt.get("ext"),
            "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
            "note": clean_text(fmt.get("format_note"), 80),
        })
    result.sort(key=lambda item: item.get("abr") or 0, reverse=True)
    return result[:8]


def job_fingerprint(url: str, options: Dict[str, Any]) -> str:
    material = json.dumps({"url": url, "options": options}, sort_keys=True, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def parse_clip_time(value: Any, label: str) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) > 3 or any(not part.strip() for part in parts):
        raise HTTPException(status_code=400, detail=f"Invalid clip {label}. Use seconds, mm:ss, or hh:mm:ss.")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid clip {label}. Use seconds, mm:ss, or hh:mm:ss.")
    if any(not math.isfinite(number) or number < 0 for number in numbers):
        raise HTTPException(status_code=400, detail=f"Invalid clip {label}. Use a positive time.")
    if len(numbers) > 1 and numbers[-1] >= 60:
        raise HTTPException(status_code=400, detail=f"Clip {label} seconds must be below 60.")
    if len(numbers) == 3 and numbers[1] >= 60:
        raise HTTPException(status_code=400, detail=f"Clip {label} minutes must be below 60.")
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    if seconds > 86_400:
        raise HTTPException(status_code=400, detail="Clip times must be within 24 hours.")
    return round(seconds, 3)


def parse_fps(value: Any) -> Optional[float]:
    try:
        text = str(value or "")
        numerator, denominator = text.split("/", 1) if "/" in text else (text, "1")
        fps = float(numerator) / float(denominator)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return round(fps, 3) if math.isfinite(fps) and fps > 0 else None


def probe_media(path: Path) -> Optional[Dict[str, Any]]:
    if not FFPROBE or not path.is_file():
        return None
    try:
        result = subprocess.run(
            [FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        return None
    streams = payload.get("streams") or []
    container = payload.get("format") or {}
    duration = safe_float(container.get("duration"))
    if duration <= 0:
        stream_durations = []
        for stream in streams:
            stream_duration = safe_float(stream.get("duration"))
            if stream_duration <= 0:
                stream_duration = safe_float(stream.get("duration_ts")) * (parse_fps(stream.get("time_base")) or 0.0)
            if stream_duration > 0:
                stream_durations.append(stream_duration)
        duration = max(stream_durations, default=0.0)
    try:
        file_size = path.stat().st_size
    except OSError:
        file_size = 0
    video_stream = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
    media: Dict[str, Any] = {
        "name": path.name,
        "duration": round(duration, 3),
        "size": safe_int(container.get("size"), file_size),
    }
    if video_stream:
        family = codec_family(video_stream.get("codec_name"))
        raw = clean_text(video_stream.get("codec_name"), 40)
        media["video"] = {
            "codec": family or raw,
            "codec_name": raw,
            "label": VIDEO_CODEC_LABELS.get(family, raw.upper() or "Video"),
            "width": safe_int(video_stream.get("width")),
            "height": safe_int(video_stream.get("height")),
            "fps": parse_fps(video_stream.get("avg_frame_rate")) or parse_fps(video_stream.get("r_frame_rate")),
            "bitrate": safe_int(video_stream.get("bit_rate")) or None,
        }
    if audio_stream:
        family = audio_codec_family(audio_stream.get("codec_name"))
        raw = clean_text(audio_stream.get("codec_name"), 40)
        media["audio"] = {
            "codec": family,
            "codec_name": raw,
            "label": AUDIO_CODEC_LABELS.get(family, raw.upper() or "Audio"),
            "channels": safe_int(audio_stream.get("channels")) or None,
            "sample_rate": safe_int(audio_stream.get("sample_rate")) or None,
            "bitrate": safe_int(audio_stream.get("bit_rate")) or None,
        }
    return media if media.get("video") or media.get("audio") else None


class JobLogger:
    def __init__(self, job: "Job") -> None:
        self.job = job

    def debug(self, msg: str) -> None:
        if str(msg).startswith("[debug] "):
            return
        self.job.add_log(msg)

    def info(self, msg: str) -> None:
        self.job.add_log(msg)

    def warning(self, msg: str) -> None:
        self.job.add_log(f"WARN {msg}")

    def error(self, msg: str) -> None:
        self.job.add_log(f"ERROR {msg}")


class Job:
    def __init__(
        self,
        url: str,
        options: Dict[str, Any],
        title: Optional[str] = None,
        job_id: Optional[str] = None,
        thumbnail: Optional[str] = None,
        ensure_dir: bool = True,
    ) -> None:
        self.id = job_id or uuid.uuid4().hex[:10]
        self.url = url
        self.options = options
        self.fingerprint = job_fingerprint(url, options)
        self.media: Optional[Dict[str, Any]] = None
        self.title = clean_text(title, 200) or "Preparing download..."
        self.thumbnail = clean_thumbnail(thumbnail)
        self.status = "queued"
        self.progress = 0.0
        self.speed: Optional[float] = None
        self.eta: Optional[int] = None
        self.downloaded = 0
        self.total = 0
        self.error: Optional[str] = None
        self.current_item: Optional[str] = None
        self.playlist_index: Optional[int] = None
        self.playlist_count: Optional[int] = None
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.cancel_event = threading.Event()
        self.future: Optional[Future] = None
        self.logs: List[str] = []
        self.lock = threading.RLock()
        self.cleanup_after = False
        self._file_snapshot: Optional[List[Dict[str, Any]]] = None
        self.dir = DOWNLOAD_DIR / self.id
        if ensure_dir:
            self.dir.mkdir(parents=True, exist_ok=True)

    def add_log(self, msg: str) -> None:
        line = clean_text(msg, 1000)
        if not line:
            return
        with self.lock:
            self.logs.append(line)
            if len(self.logs) > 200:
                del self.logs[:100]

    def file_snapshot(self) -> List[Dict[str, Any]]:
        with self.lock:
            status = self.status
            if status in TERMINAL_STATUSES and self._file_snapshot is not None:
                return self._file_snapshot

        files = []
        for path in collect_files(self.dir):
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            files.append({
                "name": path.name,
                "rel": path.relative_to(self.dir).as_posix(),
                "size": size,
            })

        with self.lock:
            if self.status == status and status in TERMINAL_STATUSES:
                self._file_snapshot = files
        return files

    def to_dict(self, include_logs: bool = True, file_limit: int = 5) -> Dict[str, Any]:
        files = self.file_snapshot()
        total_size = sum(item["size"] for item in files)
        with self.lock:
            result = {
                "id": self.id,
                "url": self.url,
                "title": self.title,
                "thumbnail": self.thumbnail,
                "dir": str(self.dir),
                "mode": self.options.get("mode", "video"),
                "quality": self.options.get("quality", "best"),
                "container": self.options.get("container", "mp4"),
                "codec": self.options.get("codec", "auto"),
                "clip_start": self.options.get("clip_start"),
                "clip_end": self.options.get("clip_end"),
                "is_playlist": bool(self.options.get("is_playlist")),
                "status": self.status,
                "progress": round(self.progress, 1),
                "speed": self.speed,
                "eta": self.eta,
                "downloaded": self.downloaded,
                "total": self.total,
                "current_item": self.current_item,
                "playlist_index": self.playlist_index,
                "playlist_count": self.playlist_count,
                "error": self.error,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "files": files[:file_limit],
                "file_count": len(files),
                "total_size": total_size,
                "has_playable": any(Path(item["rel"]).suffix.lower() in PLAYABLE_EXTENSIONS for item in files),
                "can_retry": self.status in TERMINAL_STATUSES and (self.future is None or self.future.done()),
                "media": self.media,
                "log_count": len(self.logs),
            }
            if include_logs:
                result["logs"] = self.logs[-60:]
            return result


def job_state(job: Job) -> Dict[str, Any]:
    with job.lock:
        return {
            "id": job.id,
            "url": job.url,
            "title": job.title,
            "thumbnail": job.thumbnail,
            "options": job.options,
            "status": job.status,
            "progress": job.progress,
            "downloaded": job.downloaded,
            "total": job.total,
            "error": job.error,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "media": job.media,
            "logs": job.logs[-60:],
        }


def persist_jobs() -> None:
    with state_lock:
        try:
            with jobs_lock:
                payload = [job_state(job) for job in sorted(jobs.values(), key=lambda item: item.created_at)]
            temporary = STATE_FILE.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temporary.replace(STATE_FILE)
        except OSError:
            logging.getLogger(__name__).exception("Could not save queue history to %s", STATE_FILE)


def load_jobs() -> None:
    if not STATE_FILE.exists():
        return
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("Expected a list of jobs")
    except ValueError:
        backup = STATE_FILE.with_name(f"jobs-unreadable-{uuid.uuid4().hex[:10]}.json")
        STATE_FILE.rename(backup)
        logging.getLogger(__name__).warning("Unreadable queue history preserved in %s", backup)
        return
    items = [item for item in raw if isinstance(item, dict)]
    items.sort(key=lambda item: safe_float(item.get("created_at")))
    changed = False
    restored: List[Job] = []
    for item in items[-MAX_STATE_JOBS:]:
        job_id = str(item.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,32}", job_id):
            continue
        url = str(item.get("url") or "")
        options = item.get("options")
        if not url or not isinstance(options, dict):
            continue
        job = Job(
            url=url,
            options=options,
            title=item.get("title"),
            job_id=job_id,
            thumbnail=item.get("thumbnail"),
            ensure_dir=False,
        )
        status = str(item.get("status") or "error")
        job.status = status
        job.progress = min(100.0, max(0.0, safe_float(item.get("progress"))))
        job.downloaded = max(0, safe_int(item.get("downloaded")))
        job.total = max(0, safe_int(item.get("total")))
        job.error = clean_text(item.get("error"), 400) or None
        job.created_at = safe_float(item.get("created_at"), time.time())
        job.started_at = safe_float(item.get("started_at"), 0.0) or None
        job.finished_at = safe_float(item.get("finished_at"), 0.0) or None
        media = item.get("media")
        job.media = media if isinstance(media, dict) else None
        raw_logs = item.get("logs")
        job.logs = [clean_text(line, 1000) for line in raw_logs if line][-60:] if isinstance(raw_logs, list) else []
        if status in ("queued", "downloading", "processing"):
            job.status = "error"
            job.error = "Interrupted by app restart. Use Retry to resume."
            job.finished_at = job.finished_at or time.time()
            changed = True
        elif status == "completed":
            if not collect_files(job.dir):
                job.status = "error"
                job.error = "Output files are no longer on disk."
                changed = True
            else:
                job.progress = 100.0
        elif status not in ("error", "cancelled"):
            job.status = "error"
            job.error = "Unknown job state after restart."
            changed = True
        restored.append(job)
    with jobs_lock:
        for job in restored:
            jobs[job.id] = job
    if changed:
        persist_jobs()


def build_format(mode: str, quality: str, container: str, codec: str = "auto") -> str:
    if mode == "audio":
        return "bestaudio/best"
    height = None
    if quality != "best":
        try:
            parsed = int(quality)
        except (TypeError, ValueError):
            parsed = 0
        height = parsed if QUALITY_MIN <= parsed <= QUALITY_MAX else None
    cap = f"[height<={height}]" if height else ""
    codec_part = f"[vcodec^={CODEC_FILTERS[codec]}]" if codec in CODEC_FILTERS else ""
    if container == "mp4":
        base = f"bv*[ext=mp4]{cap}+ba[ext=m4a]/bv*{cap}+ba/b{cap}"
        if codec_part:
            return f"bv*[ext=mp4]{codec_part}{cap}+ba[ext=m4a]/bv*{codec_part}{cap}+ba/b{cap}/{base}"
        return base
    if container == "webm":
        base = f"bv*[ext=webm]{cap}+ba[ext=webm]/b[ext=webm]{cap}"
        if codec_part:
            return f"bv*[ext=webm]{codec_part}{cap}+ba[ext=webm]/b[ext=webm]{codec_part}{cap}/{base}"
        return base
    base = f"bv*{cap}+ba/b{cap}"
    if codec_part:
        return f"bv*{codec_part}{cap}+ba/b{cap}/{base}"
    return base


def make_progress_hook(job: Job):
    selected = job.options.get("playlist_items") or []

    def hook(d: Dict[str, Any]) -> None:
        if job.cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled("Cancelled by user")
        info = d.get("info_dict") or {}
        status = d.get("status")
        if status == "downloading":
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            item_pct = (downloaded / total * 100) if total else 0.0
            index = info.get("playlist_index")
            count = info.get("playlist_count") or info.get("n_entries")
            if selected and index in selected:
                position = selected.index(index) + 1
                overall = ((position - 1) + item_pct / 100) / len(selected) * 100
                count = len(selected)
            elif index and count:
                overall = ((index - 1) + item_pct / 100) / count * 100
            else:
                overall = item_pct
            with job.lock:
                job.status = "downloading"
                job.progress = min(overall, 99.5)
                job.downloaded = downloaded
                job.total = total
                job.speed = d.get("speed")
                job.eta = d.get("eta")
                job.current_item = clean_text(info.get("title"), 160) or job.current_item
                job.playlist_index = index
                job.playlist_count = count
                if job.title in ("", "Preparing download..."):
                    job.title = clean_text(info.get("playlist_title") or info.get("title"), 200) or job.title
                if not job.thumbnail:
                    thumbs = info.get("thumbnails") or []
                    if thumbs:
                        job.thumbnail = clean_thumbnail(thumbs[-1].get("url"))
        elif status == "finished":
            with job.lock:
                job.speed = None
                job.eta = None
                job.progress = min(max(job.progress, 99.0), 99.5)
        elif status == "error":
            with job.lock:
                job.status = "processing"

    return hook


def make_pp_hook(job: Job):
    def hook(d: Dict[str, Any]) -> None:
        if job.cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled("Cancelled by user")
        if d.get("status") in ("started", "processing"):
            with job.lock:
                job.status = "processing"
                job.speed = None
                job.eta = None
    return hook


def build_ydl_options(job: Job) -> Dict[str, Any]:
    opts = job.options
    mode = opts["mode"]
    container = opts["container"]
    codec = opts.get("codec") or "auto"
    if opts.get("is_playlist"):
        template = "%(playlist_title|Playlist)s/%(playlist_index)03d - %(title)s [%(id)s].%(ext)s"
    else:
        template = "%(title)s [%(id)s].%(ext)s"

    ydl_opts: Dict[str, Any] = {
        "paths": {"home": str(job.dir)},
        "outtmpl": {"default": template},
        "format": build_format(mode, opts["quality"], container, codec),
        "noprogress": True,
        "quiet": True,
        "logger": JobLogger(job),
        "progress_hooks": [make_progress_hook(job)],
        "postprocessor_hooks": [make_pp_hook(job)],
        "concurrent_fragment_downloads": 4,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
        "trim_file_name": 150,
        "continuedl": True,
        "overwrites": False,
        "ignoreerrors": False,
        "noplaylist": False,
    }
    if os.name == "nt":
        ydl_opts["windowsfilenames"] = True
    if FFMPEG:
        ydl_opts["ffmpeg_location"] = FFMPEG if ANDROID_MODE else str(Path(FFMPEG).parent)
    if JS_RUNTIMES:
        ydl_opts["js_runtimes"] = JS_RUNTIMES
        ydl_opts["remote_components"] = ["ejs:github"]
    if opts.get("cookies_browser"):
        ydl_opts["cookiesfrombrowser"] = (opts["cookies_browser"],)
    if opts.get("proxy"):
        ydl_opts["proxy"] = opts["proxy"]
    if opts.get("ratelimit"):
        ydl_opts["ratelimit"] = int(opts["ratelimit"])
    if mode == "video":
        ydl_opts["merge_output_format"] = container
    clip_start = opts.get("clip_start")
    clip_end = opts.get("clip_end")
    if clip_start is not None or clip_end is not None:
        def clip_ranges(info: Dict[str, Any], _ydl: Any) -> List[Dict[str, Any]]:
            start = safe_float(clip_start)
            duration = safe_float(info.get("duration"))
            end = safe_float(clip_end) if clip_end is not None else (duration or float("inf"))
            if duration and start >= duration:
                raise yt_dlp.utils.DownloadError("Clip start is at or beyond the media duration")
            if end <= start:
                raise yt_dlp.utils.DownloadError("Clip end must be later than the start")
            return [{"start_time": start, "end_time": end}]
        ydl_opts["download_ranges"] = clip_ranges
        ydl_opts["force_keyframes_at_cuts"] = bool(opts.get("clip_precise")) and mode == "video"

    postprocessors: List[Dict[str, Any]] = []
    if opts.get("sponsorblock"):
        postprocessors.extend([
            {"key": "SponsorBlock", "categories": SPONSORBLOCK_CATEGORIES, "when": "after_filter"},
            {"key": "ModifyChapters", "remove_sponsor_segments": SPONSORBLOCK_CATEGORIES},
        ])
    if mode == "audio" and container != "original":
        preferred = opts.get("audio_quality")
        if preferred not in AUDIO_QUALITIES:
            preferred = {"mp3": "320", "m4a": "256"}.get(container, "0")
        postprocessors.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": container,
            "preferredquality": preferred,
        })
    if opts.get("embed_thumbnail"):
        if container in EMBED_THUMBNAIL_CONTAINERS:
            ydl_opts["writethumbnail"] = True
            postprocessors.append({"key": "EmbedThumbnail"})
        else:
            job.add_log("Thumbnail embedding skipped: unsupported output container.")
    postprocessors.append({"key": "FFmpegMetadata"})
    if opts.get("subtitles"):
        ydl_opts.update({
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": [opts.get("subtitle_lang") or "en"],
        })
        postprocessors.append({"key": "FFmpegSubtitlesConvertor", "format": "srt"})
    ydl_opts["postprocessors"] = postprocessors

    if opts.get("playlist_items"):
        ydl_opts["playlist_items"] = ",".join(str(i) for i in opts["playlist_items"])
    return ydl_opts


def run_job(job: Job) -> None:
    with job.lock:
        job.status = "downloading"
        job.started_at = time.time()
    persist_jobs()
    try:
        if job.cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled("Cancelled before download")
        with yt_dlp.YoutubeDL(build_ydl_options(job)) as ydl:
            if ydl.download([job.url]):
                raise RuntimeError("The downloader reported an incomplete download. See Logs for details.")
        if job.cancel_event.is_set():
            with job.lock:
                job.status = "cancelled"
        else:
            files = collect_files(job.dir)
            playable = next((path for path in files if path.suffix.lower() in PLAYABLE_EXTENSIONS), None)
            media = probe_media(playable) if playable else None
            with job.lock:
                job.media = media
                if files:
                    job.status = "completed"
                    job.progress = 100.0
                else:
                    job.status = "error"
                    job.error = "No output file was produced. The link may be unsupported or region-locked."
                if media:
                    parts = []
                    video = media.get("video")
                    if video:
                        parts.append(f"{video['width']}x{video['height']} {video['label']}".strip())
                    audio = media.get("audio")
                    if audio:
                        parts.append(audio["label"])
                    job.add_log(f"Verified media: {' · '.join(parts)}")
                elif playable and FFPROBE:
                    job.add_log("WARN Could not verify the saved media with ffprobe.")
    except yt_dlp.utils.DownloadCancelled:
        with job.lock:
            job.status = "cancelled"
    except Exception as exc:  # noqa: BLE001 - surface any yt-dlp failure to the UI
        if job.cancel_event.is_set():
            with job.lock:
                job.status = "cancelled"
        else:
            message = clean_text(exc, 400) or "Download failed"
            with job.lock:
                job.status = "error"
                job.error = message
            job.add_log(f"ERROR {message}")
    finally:
        with job.lock:
            job.finished_at = time.time()
            job.speed = None
            job.eta = None
            cleanup = job.cleanup_after
        if cleanup:
            shutil.rmtree(job.dir, ignore_errors=True)
        persist_jobs()


def get_job(job_id: str) -> Job:
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


class InfoRequest(BaseModel):
    url: str
    cookies_browser: Optional[str] = None
    proxy: Optional[str] = None


class DownloadRequest(BaseModel):
    url: str
    mode: str = "video"
    quality: str = "best"
    container: str = "mp4"
    codec: str = "auto"
    audio_quality: Optional[str] = None
    subtitles: bool = False
    subtitle_lang: str = "en"
    playlist_items: Optional[List[int]] = None
    is_playlist: bool = False
    cookies_browser: Optional[str] = None
    embed_thumbnail: bool = False
    sponsorblock: bool = False
    ratelimit: Optional[int] = None
    proxy: Optional[str] = None
    clip_start: Optional[str] = None
    clip_end: Optional[str] = None
    clip_precise: bool = False
    title: Optional[str] = None
    thumbnail: Optional[str] = None
    force: bool = False


def update_snapshot() -> Dict[str, Any]:
    with UPDATE_LOCK:
        return dict(UPDATE_STATE)


def check_for_application_updates() -> None:
    if ANDROID_MODE:
        return
    platform = "windows" if os.name == "nt" else "linux"
    try:
        update = update_service.fetch_latest_release(UPDATE_REPOSITORY, APP_VERSION, platform)
        if update.get("available") and platform == "windows" and getattr(sys, "frozen", False):
            with jobs_lock:
                has_active_jobs = any(job.status in ACTIVE_STATUSES for job in jobs.values())
            if not has_active_jobs:
                try:
                    executable = Path(sys.executable).resolve()
                    pending = update_service.download_windows_update(
                        update["asset_url"], update.get("asset_digest", ""), executable, WORK_DIR
                    )
                    update["downloaded"] = True
                    update["pending_path"] = str(pending)
                    persist_jobs()
                    update_service.launch_windows_replacement(pending, executable, os.getpid())
                    update["status"] = "installing"

                    def exit_for_update() -> None:
                        time.sleep(1.5)
                        os._exit(0)

                    threading.Thread(target=exit_for_update, name="alln1-update-restart", daemon=True).start()
                except Exception as error:
                    update["download_detail"] = str(error)[:240]
    except Exception as error:  # update checks must never prevent app startup
        update = {
            "status": "unavailable",
            "current_version": APP_VERSION,
            "latest_version": "",
            "available": False,
            "release_url": f"https://github.com/{UPDATE_REPOSITORY}/releases/latest",
            "asset_name": "",
            "asset_url": "",
            "asset_digest": "",
            "detail": str(error)[:240],
        }
    update["platform"] = platform
    with UPDATE_LOCK:
        UPDATE_STATE.update(update)


def start_application_update_check() -> None:
    if os.environ.get("ALLN1_DISABLE_UPDATE_CHECK") == "1" or os.environ.get("CI") == "true":
        with UPDATE_LOCK:
            UPDATE_STATE["status"] = "disabled"
        return
    with UPDATE_LOCK:
        if UPDATE_STATE["status"] != "idle":
            return
        UPDATE_STATE["status"] = "checking"
    threading.Thread(target=check_for_application_updates, name="alln1-update-check", daemon=True).start()


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_jobs()
    start_application_update_check()
    yield
    with jobs_lock:
        for job in jobs.values():
            job.cancel_event.set()
    persist_jobs()
    EXECUTOR.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="AllN1Downloader", version=APP_VERSION, lifespan=lifespan)


@app.middleware("http")
async def protect_local_actions(request: Request, call_next):
    target_host = (request.url.hostname or "").lower()
    if target_host not in {"127.0.0.1", "localhost", "::1"}:
        return JSONResponse(status_code=403, content={"detail": "Local requests only"})
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:

        origin = request.headers.get("origin")
        if origin:
            try:
                parsed = urlparse(origin)
                origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            except ValueError:
                return JSONResponse(status_code=403, content={"detail": "Cross-origin request blocked"})
            target_port = request.url.port or (443 if request.url.scheme == "https" else 80)
            if (
                parsed.scheme != request.url.scheme
                or (parsed.hostname or "").lower() != target_host
                or origin_port != target_port
            ):
                return JSONResponse(status_code=403, content={"detail": "Cross-origin request blocked"})
        elif request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
            return JSONResponse(status_code=403, content={"detail": "Cross-site request blocked"})
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_handler(_request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "Invalid request data"})


@app.get("/api/health")
def health() -> Dict[str, Any]:
    try:
        usage = shutil.disk_usage(DOWNLOAD_DIR)
        disk_free, disk_total = usage.free, usage.total
    except OSError:
        disk_free = disk_total = 0
    return {
        "version": APP_VERSION,
        "yt_dlp": yt_dlp.version.__version__,
        "ffmpeg": bool(FFMPEG),
        "ffmpeg_path": FFMPEG or "",
        "ffprobe": bool(FFPROBE),
        "ffprobe_path": FFPROBE or "",
        "js_runtime": next(iter(JS_RUNTIMES), ""),
        "download_dir": str(DOWNLOAD_DIR),
        "platform": "android" if ANDROID_MODE else "desktop",
        "distribution": "frozen" if getattr(sys, "frozen", False) else "source",
        "update": update_snapshot(),
        "disk_free": disk_free,
        "disk_total": disk_total,
    }


@app.get("/api/update")
def get_update_status() -> Dict[str, Any]:
    return update_snapshot()


@app.post("/api/update/apply")
def apply_application_update() -> Dict[str, Any]:
    update = update_snapshot()
    if not update.get("available"):
        raise HTTPException(status_code=409, detail="No newer release is available")
    if ANDROID_MODE:
        raise HTTPException(status_code=409, detail="Android updates are handled by the package installer")
    if not getattr(sys, "frozen", False):
        return {"status": "manual", "release_url": update.get("release_url", "")}

    if os.name == "nt":
        with jobs_lock:
            if any(job.status in ACTIVE_STATUSES for job in jobs.values()):
                raise HTTPException(status_code=409, detail="Finish active downloads before updating")
        try:
            executable = Path(sys.executable).resolve()
            pending = Path(update.get("pending_path", ""))
            downloaded = pending if pending.is_file() else update_service.download_windows_update(
                update["asset_url"], update.get("asset_digest", ""), executable, WORK_DIR
            )
            persist_jobs()
            update_service.launch_windows_replacement(downloaded, executable, os.getpid())
        except Exception as error:
            raise HTTPException(status_code=502, detail=f"Could not prepare the signed update: {error}") from error

        def exit_for_update() -> None:
            time.sleep(1.5)
            os._exit(0)

        threading.Thread(target=exit_for_update, name="alln1-update-restart", daemon=True).start()
        return {"status": "restarting", "version": update.get("latest_version", "")}

    if sys.platform.startswith("linux"):
        pkexec = shutil.which("pkexec")
        if not pkexec:
            return {"status": "manual", "release_url": update.get("release_url", "")}
        subprocess.Popen(
            [pkexec, "sh", "-c", "apt-get update && apt-get install -y --only-upgrade alln1downloader"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"status": "installing", "version": update.get("latest_version", "")}

    return {"status": "manual", "release_url": update.get("release_url", "")}


@app.post("/api/info")
def get_info(req: InfoRequest) -> Dict[str, Any]:
    url = validate_url(req.url)
    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "noprogress": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "playlistend": 200,
        "ignoreerrors": True,
        "socket_timeout": 25,
        "extractor_retries": 2,
        "retries": 3,
    }
    if FFMPEG:
        ydl_opts["ffmpeg_location"] = FFMPEG if ANDROID_MODE else str(Path(FFMPEG).parent)
    if JS_RUNTIMES:
        ydl_opts["js_runtimes"] = JS_RUNTIMES
        ydl_opts["remote_components"] = ["ejs:github"]
    if req.cookies_browser in COOKIE_BROWSERS:
        ydl_opts["cookiesfrombrowser"] = (req.cookies_browser,)
    proxy = requested_proxy(req.proxy)
    if proxy:
        ydl_opts["proxy"] = proxy
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001 - report any analysis failure to the UI
        raise HTTPException(status_code=400, detail=clean_text(exc, 400) or "Could not analyze this link")
    if not info:
        raise HTTPException(status_code=400, detail="No media found at this link")

    is_playlist = info.get("_type") in ("playlist", "multi_video") or "entries" in info
    entries: List[Dict[str, Any]] = []
    if is_playlist:
        for index, entry in enumerate(info.get("entries") or [], start=1):
            if not entry:
                continue
            thumbnail = entry.get("thumbnail")
            if not thumbnail:
                thumbs = entry.get("thumbnails") or []
                if thumbs:
                    thumbnail = thumbs[-1].get("url")
            entries.append({
                "index": index,
                "title": clean_text(entry.get("title") or f"Item {index}", 300),
                "duration": entry.get("duration"),
                "thumbnail": clean_thumbnail(thumbnail),
            })
        if not entries:
            raise HTTPException(status_code=400, detail="This playlist appears to be empty or unavailable")

    thumbnail = info.get("thumbnail")
    if not thumbnail:
        thumbs = info.get("thumbnails") or []
        if thumbs:
            thumbnail = thumbs[-1].get("url")

    formats = info.get("formats") or []
    heights = sorted({
        fmt.get("height")
        for fmt in formats
        if fmt.get("height") and fmt.get("vcodec") not in (None, "none")
    }, reverse=True)
    audio_exts = {"mp3", "m4a", "aac", "opus", "ogg", "oga", "wav", "flac", "wma", "alac"}
    audio_only = (
        bool(formats)
        and not heights
        and all(fmt.get("vcodec") in (None, "none") for fmt in formats)
        and (info.get("ext") in audio_exts or info.get("vcodec") == "none")
    )
    qualities = describe_qualities(formats)
    audio_formats = describe_audio(formats)

    return {
        "title": clean_text(info.get("title") or info.get("playlist_title") or "Untitled", 300),
        "id": info.get("id"),
        "thumbnail": clean_thumbnail(thumbnail),
        "duration": info.get("duration"),
        "uploader": clean_text(info.get("uploader") or info.get("channel") or info.get("creator"), 120),
        "extractor": clean_text(info.get("extractor_key") or info.get("extractor") or "Media", 60),
        "webpage_url": info.get("webpage_url") or url,
        "is_playlist": bool(is_playlist),
        "playlist_count": info.get("playlist_count") or (len(entries) if is_playlist else None),
        "entries": entries,
        "heights": heights,
        "qualities": qualities,
        "audio_formats": audio_formats,
        "source_audio": audio_formats[0] if audio_formats else None,
        "audio_only": audio_only,
        "is_live": bool(info.get("is_live")),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "upload_date": info.get("upload_date"),
    }


@app.post("/api/download")
def create_download(req: DownloadRequest) -> Dict[str, Any]:
    url = validate_url(req.url)
    mode = (req.mode or "video").lower()
    if mode not in ("video", "audio"):
        raise HTTPException(status_code=400, detail="Invalid download type")
    container = (req.container or ("mp4" if mode == "video" else "mp3")).lower()
    if container not in (VIDEO_CONTAINERS if mode == "video" else AUDIO_CONTAINERS):
        raise HTTPException(status_code=400, detail="Invalid output format")
    quality = normalize_quality(req.quality)
    codec = req.codec if req.codec in CODEC_FILTERS else "auto"
    audio_quality = req.audio_quality if req.audio_quality in AUDIO_QUALITIES else None
    subtitle_lang = re.sub(r"[^a-zA-Z0-9_,\-]", "", req.subtitle_lang or "en") or "en"
    clip_start = parse_clip_time(req.clip_start, "start")
    clip_end = parse_clip_time(req.clip_end, "end")
    if clip_start is not None or clip_end is not None:
        if not FFMPEG:
            raise HTTPException(status_code=400, detail="FFmpeg is required to clip a section")
        if clip_end is not None and clip_end <= (clip_start or 0):
            raise HTTPException(status_code=400, detail="Clip end must be later than the start")
    clip_precise = bool(req.clip_precise) and mode == "video" and (clip_start is not None or clip_end is not None)

    items: Optional[List[int]] = None
    if req.playlist_items:
        try:
            items = sorted({int(i) for i in req.playlist_items if int(i) > 0})[:500]
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid playlist selection")
        if not items:
            raise HTTPException(status_code=400, detail="Invalid playlist selection")
    if (clip_start is not None or clip_end is not None) and (req.is_playlist or items):
        raise HTTPException(status_code=400, detail="Clipping is available for single links only")

    options = {
        "mode": mode,
        "quality": quality,
        "container": container,
        "codec": codec,
        "audio_quality": audio_quality,
        "subtitles": bool(req.subtitles),
        "subtitle_lang": subtitle_lang,
        "playlist_items": items,
        "is_playlist": bool(req.is_playlist),
        "cookies_browser": req.cookies_browser if req.cookies_browser in COOKIE_BROWSERS else None,
        "embed_thumbnail": bool(req.embed_thumbnail),
        "sponsorblock": bool(req.sponsorblock),
        "ratelimit": clean_ratelimit(req.ratelimit),
        "proxy": requested_proxy(req.proxy),
        "clip_start": clip_start,
        "clip_end": clip_end,
        "clip_precise": clip_precise,
    }
    job = Job(
        url=url,
        options=options,
        title=req.title,
        thumbnail=req.thumbnail,
        ensure_dir=False,
    )
    with jobs_lock:
        if not req.force:
            duplicate = next(
                (
                    existing for existing in jobs.values()
                    if existing.fingerprint == job.fingerprint and existing.status in ACTIVE_STATUSES | {"completed"}
                ),
                None,
            )
            if duplicate:
                message = (
                    "This exact download is already saved."
                    if duplicate.status == "completed"
                    else "This exact download is already in the queue."
                )
                raise HTTPException(status_code=409, detail={
                    "message": message,
                    "job_id": duplicate.id,
                    "status": duplicate.status,
                })
        if len(jobs) >= MAX_STATE_JOBS:
            raise HTTPException(status_code=409, detail="Queue history is full. Save files you want to keep, then remove an old job.")
        job.dir.mkdir(parents=True, exist_ok=False)
        jobs[job.id] = job
        job.future = EXECUTOR.submit(run_job, job)
    persist_jobs()
    return job.to_dict()


@app.get("/api/jobs")
def list_jobs() -> List[Dict[str, Any]]:
    with jobs_lock:
        snapshot = list(jobs.values())
    snapshot.sort(key=lambda item: item.created_at, reverse=True)
    return [job.to_dict(include_logs=False) for job in snapshot]


@app.get("/api/jobs/{job_id}")
def get_job_detail(job_id: str) -> Dict[str, Any]:
    return get_job(job_id).to_dict()


@app.get("/api/jobs/{job_id}/logs")
def get_job_logs(job_id: str) -> Dict[str, Any]:
    job = get_job(job_id)
    with job.lock:
        return {"logs": job.logs[-60:], "log_count": len(job.logs)}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> Dict[str, Any]:
    job = get_job(job_id)
    with job.lock:
        job.cancel_event.set()
        if job.future and job.future.cancel():
            job.status = "cancelled"
            job.finished_at = time.time()
    persist_jobs()
    return job.to_dict()


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str) -> Dict[str, Any]:
    job = get_job(job_id)
    with jobs_lock, job.lock:
        if jobs.get(job_id) is not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status not in TERMINAL_STATUSES or (job.future and not job.future.done()):
            raise HTTPException(status_code=400, detail="This download is still running")
        job.dir.mkdir(parents=True, exist_ok=True)
        job.status = "queued"
        job.progress = 0.0
        job.speed = None
        job.eta = None
        job.downloaded = 0
        job.total = 0
        job.error = None
        job.current_item = None
        job.playlist_index = None
        job.playlist_count = None
        job.started_at = None
        job.finished_at = None
        job.cancel_event = threading.Event()
        job.logs.clear()
        job._file_snapshot = None
        job.future = EXECUTOR.submit(run_job, job)
    persist_jobs()
    return job.to_dict()


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> Dict[str, bool]:
    with jobs_lock:
        job = jobs.pop(job_id, None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.cancel_event.set()
    with job.lock:
        active = job.status in ("queued", "downloading", "processing")
        if active and job.future and job.future.cancel():
            active = False
        if active:
            job.cleanup_after = True
    if not active:
        shutil.rmtree(job.dir, ignore_errors=True)
    persist_jobs()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/forget")
def forget_job(job_id: str) -> Dict[str, bool]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status not in TERMINAL_STATUSES:
            raise HTTPException(status_code=400, detail="Wait for the download to finish before removing it from history")
        jobs.pop(job_id, None)
    persist_jobs()
    return {"ok": True}


@app.post("/api/jobs/clear-finished")
def clear_finished() -> Dict[str, int]:
    with jobs_lock:
        ids = [
            job_id for job_id, job in jobs.items()
            if job.status in ("completed", "error", "cancelled")
        ]
        removed = [jobs.pop(job_id) for job_id in ids]
    for job in removed:
        shutil.rmtree(job.dir, ignore_errors=True)
    persist_jobs()
    return {"removed": len(removed)}


@app.get("/api/jobs/{job_id}/files/{file_path:path}")
def download_file(job_id: str, file_path: str) -> FileResponse:
    job = get_job(job_id)
    base = job.dir.resolve()
    target = (base / file_path).resolve()
    if target != base and base not in target.parents:
        raise HTTPException(status_code=404, detail="File not found")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target, filename=target.name)


class ArchiveResponse(StreamingResponse):
    """Own a temporary archive until the response ends, including disconnects."""

    def __init__(self, output, filename: str):
        self.output = output
        size = output.tell()
        output.seek(0)
        super().__init__(iter(partial(output.read, 256 * 1024), b""), media_type="application/zip", headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            "Content-Length": str(size),
        })

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.output.close()


@app.get("/api/jobs/{job_id}/zip")
def download_zip(job_id: str) -> StreamingResponse:
    job = get_job(job_id)
    if job.status != "completed":
        raise HTTPException(status_code=409, detail="Wait for the download to finish before exporting")
    files = collect_files(job.dir)
    if not files:
        raise HTTPException(status_code=404, detail="No files to package")
    safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", job.title or "download").strip(" .")
    safe_title = (safe_title or "download")[:80]
    output = tempfile.TemporaryFile(dir=DOWNLOAD_DIR)
    try:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
            for path in files:
                archive.write(path, path.relative_to(job.dir))
        return ArchiveResponse(output, f"{safe_title}.zip")
    except BaseException:
        output.close()
        raise


@app.post("/api/jobs/{job_id}/reveal")
def reveal_job(job_id: str) -> Dict[str, Any]:
    job = get_job(job_id)
    if not job.dir.exists():
        raise HTTPException(status_code=404, detail="Download folder not found")
    if ANDROID_MODE:
        return {"ok": True, "path": str(job.dir)}
    try:
        open_path(job.dir)
    except Exception as exc:  # noqa: BLE001 - desktop integration is best-effort
        raise HTTPException(status_code=500, detail=f"Could not open folder: {clean_text(exc, 200)}")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/open-file")
def open_job_file(job_id: str, path: Optional[str] = None) -> Dict[str, Any]:
    job = get_job(job_id)
    if job.status != "completed":
        raise HTTPException(status_code=409, detail="Wait for the download to finish")
    base = job.dir.resolve()
    if base.parent != DOWNLOAD_DIR.resolve():
        raise HTTPException(status_code=404, detail="Download folder not found")
    if path:
        target = (base / path).resolve()
    else:
        target = next((p.resolve() for p in collect_files(base) if p.suffix.lower() in PLAYABLE_EXTENSIONS), base)
    if base not in target.parents or not target.is_file() or target.suffix.lower() not in PLAYABLE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="No supported media file to open. Use Open folder instead.")
    if ANDROID_MODE:
        return {"ok": True, "path": str(target)}
    try:
        open_path(target)
    except Exception as exc:  # noqa: BLE001 - desktop integration is best-effort
        raise HTTPException(status_code=500, detail=f"Could not open file: {clean_text(exc, 200)}")
    return {"ok": True}


@app.post("/api/open-downloads")
def open_downloads() -> Dict[str, Any]:
    if ANDROID_MODE:
        return {"ok": True, "path": str(DOWNLOAD_DIR)}
    try:
        open_path(DOWNLOAD_DIR)
    except Exception as exc:  # noqa: BLE001 - desktop integration is best-effort
        raise HTTPException(status_code=500, detail=f"Could not open folder: {clean_text(exc, 200)}")
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import webbrowser

    import uvicorn

    port = int(os.environ.get("PORT", "8765"))
    url = f"http://127.0.0.1:{port}"
    if sys.stdout is not None:
        print()
        print("  AllN1Downloader")
        print(f"  Running at {url}")
        print("  Press Ctrl+C to stop")
        print()
    if os.environ.get("NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        log_config=None if sys.stderr is None else uvicorn.config.LOGGING_CONFIG,
    )
