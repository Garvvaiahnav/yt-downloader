#!/bin/bash
# Build "YT Downloader.dmg" (Apple Silicon). Run from anywhere on a Mac with uv.
# Builds in a temp folder on the internal disk: external exFAT drives add
# ._ files that break code signing.
#
# Signing (optional). Without these the app is ad-hoc signed and macOS asks
# the user to approve it once in System Settings > Privacy & Security.
#   MAC_SIGN_IDENTITY   "Developer ID Application: Name (TEAMID)", in the keychain
#   APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD   for notarization
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/dist}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

rsync -a --exclude '._*' --exclude '.DS_Store' --exclude '.git' --exclude 'dist' --exclude 'build' --exclude 'packaging/bin' "$ROOT/" "$WORK/src/"
cd "$WORK/src"
export UV_PROJECT_ENVIRONMENT="$WORK/venv" UV_LINK_MODE=copy
uv sync --group build --frozen --quiet
uv run --frozen python packaging/fetch_bins.py
uv run --frozen pyinstaller --noconfirm --clean --workpath "$WORK/build" --distpath "$WORK/dist" packaging/ytd.spec

APP="$WORK/dist/YT Downloader.app"
xattr -cr "$APP"
if [ -n "${MAC_SIGN_IDENTITY:-}" ]; then
  # Inside out: every binary, then the bundle, with the hardened runtime.
  find "$APP/Contents" -type f \( -perm -u+x -o -name '*.dylib' -o -name '*.so' \) -print0 |
    xargs -0 codesign --force --timestamp --options runtime --entitlements packaging/entitlements.plist --sign "$MAC_SIGN_IDENTITY"
  codesign --force --timestamp --options runtime --entitlements packaging/entitlements.plist --sign "$MAC_SIGN_IDENTITY" "$APP"
else
  codesign --force --deep --sign - "$APP"   # ad-hoc: required on Apple Silicon
fi

mkdir -p "$OUT"
DMG="$OUT/YT Downloader.dmg"
rm -f "$DMG"
tiffutil -cathidpicheck packaging/dmg-background.png packaging/dmg-background@2x.png -out "$WORK/bg.tiff" >/dev/null
mkdir -p "$WORK/dmg"
cp -R "$APP" "$WORK/dmg/"
if command -v create-dmg >/dev/null 2>&1 && create-dmg \
    --volname "YT Downloader" --background "$WORK/bg.tiff" \
    --window-size 640 400 --icon-size 96 --text-size 12 \
    --icon "YT Downloader.app" 170 190 --app-drop-link 470 190 \
    --hide-extension "YT Downloader.app" --no-internet-enable \
    "$DMG" "$WORK/dmg/" >/dev/null; then
  :
else
  # No Finder (headless) or no create-dmg: a plain DMG still installs fine.
  rm -f "$DMG"
  ln -s /Applications "$WORK/dmg/Applications"
  hdiutil create -volname "YT Downloader" -srcfolder "$WORK/dmg" -ov -format UDZO "$DMG" >/dev/null
fi

if [ -n "${MAC_SIGN_IDENTITY:-}" ]; then
  codesign --force --timestamp --sign "$MAC_SIGN_IDENTITY" "$DMG"
  if [ -n "${APPLE_ID:-}" ]; then
    xcrun notarytool submit "$DMG" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD" --wait
    xcrun stapler staple "$DMG"
  fi
fi
echo "Built $DMG"
