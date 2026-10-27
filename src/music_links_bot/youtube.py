from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse, urlunparse

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.collection_collage import branded_video_frame_url
from music_links_bot.constants import HTTP_HEADERS
from music_links_bot.models import VideoMatch
from music_links_bot.telegram_gateway import feature_enabled
from music_links_bot.url_utils import cache_key_for_url, youtube_video_id


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
            parsed = urlparse(source_url)
            metadata_url = (
                urlunparse(parsed._replace(netloc="www.youtube.com"))
                if parsed.hostname == "music.youtube.com"
                else source_url
            )
            response = await self._client.get(
                "/oembed",
                params={"url": metadata_url, "format": "json"},
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
        thumbnail_url = str(payload.get("thumbnail_url") or "").strip()
        if not title:
            raise YouTubeLookupError("YouTube video title is missing.")

        video = VideoMatch(
            title=title,
            author=author or "YouTube",
            url=source_url,
            thumbnail_url=thumbnail_url or None,
        )
        self._cache.set(cache_key, video)
        return video


def video_still_url(video: VideoMatch) -> str | None:
    """The video's own frame: YouTube's thumbnail, or the one its id names."""
    if video.thumbnail_url:
        return video.thumbnail_url
    video_id = youtube_video_id(video.url)
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None


def video_preview_url(video: VideoMatch) -> str:
    """What a video card previews: its signed frame, not the YouTube page.

    Telegram builds a link preview before it answers the bot. Since October
    2026 it cannot build one from a YouTube page in time: the send hangs, the
    next message to the chat hits flood control and the card never arrives.
    A frame image previews at once; ours is 16:9 with ▶ and the signature,
    and the card's button opens the video. Without branding it is YouTube's
    own still. YOUTUBE_PLAYER_PREVIEW_ENABLED=1 brings the inline player back.
    """
    if feature_enabled("YOUTUBE_PLAYER_PREVIEW_ENABLED", default=False):
        return video.url
    still = video_still_url(video)
    return branded_video_frame_url(still) or still or video.url
