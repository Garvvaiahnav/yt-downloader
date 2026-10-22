"""The download queue: probe, download (stream copy), optional re-encode,
then ffprobe verification. Two jobs run at once; the rest wait."""

import itertools
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadCancelled

from . import settings, verify
from .errors import friendly
from .formats import CODEC_NAMES, InputError, check_url, container_verdict, summarize
from .threads import ThreadsIE
from .tools import NO_WINDOW, encoders, find, forget_encoders


class _QuietLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def ydl_opts(**extra):
    s = settings.load()
    opts = {
        "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
        "logger": _QuietLogger(), "windowsfilenames": True,
    }
    deno, ffmpeg = find("deno"), find("ffmpeg")
    if deno:
        opts["js_runtimes"] = {"deno": {"path": deno}}
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    if s["cookies_browser"]:
        opts["cookiesfrombrowser"] = (s["cookies_browser"],)
    opts.update(extra)
    return opts


def _extract(url, platform, opts, download):
    """extract_info with our Threads extractor available. A post with several
    videos (Instagram/X carousels, Threads) comes back as a playlist."""
    with yt_dlp.YoutubeDL(opts) as ydl:
        if platform == "Threads":
            ydl.add_info_extractor(ThreadsIE())
            return ydl.extract_info(url, download=download, ie_key="Threads")
        return ydl.extract_info(url, download=download)


# ---------- probe ----------

_probe_cache = {}  # url -> (time, info); stream URLs expire, the format list doesn't change in minutes
_PROBE_TTL = 30 * 60


def probe(url, item=None):
    url, platform = check_url(url)
    hit = _probe_cache.get(url)
    if hit and time.time() - hit[0] < _PROBE_TTL:
        info = hit[1]
    else:
        # Social posts can hold several videos; YouTube playlists stay refused.
        opts = ydl_opts(skip_download=True, noplaylist=platform == "YouTube")
        try:
            info = _extract(url, platform, opts, download=False)
        except yt_dlp.utils.DownloadError as e:
            raise InputError(friendly(e)) from None
        _probe_cache[url] = (time.time(), info)

    items = None
    if info.get("_type") == "playlist":
        if platform == "YouTube":
            raise InputError("Playlists are not supported. Use a single video link.")
        entries = [e for e in info.get("entries") or [] if e and e.get("formats")]
        if not entries:
            raise InputError("No video found in this post.")
        item = int(item or 1)
        if not 1 <= item <= len(entries):
            raise InputError("That video is not in this post.")
        items = [{"index": i, "thumbnail": e.get("thumbnail")} for i, e in enumerate(entries, 1)]
        media = {**entries[item - 1], "title": info.get("title") or entries[item - 1].get("title")}
    else:
        item, media = None, info
    if not media.get("formats"):
        raise InputError("No video found at this link.")

    summary = summarize(media, encoders(), platform)
    summary.update(source_url=url, item=item, items=items)
    return summary


# ---------- jobs ----------

_ACTIVE = {"queued", "downloading", "merging", "encoding", "converting", "verifying"}


class Job:
    def __init__(self, req, summary):
        self.id = uuid.uuid4().hex[:10]
        self.req = req
        self.summary = summary
        self.status = "queued"
        self.stage = "Queued"
        self.progress = 0.0
        self.speed = None
        self.eta = None
        self.file = None
        self.error = None
        self.verify = None
        self.cancel = threading.Event()
        self.proc = None
        self.work = None
        self.created = time.time()
        self.finished = None
        self.label, self.expect, self.total_bytes = _describe(req, summary)

    def public(self):
        return {
            "id": self.id, "status": self.status, "stage": self.stage,
            "progress": round(self.progress, 4), "speed": self.speed, "eta": self.eta,
            "title": self.summary["title"], "thumbnail": self.summary["thumbnail"],
            "platform": self.summary["platform"],
            "label": self.label, "url": self.summary["url"],
            "file": self.file, "filename": Path(self.file).name if self.file else None,
            "error": self.error, "verify": self.verify,
            "created": self.created, "finished": self.finished,
        }


def _find(rows, fid, kind):
    row = next((r for r in rows if r["id"] == fid), None)
    if not row:
        raise InputError(f"Selected {kind} stream is no longer listed for this video. Fetch the link again.")
    return row


