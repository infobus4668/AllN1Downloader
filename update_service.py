"""Signed-release discovery and Windows self-update helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_REPOSITORY = "infobus4668/AllN1Downloader"
WINDOWS_SIGNER_THUMBPRINT = "9F1BFF66846716DC3E579D9F61E7A412D36E6336"
RELEASE_API = "https://api.github.com/repos/{repository}/releases/latest"
USER_AGENT = "AllN1Downloader-UpdateCheck/1"
MAX_WINDOWS_EXE_SIZE = 750 * 1024 * 1024
MAX_RELEASE_METADATA_SIZE = 1024 * 1024
SHA256_DIGEST = re.compile(r"sha256:([0-9a-fA-F]{64})")


def version_key(value: str) -> tuple[int, ...] | None:
    """Accept stable numeric release versions, optionally prefixed with v."""
    match = re.fullmatch(r"v?([0-9]{1,9}(?:\.[0-9]{1,9}){1,3})", str(value))
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def release_info(release: dict[str, Any], current_version: str, platform: str,
                 repository: str = DEFAULT_REPOSITORY) -> dict[str, Any]:
    tag = str(release.get("tag_name") or "")
    latest_version = tag[1:] if tag.startswith("v") else tag
    current_key = version_key(current_version)
    latest_key = version_key(tag)
    result = {
        "status": "current",
        "current_version": current_version,
        "latest_version": latest_version,
        "available": False,
        "release_url": f"https://github.com/{repository}/releases/latest",
        "asset_name": "",
        "asset_url": "",
        "asset_digest": "",
    }
    if not current_key or not latest_key:
        result["status"] = "invalid_release_version"
        return result
    if latest_key <= current_key:
        return result

    asset_name = {
        "windows": "AllN1Downloader-Windows-x64.exe",
        "android": "AllN1Downloader-Android.apk",
        "linux": f"alln1downloader_{latest_version}_amd64.deb",
    }.get(platform)
    assets = release.get("assets")
    asset = next((item for item in assets if isinstance(item, dict) and item.get("name") == asset_name), None) \
        if asset_name and isinstance(assets, list) else None
    if not asset:
        result["status"] = "release_asset_missing"
        return result
    asset_url = f"https://github.com/{repository}/releases/download/{tag}/{asset_name}"
    digest = str(asset.get("digest") or "")
    if asset.get("browser_download_url") != asset_url or (platform == "windows" and not SHA256_DIGEST.fullmatch(digest)):
        result["status"] = "invalid_release_asset"
        return result

    result.update({
        "status": "available",
        "available": True,
        "asset_name": asset_name,
        "asset_url": asset_url,
        "asset_digest": digest,
    })
    return result


def fetch_latest_release(repository: str, current_version: str, platform: str, timeout: float = 4.0) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid update repository")
    request = urllib.request.Request(
        RELEASE_API.format(repository=repository),
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_RELEASE_METADATA_SIZE + 1)
    except urllib.error.HTTPError as error:
        if error.code == 404 and repository == DEFAULT_REPOSITORY:
            error.close()
            result = release_info({}, current_version, platform, repository)
            return {**result, "status": "no_release"}
        raise
    if len(payload) > MAX_RELEASE_METADATA_SIZE:
        raise ValueError("Release metadata is too large")
    release = json.loads(payload)
    if not isinstance(release, dict):
        raise ValueError("Invalid release metadata")
    return release_info(release, current_version, platform, repository)


def verify_windows_signature(path: Path, expected_thumbprint: str = WINDOWS_SIGNER_THUMBPRINT) -> None:
    """Verify Authenticode integrity and the pinned self-signed publisher identity."""
    if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_thumbprint):
        raise ValueError("Invalid Authenticode signer thumbprint")
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


def download_windows_update(asset_url: str, asset_digest: str, work_dir: Path) -> Path:
    """Download, checksum and Authenticode-verify the replacement Windows EXE."""
    if not asset_url.startswith("https://github.com/"):
        raise RuntimeError("Update asset URL is not an HTTPS GitHub release asset")
    expected_digest = SHA256_DIGEST.fullmatch(asset_digest)
    if not expected_digest:
        raise RuntimeError("Windows update requires a valid SHA-256 digest")
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
        if digest.hexdigest() != expected_digest.group(1).lower():
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
