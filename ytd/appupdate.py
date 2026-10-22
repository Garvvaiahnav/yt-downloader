"""Updating the installed app itself.

Every GitHub release carries manifest.json (version, notes, and for each
platform the installer's URL, size and SHA-256) plus manifest.sig, an Ed25519
signature over the manifest's exact bytes made with the release key in CI.
The app trusts nothing it downloads until:

  1. the signature verifies against PUBLIC_KEY below,
  2. the manifest's version is newer than the running one,
  3. the installer's size and SHA-256 match the signed manifest,
  4. (macOS) the app inside the DMG passes codesign --verify and its bundle
     id and version match what the manifest promised.

Only then is it installed, and the app restarts into the new version."""

import base64
import hashlib
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from Cryptodome.Signature import eddsa

from . import __version__
from .settings import config_dir
from .tools import FROZEN, IS_MAC, IS_WIN, NO_WINDOW

REPO = "Garvvaiahnav/yt-downloader"
FEED = os.environ.get("YTD_UPDATE_FEED") or f"https://github.com/{REPO}/releases/latest/download"
PUBLIC_KEY = "dc555759f20ae1e6869d4ae2d9f8252a0e757930785e0ff4b8ab471c5f5a5dc2"
BUNDLE_ID = "com.masterhooks.ytdownloader"
CHECK_EVERY = 6 * 3600

state = {"status": "idle", "available": None, "checks": [], "progress": 0.0, "error": None, "checked_at": None}
_lock = threading.Lock()


def platform_key():
    if IS_MAC:
        return "darwin-arm64" if platform.machine() == "arm64" else "darwin-x64"
    if IS_WIN:
        return "win32-x64"
    return None


def _vkey(v):
    return tuple(int(x) for x in str(v).split(".") if x.isdigit())


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": f"yt-downloader/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def verify_manifest(raw, sig_b64):
    """Raises ValueError unless raw was signed by the release key."""
    pub = eddsa.import_public_key(bytes.fromhex(PUBLIC_KEY))
    eddsa.new(pub, "rfc8032").verify(raw, base64.b64decode(sig_b64.strip()))


def _set(**kw):
    with _lock:
        state.update(kw)


def check(force=False):
    """Fetch and verify the manifest. Never raises; the outcome is in state."""
    if not FROZEN and not os.environ.get("YTD_UPDATE_FEED"):
        _set(status="dev", error=None)
        return state
    if state["status"] in ("installing", "restarting"):
        return state
    if not force and state["checked_at"] and time.time() - state["checked_at"] < 60:
        return state
    try:
        raw = _get(f"{FEED}/manifest.json")
        sig = _get(f"{FEED}/manifest.sig").decode()
        verify_manifest(raw, sig)
        m = json.loads(raw)
        asset = (m.get("assets") or {}).get(platform_key())
        newer = _vkey(m["version"]) > _vkey(__version__)
        if newer and asset:
            _set(status="available", error=None, available={
                "version": m["version"], "notes": m.get("notes", ""), "published": m.get("published"),
                "size": asset["size"], "asset": asset})
        else:
            _set(status="current", available=None, error=None)
    except ValueError:
        _set(status="error", available=None, checks=[],
             error="Update rejected: the release signature does not match. Nothing was installed.")
    except Exception:
        # Offline, GitHub down, no release yet: stay quiet, try again later.
        _set(status=state["status"] if state["status"] == "available" else "current", error=None)
    _set(checked_at=time.time())
    return state


def start_checks():
    def loop():
        while True:
            check(force=True)
            time.sleep(CHECK_EVERY)
    threading.Thread(target=loop, daemon=True, name="update-check").start()


# ---------- install ----------

def _step(name, ok, detail=""):
    with _lock:
        state["checks"].append({"name": name, "ok": ok, "detail": detail})
    if not ok:
        raise RuntimeError(f"{name}: {detail}")


def _download(asset, dest):
    url = asset["url"]
    if not url.startswith(f"https://github.com/{REPO}/releases/download/") and not os.environ.get("YTD_UPDATE_FEED"):
        _step("Download source", False, "URL is not this app's GitHub releases")
    req = urllib.request.Request(url, headers={"User-Agent": f"yt-downloader/{__version__}"})
    h, done = hashlib.sha256(), 0
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            _set(progress=min(done / asset["size"], 0.999))
    _step("File size", done == asset["size"], f"{done:,} bytes")
    _step("SHA-256 checksum", h.hexdigest() == asset["sha256"].lower(), h.hexdigest()[:16] + "…")