def _describe(req, s):
    """Validate a request against the probe and work out the label, the
    ffprobe expectations and the expected total bytes."""
    kind = req.get("kind")
    if kind == "audio":
        a = _find(s["audio"], req.get("audio_id"), "audio")
        out = req.get("audio_out")
        if out not in ("m4a", "opus", "mp3", "wav"):
            raise InputError("Audio format is required.")
        if out == "m4a" and a["fam"] != "aac":
            raise InputError("M4A requires an AAC source stream.")
        if out == "opus" and a["fam"] != "opus":
            raise InputError("Opus requires an Opus source stream.")
        expect = {"ext": out, "audio_only": True, "afam": {"m4a": "aac", "opus": "opus", "mp3": "mp3", "wav": "pcm"}[out]}
        label = f"Audio · {out.upper()}"
        if out in ("m4a", "opus"):
            expect.update(akbps=a["kbps"], atol=0.12)
            label += f" {a['kbps']}k"
        elif out == "mp3":
            kbps = int(req.get("mp3_kbps") or 320)
            if kbps not in (128, 192, 256, 320):
                raise InputError("MP3 bitrate must be 128, 192, 256 or 320 kbps.")
            req["mp3_kbps"] = kbps
            expect.update(akbps=kbps, atol=0.1)
            label += f" {kbps}k"
        return label, expect, a["size"] or 0

    if kind != "video":
        raise InputError("Download type must be video or audio.")
    v = _find(s["video"], req.get("video_id"), "video")
    if v["muxed"]:
        a = None  # audio is inside the video file
        req.pop("audio_id", None)
        afam = v["afam"]
    else:
        a = _find(s["audio"], req.get("audio_id"), "audio") if s["audio"] else None
        if not a and req.get("audio_id"):
            raise InputError("Selected audio stream is no longer listed. Fetch the link again.")
        afam = a["fam"] if a else None
    hdr = " HDR" if v["hdr"] else ""

    editor = req.get("editor")
    if editor:
        codec = editor.get("codec")
        if codec not in ("h264", "hevc", "prores"):
            raise InputError("Editor output must be H.264, HEVC or ProRes.")
        if not s["encoders"].get(codec):
            raise InputError(f"No working {CODEC_NAMES[codec]} encoder on this machine.")
        if v["hdr"] and codec == "h264":
            raise InputError("HDR sources require HEVC or ProRes. Select an SDR stream for H.264.")
        ext = "mov" if codec == "prores" else "mp4"
        req["container"] = ext
        expect = {"ext": ext, "vfam": codec, **_dims(v, even=True)}
        if codec == "prores":
            label = f"{v['label']}{hdr} · ProRes 422 · MOV"
        else:
            mbps = float(editor.get("mbps") or 0)
            if not 0.2 <= mbps <= 400:
                raise InputError("Bitrate must be between 0.2 and 400 Mbps.")
            editor["mbps"] = mbps
            expect.update(vkbps=mbps * 1000, vtol=0.35, vceiling=True)
            label = f"{v['label']}{hdr} · {CODEC_NAMES[codec]} {mbps:g} Mbps · MP4"
        if afam:
            expect["afam"] = "pcm" if codec == "prores" else "aac"
    else:
        container = req.get("container")
        if container not in ("mp4", "webm", "mkv"):
            raise InputError("Container is required.")
        verdict, reason = container_verdict(container, v["fam"], afam)
        if verdict == "no":
            raise InputError(reason)
        expect = {"ext": container, **_dims(v)}
        if v["fam"] != "unknown":
            expect["vfam"] = v["fam"]
        if v["kbps"] and not v["muxed"]:
            expect.update(vkbps=v["kbps"], vtol=0.1)
        if afam and afam != "unknown":
            expect["afam"] = afam
            if a and a["kbps"]:
                expect.update(akbps=a["kbps"], atol=0.12)
        known = [CODEC_NAMES.get(f, f) for f in (v["fam"], afam) if f and f != "unknown"]
        label = " · ".join([f"{v['label']}{hdr}", *([" + ".join(known)] if known else []), container.upper()])
    return label, expect, (v["size"] or 0) + ((a or {}).get("size") or 0)


