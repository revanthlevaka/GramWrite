#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build script is for macOS only." >&2
  exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ ! -d "$ROOT_DIR/.venv" ]]; then
  "$PYTHON_BIN" -m venv "$ROOT_DIR/.venv"
fi

source "$ROOT_DIR/.venv/bin/activate"
if [[ "${GRAMWRITE_SKIP_PIP_INSTALL:-0}" != "1" ]]; then
  python -m pip install --quiet --upgrade pip
  python -m pip install --quiet -r requirements.txt pyinstaller
fi

if ! "$ROOT_DIR/scripts/build_foundation_models_helper.sh"; then
  echo "Warning: could not prebuild the Apple Foundation Models helper. The app will still build, but that backend will stay unavailable until the helper can be compiled." >&2
fi

PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-/tmp/pyinstaller-cache}" \
  pyinstaller --noconfirm "$ROOT_DIR/GramWrite.spec"

echo "Built app bundle at $ROOT_DIR/dist/GramWrite.app"
