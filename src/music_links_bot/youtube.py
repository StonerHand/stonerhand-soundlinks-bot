from __future__ import annotations

from collections.abc import Mapping

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.constants import HTTP_USER_AGENT
from music_links_bot.models import VideoMatch
from music_links_bot.url_utils import cache_key_for_url

HTTP_HEADERS = {"User-Agent": HTTP_USER_AGENT}


class YouTubeLookupError(RuntimeError):
    """Raised when YouTube metadata cannot be fetched."""


class YouTubeClient:
    def __init__(self, *, timeout: float = 5.0) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://www.youtube.com",
            headers=HTTP_HEADERS,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            timeout=httpx.Timeout(timeout, connect=3.0),
        )
        self._cache: TTLCache[VideoMatch] = TTLCache()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup_video(self, source_url: str) -> VideoMatch:
        cache_key = cache_key_for_url(source_url)
        cached_video = self._cache.get(cache_key)
        if cached_video is not None:
            return cached_video

        try:
            response = await self._client.get(
                "/oembed",
                params={"url": source_url, "format": "json"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise YouTubeLookupError("Could not fetch YouTube metadata.") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise YouTubeLookupError("YouTube returned invalid metadata.") from exc

        if not isinstance(payload, Mapping):
            raise YouTubeLookupError("YouTube returned unexpected metadata.")

        title = str(payload.get("title") or "").strip()
        author = str(payload.get("author_name") or "").strip()
        if not title:
            raise YouTubeLookupError("YouTube video title is missing.")

        video = VideoMatch(
            title=title,
            author=author or "YouTube",
            url=source_url,
        )
        self._cache.set(cache_key, video)
        return video
