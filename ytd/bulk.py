"""Bulk downloads: many links, or a YouTube playlist, with one preset.

Each link is fetched like a single download and the streams are picked the
way the UI would by default: the highest resolution up to the preset's cap,
SDR and an editor-friendly codec first, then the highest bitrate. Links that
fail land in the queue as failed rows, so nothing disappears silently."""

import threading
import time
import uuid
from urllib.parse import parse_qs, urlparse

import yt_dlp

from . import jobs
from .errors import friendly
from .formats import InputError, container_verdict

MODES = ("original", "h264", "prores", "m4a", "mp3")
MAX_LINKS = 500

state = {"running": False, "total": 0, "done": 0, "failed": 0}
_lock = threading.Lock()


def _is_playlist(url):
    p = urlparse(url if "://" in url else "https://" + url)
    host = (p.hostname or "").lower()
    return ("youtube.com" in host and p.path.rstrip("/") == "/playlist") or \
           ("youtube.com" in host and "list" in parse_qs(p.query) and "v" not in parse_qs(p.query))


def _playlist_videos(url):
    opts = jobs.ydl_opts(extract_flat="in_playlist", skip_download=True, noplaylist=False)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return [e.get("url") or f"https://www.youtube.com/watch?v={e['id']}"
            for e in info.get("entries") or [] if e and (e.get("url") or e.get("id"))]


def _best_video(rows, max_h):
    fits = [r for r in rows if not max_h or r["label_h"] <= max_h] or sorted(rows, key=lambda r: r["label_h"])[:1]
    top = max(r["label_h"] for r in fits)
    at = sorted((r for r in fits if r["label_h"] == top), key=lambda r: -r["kbps"])
    editable = lambda r: r["fam"] in ("h264", "hevc", "unknown")
    return next((r for r in at if not r["hdr"] and editable(r)), None) or \
        next((r for r in at if not r["hdr"]), None) or at[0]


def _best_audio(rows):
    return next((a for a in rows if a["fam"] == "aac" and not a["drc"]), None) or \
        next((a for a in rows if not a["drc"]), None) or (rows[0] if rows else None)


def pick(summary, preset):
    """The job request the preset implies for one probed video."""
    mode, max_h = preset["mode"], preset.get("max_h")
    req = {"url": summary["source_url"], "item": summary.get("item"), "folder": preset.get("folder")}
    a = _best_audio(summary["audio"])
    if mode in ("m4a", "mp3"):
        if not a:
            raise InputError("No audio track in this video.")
        out = "m4a" if mode == "m4a" and a["fam"] == "aac" else "mp3"
        return {**req, "kind": "audio", "audio_id": a["id"], "audio_out": out, "mp3_kbps": 320}

    if not summary["video"]:
        raise InputError("No video stream at this link.")
    v = _best_video(summary["video"], max_h)
    req.update(kind="video", video_id=v["id"])
    if a and not v["muxed"]:
        req["audio_id"] = a["id"]
    afam = v["afam"] if v["muxed"] else (a["fam"] if a else None)
    if mode == "original":
        req["container"] = next((c for c in ("mp4", "mkv") if container_verdict(c, v["fam"], afam)[0] == "ok"), "mkv")
    elif mode == "prores":
        req["editor"] = {"codec": "prores"}
    else:  # h264, or HEVC when the source is HDR (H.264 can't carry it)
        codec = "hevc" if v["hdr"] else "h264"
        req["editor"] = {"codec": codec, "mbps": v["editor"][codec]["rec"]}
    return req


class _Failed:
    """A link that couldn't be queued, shown in the queue as a failed row."""
    def __init__(self, url, error):
        self.id, self.url, self.error, self.created = uuid.uuid4().hex[:10], url, error, time.time()
        self.status, self.cancel, self.proc = "error", threading.Event(), None

    def public(self):
        return {"id": self.id, "status": "error", "stage": "Failed", "progress": 0, "speed": None, "eta": None,
                "title": self.url, "thumbnail": None, "platform": None, "label": "Bulk", "url": self.url,
                "file": None, "filename": None, "error": self.error, "verify": None,
                "created": self.created, "finished": self.created}


def _fail(url, err):
    f = _Failed(url, err)
    with jobs._lock:
        jobs._jobs[f.id] = f
    jobs._touch()
    with _lock:
        state["failed"] += 1


def start(urls, preset):
    if preset.get("mode") not in MODES:
        raise InputError("Pick what to download.")
    if preset.get("max_h") not in (None, 2160, 1440, 1080, 720, 480):
        raise InputError("Pick a resolution limit.")
    if preset.get("folder"):
        jobs._dest_folder(preset["folder"])  # validate before anything is queued
    links = list(dict.fromkeys(u.strip() for u in urls if u and u.strip()))
    if not links:
        raise InputError("Paste at least one link.")
    with _lock:
        if state["running"]:
            raise InputError("A bulk download is still being added. Wait for it to finish.")
        state.update(running=True, total=len(links), done=0, failed=0)

    def run():
        try:
            pending = list(links)
            while pending:
                url = pending.pop(0)
                try:
                    if _is_playlist(url):
                        videos = _playlist_videos(url)[:MAX_LINKS]
                        with _lock:
                            state["total"] += len(videos) - 1
                        pending[:0] = videos
                        continue
                    summary = jobs.probe(url)
                    items = [i["index"] for i in summary["items"]] if summary.get("items") else [None]
                    for n in items:
                        s = summary if n in (None, summary.get("item")) else jobs.probe(url, n)
                        jobs.submit(pick(s, preset))
                except InputError as e:
                    _fail(url, str(e))
                except Exception as e:
                    _fail(url, friendly(e))
                finally:
                    with _lock:
                        state["done"] += 1
                    jobs._touch()
        finally:
            with _lock:
                state["running"] = False
            jobs._touch()

    threading.Thread(target=run, daemon=True, name="bulk").start()
    return state
