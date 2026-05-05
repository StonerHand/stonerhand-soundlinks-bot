from __future__ import annotations

from collections.abc import Mapping

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.models import VideoMatch


class YouTubeLookupError(RuntimeError):
    """Raised when YouTube metadata cannot be fetched."""


class YouTubeClient:
    def __init__(self, *, timeout: float = 8.0) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://www.youtube.com",
            timeout=timeout,
        )
        self._cache: TTLCache[VideoMatch] = TTLCache()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup_video(self, source_url: str) -> VideoMatch:
        cached_video = self._cache.get(source_url)
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
        self._cache.set(source_url, video)
        return video
