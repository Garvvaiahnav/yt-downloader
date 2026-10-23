"""Installs the After Effects panel (a CEP extension shipped in aepanel/).

The panel is unsigned, so CEP's PlayerDebugMode is switched on for the
current user; that is how in-house CEP panels are deployed without going
through Adobe Exchange. The panel talks to this app's local API, and is
re-copied whenever the app updates so the two never drift apart."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .tools import FROZEN, IS_MAC, IS_WIN, NO_WINDOW

BUNDLE = "com.garv.videodownloader"
SRC = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "aepanel"
CSXS_VERSIONS = range(9, 14)  # AE 2019 (CSXS 9) through current releases


def _dest():
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "Adobe" / "CEP" / "extensions" / BUNDLE
    if IS_WIN:
        return Path(os.environ["APPDATA"]) / "Adobe" / "CEP" / "extensions" / BUNDLE
    return None


def _app_path():
    if not FROZEN:
        return None
    exe = Path(sys.executable).resolve()
    return str(exe.parents[2]) if IS_MAC else str(exe)  # Mac: the .app bundle


def _installed_version():
    d = _dest()
    try:
        m = re.search(r'ExtensionBundleVersion="([^"]+)"', (d / "CSXS" / "manifest.xml").read_text("utf-8"))
        return m.group(1) if m else None
    except (OSError, TypeError):
        return None


def status():
    return {"supported": _dest() is not None and SRC.is_dir(), "installed": _installed_version(),
            "current": __version__}


def _debug_mode():
    for v in CSXS_VERSIONS:
        if IS_MAC:
            subprocess.run(["defaults", "write", f"com.adobe.CSXS.{v}", "PlayerDebugMode", "1"], capture_output=True)
        else:
            subprocess.run(["reg", "add", rf"HKCU\Software\Adobe\CSXS.{v}", "/v", "PlayerDebugMode", "/t", "REG_SZ",
                            "/d", "1", "/f"], capture_output=True, creationflags=NO_WINDOW)


def install():
    d = _dest()
    if not d or not SRC.is_dir():
        raise RuntimeError("The After Effects panel isn't available on this system.")
    tmp = d.with_name(d.name + ".new")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(SRC, tmp, ignore=shutil.ignore_patterns("._*", ".DS_Store"))
    manifest = tmp / "CSXS" / "manifest.xml"
    manifest.write_text(manifest.read_text("utf-8").replace("__VERSION__", __version__), "utf-8")
    (tmp / "app.json").write_text(json.dumps({"app": _app_path(), "version": __version__}), "utf-8")
    shutil.rmtree(d, ignore_errors=True)
    tmp.rename(d)
    _debug_mode()
    return status()


def refresh():
    """After an app update: bring an installed panel to the same version."""
    try:
        if _installed_version() and _installed_version() != __version__:
            install()
    except Exception:
        pass
