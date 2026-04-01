#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build script is for macOS only." >&2
  exit 1
fi

"$ROOT_DIR/scripts/build_macos_app.sh"

VERSION="$(python3 - <<'PY'
from gramwrite import __version__
print(__version__)
PY
)"

STAGE_DIR="$ROOT_DIR/dist/dmg-stage"
DMG_PATH="$ROOT_DIR/dist/GramWrite-${VERSION}.dmg"

rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"
cp -R "$ROOT_DIR/dist/GramWrite.app" "$STAGE_DIR/GramWrite.app"
ln -s /Applications "$STAGE_DIR/Applications"
rm -f "$DMG_PATH"

hdiutil create \
  -volname "GramWrite" \
  -srcfolder "$STAGE_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

echo "Built DMG at $DMG_PATH"
