from __future__ import annotations

from collections.abc import Mapping

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.models import ArtistMatch
from music_links_bot.url_utils import is_spotify_artist_url


class ArtistLookupError(RuntimeError):
    """Raised when artist metadata cannot be fetched."""


class ArtistClient:
    def __init__(self, *, timeout: float = 8.0) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://open.spotify.com",
            timeout=timeout,
            follow_redirects=True,
        )
        self._cache: TTLCache[ArtistMatch] = TTLCache()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup_artist(self, source_url: str) -> ArtistMatch:
        if not is_spotify_artist_url(source_url):
            raise ArtistLookupError("Unsupported artist URL.")

        cached_artist = self._cache.get(source_url)
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

        title = _clean_spotify_title(str(payload.get("title") or ""))
        artist = ArtistMatch(
            title=title or "Spotify artist",
            platform="Spotify",
            url=source_url,
        )
        self._cache.set(source_url, artist)
        return artist


def _clean_spotify_title(title: str) -> str:
    title = title.strip()
    for suffix in (" | Spotify", " - Spotify"):
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()

    return title
