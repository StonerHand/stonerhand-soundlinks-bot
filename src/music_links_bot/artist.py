from __future__ import annotations

from collections.abc import Mapping

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.constants import HTTP_HEADERS
from music_links_bot.metadata_cleaning import clean_spotify_metadata_title
from music_links_bot.models import ArtistMatch
from music_links_bot.url_utils import cache_key_for_url, is_spotify_artist_url


class ArtistLookupError(RuntimeError):
    """Raised when artist metadata cannot be fetched."""


class ArtistClient:
    def __init__(self, *, timeout: float = 5.0) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://open.spotify.com",
            follow_redirects=True,
            headers=HTTP_HEADERS,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            timeout=httpx.Timeout(timeout, connect=3.0),
        )
        self._cache: TTLCache[ArtistMatch] = TTLCache()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup_artist(self, source_url: str) -> ArtistMatch:
        if not is_spotify_artist_url(source_url):
            raise ArtistLookupError("Unsupported artist URL.")

        cache_key = cache_key_for_url(source_url)
        cached_artist = self._cache.get(cache_key)
        if cached_artist is not None:
            return cached_artist

        try:
            response = await self._client.get("/oembed", params={"url": source_url})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ArtistLookupError("Could not fetch artist metadata.") from exc

        if not isinstance(payload, Mapping):
            raise ArtistLookupError("Unexpected artist metadata.")

        title = clean_spotify_metadata_title(payload.get("title"))
        artist = ArtistMatch(
            title=title or "Spotify artist",
            platform="Spotify",
            url=source_url,
        )
        self._cache.set(cache_key, artist)
        return artist
