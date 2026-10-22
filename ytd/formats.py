"""Turning yt-dlp's format list into what the UI may offer.

Nothing here invents an option: every video and audio row is a stream the site
actually serves for this video, so a 1080p-only upload never shows 4K."""

import re
from urllib.parse import parse_qs, urlparse

# host suffix -> platform. Anything else is refused: arbitrary sites are a
# separate feature.
PLATFORMS = {
    "youtube.com": "YouTube", "youtu.be": "YouTube", "youtube-nocookie.com": "YouTube",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook", "fb.watch": "Facebook", "fb.com": "Facebook",
    "x.com": "X", "twitter.com": "X",
    "threads.net": "Threads", "threads.com": "Threads",
    "tiktok.com": "TikTok",
}


def platform_of(host):
    host = (host or "").lower()
    for suffix, name in PLATFORMS.items():
        if host == suffix or host.endswith("." + suffix):
            return name
    return None


class InputError(Exception):
    """A problem with what the user typed; the message is shown as is."""


def check_url(url):
    """(normalized url, platform name)"""
    url = (url or "").strip()
    if not url:
        raise InputError("Paste a link.")
    if "://" not in url:
        url = "https://" + url
    p = urlparse(url)
    platform = platform_of(p.hostname)
    if not platform:
        raise InputError("Supported: YouTube, Instagram, Facebook, X, Threads and TikTok links.")
    if platform == "YouTube" and (p.path.rstrip("/") == "/playlist" or (p.path == "/watch" and "v" not in parse_qs(p.query))):
        raise InputError("Playlists are not supported. Use a single video link.")
    return url, platform


def vfamily(vcodec):
    v = (vcodec or "").lower()
    if v.startswith("avc1") or v == "h264":
        return "h264"
    if v.startswith(("vp09", "vp9")):
        return "vp9"
    if v.startswith("av01"):
        return "av1"
    if v.startswith(("hev1", "hvc1", "hevc", "h265")):
        return "hevc"
    if v.startswith(("prores", "apch", "apcn", "apcs", "apco", "ap4h")):
        return "prores"
    return v.split(".")[0] or "unknown"


def afamily(acodec):
    a = (acodec or "").lower()
    if a.startswith("mp4a") or a == "aac":
        return "aac"
    if a == "opus":
        return "opus"
    if a == "vorbis":
        return "vorbis"
    if a in ("mp3", "mp4a.40.34"):
        return "mp3"
    if a.startswith("pcm"):
        return "pcm"
    return a.split(".")[0] or "unknown"


CODEC_NAMES = {"h264": "H.264", "vp9": "VP9", "av1": "AV1", "hevc": "HEVC", "prores": "ProRes 422",
               "aac": "AAC", "opus": "Opus", "vorbis": "Vorbis", "mp3": "MP3", "pcm": "PCM",
               "unknown": "Unknown"}

# Stream copy rules, per container. "warn" plays in VLC and browsers but not
# in QuickTime or Premiere; "no" cannot be muxed at all.
CONTAINER_RULES = {
    "mp4": {
        "video": {"h264": "ok", "av1": "ok", "hevc": "ok",
                  "vp9": ["warn", "VP9 in MP4 does not open in QuickTime or Premiere."]},
        "audio": {"aac": "ok",
                  "opus": ["warn", "Opus in MP4 does not open in QuickTime or Premiere."]},
    },
    "webm": {
        "video": {"vp9": "ok", "av1": "ok",
                  "h264": ["no", "WebM supports VP9 and AV1 video only."],
                  "hevc": ["no", "WebM supports VP9 and AV1 video only."],
                  "unknown": ["no", "WebM supports VP9 and AV1 video only."]},
        "audio": {"opus": "ok", "vorbis": "ok",
                  "aac": ["no", "WebM supports Opus and Vorbis audio only."]},
    },
    "mkv": {"video": {}, "audio": {}},  # anything goes
}