def _dims(v, even=False):
    """Expected frame size and rate for ffprobe, when the site reported them.
    Encodes round odd sizes down to even (H.264/HEVC 4:2:0 needs it)."""
    out = {}
    if v["width"] and v["height"]:
        w, h = v["width"], v["height"]
        out.update(width=w - w % 2 if even else w, height=h - h % 2 if even else h)
    if v["fps"]:
        out["fps"] = v["fps"]
    return out


_jobs = {}
_lock = threading.Lock()
_version = itertools.count(1)
state_version = 0
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dl")


def _touch():
    global state_version
    state_version = next(_version)


def submit(req):
    summary = probe(req.get("url"), req.get("item"))
    if summary["live_status"] in ("is_live", "is_upcoming", "post_live"):
        raise InputError({
            "is_live": "Live streams can be downloaded after they end.",
            "is_upcoming": "This premiere or stream has not started.",
            "post_live": "This stream just ended and is still processing on YouTube.",
        }[summary["live_status"]])
    job = Job(dict(req), summary)
    with _lock:
        _jobs[job.id] = job
    _touch()
    _pool.submit(_run, job)
    return job


def snapshot():
    with _lock:
        return [j.public() for j in sorted(_jobs.values(), key=lambda j: -j.created)]


def get(job_id):
    return _jobs.get(job_id)


def cancel(job_id):
    job = _jobs.get(job_id)
    if not job:
        return False
    job.cancel.set()
    if job.status == "queued":
        _set(job, status="cancelled", stage="Cancelled")
    if job.proc and job.proc.poll() is None:
        job.proc.kill()
    return True


def remove(job_id):
    with _lock:
        job = _jobs.get(job_id)
        if job and job.status not in _ACTIVE:
            del _jobs[job_id]
            _touch()
            return True
    return False


def _set(job, **kw):
    for k, v in kw.items():
        setattr(job, k, v)
    _touch()


def _work_dir(job):
    # Each job downloads into its own folder and only the finished file is
    # moved out. Two jobs on the same video (say M4A and WAV of one stream)
    # would otherwise share an intermediate file and delete each other's.
    d = Path(settings.load()["download_dir"]) / ".ytd-tmp" / job.id
    d.mkdir(parents=True, exist_ok=True)
    job.work = d
    return d


def _deliver(src, name):
    """Move a finished file into the download folder without overwriting:
    'x.mp4' becomes 'x (2).mp4' if needed."""
    out = Path(settings.load()["download_dir"])
    stem, ext = os.path.splitext(name)
    dest, n = out / name, 2
    while dest.exists():
        dest, n = out / f"{stem} ({n}){ext}", n + 1
    shutil.move(str(src), dest)
    return str(dest)


def _run(job):
    if job.cancel.is_set():
        return
    try:
        try:
            _download(job)
        except yt_dlp.utils.DownloadError as e:
            # YouTube hands out the odd stream URL that 403s; a fresh extract
            # gets new URLs and almost always works. Once, not in a loop.
            if "HTTP Error 403" not in str(e) or job.cancel.is_set():
                raise
            _set(job, stage="Retrying with fresh links", progress=0.0)
            _download(job)
        if job.req.get("editor"):
            _encode(job)
        _set(job, status="verifying", stage="Verifying", progress=1.0, speed=None, eta=None)
        job.verify = verify.check(job.file, job.expect)
        _set(job, status="done", stage="Done", finished=time.time())
    except DownloadCancelled:
        _set(job, status="cancelled", stage="Cancelled", speed=None, eta=None)
    except Exception as e:  # anything else is shown to the user, in words
        if job.cancel.is_set():
            _set(job, status="cancelled", stage="Cancelled", speed=None, eta=None)
        else:
            _set(job, status="error", stage="Failed", error=friendly(e), speed=None, eta=None)
    finally:
        if job.work:
            shutil.rmtree(job.work, ignore_errors=True)


