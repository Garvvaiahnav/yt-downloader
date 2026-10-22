"""The installed app: runs the local server and shows it in a native window
(WKWebView on Mac, Edge WebView2 on Windows). Closing the window quits."""

import os
import socket
import sys
import threading
import time
import webbrowser

# A windowed build has no console; anything that prints would crash.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from ytd import updater

updater.activate()  # before anything imports yt_dlp

import uvicorn  # noqa: E402
import webview  # noqa: E402

from ytd.api import app  # noqa: E402

TITLE = "YT Downloader"


def free_port(start=8765):
    for port in range(start, start + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("No free port")


def main():
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_config=None, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    from ytd import appupdate
    appupdate.start_checks()

    webview.create_window(TITLE, url, width=1320, height=880, min_size=(760, 560),
                          background_color="#0F0F11")
    try:
        webview.start(gui="edgechromium" if sys.platform == "win32" else None)
    except Exception:
        # No WebView2 on this PC: use the default browser and keep serving.
        webbrowser.open(url)
        while True:
            time.sleep(3600)
    server.should_exit = True


if __name__ == "__main__":
    main()
