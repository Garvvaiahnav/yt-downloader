import asyncio
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, account, appupdate, bulk, jobs, native, settings, updater
from .formats import InputError
from .tools import IS_MAC, IS_WIN, NO_WINDOW, encoder_label, encoders, version

# Installed app: files unpacked under sys._MEIPASS. Dev: the repo root.
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(InputError)
async def input_error(_, exc):
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/api/probe")
async def probe(body: dict):
    return await asyncio.to_thread(jobs.probe, body.get("url"))


@app.post("/api/jobs")
async def create_job(body: dict):
    job = await asyncio.to_thread(jobs.submit, body)
    return job.public()


@app.get("/api/jobs")
def list_jobs():
    return jobs.snapshot()


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if not jobs.cancel(job_id):
        raise HTTPException(404)
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def remove_job(job_id: str):
    return {"ok": jobs.remove(job_id)}


@app.get("/api/events")
async def events(request: Request):
    async def stream():
        seen = -1
        while not await request.is_disconnected():
            if jobs.state_version != seen:
                seen = jobs.state_version
                yield f"data: {json.dumps(jobs.snapshot())}\n\n"
            await asyncio.sleep(0.3)
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/jobs/{job_id}/file")
def job_file(job_id: str):
    job = jobs.get(job_id)
    if not job or not job.file or not os.path.exists(job.file):
        raise HTTPException(404)
    return FileResponse(job.file, filename=Path(job.file).name)


@app.post("/api/jobs/{job_id}/reveal")
def reveal(job_id: str):
    job = jobs.get(job_id)
    if not job or not job.file or not os.path.exists(job.file):
        raise HTTPException(404)
    if IS_MAC:
        subprocess.Popen(["open", "-R", job.file])
    elif IS_WIN:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(job.file)], creationflags=NO_WINDOW)
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(job.file)])
    return {"ok": True}


_latest = {"version": None}


def _fetch_latest():
    try:
        _latest["version"] = updater.latest_version()
    except Exception:
        pass


threading.Thread(target=_fetch_latest, daemon=True).start()


def _norm(v):
    # PyPI says 2026.8.19, yt-dlp says 2026.08.19
    return tuple(int(x) for x in (v or "0").split(".") if x.isdigit())


@app.get("/api/system")
def system():
    enc = encoders()
    current = yt_dlp.version.__version__
    return {
        "version": __version__,
        "settings": settings.load(),
        "native_picker": native.pick_folder is not None,
        "browsers": settings.BROWSERS,
        "ytdlp": current,
        "ytdlp_latest": _latest["version"],
        "update_available": bool(_latest["version"]) and _norm(_latest["version"]) > _norm(current),
        "ffmpeg": version("ffmpeg"), "ffprobe": version("ffprobe"), "deno": version("deno"),
        "encoders": {k: ({"name": v, "label": encoder_label(v)} if v else None) for k, v in enc.items()},
    }


@app.post("/api/bulk")
async def bulk_start(body: dict):
    preset = {"mode": body.get("mode"), "max_h": body.get("max_h"), "folder": body.get("folder")}
    return await asyncio.to_thread(bulk.start, body.get("urls") or [], preset)


@app.get("/api/bulk")
def bulk_state():
    return bulk.state


@app.post("/api/pick-folder")
def pick_folder(body: dict):
    """Native folder chooser. Blocks until the user picks or cancels."""
    if not native.pick_folder:
        raise HTTPException(400, "The folder picker works in the installed app; type the path instead.")
    path = native.pick_folder(body.get("start") or settings.load()["download_dir"])
    return {"path": path}


@app.get("/api/account")
def account_status():
    return account.status()


@app.post("/api/account/signin")
def account_signin():
    if not account.open_window:
        raise HTTPException(400, "Sign-in works in the installed app.")
    account.open_window()
    return account.status()


@app.post("/api/account/signout")
def account_signout():
    account.sign_out()
    return account.status()


@app.get("/api/app-update")
def app_update_state():
    return appupdate.state


@app.post("/api/app-update/check")
async def app_update_check():
    return await asyncio.to_thread(appupdate.check, True)


@app.post("/api/app-update/install")
def app_update_install():
    appupdate.install()
    return appupdate.state


@app.post("/api/settings")
def save_settings(body: dict):
    try:
        return settings.save(body)
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/update")
async def update():
    """Fetch newer yt-dlp wheels; they load on the next launch."""
    try:
        new, changed = await asyncio.to_thread(updater.update)
    except Exception as e:
        raise HTTPException(500, f"Update failed: {e}")
    return {"version": new, "changed": changed}


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
