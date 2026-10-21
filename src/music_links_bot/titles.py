"""Film and series cards: Netflix, Apple TV+ and Disney+ title pages, the
official trailer and the official soundtrack."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from html import unescape

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.metadata_cleaning import match_key
from music_links_bot.models import TitleMatch
from music_links_bot.single_flight import shared
from music_links_bot.url_utils import (
    cache_key_for_url,
    is_direct_platform_url,
    streaming_title,
)

# Streaming sites and YouTube serve a bare shell to unknown clients, so these
# pages are requested the way a desktop browser would.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "en",
}
MAX_PAGE_BYTES = 4 * 1024 * 1024
_STRING = r'"((?:[^"\\]|\\.)*)"'
_SOUNDTRACK = re.compile(r"\b(soundtrack|score|music from)\b", re.IGNORECASE)
_TRAILER = re.compile(r"\b(trailer|teaser)\b", re.IGNORECASE)


class TitleLookupError(RuntimeError):
    """Raised when a title page cannot be read."""


class TitleUnavailableError(TitleLookupError):
    """The service did not answer or refused us: worth a retry, not "not found"."""


def _decode_js(page: str) -> str:
    """Netflix escapes its page data as \\xNN; turn it back into text."""
    return re.sub(r"\\x([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), page)


def _json_string(raw: str) -> str:
    try:
        return str(json.loads(f'"{raw}"'))
    except ValueError:
        return raw


def _first(pattern: str, page: str) -> str | None:
    match = re.search(pattern, page, re.DOTALL)
    return match.group(1) if match else None


def _meta(page: str, name: str) -> str:
    raw = _first(rf'<meta[^>]+property="og:{name}"[^>]+content="([^"]*)"', page)
    return " ".join(unescape(raw or "").split())


def _image(url: str | None) -> str | None:
    return url if url and is_direct_platform_url(url) else None


def _year(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def _parse_netflix(page: str, source_url: str, title_id: str) -> TitleMatch | None:
    page = _decode_js(page)
    heading = _first(r"<h1[^>]*>(.*?)</h1>", page)
    title = " ".join(unescape(re.sub(r"<[^>]+>", "", heading or "")).split())
    if not title:
        raw = _first(rf'"title":{_STRING},"synopsis":', page)
        title = _json_string(raw) if raw else ""
    if not title:
        return None
    kind = _first(rf'"type":"(Show|Movie)","videoId":{title_id}\b', page)
    seasons = _first(r'"numSeasonsLabel":"(\d+)', page)
    genre = _first(rf'"primaryGenres":\{{.{{0,200}}?"name":{_STRING}', page)
    return TitleMatch(
        title=title,
        url=source_url,
        watch_url=f"https://www.netflix.com/title/{title_id}",
        kind="film" if kind == "Movie" else "series",
        year=_year(_first(r'"latestYear":(\d{4})\b', page)),
        seasons=int(seasons) if seasons and kind != "Movie" else None,
        genre=_json_string(genre) if genre else "",
        rating=_first(r'"certificationValue":"([^"]{1,8})"', page) or "",
        image_url=_image(_first(r'"heroImage":\{"url":"(https://[^"]+)"', page)),
        service="Netflix",
    )


def _parse_apple_tv(page: str, source_url: str, title_id: str) -> TitleMatch | None:
    del title_id
    for block in re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S
    ):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("@type") not in {"TVSeries", "Movie"}:
            continue
        title = " ".join(str(data.get("name") or "").split())
        if not title:
            return None
        genre = _first(rf'"genres":\[{_STRING}', page)
        return TitleMatch(
            title=title,
            url=source_url,
            watch_url=source_url.split("?", 1)[0],
            kind="film" if data["@type"] == "Movie" else "series",
            year=_year(str(data.get("datePublished") or "")[:4]),
            genre=_json_string(genre) if genre else "",
            rating=_first(
                r'"ariaLabel":"Rated [^"]+","fallbackText":"([^"]{1,8})"', page
            )
            or "",
            image_url=_image(str(data.get("image") or "")),
            service="Apple TV+",
        )
    return None


def _parse_disney(page: str, source_url: str, title_id: str) -> TitleMatch | None:
    title = _meta(page, "title").split(" | ", 1)[0].strip()
    if not title:
        return None
    seasons = _first(r'"seasonsAvailable":"(\d+)', page)
    genre = _first(rf'"genres":\[{_STRING}', page)
    entity = title_id if title_id.startswith("entity-") else ""
    return TitleMatch(
        title=title,
        url=source_url,
        watch_url=f"https://www.disneyplus.com/browse/{entity}"
        if entity
        else source_url.split("?", 1)[0],
        kind="series" if seasons else "film",
        year=_year(_first(r'"releaseYear":"(\d{4})', page)),
        seasons=int(seasons) if seasons else None,
        genre=_json_string(genre) if genre else "",
        image_url=_image(_meta(page, "image")),
        service="Disney+",
    )


@dataclass(frozen=True, slots=True)
class Service:
    name: str
    # Official YouTube channels whose trailers we trust, as name prefixes.
    channels: tuple[str, ...]
    parse: Callable[[str, str, str], TitleMatch | None]


SERVICES = {
    "netflix": Service("Netflix", ("netflix",), _parse_netflix),
    "appletv": Service("Apple TV+", ("apple tv",), _parse_apple_tv),
    "disney": Service(
        "Disney+",
        (
            "disney",
            "walt disney",
            "marvel",
            "pixar",
            "star wars",
            "national geographic",
        ),
        _parse_disney,
    ),
}


def parse_title_page(page: str, source_url: str) -> TitleMatch | None:
    """Read the card fields from a public title page; None when it has none."""
    found = streaming_title(source_url)
    if found is None:
        return None
    key, title_id = found
    return SERVICES[key].parse(page, source_url, title_id)


def pick_soundtrack(results: object, title: str) -> str | None:
    """The official soundtrack album from an iTunes search, never a cover.

    "Title (Original Soundtrack)" wins over "Title 2 (…)": the album named
    exactly like the film or series comes first, whatever iTunes' order.
    """
    wanted = match_key(title)
    found: list[tuple[int, str]] = []
    for item in results if isinstance(results, list) else []:
        name = str(item.get("collectionName") or "") if isinstance(item, dict) else ""
        album_id = item.get("collectionId") if isinstance(item, dict) else None
        if (
            wanted
            and wanted in match_key(name)
            and _SOUNDTRACK.search(name)
            and isinstance(album_id, int)
        ):
            base = re.split(r"\s*[(\[–—]|\s-\s", name, maxsplit=1)[0]
            exact = 0 if match_key(base) == wanted else 1
            found.append((exact, f"https://album.link/i/{album_id}"))
    found.sort(key=lambda candidate: candidate[0])
    return found[0][1] if found else None


def pick_trailer(
    initial_data: object, title: str, channels: tuple[str, ...] = ("netflix",)
) -> str | None:
    """The first trailer from an official channel in YouTube results."""
    wanted = match_key(title)
    found: list[tuple[int, str]] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            video = node.get("videoRenderer")
            if isinstance(video, dict):
                found.extend(_trailer_candidate(video, wanted, channels))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(initial_data)
    # A clean trailer beats a teaser, which beats an NSFW cut; YouTube's own
    # order breaks ties.
    found.sort(key=lambda candidate: candidate[0])
    return found[0][1] if found else None


def _trailer_candidate(
    video: dict, wanted: str, channels: tuple[str, ...]
) -> list[tuple[int, str]]:
    def runs(field: str) -> str:
        value = video.get(field)
        parts = value.get("runs", []) if isinstance(value, dict) else []
        return "".join(str(part.get("text") or "") for part in parts)

    video_id = video.get("videoId")
    name = runs("title")
    kind = _TRAILER.search(name)
    if (
        not isinstance(video_id, str)
        or not re.fullmatch(r"[\w-]{11}", video_id)
        or not runs("ownerText").casefold().startswith(channels)
        or not kind
        or not wanted
        or wanted not in match_key(name)
    ):
        return []
    rank = 0 if kind.group(1).casefold() == "trailer" else 1
    if re.search(r"\b(nsfw|uncensored|red band)\b", name, re.IGNORECASE):
        rank = 2
    return [(rank, f"https://www.youtube.com/watch?v={video_id}")]


class TitleClient:
    def __init__(self, *, timeout: float = 6.0) -> None:
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            headers=_BROWSER_HEADERS,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            timeout=httpx.Timeout(timeout, connect=3.0),
        )
        self._cache: TTLCache[TitleMatch] = TTLCache()
        self._inflight: dict[str, asyncio.Task[TitleMatch]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup_title(self, source_url: str) -> TitleMatch:
        found = streaming_title(source_url)
        if found is None:
            raise TitleLookupError("Unsupported title URL.")
        key = cache_key_for_url(source_url)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        service = SERVICES[found[0]]
        return await shared(
            self._inflight, key, lambda: self._fetch(source_url, key, service)
        )

    async def _fetch(self, source_url: str, key: str, service: Service) -> TitleMatch:
        try:
            page = await self._get_text(source_url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise TitleLookupError(f"{service.name} has no such title.") from exc
            raise TitleUnavailableError(f"{service.name} refused the page.") from exc
        except httpx.HTTPError as exc:
            raise TitleUnavailableError(f"{service.name} is unavailable.") from exc
        title = parse_title_page(page, source_url)
        if title is None:
            raise TitleLookupError(f"{service.name} page has no title.")
        trailer, soundtrack = await asyncio.gather(
            self._trailer(title.title, service), self._soundtrack(title.title)
        )
        title.trailer_url, title.soundtrack_url = trailer, soundtrack
        self._cache.set(key, title)
        return title

    async def _trailer(self, title: str, service: Service) -> str | None:
        try:
            page = await self._get_text(
                "https://www.youtube.com/results",
                params={"search_query": f"{title} official trailer {service.name}"},
            )
            raw = _first(r"var ytInitialData = (\{.*?\});</script>", page)
            return (
                pick_trailer(json.loads(raw), title, service.channels) if raw else None
            )
        # The trailer is a bonus button: a slow or changed YouTube page only
        # means the card goes out without it.
        except (httpx.HTTPError, ValueError, TitleLookupError):
            return None

    async def _soundtrack(self, title: str) -> str | None:
        try:
            response = await self._client.get(
                "https://itunes.apple.com/search",
                params={
                    "term": f"{title} soundtrack",
                    "entity": "album",
                    "media": "music",
                    "limit": "10",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        results = payload.get("results") if isinstance(payload, dict) else None
        return pick_soundtrack(results, title)

    async def _get_text(self, url: str, **kwargs) -> str:
        async with self._client.stream("GET", url, **kwargs) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_PAGE_BYTES:
                    raise TitleLookupError("Page is too large.")
            return body.decode(response.encoding or "utf-8", errors="replace")
