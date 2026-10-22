"""Updating yt-dlp inside an installed app.

YouTube changes every few weeks and yt-dlp follows; the app can't wait for a
new installer each time. yt-dlp and yt-dlp-ejs are pure-Python wheels, so the
update downloads them from PyPI, unpacks them into the user's data folder, and
the next launch puts that folder ahead of the bundled copy on sys.path.

activate() must run before anything imports yt_dlp."""

import io
import json
import shutil
import sys
import urllib.request
import zipfile
from importlib import metadata

from .settings import config_dir

LIB = config_dir() / "lib"
PACKAGES = ("yt-dlp", "yt-dlp-ejs")


def _vkey(v):
    return tuple(int(x) for x in v.replace("-", ".").split(".") if x.isdigit())


def _installed(pkg):
    """Version unpacked in LIB, or None."""
    best = None
    for d in LIB.glob(f"{pkg}-*"):
        v = d.name[len(pkg) + 1:]
        if d.is_dir() and (best is None or _vkey(v) > _vkey(best)):
            best = v
    return best


def _bundled(pkg):
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return "0"


def activate():
    for pkg in PACKAGES:
        v = _installed(pkg)
        if v and _vkey(v) > _vkey(_bundled(pkg)):
            sys.path.insert(0, str(LIB / f"{pkg}-{v}"))


def _wheel_url(pkg):
    with urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json", timeout=15) as r:
        data = json.load(r)
    version = data["info"]["version"]
    for f in data["urls"]:
        if f["packagetype"] == "bdist_wheel" and f["filename"].endswith("py3-none-any.whl"):
            return version, f["url"]
    raise RuntimeError(f"No pure-Python wheel for {pkg} {version}")


def latest_version():
    return _wheel_url("yt-dlp")[0]


def update():
    """Download newer wheels. Returns the yt-dlp version that will load on the
    next launch, and whether anything changed."""
    changed = False
    for pkg in PACKAGES:
        version, url = _wheel_url(pkg)
        current = _installed(pkg) or _bundled(pkg)
        if _vkey(version) <= _vkey(current):
            continue
        with urllib.request.urlopen(url, timeout=120) as r:
            blob = r.read()
        dest = LIB / f"{pkg}-{version}"
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            z.extractall(tmp)
        shutil.rmtree(dest, ignore_errors=True)
        tmp.rename(dest)
        for old in LIB.glob(f"{pkg}-*"):
            if old != dest:
                shutil.rmtree(old, ignore_errors=True)
        changed = True
    return _installed("yt-dlp") or _bundled("yt-dlp"), changed