# What Premiere Pro and After Effects import. Anything "no" gets the
# "convert for editing" options in the UI. VP9, AV1, Opus, WebM and MKV are
# the usual offenders from YouTube; most Instagram/X/TikTok files are H.264 +
# AAC in MP4 and pass.
EDIT_COMPAT = {
    "container": {"mp4": "ok", "mov": "ok", "m4a": "ok", "mp3": "ok", "wav": "ok",
                  "webm": "no", "mkv": "no", "opus": "no"},
    "video": {"h264": "ok", "hevc": "ok", "prores": "ok", "vp9": "no", "av1": "no", "unknown": "check"},
    "audio": {"aac": "ok", "mp3": "ok", "pcm": "ok", "opus": "no", "vorbis": "no", "unknown": "check"},
}


def container_verdict(container, vfam, afam):
    """('ok'|'warn'|'no', reason). The worst of the video and audio verdicts."""
    rules = CONTAINER_RULES[container]
    rank = {"ok": 0, "warn": 1, "no": 2}
    worst = ("ok", "")
    for kind, fam in (("video", vfam), ("audio", afam)):
        if fam is None:
            continue
        r = rules[kind].get(fam, "ok")
        r = (r, "") if isinstance(r, str) else tuple(r)
        if rank[r[0]] > rank[worst[0]]:
            worst = r
    return worst


# Bits each codec needs for the same picture, relative to H.264. Re-encoding
# can't add quality, so the most an encode is ever offered is the bitrate
# that *matches* the source in the target codec: a 12 Mbps VP9 stream is
# worth ~20 Mbps of H.264, and anything above that only makes the file bigger.
_EFFICIENCY = {"h264": 1.0, "hevc": 0.6, "vp9": 0.6, "av1": 0.45}

# Fallback when a site doesn't report the stream's bitrate: YouTube's upload
# recommendations for SDR H.264 (Mbps), (<=30 fps, >30 fps).
_YT_REC = {2160: (45, 68), 1440: (16, 24), 1080: (8, 12), 720: (5, 7.5),
           480: (2.5, 4), 360: (1, 1.5), 240: (0.5, 0.75), 144: (0.3, 0.4)}


def _nice(mbps):
    return round(mbps, 1) if mbps < 10 else round(mbps)


def source_match_mbps(src_kbps, src_fam, target, label_h, fps):
    """Bitrate in the target codec that keeps the source's quality."""
    if src_kbps:
        ratio = _EFFICIENCY.get(target, 1.0) / _EFFICIENCY.get(src_fam, 1.0)
        return max(0.3, src_kbps / 1000 * ratio)
    key = min(_YT_REC, key=lambda k: abs(k - (label_h or 720)))
    lo, hi = _YT_REC[key]
    return (hi if (fps or 30) > 30 else lo) * _EFFICIENCY.get(target, 1.0)


def bitrate_choices(src_kbps, src_fam, target, label_h, fps):
    """(top, choices): top keeps source quality; the others trade size for
    quality. Never more than the source is worth."""
    top = _nice(source_match_mbps(src_kbps, src_fam, target, label_h, fps))
    choices = sorted({_nice(top * f) for f in (0.5, 0.75)} | {top})
    return top, choices


def _label_height(f):
    m = re.match(r"(\d+)p", f.get("format_note") or "")
    if m:
        return int(m.group(1))
    w, h = f.get("width") or 0, f.get("height") or 0
    return min(w, h) if w and h else h


def _size(f):
    return f.get("filesize") or f.get("filesize_approx")


def _has_video(f):
    # yt-dlp: "none" = absent, None = not reported. Social sites often leave
    # codecs unreported on progressive MP4s that do carry video.
    v = f.get("vcodec")
    if v == "none":
        return False
    return v is not None or bool(f.get("height") or f.get("width")) or (
        f.get("acodec") is None and f.get("ext") in ("mp4", "mov", "webm"))