def _download(job):
    req = job.req
    work = _work_dir(job)
    tag = job.label.split(" · ")[0].replace(" ", "")
    pps = []
    if req["kind"] == "audio":
        fmt = req["audio_id"]
        q = str(req.get("mp3_kbps") or 0)
        pps.append({"key": "FFmpegExtractAudio", "preferredcodec": req["audio_out"], "preferredquality": q})
        name = f"%(title).120B [%(id)s] audio.%(ext)s"
        extra = {}
    else:
        v = next(r for r in job.summary["video"] if r["id"] == req["video_id"])
        fmt = f"{req['video_id']}+{req['audio_id']}" if req.get("audio_id") else req["video_id"]
        target = "mkv" if req.get("editor") else req["container"]
        if req.get("editor"):
            name = f"{job.id}.%(ext)s"
        else:
            codec = "" if v["fam"] == "unknown" else " " + CODEC_NAMES.get(v["fam"], v["fam"])
            name = f"%(title).120B [%(id)s] {tag}{codec}.%(ext)s"
        if req.get("audio_id"):
            extra = {"merge_output_format": target}
        else:
            # One file already holds video and audio; only change its container.
            extra = {}
            if v["ext"] != target:
                pps.append({"key": "FFmpegVideoRemuxer", "preferedformat": target})

    done_bytes = {}  # filename -> bytes, so video + audio add up to one bar

    def on_progress(d):
        if job.cancel.is_set():
            raise DownloadCancelled()
        if d["status"] == "downloading":
            done_bytes[d.get("filename")] = d.get("downloaded_bytes") or 0
            total = max(job.total_bytes, sum(done_bytes.values())) or (d.get("total_bytes") or d.get("total_bytes_estimate") or 1)
            _set(job, status="downloading", stage="Downloading",
                 progress=min(sum(done_bytes.values()) / total, 0.999),
                 speed=d.get("speed"), eta=d.get("eta"))
        elif d["status"] == "finished":
            done_bytes[d.get("filename")] = d.get("total_bytes") or d.get("downloaded_bytes") or 0

    def on_pp(d):
        if d["status"] == "started":
            pp = d.get("postprocessor", "")
            if pp == "Merger":
                _set(job, status="merging", stage="Merging", speed=None, eta=None)
            elif pp == "VideoRemuxer":
                _set(job, status="merging", stage=f"Remuxing to {req['container'].upper()}", speed=None, eta=None)
            elif pp == "ExtractAudio":
                _set(job, status="converting", stage=f"Converting to {req['audio_out'].upper()}", speed=None, eta=None)

    opts = ydl_opts(format=fmt, outtmpl=name, paths={"home": str(work), "temp": str(work)},
                    postprocessors=pps, progress_hooks=[on_progress], postprocessor_hooks=[on_pp],
                    overwrites=True, **extra)
    item = job.summary.get("item")
    if item:
        opts.update(noplaylist=False, playlist_items=str(item))
    _set(job, status="downloading", stage="Starting")
    info = _extract(job.summary["source_url"], job.summary["platform"], opts, download=True)
    if info.get("_type") == "playlist":
        info = next((e for e in info.get("entries") or [] if e), {})
    path = (info.get("requested_downloads") or [{}])[0].get("filepath")
    if not path or not os.path.exists(path):
        raise RuntimeError("Download finished but the output file is missing.")
    job.file = path if req.get("editor") else _deliver(path, os.path.basename(path))


_STD_RATES = (23.976, 24, 25, 29.97, 30, 48, 50, 59.94, 60)


