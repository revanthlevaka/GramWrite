#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_FILE="$ROOT_DIR/gramwrite/native/GramWriteFoundationModels.swift"
APP_BUNDLE="$ROOT_DIR/gramwrite/native/GramWriteFoundationModelsHelper.app"
OUTPUT_FILE="$APP_BUNDLE/Contents/MacOS/gramwrite-foundation-models"
CACHE_ROOT="${TMPDIR:-/tmp}/gramwrite-swift-build-cache"

mkdir -p "$CACHE_ROOT/swift" "$CACHE_ROOT/clang"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Foundation Models helper builds only on macOS." >&2
  exit 1
fi

if ! command -v xcrun >/dev/null 2>&1; then
  echo "xcrun is required to build the Foundation Models helper." >&2
  exit 1
fi

if [[ ! -f "$SOURCE_FILE" ]]; then
  echo "Missing helper source: $SOURCE_FILE" >&2
  exit 1
fi

rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
cat > "$APP_BUNDLE/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>gramwrite-foundation-models</string>
  <key>CFBundleIdentifier</key><string>com.revanthlevaka.gramwrite.foundationmodels</string>
  <key>CFBundleName</key><string>GramWrite Foundation Models Helper</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>15.1</string>
</dict>
</plist>
PLIST

SWIFT_MODULECACHE_PATH="$CACHE_ROOT/swift" \
CLANG_MODULE_CACHE_PATH="$CACHE_ROOT/clang" \
xcrun swiftc -parse-as-library "$SOURCE_FILE" -o "$OUTPUT_FILE"

chmod +x "$OUTPUT_FILE"
/usr/bin/codesign --force --deep --sign - "$APP_BUNDLE"
echo "Built Foundation Models helper app at $APP_BUNDLE"
