import json
import os
import sys
import threading
from pathlib import Path

BROWSERS = ["", "chrome", "safari", "firefox", "edge", "brave", "chromium", "opera", "vivaldi"]


def config_dir():
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "yt-downloader"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "yt-downloader"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "yt-downloader"


_FILE = config_dir() / "settings.json"
_lock = threading.Lock()
# macOS asks permission before any app writes to Downloads, Desktop or
# Documents; Movies is not on that list, and it is where editors look anyway.
_DEFAULTS = {
    "download_dir": str(Path.home() / ("Movies" if sys.platform == "darwin" else "Downloads") / "YT Downloader"),
    "cookies_browser": "",
}


def load():
    try:
        data = json.loads(_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        data = {}
    return {**_DEFAULTS, **{k: v for k, v in data.items() if k in _DEFAULTS}}


def save(changes):
    with _lock:
        data = load()
        if "download_dir" in changes:
            d = Path(os.path.expanduser(str(changes["download_dir"]).strip()))
            if not d.is_absolute():
                raise ValueError("Folder must be an absolute path.")
            d.mkdir(parents=True, exist_ok=True)
            data["download_dir"] = str(d)
        if "cookies_browser" in changes:
            if changes["cookies_browser"] not in BROWSERS:
                raise ValueError("Unsupported browser.")
            data["cookies_browser"] = changes["cookies_browser"]
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(data, indent=2), "utf-8")
        return data
