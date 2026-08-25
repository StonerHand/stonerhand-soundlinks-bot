from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from music_links_bot.url_utils import cache_key_for_url, normalize_host

UNIVERSAL_RELEASE_HOSTS = frozenset(
    {
        "album.link",
        "artist.link",
        "odesli.co",
        "pod.link",
        "pods.link",
        "song.link",
    }
)
_SAFE_PROVIDER_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
_PLATFORM_PRIORITY = (
    "spotify",
    "appleMusic",
    "youtubeMusic",
    "youtube",
    "deezer",
    "tidal",
)


def is_universal_release_url(url: str | None) -> bool:
    if not url:
        return False
    return normalize_host(urlparse(url).hostname) in UNIVERSAL_RELEASE_HOSTS


def canonical_release_hub_url(
    source_url: str | None,
    *,
    release_kind: str = "song",
) -> str | None:
    """Build a real Odesli page URL for provider IDs with a stable mapping."""
    if not source_url:
        return None

    clean_url = cache_key_for_url(source_url)
    if is_universal_release_url(clean_url):
        return clean_url

    parsed = urlparse(clean_url)
    host = normalize_host(parsed.hostname)
    parts = [part for part in parsed.path.split("/") if part]

    if host == "open.spotify.com" and len(parts) >= 2:
        provider_kind, provider_id = parts[-2].casefold(), parts[-1]
        if not _SAFE_PROVIDER_ID.fullmatch(provider_id):
            return None
        if provider_kind == "track":
            return f"https://song.link/s/{provider_id}"
        if provider_kind == "album":
            return f"https://album.link/s/{provider_id}"
        if provider_kind in {"episode", "show"}:
            return f"https://pods.link/s/{provider_id}"
        return None

    if host == "music.apple.com" and parts:
        query_item_id = (parse_qs(parsed.query).get("i") or [""])[0]
        if query_item_id and _SAFE_PROVIDER_ID.fullmatch(query_item_id):
            return f"https://song.link/i/{query_item_id}"
        provider_id = parts[-1]
        if release_kind == "album" and _SAFE_PROVIDER_ID.fullmatch(provider_id):
            return f"https://album.link/i/{provider_id}"
        return None

    if host == "podcasts.apple.com" and parts:
        provider_id = next(
            (
                part.removeprefix("id")
                for part in reversed(parts)
                if part.startswith("id") and part[2:]
            ),
            "",
        )
        if provider_id and _SAFE_PROVIDER_ID.fullmatch(provider_id):
            return f"https://pods.link/i/{provider_id}"

    if host in {"youtube.com", "m.youtube.com", "youtu.be"}:
        video_id = parts[0] if host == "youtu.be" and parts else ""
        if not video_id:
            video_id = (parse_qs(parsed.query).get("v") or [""])[0]
        if video_id and _SAFE_PROVIDER_ID.fullmatch(video_id):
            return f"https://song.link/y/{video_id}"

    if host == "deezer.com" and len(parts) >= 2:
        provider_kind, provider_id = parts[-2].casefold(), parts[-1]
        if _SAFE_PROVIDER_ID.fullmatch(provider_id):
            domain = "album.link" if provider_kind == "album" else "song.link"
            return f"https://{domain}/d/{provider_id}"

    if host in {"tidal.com", "listen.tidal.com"} and len(parts) >= 2:
        provider_kind, provider_id = parts[-2].casefold(), parts[-1]
        if _SAFE_PROVIDER_ID.fullmatch(provider_id):
            domain = "album.link" if provider_kind == "album" else "song.link"
            return f"https://{domain}/t/{provider_id}"

    return None


def resolve_release_hub_url(
    release_page_url: str | None,
    links: dict[str, str],
    *,
    release_kind: str = "song",
) -> str | None:
    """Prefer Odesli's pageUrl and repair Spotify metadata fallbacks."""
    if is_universal_release_url(release_page_url):
        return cache_key_for_url(str(release_page_url))

    candidates = [release_page_url]
    candidates.extend(links.get(platform) for platform in _PLATFORM_PRIORITY)
    candidates.extend(links.values())
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        hub_url = canonical_release_hub_url(
            candidate,
            release_kind=release_kind,
        )
        if hub_url:
            return hub_url
    return None
