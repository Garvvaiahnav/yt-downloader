"""Signed-in YouTube session for the bot check ("Sign in to confirm you're
not a bot"), age-restricted and members-only videos.

Reading another browser's cookies does not work on Windows: Chrome, Edge and
Brave lock the cookie database while running and, since Chrome 127, encrypt
it so only the browser itself can read it. So the app signs in in its own
window instead, then writes that window's YouTube cookies to a cookies.txt
that only this user can read, and hands yt-dlp a private copy per run."""

import email.utils
import os
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path

from .settings import config_dir

COOKIES = config_dir() / "youtube-cookies.txt"
SIGNIN_URL = ("https://accounts.google.com/ServiceLogin?service=youtube"
              "&continue=https%3A%2F%2Fwww.youtube.com%2F")
# Present once the Google account session reaches youtube.com.
_SIGNED_IN = {"LOGIN_INFO", "SAPISID", "__Secure-3PAPISID"}

open_window = None  # set by desktop.py; None when running in a plain browser


def status():
    if not COOKIES.is_file():
        return {"signed_in": False, "can_sign_in": open_window is not None}
    return {"signed_in": True, "can_sign_in": open_window is not None,
            "since": time.strftime("%Y-%m-%d", time.localtime(COOKIES.stat().st_mtime))}


def _expiry(value):
    """Epoch seconds from WebView2's RFC 1123 string or WKWebView's NSDate."""
    if not value:
        return int(time.time()) + 30 * 86400  # session cookie: keep a month
    text = str(value)
    for parse in (lambda t: email.utils.parsedate_to_datetime(t),
                  lambda t: datetime.strptime(t, "%Y-%m-%d %H:%M:%S %z")):
        try:
            return int(parse(text).timestamp())
        except (TypeError, ValueError):
            continue
    return int(time.time()) + 30 * 86400


def save(cookies):
    """cookies: pywebview's list of SimpleCookie. True when they hold a
    signed-in session (and were written)."""
    lines, names = ["# Netscape HTTP Cookie File"], set()
    for jar in cookies or []:
        for name, m in jar.items():
            domain = m["domain"] or ".youtube.com"
            if "youtube.com" not in domain and "google.com" not in domain:
                continue
            names.add(name)
            lines.append("\t".join([
                domain, "TRUE" if domain.startswith(".") else "FALSE", m["path"] or "/",
                "TRUE" if m["secure"] else "FALSE", str(_expiry(m["expires"])), name, m.value]))
    if not names & _SIGNED_IN:
        return False
    COOKIES.parent.mkdir(parents=True, exist_ok=True)
    tmp = COOKIES.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, COOKIES)
    return True


def sign_out():
    COOKIES.unlink(missing_ok=True)


def private_copy():
    """A throwaway copy for one yt-dlp run: yt-dlp rewrites its cookie file on
    exit, and two downloads finishing together must not interleave writes."""
    if not COOKIES.is_file():
        return None
    fd, path = tempfile.mkstemp(prefix="ytd-cookies-", suffix=".txt")
    os.close(fd)
    shutil.copyfile(COOKIES, path)
    return path
