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

TITLE = "Video Downloader"


SAFARI_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")
_signin = {"window": None}


def open_signin():
    """A second window on Google's sign-in page. Once it lands back on
    youtube.com signed in, its cookies are saved and the window closes."""
    from ytd import account

    if _signin["window"]:
        return
    w = webview.create_window("Sign in to YouTube", account.SIGNIN_URL, width=520, height=760)
    _signin["window"] = w
    closed = threading.Event()
    w.events.closed += closed.set

    def watch():
        try:
            for _ in range(900):  # give up after 15 minutes
                if closed.wait(1):
                    return  # closed by the user
                try:
                    page = w.get_current_url() or ""
                except Exception:
                    return
                if "youtube.com" in page and "accounts." not in page and account.save(w.get_cookies()):
                    w.destroy()
                    return
        finally:
            _signin["window"] = None

    threading.Thread(target=watch, daemon=True, name="signin").start()


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

    from ytd import account
    account.open_window = open_signin

    webview.create_window(TITLE, url, width=1320, height=880, min_size=(760, 560),
                          background_color="#0F0F11")
    try:
        # WKWebView's stock user agent has no Safari version, and Google turns
        # such "embedded" browsers away at sign-in; present as Safari.
        webview.start(gui="edgechromium" if sys.platform == "win32" else None,
                      user_agent=SAFARI_UA if sys.platform == "darwin" else None)
    except Exception:
        # No WebView2 on this PC: use the default browser and keep serving.
        webbrowser.open(url)
        while True:
            time.sleep(3600)
    server.should_exit = True


if __name__ == "__main__":
    main()
