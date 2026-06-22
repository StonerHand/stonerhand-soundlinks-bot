from __future__ import annotations

import re
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

from music_links_bot.constants import SUPPORTED_INPUT_HOSTS

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,!?)]}>\"'"
YOUTUBE_MUSIC_HOST = "music.youtube.com"
YOUTUBE_VIDEO_HOSTS = {"youtube.com", "m.youtube.com", "youtu.be"}
SOUNDCLOUD_HOSTS = {"soundcloud.com", "m.soundcloud.com", "on.soundcloud.com"}
NTS_HOSTS = {"nts.live", "www.nts.live"}
TRACKING_QUERY_KEYS = {
    "fbclid",
    "feature",
    "gclid",
    "igsh",
    "igshid",
    "si",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


def clean_url_token(token: str) -> str:
    return token.rstrip(TRAILING_PUNCTUATION)


def normalize_host(host: str | None) -> str:
    return (host or "").lower().removeprefix("www.")


def is_supported_music_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    normalized = normalize_host(parsed.hostname)

    if normalized == YOUTUBE_MUSIC_HOST:
        return True

    if normalized in YOUTUBE_VIDEO_HOSTS:
        return is_youtube_video_url(url)

    if normalized.endswith(".youtube.com"):
        return False

    if normalized in SUPPORTED_INPUT_HOSTS:
        return True

    return any(normalized.endswith(f".{host}") for host in SUPPORTED_INPUT_HOSTS)


def extract_supported_urls(text: str | None) -> list[str]:
    if not text:
        return []

    urls: list[str] = []
    seen: set[str] = set()
    for match in URL_RE.finditer(text):
        candidate = clean_url_token(match.group(0))
        dedupe_key = cache_key_for_url(candidate)
        if dedupe_key in seen or not is_supported_music_url(candidate):
            continue

        urls.append(candidate)
        seen.add(dedupe_key)

    return urls


def cache_key_for_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return url

    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS
    ]
    return urlunparse(
        parsed._replace(
            query=urlencode(query_items),
            fragment="",
        )
    )


def strip_supported_urls(text: str | None) -> str:
    if not text:
        return ""

    spans: list[tuple[int, int]] = []
    for match in URL_RE.finditer(text):
        candidate = clean_url_token(match.group(0))
        if is_supported_music_url(candidate):
            spans.append(match.span())

    stripped = text
    for start, end in reversed(spans):
        before = stripped[start - 1] if start > 0 else ""
        after = stripped[end] if end < len(stripped) else ""

        # Remove one separator together with an inline URL, while preserving
        # every other user-authored space, line break, and empty paragraph.
        if before in " \t" and after in " \t":
            end += 1
        elif before in " \t" and (
            not after or after in "\r\n" or after in TRAILING_PUNCTUATION
        ):
            start -= 1
        elif (not before or before in "\r\n") and after in " \t":
            end += 1

        stripped = stripped[:start] + stripped[end:]

    lines = stripped.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    return "\n".join(line.rstrip() for line in lines)


def is_youtube_video_url(url: str) -> bool:
    parsed = urlparse(url)
    normalized_host = normalize_host(parsed.hostname)
    if normalized_host == YOUTUBE_MUSIC_HOST:
        return False

    if normalized_host == "youtu.be":
        return bool([part for part in parsed.path.split("/") if part])

    if normalized_host not in {"youtube.com", "m.youtube.com"}:
        return False

    parts = [part.lower() for part in parsed.path.split("/") if part]
    if not parts:
        return False

    if parts[0] == "watch":
        return bool(parse_qs(parsed.query).get("v"))

    return parts[0] in {"shorts", "live", "embed"} and len(parts) >= 2


def is_soundcloud_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    normalized_host = normalize_host(parsed.hostname)
    return normalized_host in SOUNDCLOUD_HOSTS or normalized_host.endswith(
        ".soundcloud.com"
    )


def is_nts_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    normalized_host = normalize_host(parsed.hostname)
    return normalized_host in NTS_HOSTS or normalized_host.endswith(".nts.live")


def spotify_url_type(url: str) -> str | None:
    parsed = urlparse(url)
    if normalize_host(parsed.hostname) not in {"open.spotify.com", "spotify.com"}:
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None

    return parts[0].lower()


def is_spotify_playlist_url(url: str) -> bool:
    return spotify_url_type(url) == "playlist"


def is_spotify_artist_url(url: str) -> bool:
    return spotify_url_type(url) == "artist"


def apple_podcasts_url_type(url: str) -> str | None:
    parsed = urlparse(url)
    if normalize_host(parsed.hostname) != "podcasts.apple.com":
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if "podcast" not in parts:
        return None

    if parse_qs(parsed.query).get("i"):
        return "episode"

    return "show"
