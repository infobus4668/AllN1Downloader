"""Update pinned Android build-tools and NDK versions from sdkmanager output."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIN_FILES = {
    "build-tools": ROOT / "android" / "build-tools-version.txt",
    "ndk": ROOT / "android" / "ndk-version.txt",
}


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def latest_sdk_version(output: str, package: str) -> str | None:
    """Return the highest stable version for an sdkmanager package family."""
    pattern = re.compile(rf"^\s*{re.escape(package)};([0-9]+(?:\.[0-9]+)+)\s+\|")
    versions = {match.group(1) for line in output.splitlines() if (match := pattern.match(line))}
    return max(versions, key=version_key) if versions else None


def update_pins(output: str) -> list[tuple[str, str, str]]:
    """Update local pins only when sdkmanager reports a newer stable release."""
    changes = []
    for package, path in PIN_FILES.items():
        latest = latest_sdk_version(output, package)
        if latest is None:
            raise RuntimeError(f"sdkmanager returned no stable {package} package")
        current = path.read_text(encoding="utf-8").strip()
        if version_key(latest) > version_key(current):
            path.write_text(f"{latest}\n", encoding="utf-8", newline="\n")
            changes.append((package, current, latest))
    return changes


def main() -> int:
    result = subprocess.run(
        ["sdkmanager", "--list", "--channel=0"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    changes = update_pins(result.stdout + "\n" + result.stderr)
    changed = bool(changes)
    if changed:
        for package, old, new in changes:
            print(f"{package}: {old} -> {new}")
    else:
        print("Android SDK pins are already current.")

    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as stream:
            stream.write(f"changed={'true' if changed else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
