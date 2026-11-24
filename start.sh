#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python3}"

if [ ! -x .venv/bin/python ]; then
  "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || {
    echo 'Install Python 3.11 or newer.' >&2
    exit 1
  }
  "$PYTHON" -m venv .venv
fi

if [ "${ALLN1_AUTO_UPDATE:-1}" != '0' ]; then
  .venv/bin/python scripts/update_source.py || true
fi

if ! cmp -s requirements.txt .venv/installed-requirements.txt; then
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
  .venv/bin/python -m pip check
  cp requirements.txt .venv/installed-requirements.txt
fi

exec .venv/bin/python app.py
