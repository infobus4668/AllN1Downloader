#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
cd "$ROOT"

command -v dpkg-deb >/dev/null || { echo 'dpkg-deb is required to build the .deb package' >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo 'Install FFmpeg before building the .deb package' >&2; exit 1; }
"$PYTHON" -m pip install -r requirements.txt -r packaging/requirements-build.txt
"$PYTHON" -m PyInstaller --noconfirm --clean --onefile --name AllN1Downloader \
  --collect-all yt_dlp --collect-all fastapi --collect-all uvicorn --collect-all starlette \
  --add-data 'static:static' app.py

VERSION="$(sed -n 's/^APP_VERSION = "\([^"]*\)"/\1/p' app.py | head -n 1)"
ARCH="$(dpkg --print-architecture)"
STAGE="$(mktemp -d)"
SIGNING_HOME=""
cleanup() {
  rm -rf "$STAGE"
  if [[ -n "$SIGNING_HOME" ]]; then rm -rf "$SIGNING_HOME"; fi
}
trap cleanup EXIT
install -Dm755 dist/AllN1Downloader "$STAGE/opt/alln1downloader/AllN1Downloader"
install -d "$STAGE/usr/bin" "$STAGE/usr/share/applications" "$STAGE/DEBIAN"
install -Dm644 packaging/apt/alln1downloader-archive-keyring.asc \
  "$STAGE/usr/share/keyrings/alln1downloader-archive-keyring.asc"
install -d "$STAGE/etc/apt/sources.list.d"
cat > "$STAGE/etc/apt/sources.list.d/alln1downloader.sources" <<'APT_SOURCE'
Types: deb
URIs: https://infobus4668.github.io/AllN1Downloader/apt
Suites: stable
Components: main
Architectures: amd64
Signed-By: /usr/share/keyrings/alln1downloader-archive-keyring.asc
APT_SOURCE
cat > "$STAGE/usr/bin/alln1downloader" <<'WRAPPER'
#!/bin/sh
exec /opt/alln1downloader/AllN1Downloader "$@"
WRAPPER
chmod 755 "$STAGE/usr/bin/alln1downloader"
cat > "$STAGE/usr/share/applications/alln1downloader.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=AllN1Downloader
Comment=Download media with yt-dlp
Exec=alln1downloader
Terminal=false
Categories=AudioVideo;Video;
DESKTOP
cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: alln1downloader
Version: $VERSION
Section: video
Priority: optional
Architecture: $ARCH
Depends: ffmpeg, xdg-utils
Suggests: nodejs (>= 20)
Maintainer: AllN1Downloader maintainers
Description: Local web-interface media downloader powered by yt-dlp
 Download media to the current user's machine using a loopback-only web interface.
CONTROL
mkdir -p dist
dpkg-deb --build --root-owner-group "$STAGE" "dist/alln1downloader_${VERSION}_${ARCH}.deb"
echo "Built dist/alln1downloader_${VERSION}_${ARCH}.deb"

if [[ -n "${DEB_SIGNING_KEY_BASE64:-}" ]]; then
  command -v gpg >/dev/null || { echo 'gpg is required to sign Debian artifacts' >&2; exit 1; }
  [[ -n "${DEB_SIGNING_KEY_ID:-}" ]] || { echo 'DEB_SIGNING_KEY_ID is required to sign Debian artifacts' >&2; exit 1; }
  SIGNING_HOME="$(mktemp -d)"
  chmod 700 "$SIGNING_HOME"
  export GNUPGHOME="$SIGNING_HOME"
  printf '%s' "$DEB_SIGNING_KEY_BASE64" | base64 --decode > "$SIGNING_HOME/signing-key.asc"
  gpg --batch --import "$SIGNING_HOME/signing-key.asc"
  PACKAGE="dist/alln1downloader_${VERSION}_${ARCH}.deb"
  [[ -f "$PACKAGE" ]] || { echo "Debian package not found: $PACKAGE" >&2; exit 1; }
  if [[ -n "${DEB_SIGNING_PASSPHRASE:-}" ]]; then
    printf '%s\n' "$DEB_SIGNING_PASSPHRASE" | gpg --batch --yes --pinentry-mode loopback --passphrase-fd 0 \
      --local-user "$DEB_SIGNING_KEY_ID" --armor --detach-sign --output "${PACKAGE}.asc" "$PACKAGE"
  else
    gpg --batch --yes --local-user "$DEB_SIGNING_KEY_ID" --armor --detach-sign --output "${PACKAGE}.asc" "$PACKAGE"
  fi
  (cd dist && sha256sum -- "${PACKAGE##*/}" > SHA256SUMS)
  if [[ -n "${DEB_SIGNING_PASSPHRASE:-}" ]]; then
    printf '%s\n' "$DEB_SIGNING_PASSPHRASE" | gpg --batch --yes --pinentry-mode loopback --passphrase-fd 0 \
      --local-user "$DEB_SIGNING_KEY_ID" --armor --detach-sign --output dist/SHA256SUMS.asc dist/SHA256SUMS
  else
    gpg --batch --yes --local-user "$DEB_SIGNING_KEY_ID" --armor --detach-sign --output dist/SHA256SUMS.asc dist/SHA256SUMS
  fi
  echo 'Created detached GPG signatures and signed SHA256SUMS in dist/'
elif [[ "${REQUIRE_DEB_SIGNING:-0}" == '1' ]]; then
  echo 'Debian artifact signing is required but DEB_SIGNING_KEY_BASE64 was not supplied.' >&2
  exit 1
else
  echo 'Debian artifacts are unsigned (set DEB_SIGNING_KEY_BASE64 to sign them).'
fi
