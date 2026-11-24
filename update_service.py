"""Signed-release discovery and Windows self-update helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_REPOSITORY = "infobus4668/AllN1Downloader"
WINDOWS_SIGNER_THUMBPRINT = "9F1BFF66846716DC3E579D9F61E7A412D36E6336"
RELEASE_API = "https://api.github.com/repos/{repository}/releases/latest"
USER_AGENT = "AllN1Downloader-UpdateCheck/1"
MAX_WINDOWS_EXE_SIZE = 750 * 1024 * 1024


def version_key(value: str) -> tuple[int, ...] | None:
    """Accept stable numeric release versions, optionally prefixed with v."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+){1,3})", str(value).strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def release_info(release: dict[str, Any], current_version: str, platform: str) -> dict[str, Any]:
    tag = str(release.get("tag_name") or "")
    latest_version = tag[1:] if tag.startswith("v") else tag
    current_key = version_key(current_version)
    latest_key = version_key(latest_version)
    result = {
        "status": "current",
        "current_version": current_version,
        "latest_version": latest_version,
        "available": False,
        "release_url": str(release.get("html_url") or ""),
        "asset_name": "",
        "asset_url": "",
        "asset_digest": "",
    }
    if not current_key or not latest_key:
        result["status"] = "invalid_release_version"
        return result
    if latest_key <= current_key:
        return result

    assets = release.get("assets") or []
    if platform == "windows":
        asset = next((item for item in assets if item.get("name") == "AllN1Downloader-Windows-x64.exe"), None)
    elif platform == "android":
        asset = next((item for item in assets if item.get("name") == "AllN1Downloader-Android.apk"), None)
    elif platform == "linux":
        asset = next((item for item in assets if str(item.get("name", "")).startswith("alln1downloader_") and str(item.get("name", "")).endswith("_amd64.deb")), None)
    else:
        asset = None
    if not asset:
        result["status"] = "release_asset_missing"
        return result

    result.update({
        "status": "available",
        "available": True,
        "asset_name": str(asset.get("name") or ""),
        "asset_url": str(asset.get("browser_download_url") or ""),
        "asset_digest": str(asset.get("digest") or ""),
    })
    return result


def fetch_latest_release(repository: str, current_version: str, platform: str, timeout: float = 4.0) -> dict[str, Any]:
    request = urllib.request.Request(
        RELEASE_API.format(repository=repository),
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        release = json.load(response)
    return release_info(release, current_version, platform)


def verify_windows_signature(path: Path, expected_thumbprint: str = WINDOWS_SIGNER_THUMBPRINT) -> None:
    """Verify Authenticode integrity and the pinned self-signed publisher identity."""
    escaped = str(path).replace("'", "''")
    script = (
        f"$s=Get-AuthenticodeSignature -LiteralPath '{escaped}'; "
        "if (-not $s.SignerCertificate) { exit 20 }; "
        f"if ($s.SignerCertificate.Thumbprint -ne '{expected_thumbprint}') {{ exit 21 }}; "
        "if ($s.Status -eq 'HashMismatch' -or $s.Status -eq 'NotSigned') { exit 22 }; "
        "if ($null -eq $s.TimeStamperCertificate) { exit 23 }; "
        "if ($s.Status -ne 'Valid' -and $s.Status -ne 'UnknownError') { exit 24 }; "
        "Write-Output $s.SignerCertificate.Thumbprint"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0 or result.stdout.strip().upper() != expected_thumbprint.upper():
        raise RuntimeError("Downloaded update does not have a valid signature from the pinned publisher")


def download_windows_update(asset_url: str, asset_digest: str, executable: Path, work_dir: Path) -> Path:
    """Download, checksum and Authenticode-verify the replacement Windows EXE."""
    if not asset_url.startswith("https://github.com/"):
        raise RuntimeError("Update asset URL is not an HTTPS GitHub release asset")
    update_dir = work_dir / "updates"
    update_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix="alln1downloader-", suffix=".exe", dir=update_dir)
    temporary = Path(temporary_name)
    try:
        request = urllib.request.Request(asset_url, headers={"User-Agent": USER_AGENT})
        digest = hashlib.sha256()
        total = 0
        with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(request, timeout=30) as response:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_WINDOWS_EXE_SIZE:
                    raise RuntimeError("Windows update exceeds the supported package size")
                digest.update(chunk)
                output.write(chunk)
        if total == 0:
            raise RuntimeError("Downloaded Windows update is empty")
        if asset_digest.startswith("sha256:") and digest.hexdigest().lower() != asset_digest.split(":", 1)[1].lower():
            raise RuntimeError("Windows update checksum does not match the GitHub release metadata")
        verify_windows_signature(temporary)
        return temporary
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def launch_windows_replacement(downloaded: Path, executable: Path, process_id: int) -> None:
    """Start a small PowerShell helper that replaces the EXE after this process exits."""
    helper = executable.parent / f".alln1-update-{process_id}.ps1"
    source = str(downloaded).replace("'", "''")
    target = str(executable).replace("'", "''")
    script = "\n".join((
        "$ErrorActionPreference = 'Stop'",
        f"Wait-Process -Id {process_id}",
        f"Move-Item -LiteralPath '{source}' -Destination '{target}' -Force",
        f"Start-Process -FilePath '{target}'",
        "Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue",
    ))
    helper.write_text(script, encoding="utf-8")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(helper)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
            close_fds=True,
        )
    except Exception:
        helper.unlink(missing_ok=True)
        raise
