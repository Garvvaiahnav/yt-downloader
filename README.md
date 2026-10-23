# Video Downloader

Desktop app for downloading videos from YouTube, Instagram, Facebook, X, Threads
and TikTok at an exact resolution, codec and bitrate, and converting them so
Premiere Pro and After Effects open them. Every file is checked with ffprobe.

Developed by Garv.

## Install

Use the one-liner for your computer. It downloads the latest release, checks its
checksum and installs it, and the warnings below don't appear.

**Mac (Apple Silicon)**. Open Terminal, paste, press Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/Garvvaiahnav/yt-downloader/main/install.sh | bash
```

**Windows (64-bit)**. Open PowerShell, paste, press Enter. Installs for the current
user, no admin needed:

```powershell
irm https://raw.githubusercontent.com/Garvvaiahnav/yt-downloader/main/install.ps1 | iex
```

After that the app updates itself: it checks for new versions at launch and every
6 hours, and the version number is shown at the top of the app.

### Why a one-liner instead of the download button

The app isn't signed with a paid Apple/Microsoft certificate. A file saved by a
browser is flagged, and then macOS says "Video Downloader Not Opened" and Windows
SmartScreen warns about an unknown publisher. Files saved by `curl` and PowerShell
aren't flagged, so the same app opens normally. In-app updates work the same way.

### Already downloaded the DMG or Setup.exe from a browser?

- **Mac:** run the Mac one-liner above (it replaces the blocked copy), or, to keep
  the copy you have: `xattr -dr com.apple.quarantine "/Applications/Video Downloader.app"`
- **Windows:** right-click the Setup.exe → Properties → tick **Unblock** → OK, then run it.
  Or run the Windows one-liner above.

### Removing the warnings completely

Needs paid certificates, which the build already supports through GitHub secrets:
a Developer ID certificate plus notarization on Mac (`MAC_CERT_P12_BASE64`,
`MAC_CERT_PASSWORD`, `MAC_SIGN_IDENTITY`, `APPLE_ID`, `APPLE_TEAM_ID`,
`APPLE_APP_PASSWORD`), and an Authenticode certificate on Windows
(`WINDOWS_PFX_BASE64`, `WINDOWS_PFX_PASSWORD`).

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

## After Effects panel

Settings → After Effects panel → Install, restart After Effects, then
Window → Extensions → Video Downloader. Paste a link, pick ProRes 422 (smoothest
in AE), H.264 or Original, and **Download & Import** lands it in the project's
"Video Downloader" folder, and in the active comp if that box is ticked. The
Video Downloader app must be open; the panel's button opens it if it isn't.

## Build

- Mac: `packaging/build_mac.sh` → `dist/Video Downloader.dmg`
- Windows: `packaging/build_windows.ps1` → `dist/Video Downloader Setup.exe`
- CI: `.github/workflows/build.yml` builds both on every push to `main`.

Dev run without packaging: `uv run app.py` (needs ffmpeg on PATH).
