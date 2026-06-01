from __future__ import annotations

from collections.abc import Mapping

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.constants import HTTP_USER_AGENT
from music_links_bot.models import TrackMatch
from music_links_bot.url_utils import cache_key_for_url, is_soundcloud_url

HTTP_HEADERS = {"User-Agent": HTTP_USER_AGENT}


class SoundCloudLookupError(RuntimeError):
    """Raised when SoundCloud metadata cannot be fetched."""


class SoundCloudClient:
    def __init__(self, *, timeout: float = 5.0) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://soundcloud.com",
            follow_redirects=True,
            headers=HTTP_HEADERS,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            timeout=httpx.Timeout(timeout, connect=3.0),
        )
        self._cache: TTLCache[TrackMatch] = TTLCache()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup_track(self, source_url: str) -> TrackMatch:
        if not is_soundcloud_url(source_url):
            raise SoundCloudLookupError("Unsupported SoundCloud URL.")

        cache_key = cache_key_for_url(source_url)
        cached_track = self._cache.get(cache_key)
        if cached_track is not None:
            return cached_track

        try:
            response = await self._client.get(
                "/oembed",
                params={"url": source_url, "format": "json"},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SoundCloudLookupError("Could not fetch SoundCloud metadata.") from exc

        if not isinstance(payload, Mapping):
            raise SoundCloudLookupError("Unexpected SoundCloud metadata.")

        track = parse_soundcloud_metadata(source_url, payload)
        self._cache.set(cache_key, track)
        return track


def parse_soundcloud_metadata(
    source_url: str,
    payload: Mapping[str, object],
) -> TrackMatch:
    raw_title = str(payload.get("title") or "").strip()
    raw_author = str(payload.get("author_name") or "").strip()
    title, artist = _split_title_and_artist(raw_title, raw_author)

    return TrackMatch(
        title=title or "SoundCloud",
        artist=artist or "SoundCloud",
        links={"soundcloud": source_url},
        page_url=source_url,
        kind=_soundcloud_release_kind(source_url),
    )


def build_soundcloud_fallback(source_url: str) -> TrackMatch | None:
    if not is_soundcloud_url(source_url):
        return None

    return TrackMatch(
        title="SoundCloud",
        artist="SoundCloud",
        links={"soundcloud": source_url},
        page_url=source_url,
        kind=_soundcloud_release_kind(source_url),
    )


def _split_title_and_artist(raw_title: str, raw_author: str) -> tuple[str, str]:
    title = raw_title
    artist = raw_author

    if artist:
        suffix = f" by {artist}"
        if title.casefold().endswith(suffix.casefold()):
            title = title[: -len(suffix)].strip()

        return title, artist

    if " by " in title:
        guessed_title, guessed_artist = title.rsplit(" by ", 1)
        return guessed_title.strip(), guessed_artist.strip()

    if " - " in title:
        guessed_artist, guessed_title = title.split(" - ", 1)
        return guessed_title.strip(), guessed_artist.strip()

    return title, artist


def _soundcloud_release_kind(source_url: str) -> str:
    normalized = cache_key_for_url(source_url).lower()
    if "/sets/" in normalized:
        return "album"

    return "song"
