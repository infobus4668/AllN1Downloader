"""Fast-forward a clean Git checkout before source-mode startup."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=45, check=False
    )


def update_checkout() -> str:
    if os.environ.get("ALLN1_AUTO_UPDATE", "1").strip().lower() in {"0", "false", "no", "off"}:
        return "Source auto-update disabled by ALLN1_AUTO_UPDATE."
    if not (ROOT / ".git").exists() or not shutil.which("git"):
        return "No Git checkout detected; source update skipped."

    branch = run_git("symbolic-ref", "--quiet", "--short", "HEAD")
    upstream = run_git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if branch.returncode or upstream.returncode:
        return "No tracked Git branch; source update skipped."

    status = run_git("status", "--porcelain", "--untracked-files=all")
    if status.returncode or status.stdout.strip():
        return "Local source changes found; source update skipped to preserve them."

    fetched = run_git("fetch", "--quiet", "--prune", "origin")
    if fetched.returncode:
        return "Could not check the source update host; continuing with the installed copy."
    before = run_git("rev-parse", "HEAD")
    if before.returncode:
        return "Could not read the source revision; continuing with the installed copy."
    pulled = run_git("pull", "--ff-only", "--quiet")
    if pulled.returncode:
        return "Source update was not a fast-forward; continuing with the installed copy."
    after = run_git("rev-parse", "HEAD")
    if after.returncode:
        return "Source checkout refreshed."
    if before.stdout.strip() != after.stdout.strip():
        return "Source checkout updated to the latest fast-forward."
    return "Source checkout is current."


if __name__ == "__main__":
    print(update_checkout())
