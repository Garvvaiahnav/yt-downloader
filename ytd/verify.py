"""After every download: ffprobe the file and compare it with what was picked.

The comparison is against yt-dlp's own numbers for the chosen streams (or the
chosen encode settings), so a pass means the file on disk is what the UI said
it would be, not just that "a file appeared"."""

import json
import subprocess

from .formats import afamily, vfamily
from .tools import NO_WINDOW, find

_FORMAT_FAMILY = {"mp4": "mp4", "m4a": "mp4", "mov": "mov", "webm": "matroska", "mkv": "matroska",
                  "mp3": "mp3", "wav": "wav", "opus": "ogg"}


def _probe(path):
    out = subprocess.run([find("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                         capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW,
                         encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "ffprobe failed")
    return json.loads(out.stdout)


def _stream_kbps(path, stream, index_kind, duration):
    """Exact average bitrate of one stream. MKV/WebM written by ffmpeg carry no
    per-stream bit_rate, so sum the packet sizes instead of guessing."""
    if stream.get("bit_rate"):
        return int(stream["bit_rate"]) / 1000
    if not duration:
        return None
    out = subprocess.run([find("ffprobe"), "-v", "error", "-select_streams", index_kind,
                          "-show_entries", "packet=size", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, timeout=300, creationflags=NO_WINDOW)
    total = sum(int(x) for x in out.stdout.split() if x.strip().isdigit())
    return total * 8 / duration / 1000 if total else None


def _fps(s):
    num, _, den = (s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1").partition("/")
    try:
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0


def _row(field, expected, actual, ok):
    return {"field": field, "expected": expected, "actual": actual, "ok": bool(ok)}


def check(path, expect):
    """expect keys (all optional): ext, vfam, width, height, fps, vkbps, vtol,
    afam, akbps, atol. Returns {'ok': bool, 'rows': [...]}."""
    data = _probe(path)
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or 0)
    vs = next((s for s in data["streams"] if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    as_ = next((s for s in data["streams"] if s.get("codec_type") == "audio"), None)
    rows = []

    ext = expect.get("ext")
    if ext:
        actual_ext = str(path).rsplit(".", 1)[-1].lower()
        fam = _FORMAT_FAMILY.get(ext, ext)
        rows.append(_row("Container", ext.upper(), f"{actual_ext.upper()} ({fmt.get('format_name')})",
                         actual_ext == ext and fam in (fmt.get("format_name") or "")))

    if expect.get("audio_only"):
        if vs:
            rows.append(_row("Video", "none (audio only)", vfamily(vs.get("codec_name")), False))
    elif not vs:
        rows.append(_row("Video", expect.get("vfam", "video"), "no video stream", False))
    else:
        got = vfamily(vs.get("codec_name"))
        if "vfam" in expect:
            rows.append(_row("Video codec", expect["vfam"].upper(), got.upper(), got == expect["vfam"]))
        else:  # the site didn't say; report what arrived
            rows.append(_row("Video codec", "as served", got.upper(), True))
        w, h = vs.get("width"), vs.get("height")
        if "width" in expect:
            rows.append(_row("Resolution", f"{expect['width']}x{expect['height']}", f"{w}x{h}",
                             (w, h) == (expect["width"], expect["height"])))
        if expect.get("fps"):
            fps = _fps(vs)
            rows.append(_row("FPS", expect["fps"], round(fps, 2), abs(fps - expect["fps"]) <= 1))
        if expect.get("vkbps"):
            kbps = _stream_kbps(path, vs, "v:0", duration)
            tol = expect.get("vtol", 0.1)
            if expect.get("vceiling"):
                # An encode's bitrate is a ceiling: hardware encoders spend
                # less on simple pictures, which is not a fault.
                ok = kbps is not None and kbps <= expect["vkbps"] * (1 + tol)
                want = f"up to {expect['vkbps']:.0f} kbps"
            else:
                ok = kbps is not None and abs(kbps - expect["vkbps"]) <= expect["vkbps"] * tol
                want = f"{expect['vkbps']:.0f} kbps (±{tol:.0%})"
            rows.append(_row("Video bitrate", want, f"{kbps:.0f} kbps" if kbps else "unknown", ok))

    if "afam" in expect:
        if not as_:
            rows.append(_row("Audio", expect["afam"], "no audio stream", False))
        else:
            got = afamily(as_.get("codec_name"))
            rows.append(_row("Audio codec", expect["afam"].upper(), got.upper(), got == expect["afam"]))
            if expect.get("akbps"):
                kbps = _stream_kbps(path, as_, "a:0", duration)
                tol = expect.get("atol", 0.1)
                ok = kbps is not None and abs(kbps - expect["akbps"]) <= expect["akbps"] * tol
                rows.append(_row("Audio bitrate", f"{expect['akbps']:.0f} kbps (±{tol:.0%})",
                                 f"{kbps:.0f} kbps" if kbps else "unknown", ok))

    return {"ok": all(r["ok"] for r in rows), "rows": rows, "duration": duration,
            "size": int(fmt.get("size") or 0)}
