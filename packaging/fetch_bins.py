"""Download the ffmpeg, ffprobe and deno binaries that ship inside the app.

    python packaging/fetch_bins.py        -> packaging/bin/

Every download is a fixed version checked against a SHA-256 recorded here, so
a build never picks up a binary nobody has looked at. To upgrade one, change
its URL and checksum together.

Sources:
  macOS arm64  ffmpeg/ffprobe 9.0.2  ffmpeg.martin-riedl.de (static builds)
  Windows x64  ffmpeg/ffprobe 9.0.2  github.com/GyanD/codexffmpeg (gyan.dev essentials)
  both         deno 2.9.8            github.com/denoland/deno releases
"""

import hashlib
import io
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parent / "bin"

_RIEDL = "https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2"
_DENO = "https://github.com/denoland/deno/releases/download/v2.9.8"
_GYAN = "https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip"

# name in bin/ -> (url, member inside the zip, sha256 of the zip)
MAC = {
    "ffmpeg": (f"{_RIEDL}/ffmpeg.zip", "ffmpeg", "c8ed4c4e6978a03c485edbfe4e0a5dc2380f8a30bba5150531b31b094492d924"),
    "ffprobe": (f"{_RIEDL}/ffprobe.zip", "ffprobe", "fcbe839537485eaee7a7a8bc5cbc0f90d53617e80943e8a5b2e31cb851197ea6"),
    "deno": (f"{_DENO}/deno-aarch64-apple-darwin.zip", "deno", "9f0bf660393da2eaff044cdc7444cb08c73f235849b61d224d825a194ce7c98e"),
}
WIN = {
    "ffmpeg.exe": (_GYAN, "ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe", "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"),
    "ffprobe.exe": (_GYAN, "ffmpeg-9.0.2-essentials_build/bin/ffprobe.exe", "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"),
    "deno.exe": (f"{_DENO}/deno-x86_64-pc-windows-msvc.zip", "deno.exe", "cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf"),
}

_cache = {}


def fetch(url):
    if url not in _cache:
        print("  GET", url, flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": "yt-downloader-build"})
        with urllib.request.urlopen(req, timeout=600) as r:
            _cache[url] = r.read()
    return _cache[url]


def main():
    if sys.platform == "darwin":
        if platform.machine() != "arm64":
            sys.exit("Mac builds are arm64 only.")
        table = MAC
    elif sys.platform == "win32":
        table = WIN
    else:
        sys.exit("Unsupported build platform.")
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    for name, (url, member, sha) in table.items():
        blob = fetch(url)
        got = hashlib.sha256(blob).hexdigest()
        if got != sha:
            sys.exit(f"Checksum mismatch for {url}\n  expected {sha}\n  got      {got}")
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            data = z.read(member)
        dest = OUT / name
        dest.write_bytes(data)
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    for name in table:
        arg = "--version" if name.startswith("deno") else "-version"
        out = subprocess.run([str(OUT / name), arg], capture_output=True, text=True).stdout.splitlines()
        print(f"  {name}: {out[0] if out else '??'}")
    if sys.platform == "darwin":
        subprocess.run(["xattr", "-cr", str(OUT)], stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