def _app_bundle():
    # .../Video Downloader.app/Contents/MacOS/Video Downloader
    return Path(sys.executable).resolve().parents[2]


def _install_mac(dmg, version, work):
    mnt = work / "mnt"
    mnt.mkdir()
    subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mnt), str(dmg)],
                   check=True, capture_output=True)
    try:
        apps = list(mnt.glob("*.app"))
        _step("Installer contents", len(apps) == 1, apps[0].name if apps else "no app in the DMG")
        new = work / apps[0].name
        subprocess.run(["ditto", str(apps[0]), str(new)], check=True)
    finally:
        subprocess.run(["hdiutil", "detach", str(mnt), "-quiet"], capture_output=True)
    sig = subprocess.run(["codesign", "--verify", "--deep", "--strict", str(new)], capture_output=True, text=True)
    _step("Code signature", sig.returncode == 0, sig.stderr.strip()[-120:] or "valid")
    info = plistlib.loads((new / "Contents" / "Info.plist").read_bytes())
    _step("App identity", info.get("CFBundleIdentifier") == BUNDLE_ID, info.get("CFBundleIdentifier", "?"))
    _step("App version", info.get("CFBundleShortVersionString") == version, info.get("CFBundleShortVersionString", "?"))

    old = _app_bundle()
    # Same folder, the new release's name (handles the YT -> Video Downloader rename).
    target = old.parent / new.name
    script = work / "swap.sh"
    script.write_text(f"""#!/bin/bash
while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.2; done
mv "{old}" "{old}.old" && ditto "{new}" "{target}" && rm -rf "{old}.old" \\
  || {{ rm -rf "{target}"; mv "{old}.old" "{old}"; }}
open "{target}"
rm -rf "{work}"
""")
    script.chmod(0o700)
    subprocess.Popen(["/bin/bash", str(script)], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _install_win(exe, work):
    with open(exe, "rb") as f:
        _step("Installer format", f.read(2) == b"MZ", "Windows executable")
    # The installer closes this app, replaces it, and relaunches it.
    subprocess.Popen([str(exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=NO_WINDOW | subprocess.DETACHED_PROCESS, close_fds=True)


def install():
    """Download, verify and install the available update, then quit so the
    new version can start. Runs in a background thread."""
    with _lock:
        if state["status"] in ("installing", "restarting") or not state["available"]:
            return
        upd = state["available"]
        state.update(status="installing", checks=[], progress=0.0, error=None)

    def run():
        work = None
        try:
            config_dir().mkdir(parents=True, exist_ok=True)
            work = Path(tempfile.mkdtemp(prefix="ytd-update-", dir=config_dir()))
            # Re-fetch and re-verify: never act on a manifest older than this click.
            raw = _get(f"{FEED}/manifest.json")
            verify_manifest(raw, _get(f"{FEED}/manifest.sig").decode())
            m = json.loads(raw)
            _step("Release signature", True, "signed with the release key")
            _step("Newer version", _vkey(m["version"]) > _vkey(__version__), f"{__version__} → {m['version']}")
            asset = m["assets"][platform_key()]
            file = work / Path(asset["url"]).name
            _download(asset, file)
            if not FROZEN:
                # A dev run has no installed app to replace: stop after verifying.
                _step("Install", False, "dev run: verified only, nothing installed")
            if IS_MAC:
                _install_mac(file, m["version"], work)
            else:
                _install_win(file, work)
            _set(status="restarting", progress=1.0)
            time.sleep(1.5)  # let the UI show the result
            os._exit(0)
        except ValueError:
            _set(status="error", error="Update rejected: the release signature does not match. Nothing was installed.")
        except Exception as e:
            _set(status="error", error=f"Update stopped, nothing was installed. {e}")
        finally:
            if work and state["status"] != "restarting":
                shutil.rmtree(work, ignore_errors=True)

    threading.Thread(target=run, daemon=True, name="update-install").start()