def _has_audio(f):
    a = f.get("acodec")
    if a == "none":
        return False
    # Unreported on a progressive file whose video codec is unreported too:
    # assume it carries audio (the ffprobe check after download is the judge).
    return a is not None or f.get("vcodec") is None


def summarize(info, encoders, platform="YouTube"):
    formats = info.get("formats") or []
    video, audio = [], []
    for f in formats:
        if f.get("format_id", "").startswith("sb") or f.get("ext") in ("mhtml", "jpg", "png", "webp"):
            continue
        has_v = _has_video(f)
        has_a = _has_audio(f)
        if has_v:
            lh = _label_height(f)
            fps = round(f.get("fps") or 0)
            hdr = (f.get("dynamic_range") or "SDR") != "SDR"
            note = (f.get("format_note") or "").strip()
            label = f"{lh}p{fps if fps > 30 else ''}" if lh else (note.upper()[:12] or "Source")
            video.append({
                "id": f["format_id"],
                "muxed": has_a,
                "afam": afamily(f.get("acodec")) if has_a else None,
                "fam": vfamily(f.get("vcodec")),
                "vcodec": f.get("vcodec"),
                "width": f.get("width"), "height": f.get("height"),
                "label_h": lh, "fps": fps, "hdr": hdr,
                "dynamic_range": f.get("dynamic_range") or "SDR",
                "label": label,
                "kbps": round(f.get("vbr") or f.get("tbr") or 0),
                "size": _size(f), "ext": f.get("ext"),
                "protocol": f.get("protocol"),
                "editor": {c: dict(zip(("rec", "choices"), bitrate_choices(
                    round(f.get("vbr") or f.get("tbr") or 0), vfamily(f.get("vcodec")), c, lh, fps)))
                           for c in ("h264", "hevc")},
            })
        elif has_a:
            fid = f["format_id"]
            audio.append({
                "id": fid,
                "fam": afamily(f.get("acodec")),
                "acodec": f.get("acodec"),
                "kbps": round(f.get("abr") or f.get("tbr") or 0),
                "size": _size(f), "ext": f.get("ext"),
                "language": f.get("language"),
                "note": f.get("format_note") or "",
                "drc": "drc" in fid,
                "channels": f.get("audio_channels"),
                "asr": f.get("asr"),
                "protocol": f.get("protocol"),
            })

    # Drop HLS copies when the same height/codec exists over plain https.
    def dedupe(rows, key):
        https_keys = {key(r) for r in rows if r["protocol"] == "https"}
        return [r for r in rows if r["protocol"] == "https" or key(r) not in https_keys]

    video = dedupe(video, lambda r: (r["label_h"], r["fps"], r["fam"], r["hdr"], r["muxed"]))
    audio = dedupe(audio, lambda r: (r["fam"], r["language"], r["drc"]))
    order = ["h264", "av1", "vp9", "hevc"]
    video.sort(key=lambda r: (-r["label_h"], -r["fps"], r["hdr"], r["muxed"],
                              order.index(r["fam"]) if r["fam"] in order else 9, -r["kbps"]))
    audio.sort(key=lambda r: (r["drc"], "original" not in r["note"].lower(), -r["kbps"]))

    w, h = info.get("width") or 0, info.get("height") or 0
    top = video[0] if video else None
    return {
        "id": info.get("id"),
        "platform": platform,
        "url": info.get("webpage_url") or info.get("original_url"),
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "live_status": info.get("live_status"),
        "vertical": bool(w and h and h > w) or "/shorts/" in (info.get("original_url") or ""),
        "max": (top["label"] + (" HDR" if any(v["hdr"] and v["label_h"] == top["label_h"] for v in video) else "")) if top else None,
        "video": video,
        "audio": audio,
        "rules": CONTAINER_RULES,
        "compat": EDIT_COMPAT,
        "encoders": encoders,
    }
