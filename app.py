"""Start the downloader on this machine only: python app.py [--port 8765]

Normally started by start.command (Mac) or start.bat (Windows)."""

import argparse
import os
import socket
import sys
import threading
import webbrowser


def free_port(host, start):
    for port in range(start, start + 20):
        with socket.socket() as s:
            if os.name != "nt":  # match uvicorn, so a port in TIME_WAIT after a restart still counts as free
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    sys.exit(f"Ports {start}-{start + 19} are all in use.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    from ytd.tools import find
    missing = [n for n in ("ffmpeg", "ffprobe") if not find(n)]
    if missing:
        sys.exit(f"{' and '.join(missing)} not found. Install ffmpeg and put it on PATH.")

    from ytd import updater
    updater.activate()  # before anything imports yt_dlp

    import uvicorn
    from ytd.api import app

    port = free_port("127.0.0.1", args.port)
    url = f"http://127.0.0.1:{port}"
    print("\n  Video Downloader is running.\n")
    print("  It opens in your browser automatically. If it doesn't, open this link:\n")
    print(f"      {url}\n")
    print("  Keep this window open while you use it. Close it (or press Ctrl+C) to stop.\n", flush=True)
    if not args.no_browser and not os.environ.get("YTD_RESTARTED"):
        threading.Timer(1.0, webbrowser.open, [url]).start()
    os.environ["YTD_RESTARTED"] = "1"  # the in-app update re-execs; don't open a second tab
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
