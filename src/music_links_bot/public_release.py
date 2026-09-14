"""Exact public metadata for providers without an anonymous resolver API."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.constants import HTTP_HEADERS
from music_links_bot.models import TrackMatch
from music_links_bot.release_metadata import duration_ms
from music_links_bot.url_utils import (
    cache_key_for_url,
    is_direct_platform_url,
    normalize_host,
)


class PublicReleaseError(RuntimeError):
    """The public page does not identify the requested release."""


class PublicReleaseRegionUnavailable(PublicReleaseError):
    """The provider explicitly denies catalog access in this region."""


def release_identity(url: str) -> tuple[str, str, str] | None:
    if not is_direct_platform_url(url):
        return None
    parsed = urlparse(url)
    host = normalize_host(parsed.hostname)
    path = parsed.path.rstrip("/")
    if host in {"tidal.com", "listen.tidal.com"}:
        match = re.fullmatch(r"/(?:browse/)?(track|album)/(\d+)", path)
        return ("tidal", match[1], match[2]) if match else None
    if host in {"music.yandex.ru", "music.yandex.com"}:
        match = re.fullmatch(r"/(?:album/\d+/)?(track|album)/(\d+)", path)
        return ("yandexMusic", match[1], match[2]) if match else None
    if host.endswith(".bandcamp.com"):
        match = re.fullmatch(r"/(track|album)/([A-Za-z0-9_-]+)", path)
        return ("bandcamp", match[1], host + "/" + match[2]) if match else None
    return None


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.visible: list[str] = []
        self.structured: list[dict] = []
        self._json_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            if key and attributes.get("content"):
                self.meta.setdefault(key, attributes["content"] or "")
        if tag == "script" and attributes.get("type") == "application/ld+json":
            self._json_parts = []

    def handle_data(self, data: str) -> None:
        if self._json_parts is not None:
            self._json_parts.append(data)
        else:
            self.visible.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "script" or self._json_parts is None:
            return
        try:
            value = json.loads("".join(self._json_parts))
        except ValueError:
            value = None
        self._json_parts = None
        items = value if isinstance(value, list) else [value]
        for item in items:
            if isinstance(item, dict):
                self.structured.append(item)
                graph = item.get("@graph")
                if isinstance(graph, list):
                    self.structured.extend(x for x in graph if isinstance(x, dict))


class PublicReleaseClient:
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
        expected = release_identity(source_url)
        if not expected or urlparse(source_url).scheme != "https":
            raise PublicReleaseError("Unsupported public release URL")
        key = cache_key_for_url(source_url)
        if cached := self._cache.get(key):
            return cached
        try:
            url = source_url
            for _ in range(4):
                if release_identity(url) != expected or urlparse(url).scheme != "https":
                    raise PublicReleaseError("Redirect changed the requested release")
                response = await self._client.get(url)
                if not response.is_redirect:
                    response.raise_for_status()
                    break
                url = urljoin(url, response.headers.get("location", ""))
            else:
                raise PublicReleaseError("Too many public release redirects")
            match = parse_public_release(url, response.text)
        except httpx.HTTPError as exc:
            raise PublicReleaseError("Public release metadata is unavailable") from exc
        self._cache.set(key, match)
        return match


def parse_public_release(source_url: str, html: str) -> TrackMatch:
    identity = release_identity(source_url)
    if not identity:
        raise PublicReleaseError("Unsupported release")
    platform, kind, _ = identity
    parser = _MetadataParser()
    parser.feed(html)
    canonical = parser.meta.get("og:url", "")
    if (
        platform == "yandexMusic"
        and not canonical
        and any(
            notice in " ".join(" ".join(parser.visible).split())
            for notice in (
                "Яндекс Музыка недоступна в вашем регионе",
                "Yandex Music is not available in your region",
            )
        )
    ):
        raise PublicReleaseRegionUnavailable(
            "Yandex Music is unavailable in the server region"
        )
    if release_identity(urljoin(source_url, canonical)) != identity or not canonical:
        raise PublicReleaseError("Page does not identify this release")
    expected_type = "MusicAlbum" if kind == "album" else "MusicRecording"
    schema = next(
        (
            x
            for x in parser.structured
            if x.get("@type") == expected_type
            and release_identity(
                urljoin(source_url, str(x.get("url") or x.get("@id") or ""))
            )
            == identity
        ),
        {},
    )
    title = schema.get("name") or parser.meta.get("og:title", "")
    by_artist = schema.get("byArtist") or {}
    artist = by_artist.get("name", "") if isinstance(by_artist, dict) else ""
    if platform == "yandexMusic":
        description = parser.meta.get("og:description", "").split(" • ")
        expected_labels = {"Альбом", "Album"} if kind == "album" else {"Трек", "Track"}
        if len(description) < 2 or description[1] not in expected_labels:
            raise PublicReleaseError("Yandex page lacks release metadata")
        artist = description[0]
        year = description[2] if len(description) > 2 else ""
    else:
        if not schema:
            raise PublicReleaseError("Missing exact structured release metadata")
        year = str(
            schema.get("datePublished") or parser.meta.get("music:release_date", "")
        )[:4]
    if (
        not isinstance(title, str)
        or not title.strip()
        or not isinstance(artist, str)
        or not artist.strip()
    ):
        raise PublicReleaseError("Incomplete release title or artist")
    album = schema.get("inAlbum") or {}
    cover = parser.meta.get("og:image")
    if (
        not cover
        or not is_direct_platform_url(cover)
        or not cover.startswith("https://")
    ):
        cover = None
    duration = re.fullmatch(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?",
        str(schema.get("duration", "")),
    )
    milliseconds = (
        int(
            sum(
                float(v or 0) * unit
                for v, unit in zip(duration.groups(), (3600, 60, 1), strict=True)
            )
            * 1000
        )
        if duration
        else None
    )
    return TrackMatch(
        title=title.strip(),
        artist=artist.strip(),
        links={platform: cache_key_for_url(source_url)},
        kind="album" if kind == "album" else "song",
        thumbnail_url=cover,
        release_year=year if len(year) == 4 and year.isdigit() else None,
        album_title=album.get("name")
        if isinstance(album, dict) and isinstance(album.get("name"), str)
        else None,
        duration_ms=duration_ms(milliseconds),
    )
