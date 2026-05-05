from __future__ import annotations

from collections.abc import Mapping

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.models import PlaylistMatch
from music_links_bot.url_utils import is_spotify_playlist_url


class PlaylistLookupError(RuntimeError):
    """Raised when playlist metadata cannot be fetched."""


class PlaylistClient:
    def __init__(self, *, timeout: float = 8.0) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://open.spotify.com",
            timeout=timeout,
            follow_redirects=True,
        )
        self._cache: TTLCache[PlaylistMatch] = TTLCache()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup_playlist(self, source_url: str) -> PlaylistMatch:
        if not is_spotify_playlist_url(source_url):
            raise PlaylistLookupError("Unsupported playlist URL.")

        cached_playlist = self._cache.get(source_url)
        if cached_playlist is not None:
            return cached_playlist

        try:
            response = await self._client.get("/oembed", params={"url": source_url})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PlaylistLookupError("Could not fetch playlist metadata.") from exc

        if not isinstance(payload, Mapping):
            raise PlaylistLookupError("Unexpected playlist metadata.")

        title = str(payload.get("title") or "").strip()
        playlist = PlaylistMatch(
            title=title or "Spotify playlist",
            platform="Spotify",
            url=source_url,
        )
        self._cache.set(source_url, playlist)
        return playlist