def _source_rate(path):
    """Average frame rate of the downloaded file, snapped to a standard rate
    when it is within 0.5% of one. Phone and social videos are often variable
    frame rate, which Premiere and After Effects drift on; editor output is
    always written at this constant rate."""
    out = subprocess.run([find("ffprobe"), "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=avg_frame_rate:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, creationflags=NO_WINDOW)
    try:
        data = json.loads(out.stdout)
        num, _, den = data["streams"][0]["avg_frame_rate"].partition("/")
        fps = float(num) / float(den or 1)
        duration = float(data["format"].get("duration") or 0)
    except (ValueError, KeyError, IndexError, ZeroDivisionError):
        return None, 0
    for std in _STD_RATES:
        if abs(fps - std) / std < 0.005:
            return {23.976: "24000/1001", 29.97: "30000/1001", 59.94: "60000/1001"}.get(std, str(std)), duration
    return (f"{fps:.3f}" if fps else None), duration


def _video_args(enc, codec, mbps, fps, hdr):
    hdr_tags = ["-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc"]
    if codec == "prores":
        # Profile 2 = ProRes 422 (standard): the usual After Effects working format.
        args = ["-c:v", enc, "-profile:v", "2"]
        if enc == "prores_ks":
            args += ["-pix_fmt", "yuv422p10le", "-vendor", "apl0"]
        return args + (hdr_tags if hdr else [])
    b, mx, buf = f"{mbps:g}M", f"{mbps * 1.5:g}M", f"{mbps * 2:g}M"
    args = ["-c:v", enc, "-b:v", b, "-g", str(max(1, round(fps or 30)))]
    if "nvenc" in enc:
        args += ["-rc", "vbr", "-maxrate", mx, "-bufsize", buf, "-preset", "p5"]
    elif "qsv" in enc:
        args += ["-maxrate", mx, "-preset", "medium"]
    elif enc in ("libx264", "libx265"):
        args += ["-maxrate", mx, "-bufsize", buf, "-preset", "medium"]
        if enc == "libx265":
            args += ["-x265-params", "log-level=error"]
    if hdr:  # only HEVC gets here
        args += ["-profile:v", "main10", "-pix_fmt", "yuv420p10le" if enc == "libx265" else "p010le", *hdr_tags]
    else:
        args += ["-profile:v", "high" if codec == "h264" else "main", "-pix_fmt", "yuv420p"]
    if codec == "hevc":
        args += ["-tag:v", "hvc1"]  # QuickTime/Premiere want hvc1, not hev1
    return args


def _encode(job):
    req = job.req
    src = Path(job.file)
    v = next(r for r in job.summary["video"] if r["id"] == req["video_id"])
    afam = v["afam"] if v["muxed"] else next((r["fam"] for r in job.summary["audio"] if r["id"] == req.get("audio_id")), None)
    codec, mbps = req["editor"]["codec"], req["editor"].get("mbps")
    enc = job.summary["encoders"][codec]
    title = job.summary["title"] or job.summary["id"]
    safe = "".join(c for c in title if c not in '<>:"/\\|?*').strip()[:120] or job.summary["id"]
    if codec == "prores":
        ext, tail = "mov", "ProRes 422"
        audio = ["-c:a", "pcm_s16le", "-ar", "48000"]
    else:
        ext, tail = "mp4", f"{CODEC_NAMES[codec]} {mbps:g}M"
        audio = ["-c:a", "copy"] if afam == "aac" else ["-c:a", "aac", "-b:a", "320k", "-ar", "48000"]
    dest_name = f"{safe} [{job.summary['id']}] {v['label']} {tail} editor.{ext}"
    tmp_out = src.with_name(f"{job.id}.encode.{ext}")
    rate, duration = _source_rate(src)
    cfr = ["-fps_mode", "cfr", "-r", rate] if rate else []
    cmd = [find("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
           "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0",
           "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", *cfr,
           *_video_args(enc, codec, mbps, v["fps"], v["hdr"]), *audio,
           *(["-movflags", "+faststart"] if ext == "mp4" else []),
           "-progress", "pipe:1", "-nostats", str(tmp_out)]
    duration = duration or job.summary["duration"] or 0
    _set(job, status="encoding", stage=f"Encoding {CODEC_NAMES[codec]}", progress=0.0, speed=None, eta=None)
    started = time.time()
    job.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
    for line in job.proc.stdout:
        key, _, val = line.strip().partition("=")
        if key == "out_time_us" and val.isdigit() and duration:
            p = min(int(val) / 1e6 / duration, 0.999)
            spent = time.time() - started
            _set(job, progress=p, eta=round(spent / p - spent) if p > 0.01 else None)
    err = job.proc.stderr.read()
    rc = job.proc.wait()
    job.proc = None
    if job.cancel.is_set():
        tmp_out.unlink(missing_ok=True)
        raise DownloadCancelled()
    if rc != 0:
        tmp_out.unlink(missing_ok=True)
        forget_encoders()
        raise RuntimeError(f"Encode failed: {err.strip().splitlines()[-1] if err.strip() else rc}")
    job.file = _deliver(tmp_out, dest_name)
