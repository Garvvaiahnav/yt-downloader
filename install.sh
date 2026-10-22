#!/bin/bash
# Video Downloader installer for Mac (Apple Silicon). Developed by Garv.
#
#   curl -fsSL https://raw.githubusercontent.com/Garvvaiahnav/yt-downloader/main/install.sh | bash
#
# Why this exists: a DMG downloaded in a browser is quarantined, and macOS then
# refuses to open an app that isn't notarized ("Video Downloader Not Opened").
# Files fetched by curl are not quarantined, so the app installed here opens
# normally. The app updates itself afterwards the same way.
#
# Test overrides: VD_INSTALL_DIR (default /Applications), VD_NO_LAUNCH=1.
set -euo pipefail

REPO="Garvvaiahnav/yt-downloader"
FEED="https://github.com/$REPO/releases/latest/download"
APP="Video Downloader.app"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf 'Install stopped: %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "this installer is for Mac. On Windows use install.ps1."
[ "$(uname -m)" = "arm64" ] || die "Video Downloader needs an Apple Silicon Mac (M1 or newer)."

DEST="${VD_INSTALL_DIR:-/Applications}"
if [ ! -w "$DEST" ]; then
  DEST="$HOME/Applications"
  mkdir -p "$DEST"
fi

WORK="$(mktemp -d)"
MNT="$WORK/mnt"
cleanup() {
  hdiutil detach "$MNT" -quiet >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

say "Looking up the latest version..."
curl -fsSL "$FEED/manifest.json" -o "$WORK/manifest.json" || die "could not reach GitHub."
VERSION="$(plutil -extract version raw -o - "$WORK/manifest.json")"
URL="$(plutil -extract assets.darwin-arm64.url raw -o - "$WORK/manifest.json")"
SHA="$(plutil -extract assets.darwin-arm64.sha256 raw -o - "$WORK/manifest.json")"
case "$URL" in
  "https://github.com/$REPO/releases/download/"*) ;;
  *) die "the release points somewhere unexpected." ;;
esac

say "Downloading Video Downloader $VERSION..."
curl -fL --progress-bar "$URL" -o "$WORK/app.dmg" || die "download failed."
[ "$(shasum -a 256 "$WORK/app.dmg" | cut -d' ' -f1)" = "$SHA" ] || die "the download is corrupted (checksum mismatch). Run the command again."

say "Installing to $DEST..."
mkdir -p "$MNT"
hdiutil attach -nobrowse -readonly -mountpoint "$MNT" "$WORK/app.dmg" >/dev/null
[ -d "$MNT/$APP" ] || die "the installer file has no $APP inside."

# Quit a running copy so it can be replaced.
if pgrep -f "$APP/Contents/MacOS" >/dev/null 2>&1; then
  osascript -e 'tell application "Video Downloader" to quit' >/dev/null 2>&1 || true
  sleep 2
fi
rm -rf "$DEST/$APP" "$DEST/YT Downloader.app"
ditto "$MNT/$APP" "$DEST/$APP"
xattr -cr "$DEST/$APP" 2>/dev/null || true

say "Done. Video Downloader $VERSION is in $DEST."
if [ -z "${VD_NO_LAUNCH:-}" ]; then
  open "$DEST/$APP"
fi
