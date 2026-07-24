#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 ConcordiaPax LLC
#
# Build the distributable Fukasawa executable with PyInstaller.
# Run from anywhere; it locates the repo root from its own path.
#
#   ./packaging/build.sh            # build with the active python
#   PYTHON=.venv/bin/python ./packaging/build.sh   # pin an interpreter
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
echo "==> Building from $ROOT with $PYTHON"

# PyInstaller is a build-time tool, not a runtime dependency.
"$PYTHON" -m PyInstaller --version >/dev/null 2>&1 || {
  echo "PyInstaller not found. Install it: $PYTHON -m pip install pyinstaller"
  exit 1
}

# Clean previous artifacts so a stale build can't masquerade as a fresh one.
rm -rf build dist

"$PYTHON" -m PyInstaller --clean --noconfirm packaging/fukasawa.spec

BIN="dist/fukasawa"
if [[ -x "$BIN" ]]; then
  echo "==> Built: $BIN ($(du -h "$BIN" | cut -f1))"
  echo "    Double-click it for the desktop app, or run '$BIN --help' for the CLI."
else
  echo "Build finished but $BIN was not found." >&2
  exit 1
fi
