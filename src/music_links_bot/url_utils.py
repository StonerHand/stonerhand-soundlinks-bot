from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from music_links_bot.constants import SUPPORTED_INPUT_HOSTS

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,!?)]}>\"'"
YOUTUBE_MUSIC_HOST = "music.youtube.com"
YOUTUBE_VIDEO_HOSTS = {"youtube.com", "m.youtube.com", "youtu.be"}


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
        if candidate in seen or not is_supported_music_url(candidate):
            continue

        urls.append(candidate)
        seen.add(candidate)

    return urls


def strip_supported_urls(text: str | None) -> str:
    if not text:
        return ""

    stripped = URL_RE.sub("", text)
    stripped = re.sub(r"\s+", " ", stripped)
    return stripped.strip(TRAILING_PUNCTUATION + " \n\t")


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


def spotify_url_type(url: str) -> str | None:
    parsed = urlparse(url)
    if normalize_host(parsed.hostname) not in {"open.spotify.com", "spotify.com"}:
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None

    return parts[0].lower()


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
