"""yt-dlp and ffmpeg errors, mapped to short user-facing messages."""

import re

_RULES = [
    (r"confirm your age|age[- ]restricted|inappropriate for some users",
     "Age-restricted video. Enable browser cookies in Settings, using a browser signed in to YouTube."),
    (r"not a bot|Sign in to confirm",
     "The site requested sign-in. Enable browser cookies in Settings, or retry later."),
    (r"Instagram.*(login required|rate-limit reached)|login required|You need to log in|Requested content is not available",
     "This site wants a signed-in session. Enable browser cookies in Settings, using a browser signed in to it."),
    (r"No video could be found in this tweet|There's no video in this|has no video",
     "No video in this post."),
    (r"Private video|This account is private|private account", "Private video."),
    (r"Unexpected response from webpage request",
     "TikTok refused the request. TikTok is not available in some regions, including India."),
    (r"members[- ]only|Join this channel", "Members-only video. Enable cookies from a member account in Settings."),
    (r"Premieres in|This live event will begin|will begin in|Premiere will begin",
     "This premiere or stream has not started."),
    (r"live stream recording is not available",
     "No recording is available for this stream."),
    (r"removed by the uploader|account associated with this video has been terminated|Video unavailable|This video is unavailable|no longer available",
     "Video unavailable."),
    (r"not available in your country|blocked it in your country", "Video is blocked in your region."),
    (r"copyright", "Video removed after a copyright claim."),
    (r"Requested format is not available",
     "Selected format is no longer available. Fetch the link again."),
    (r"HTTP Error 403",
     "The site refused the download (HTTP 403). Update yt-dlp in Settings and retry."),
    (r"HTTP Error 429|Too Many Requests", "Rate limited (HTTP 429). Retry in 10–15 minutes."),
    (r"Unsupported URL|is not a valid URL", "Unrecognized link."),
    (r"Unable to download webpage|getaddrinfo|Name or service not known|timed out|Connection reset|Network is unreachable",
     "Network error. Check the connection and retry."),
    (r"No space left on device", "Disk full."),
    (r"Permission denied|Access is denied", "No write permission for the download folder."),
    (r"could not find .*cookies|Failed to decrypt|cookies database|Operation not permitted",
     "Could not read browser cookies. Close the browser and retry. Safari requires Full Disk Access for Terminal."),
    (r"ffmpeg (is )?not (installed|found)|ffprobe .*not found",
     "ffmpeg not found. Run the start script again."),
    (r"n challenge solving failed|JS challenge|javascript runtime|No supported JavaScript runtime",
     "YouTube challenge failed. Update yt-dlp in Settings."),
]


def friendly(err):
    text = str(err)
    for pat, msg in _RULES:
        if re.search(pat, text, re.I):
            return msg
    # Unknown: keep yt-dlp's own one-line reason, without the "ERROR: [youtube] id:" prefix.
    line = text.strip().splitlines()[-1] if text.strip() else "Unknown error"
    line = re.sub(r"^(ERROR:\s*)?(\[[^\]]+\]\s*)?([\w-]{11}:\s*)?", "", line)
    return f"Download failed: {line[:220]}"
