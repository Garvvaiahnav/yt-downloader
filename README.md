# Video Downloader

Desktop app for downloading videos from YouTube, Instagram, Facebook, X, Threads
and TikTok at an exact resolution, codec and bitrate, and converting them so
Premiere Pro and After Effects open them. Every file is checked with ffprobe.

Made by Garv.

## Install

- **Mac (Apple Silicon):** open `Video Downloader.dmg`, drag the app to Applications.
  First launch only: macOS blocks apps from unidentified developers. Open
  System Settings → Privacy & Security, scroll down, click **Open Anyway**.
- **Windows (64-bit):** run `Video Downloader Setup.exe`. If SmartScreen appears,
  click **More info → Run anyway**. Installs for the current user, no admin needed.

ffmpeg, ffprobe and deno are bundled; nothing else needs installing.

## Use

1. Paste a YouTube link, press Fetch.
2. Pick resolution, video stream and audio stream. Only streams the video has
   are listed; the highest resolution is preselected.
3. Output: **Original** saves the streams as-is (MP4 / WebM / MKV).
   **Editor-ready** re-encodes to H.264 or HEVC MP4 for Premiere, Final Cut and
   Resolve. YouTube serves 1440p and 4K only as VP9/AV1, so use this for those.
4. Files go to `Movies/Video Downloader` on Mac, `Downloads/Video Downloader` on Windows (change in Settings).

If downloads start failing, Settings → Update yt-dlp, then restart the app.
Age-restricted and members-only videos need Settings → Browser cookies.

## Build

- Mac: `packaging/build_mac.sh` → `dist/Video Downloader.dmg`
- Windows: `packaging/build_windows.ps1` → `dist/Video Downloader Setup.exe`
- CI: `.github/workflows/build.yml` builds both on every push to `main`.

Dev run without packaging: `uv run app.py` (needs ffmpeg on PATH).
