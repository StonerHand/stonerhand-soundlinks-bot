from __future__ import annotations

import json
from collections.abc import Mapping
from html.parser import HTMLParser

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.constants import HTTP_USER_AGENT
from music_links_bot.models import TrackMatch
from music_links_bot.url_utils import cache_key_for_url, spotify_url_type

SPOTIFY_EMBED_BASE_URL = "https://open.spotify.com/embed"


class SpotifyLookupError(RuntimeError):
    """Raised when Spotify cannot provide public metadata for a release."""


class _NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._inside_next_data = False
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag != "script":
            return
        attributes = dict(attrs)
        self._inside_next_data = attributes.get("id") == "__NEXT_DATA__"

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._inside_next_data = False

    def handle_data(self, data: str) -> None:
        if self._inside_next_data:
            self.parts.append(data)


class SpotifyClient:
    """Best-effort metadata fallback for Spotify URLs.

    Song.link remains the primary resolver because it supplies cross-platform
    buttons. This client only prevents a valid Spotify release from silently
    disappearing when the aggregator cannot resolve it.
    """

    def __init__(self, *, timeout: float = 6.0) -> None:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": HTTP_USER_AGENT},
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            timeout=httpx.Timeout(timeout, connect=3.0),
        )
        self._cache: TTLCache[TrackMatch] = TTLCache(ttl_seconds=24 * 3600)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup_release(self, source_url: str) -> TrackMatch:
        kind = spotify_url_type(source_url)
        if kind not in {"track", "album"}:
            raise SpotifyLookupError("Unsupported Spotify release type.")

        cache_key = cache_key_for_url(source_url)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        embed_url = _spotify_embed_url(source_url, kind)
        try:
            response = await self._client.get(embed_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SpotifyLookupError("Spotify metadata is unavailable.") from exc

        match = parse_spotify_embed(source_url, response.text)
        self._cache.set(cache_key, match)
        return match


def parse_spotify_embed(source_url: str, html: str) -> TrackMatch:
    parser = _NextDataParser()
    parser.feed(html)
    if not parser.parts:
        raise SpotifyLookupError("Spotify embed metadata is missing.")

    try:
        payload = json.loads("".join(parser.parts))
    except (TypeError, ValueError) as exc:
        raise SpotifyLookupError("Spotify returned invalid metadata.") from exc

    entity = _find_entity(payload)
    if entity is None:
        raise SpotifyLookupError("Spotify release metadata is missing.")

    title = str(entity.get("name") or entity.get("title") or "").strip()
    artist = _spotify_artist(entity)
    if not title or not artist:
        raise SpotifyLookupError("Spotify title or artist is missing.")

    kind = str(entity.get("type") or spotify_url_type(source_url) or "song")
    normalized_kind = "album" if kind == "album" else "song"
    release_date = entity.get("releaseDate")
    if isinstance(release_date, Mapping):
        release_date = release_date.get("isoString")
    release_year = str(release_date or "")[:4]
    if not release_year.isdigit():
        release_year = None

    return TrackMatch(
        title=title,
        artist=artist,
        links={"spotify": cache_key_for_url(source_url)},
        page_url=cache_key_for_url(source_url),
        release_year=release_year,
        kind=normalized_kind,
        release_format="album" if normalized_kind == "album" else None,
        thumbnail_url=_spotify_thumbnail(entity),
    )


def _spotify_embed_url(source_url: str, kind: str) -> str:
    clean = cache_key_for_url(source_url)
    item_id = clean.rstrip("/").rsplit("/", 1)[-1]
    return f"{SPOTIFY_EMBED_BASE_URL}/{kind}/{item_id}"


def _find_entity(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        entity = value.get("entity")
        if isinstance(entity, Mapping):
            return entity
        for child in value.values():
            found = _find_entity(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_entity(child)
            if found is not None:
                return found
    return None


def _spotify_artist(entity: Mapping[str, object]) -> str:
    artists = entity.get("artists")
    if isinstance(artists, list):
        names = [
            str(artist.get("name") or "").strip()
            for artist in artists
            if isinstance(artist, Mapping)
        ]
        if clean_names := [name for name in names if name]:
            return ", ".join(clean_names)

    for key in ("artistName", "subtitle", "ownerName"):
        value = str(entity.get(key) or "").strip()
        if value:
            return value
    return ""


def _spotify_thumbnail(entity: Mapping[str, object]) -> str | None:
    for key in ("coverArt", "images"):
        images = entity.get(key)
        if isinstance(images, Mapping):
            images = images.get("sources") or images.get("items")
        if not isinstance(images, list):
            continue
        for image in images:
            if not isinstance(image, Mapping):
                continue
            url = image.get("url")
            if isinstance(url, str) and url.startswith("http"):
                return url
    return None
