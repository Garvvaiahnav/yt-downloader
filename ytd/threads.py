"""Threads extractor. yt-dlp has none; Threads posts are Instagram media
underneath, and a normal browser request for the post page carries the post's
JSON (including its DASH manifest) inline, the same data the page renders
from. Registered on every YoutubeDL in jobs.py."""

import json
import re

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError, float_or_none, int_or_none, url_or_none

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


def _find_post(obj, code):
    if isinstance(obj, dict):
        if obj.get("code") == code and ("video_versions" in obj or "carousel_media" in obj):
            return obj
        obj = obj.values()
    if isinstance(obj, (list, type({}.values()))):
        for v in obj:
            hit = _find_post(v, code)
            if hit:
                return hit
    return None


class ThreadsIE(InfoExtractor):
    IE_NAME = "threads"
    _VALID_URL = r"https?://(?:www\.)?threads\.(?:net|com)/@(?P<user>[\w.]+)/post/(?P<id>[\w-]+)"

    def _media(self, media, video_id):
        formats = []
        for v in media.get("video_versions") or []:
            if url_or_none(v.get("url")) and v["url"] not in {f["url"] for f in formats}:
                formats.append({"url": v["url"], "format_id": f"mp4-{v.get('type')}", "ext": "mp4",
                                "width": int_or_none(v.get("width")), "height": int_or_none(v.get("height"))})
        dash = media.get("video_dash_manifest")
        if dash:
            formats.extend(self._parse_mpd_formats(self._parse_xml(dash, video_id), mpd_id="dash"))
        thumbs = ((media.get("image_versions2") or {}).get("candidates") or [])
        return {
            "id": video_id,
            "formats": formats,
            "duration": float_or_none(media.get("video_duration")),
            "width": int_or_none(media.get("original_width")),
            "height": int_or_none(media.get("original_height")),
            "thumbnail": url_or_none(thumbs[0].get("url")) if thumbs else None,
        }

    def _real_extract(self, url):
        user, code = self._match_valid_url(url).group("user", "id")
        page = self._download_webpage(url, code, headers=_HEADERS)
        post = None
        for blob in re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', page, re.S):
            if code in blob and ("video_versions" in blob or "carousel_media" in blob):
                post = _find_post(json.loads(blob), code)
                if post:
                    break
        if not post:
            raise ExtractorError("Threads post not found. It may be private or deleted.", expected=True)

        caption = ((post.get("caption") or {}).get("text") or "").strip()
        title = caption.splitlines()[0][:100] if caption else f"Threads post by @{user}"
        common = {"title": title, "description": caption, "channel": user, "uploader": user,
                  "webpage_url": url, "timestamp": int_or_none(post.get("taken_at"))}

        media = [m for m in (post.get("carousel_media") or [post]) if m.get("video_versions") or m.get("video_dash_manifest")]
        if not media:
            raise ExtractorError("This Threads post has no video.", expected=True)
        if len(media) == 1:
            return {**self._media(media[0], code), **common}
        entries = [{**self._media(m, f"{code}_{i}"), **common, "title": f"{title} ({i})"}
                   for i, m in enumerate(media, 1)]
        return self.playlist_result(entries, code, title)
