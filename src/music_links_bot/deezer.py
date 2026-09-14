from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.constants import HTTP_HEADERS
from music_links_bot.metadata_cleaning import positive_track_count
from music_links_bot.models import TrackMatch
from music_links_bot.release_hubs import canonical_release_hub_url
from music_links_bot.release_metadata import duration_ms
from music_links_bot.url_utils import (
    cache_key_for_url,
    is_direct_platform_url,
    normalize_host,
)

_RELEASE_PATH = re.compile(r"^/(?:[a-z]{2}/)?(track|album)/(\d+)/?$", re.I)
_SHORT_HOSTS = {"link.deezer.com", "deezer.page.link"}


class DeezerLookupError(RuntimeError):
    """Deezer did not return the requested release."""


def _safe_deezer_url(url: str) -> bool:
    if not is_direct_platform_url(url):
        return False
    parsed = urlparse(url)
    return parsed.scheme == "https" and normalize_host(parsed.hostname) in {
        "deezer.com",
        *_SHORT_HOSTS,
    }


def _release_identity(url: str) -> tuple[str, str] | None:
    if (
        not _safe_deezer_url(url)
        or normalize_host(urlparse(url).hostname) != "deezer.com"
    ):
        return None
    match = _RELEASE_PATH.fullmatch(urlparse(url).path)
    return (match[1].lower(), match[2]) if match else None


def is_deezer_release_url(url: str) -> bool:
    return bool(_release_identity(url)) or (
        _safe_deezer_url(url) and normalize_host(urlparse(url).hostname) in _SHORT_HOSTS
    )


class DeezerClient:
    def __init__(self, *, timeout: float = 6.0) -> None:
        self._client = httpx.AsyncClient(
            headers=HTTP_HEADERS,
            follow_redirects=False,
            timeout=httpx.Timeout(timeout, connect=3.0),
        )
        self._cache: TTLCache[TrackMatch] = TTLCache(ttl_seconds=6 * 3600)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup_release(self, source_url: str) -> TrackMatch:
        if not is_deezer_release_url(source_url):
            raise DeezerLookupError("Unsupported Deezer release URL")
        key = cache_key_for_url(source_url)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            url = source_url
            for _ in range(5):
                identity = _release_identity(url)
                if identity:
                    break
                if not _safe_deezer_url(url):
                    raise DeezerLookupError("Deezer redirect left the provider")
                # Never follow arbitrary redirect targets or embedded query URLs.
                response = await self._client.get(url)
                if not response.is_redirect or not response.headers.get("location"):
                    raise DeezerLookupError("Deezer short link did not resolve")
                url = urljoin(url, response.headers["location"])
                # Deezer's own redirect envelope carries the canonical target.
                # Only a validated Deezer track/album ID can skip the extra hop.
                if (
                    _safe_deezer_url(url)
                    and normalize_host(urlparse(url).hostname) == "link.deezer.com"
                ):
                    destination = (parse_qs(urlparse(url).query).get("dest") or [""])[0]
                    if _release_identity(destination):
                        url = destination
            else:
                raise DeezerLookupError("Too many Deezer redirects")
            kind, item_id = identity
            response = await self._client.get(
                f"https://api.deezer.com/{kind}/{item_id}"
            )
            response.raise_for_status()
            match = parse_deezer_release(url, response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise DeezerLookupError("Deezer metadata is unavailable") from exc
        self._cache.set(key, match)
        return match


def parse_deezer_release(source_url: str, payload: object) -> TrackMatch:
    identity = _release_identity(source_url)
    if not identity or not isinstance(payload, Mapping):
        raise DeezerLookupError("Invalid Deezer release metadata")
    kind, item_id = identity
    if str(payload.get("id")) != item_id or payload.get("type") != kind:
        raise DeezerLookupError("Deezer returned another release")
    artist = payload.get("artist")
    title = payload.get("title")
    if (
        not isinstance(artist, Mapping)
        or not isinstance(title, str)
        or not title.strip()
    ):
        raise DeezerLookupError("Deezer release metadata is incomplete")
    name = artist.get("name")
    if not isinstance(name, str) or not name.strip():
        raise DeezerLookupError("Deezer artist is missing")
    album = payload if kind == "album" else payload.get("album")
    album = album if isinstance(album, Mapping) else {}
    cover = album.get("cover_xl") or album.get("cover_big") or album.get("cover_medium")
    if (
        not isinstance(cover, str)
        or not is_direct_platform_url(cover)
        or not cover.startswith("https://")
    ):
        cover = None
    seconds = payload.get("duration")
    duration = duration_ms(seconds * 1000) if type(seconds) is int else None
    year = str(payload.get("release_date") or "")[:4]
    canonical = f"https://www.deezer.com/{kind}/{item_id}"
    return TrackMatch(
        title=title.strip(),
        artist=name.strip(),
        kind="album" if kind == "album" else "song",
        links={"deezer": canonical},
        page_url=canonical_release_hub_url(canonical),
        release_year=year if len(year) == 4 and year.isdigit() else None,
        album_title=album.get("title")
        if kind == "track" and isinstance(album.get("title"), str)
        else None,
        thumbnail_url=cover,
        duration_ms=duration,
        track_count=positive_track_count(payload.get("nb_tracks"))
        if kind == "album"
        else None,
    )
