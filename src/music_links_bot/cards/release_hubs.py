from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from music_links_bot.core.url_utils import (
    cache_key_for_url,
    is_direct_platform_url,
    normalize_host,
    spotify_url_type,
    youtube_video_id,
)

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
    if not url or not is_direct_platform_url(url):
        return False
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and normalize_host(parsed.hostname) in UNIVERSAL_RELEASE_HOSTS
    )


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
    if not is_direct_platform_url(clean_url):
        return None
    if video_id := youtube_video_id(clean_url):
        return f"https://song.link/y/{video_id}"
    parsed = urlparse(clean_url)
    parts = [part for part in parsed.path.split("/") if part]
    hub = _HUBS.get(normalize_host(parsed.hostname))
    return hub(parts, parse_qs(parsed.query), release_kind) if hub and parts else None


def _safe(provider_id: str) -> bool:
    return bool(_SAFE_PROVIDER_ID.fullmatch(provider_id))


_SPOTIFY_HUB_DOMAINS = {
    "track": "song.link",
    "album": "album.link",
    "episode": "pods.link",
    "show": "pods.link",
}


def _spotify_hub(parts: list[str], _query: dict, _kind: str) -> str | None:
    if len(parts) < 2 or not _safe(parts[-1]):
        return None
    found = _SPOTIFY_HUB_DOMAINS.get(parts[-2].casefold())
    return f"https://{found}/s/{parts[-1]}" if found else None


def _apple_music_hub(parts: list[str], query: dict, release_kind: str) -> str | None:
    item_id = (query.get("i") or [""])[0]
    if item_id and _safe(item_id):
        return f"https://song.link/i/{item_id}"
    if release_kind == "album" and _safe(parts[-1]):
        return f"https://album.link/i/{parts[-1]}"
    return None


def _apple_podcasts_hub(parts: list[str], _query: dict, _kind: str) -> str | None:
    provider_id = next(
        (
            part.removeprefix("id")
            for part in reversed(parts)
            if part.startswith("id") and part[2:]
        ),
        "",
    )
    return f"https://pods.link/i/{provider_id}" if _safe(provider_id) else None


def _kind_id_hub(letter: str):
    """Deezer and Tidal: …/album/<id> is an album page, anything else a song."""

    def hub(parts: list[str], _query: dict, _kind: str) -> str | None:
        if len(parts) < 2 or not _safe(parts[-1]):
            return None
        domain = "album.link" if parts[-2].casefold() == "album" else "song.link"
        return f"https://{domain}/{letter}/{parts[-1]}"

    return hub


_HUBS = {
    "open.spotify.com": _spotify_hub,
    "music.apple.com": _apple_music_hub,
    "podcasts.apple.com": _apple_podcasts_hub,
    "deezer.com": _kind_id_hub("d"),
    "tidal.com": _kind_id_hub("t"),
    "listen.tidal.com": _kind_id_hub("t"),
}


def resolve_release_hub_url(
    release_page_url: str | None,
    links: dict[str, str],
    *,
    release_kind: str = "song",
) -> str | None:
    """Prefer Odesli's pageUrl and repair Spotify metadata fallbacks."""
    spotify_type = spotify_url_type(links.get("spotify") or "")
    expected_spotify_types = {
        "album": {"album"},
        "podcast": {"episode", "show"},
        "song": {"track"},
    }.get(release_kind, {"track"})
    has_verified_spotify = spotify_type in expected_spotify_types
    if is_universal_release_url(release_page_url):
        clean_page_url = cache_key_for_url(str(release_page_url))
        page_parts = [part for part in urlparse(clean_page_url).path.split("/") if part]
        is_apple_origin_page = len(page_parts) >= 2 and page_parts[-2] == "i"
        if is_apple_origin_page and has_verified_spotify:
            return canonical_release_hub_url(
                links["spotify"],
                release_kind=release_kind,
            )
        if is_apple_origin_page and set(links) <= {"appleMusic"}:
            return None
        return clean_page_url

    candidates = [release_page_url]
    candidates.extend(links.get(platform) for platform in _PLATFORM_PRIORITY)
    candidates.extend(links.values())
    for candidate in candidates:
        if not isinstance(candidate, str) or not is_direct_platform_url(candidate):
            continue
        # An Apple-only iTunes fallback proves the Apple destination, not
        # Spotify or any other provider. Its public song.link page may show a
        # Spotify tile without a direct URL, so presenting it as an exhaustive
        # “All platforms” action would be misleading.
        candidate_host = normalize_host(urlparse(candidate).hostname)
        if candidate_host in {"open.spotify.com", "spotify.com"} and (
            spotify_url_type(candidate) not in expected_spotify_types
        ):
            continue
        if candidate_host in {"music.apple.com", "itunes.apple.com"} and not (
            has_verified_spotify
        ):
            continue
        hub_url = canonical_release_hub_url(
            candidate,
            release_kind=release_kind,
        )
        if hub_url:
            return hub_url
    return None
