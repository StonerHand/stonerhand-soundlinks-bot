from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from html.parser import HTMLParser

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.constants import HTTP_HEADERS
from music_links_bot.metadata_cleaning import clean_spotify_metadata_title
from music_links_bot.models import PlaylistMatch
from music_links_bot.url_utils import (
    cache_key_for_url,
    is_apple_music_playlist_url,
    is_playlist_url,
    is_spotify_playlist_url,
)

MAX_PLAYLIST_IMPORT_TRACKS = 10
PLAYLIST_IMPORT_TIMEOUT_SECONDS = 2.0
_SPOTIFY_TRACK_RE = re.compile(
    r"(?:https://open\.spotify\.com/track/|spotify:track:)([A-Za-z0-9]{10,32})"
)
_APPLE_TRACK_RE = re.compile(
    r"https://music\.apple\.com/[^\s\"'<>?]+\?[^\s\"'<>]*\bi=\d+[^\s\"'<>]*"
)


class PlaylistLookupError(RuntimeError):
    """Raised when playlist metadata cannot be fetched."""


class _PageTitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.open_graph_title = ""
        self.twitter_title = ""
        self.document_title = ""
        self._inside_title = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        if tag.casefold() == "title":
            self._inside_title = True
            return

        if tag.casefold() != "meta":
            return

        meta_name = (
            attributes.get("property") or attributes.get("name") or ""
        ).casefold()
        content = str(attributes.get("content") or "").strip()
        if meta_name == "og:title":
            self.open_graph_title = content
        elif meta_name == "twitter:title":
            self.twitter_title = content

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self._inside_title = False

    def handle_data(self, data: str) -> None:
        if self._inside_title:
            self.document_title += data


class PlaylistClient:
    def __init__(self, *, timeout: float = 5.0) -> None:
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            headers=HTTP_HEADERS,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            timeout=httpx.Timeout(timeout, connect=3.0),
        )
        self._cache: TTLCache[PlaylistMatch] = TTLCache()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup_playlist(self, source_url: str) -> PlaylistMatch:
        if not is_playlist_url(source_url):
            raise PlaylistLookupError("Unsupported playlist URL.")

        cache_key = cache_key_for_url(source_url)
        cached_playlist = self._cache.get(cache_key)
        if cached_playlist is not None:
            return cached_playlist

        if is_spotify_playlist_url(source_url):
            playlist = await self._lookup_spotify_playlist(source_url)
        elif is_apple_music_playlist_url(source_url):
            playlist = await self._lookup_apple_music_playlist(source_url)
        else:
            raise PlaylistLookupError("Unsupported playlist URL.")

        self._cache.set(cache_key, playlist)
        return playlist

    async def _lookup_spotify_playlist(self, source_url: str) -> PlaylistMatch:
        try:
            response = await self._client.get(
                "https://open.spotify.com/oembed",
                params={"url": source_url},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PlaylistLookupError("Could not fetch playlist metadata.") from exc

        if not isinstance(payload, Mapping):
            raise PlaylistLookupError("Unexpected playlist metadata.")

        title = clean_spotify_metadata_title(payload.get("title"))
        track_urls: list[str] = []
        try:
            page = await asyncio.wait_for(
                self._client.get(source_url),
                timeout=PLAYLIST_IMPORT_TIMEOUT_SECONDS,
            )
            page.raise_for_status()
            track_urls = _extract_spotify_track_urls(page.text)
        except (httpx.HTTPError, asyncio.TimeoutError):
            # Metadata still makes a useful playlist card. Track import is a
            # progressive enhancement and must not make the lookup fail.
            track_urls = []
        return PlaylistMatch(
            title=title or "Spotify playlist",
            platform="Spotify",
            url=source_url,
            track_urls=track_urls,
        )

    async def _lookup_apple_music_playlist(
        self,
        source_url: str,
    ) -> PlaylistMatch:
        try:
            response = await self._client.get(source_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PlaylistLookupError("Could not fetch playlist metadata.") from exc

        title = _extract_apple_music_title(response.text)
        if not title:
            raise PlaylistLookupError("Unexpected playlist metadata.")

        return PlaylistMatch(
            title=title,
            platform="Apple Music",
            url=source_url,
            track_urls=_extract_apple_track_urls(response.text),
        )


def _unique_urls(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= MAX_PLAYLIST_IMPORT_TRACKS:
            break
    return result


def _extract_spotify_track_urls(page_html: str) -> list[str]:
    normalized = str(page_html or "").replace("\\/", "/")
    return _unique_urls(
        [
            f"https://open.spotify.com/track/{match.group(1)}"
            for match in _SPOTIFY_TRACK_RE.finditer(normalized)
        ]
    )


def _extract_apple_track_urls(page_html: str) -> list[str]:
    normalized = str(page_html or "").replace("\\/", "/").replace("&amp;", "&")
    return _unique_urls(
        [match.group(0) for match in _APPLE_TRACK_RE.finditer(normalized)]
    )


def _extract_apple_music_title(page_html: str) -> str:
    parser = _PageTitleParser()
    try:
        parser.feed(page_html)
    except (TypeError, ValueError):
        return ""

    title = parser.open_graph_title or parser.twitter_title or parser.document_title
    title = title.strip().lstrip("\u200e\u200f\ufeff")
    for suffix in (
        " on Apple Music",
        " - Playlist - Apple Music",
    ):
        if title.casefold().endswith(suffix.casefold()):
            title = title[: -len(suffix)].rstrip()
            break
    return title


def build_playlist_fallback(source_url: str) -> PlaylistMatch:
    if is_apple_music_playlist_url(source_url):
        return PlaylistMatch(
            title="Apple Music playlist",
            platform="Apple Music",
            url=source_url,
        )

    return PlaylistMatch(
        title="Spotify playlist",
        platform="Spotify",
        url=source_url,
    )
