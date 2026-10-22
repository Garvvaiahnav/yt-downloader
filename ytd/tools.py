"""Finding ffmpeg, ffprobe and deno, and working out which video encoders
actually run on this machine (an encoder can be compiled into ffmpeg and still
fail, e.g. h264_nvenc on a PC with no NVIDIA card)."""

import functools
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# Hide the console window that subprocess would flash on Windows.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WIN else 0


FROZEN = getattr(sys, "frozen", False)
# The installed app carries its own ffmpeg, ffprobe and deno here.
BUNDLED = Path(getattr(sys, "_MEIPASS", "")) / "bin" if FROZEN else None


def _extra_dirs():
    # Dev runs: the venv's bin dir holds deno (from PyPI), Homebrew holds ffmpeg.
    dirs = [Path(sys.executable).parent]
    if IS_MAC:
        dirs += [Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
    return dirs


@functools.cache
def find(name):
    exe = name + (".exe" if IS_WIN else "")
    if BUNDLED:
        # Never fall back to whatever happens to be on PATH: the bundled
        # binaries are the ones the app was tested with.
        p = BUNDLED / exe
        return str(p) if p.is_file() else None
    found = shutil.which(name)
    if found:
        return found
    for d in _extra_dirs():
        p = d / exe
        if p.is_file():
            return str(p)
    return None


def run(args, timeout=30):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          creationflags=NO_WINDOW, encoding="utf-8", errors="replace")


@functools.cache
def version(name):
    path = find(name)
    if not path:
        return None
    try:
        out = run([path, "-version" if name.startswith("ff") else "--version"]).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    first = out.splitlines()[0] if out else ""
    # "ffmpeg version 8.1.1 Copyright ..." / "deno 2.9.8 (stable, ...)"
    parts = first.split()
    if name.startswith("ff") and len(parts) > 2:
        return parts[2]
    return parts[1] if len(parts) > 1 else first


# Hardware first, CPU last. Order inside each list is the preference order.
_CANDIDATES = {
    "h264": ["h264_videotoolbox", "h264_nvenc", "h264_qsv", "h264_amf", "libx264"],
    "hevc": ["hevc_videotoolbox", "hevc_nvenc", "hevc_qsv", "hevc_amf", "libx265"],
    "prores": ["prores_videotoolbox", "prores_ks"],
}

ENCODER_NAMES = {
    "videotoolbox": "Apple VideoToolbox",
    "nvenc": "NVIDIA NVENC",
    "qsv": "Intel Quick Sync",
    "amf": "AMD AMF",
    "libx264": "CPU (x264)",
    "libx265": "CPU (x265)",
    "prores_ks": "CPU",
}


def encoder_label(enc):
    for key, label in ENCODER_NAMES.items():
        if key in enc:
            return label
    return enc


def _encoder_works(ffmpeg, enc):
    # 256x256 because NVENC refuses tiny frames; 10 frames so the encoder has
    # to actually open a session, not just parse options.
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", "color=c=black:s=256x256:r=10:d=1", "-frames:v", "10",
            "-c:v", enc, "-f", "null", "-"]
    try:
        return run(args, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


_ENCODER_CACHE_DAYS = 7


@functools.cache
def encoders():
    """{'h264': 'h264_videotoolbox', 'hevc': 'libx265', ...} - the first working
    encoder per codec, or None for a codec nothing here can produce.

    Probing means a test encode per candidate (~0.6 s on every launch), so the
    answer is kept on disk for a week, keyed by the ffmpeg build, and the
    probes run in parallel when it is recomputed."""
    from concurrent.futures import ThreadPoolExecutor
    from .settings import config_dir

    ffmpeg = find("ffmpeg")
    if not ffmpeg:
        return {codec: None for codec in _CANDIDATES}
    key = f"{ffmpeg}|{version('ffmpeg')}|{sys.platform}"
    cache = config_dir() / "encoders.json"
    try:
        saved = json.loads(cache.read_text("utf-8"))
        if saved["key"] == key and time.time() - saved["at"] < _ENCODER_CACHE_DAYS * 86400 \
                and set(saved["picked"]) == set(_CANDIDATES):
            return saved["picked"]
    except (OSError, ValueError, KeyError):
        pass

    listed = run([ffmpeg, "-hide_banner", "-encoders"]).stdout
    names = [n for ns in _CANDIDATES.values() for n in ns if f" {n} " in listed]
    with ThreadPoolExecutor(max_workers=len(names) or 1) as pool:
        works = dict(zip(names, pool.map(lambda n: _encoder_works(ffmpeg, n), names)))
    picked = {codec: next((n for n in ns if works.get(n)), None) for codec, ns in _CANDIDATES.items()}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"key": key, "at": time.time(), "picked": picked}), "utf-8")
    except OSError:
        pass
    return picked


def forget_encoders():
    """After an encode fails (driver removed, GPU swapped), re-probe next launch."""
    from .settings import config_dir
    (config_dir() / "encoders.json").unlink(missing_ok=True)
