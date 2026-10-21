"""Netflix film and series cards: the title page, its trailer and soundtrack."""

from __future__ import annotations

import asyncio
import json
import re
from html import unescape

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.metadata_cleaning import match_key
from music_links_bot.models import TitleMatch
from music_links_bot.single_flight import shared
from music_links_bot.url_utils import (
    cache_key_for_url,
    is_direct_platform_url,
    netflix_title_id,
)

# Netflix and YouTube serve a bare shell to unknown clients, so these pages
# are requested the way a desktop browser would.
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


class NetflixLookupError(RuntimeError):
    """Raised when a Netflix title page cannot be read."""


class NetflixUnavailableError(NetflixLookupError):
    """Netflix did not answer or refused us: worth a retry, not "not found"."""


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


def parse_title_page(page: str, source_url: str) -> TitleMatch | None:
    """Read the card fields from a public title page; None when it has none."""
    title_id = netflix_title_id(source_url)
    if not title_id:
        return None
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
    year = _first(r'"latestYear":(\d{4})\b', page)
    genre = _first(rf'"primaryGenres":\{{.{{0,200}}?"name":{_STRING}', page)
    rating = _first(r'"certificationValue":"([^"]{1,8})"', page)
    image = _first(r'"heroImage":\{"url":"(https://[^"]+)"', page)
    return TitleMatch(
        title=title,
        url=source_url,
        watch_url=f"https://www.netflix.com/title/{title_id}",
        kind="film" if kind == "Movie" else "series",
        year=int(year) if year else None,
        seasons=int(seasons) if seasons and kind != "Movie" else None,
        genre=_json_string(genre) if genre else "",
        rating=rating or "",
        image_url=image if image and is_direct_platform_url(image) else None,
    )


def pick_soundtrack(results: object, title: str) -> str | None:
    """The official soundtrack album from an iTunes search, never a cover."""
    wanted = match_key(title)
    for item in results if isinstance(results, list) else []:
        name = str(item.get("collectionName") or "") if isinstance(item, dict) else ""
        album_id = item.get("collectionId") if isinstance(item, dict) else None
        if (
            wanted
            and wanted in match_key(name)
            and _SOUNDTRACK.search(name)
            and isinstance(album_id, int)
        ):
            return f"https://album.link/i/{album_id}"
    return None


def pick_trailer(initial_data: object, title: str) -> str | None:
    """The first trailer from an official Netflix channel in YouTube results."""
    wanted = match_key(title)
    found: list[tuple[int, str]] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            video = node.get("videoRenderer")
            if isinstance(video, dict):
                found.extend(_trailer_candidate(video, wanted))
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


def _trailer_candidate(video: dict, wanted: str) -> list[tuple[int, str]]:
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
        or not runs("ownerText").casefold().startswith("netflix")
        or not kind
        or not wanted
        or wanted not in match_key(name)
    ):
        return []
    rank = 0 if kind.group(1).casefold() == "trailer" else 1
    if re.search(r"\b(nsfw|uncensored|red band)\b", name, re.IGNORECASE):
        rank = 2
    return [(rank, f"https://www.youtube.com/watch?v={video_id}")]


class NetflixClient:
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
        if not netflix_title_id(source_url):
            raise NetflixLookupError("Unsupported Netflix URL.")
        key = cache_key_for_url(source_url)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        return await shared(self._inflight, key, lambda: self._fetch(source_url, key))

    async def _fetch(self, source_url: str, key: str) -> TitleMatch:
        try:
            page = await self._get_text(source_url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise NetflixLookupError("Netflix has no such title.") from exc
            raise NetflixUnavailableError("Netflix refused the page.") from exc
        except httpx.HTTPError as exc:
            raise NetflixUnavailableError("Netflix page is unavailable.") from exc
        title = parse_title_page(page, source_url)
        if title is None:
            raise NetflixLookupError("Netflix page has no title.")
        trailer, soundtrack = await asyncio.gather(
            self._trailer(title.title), self._soundtrack(title.title)
        )
        title.trailer_url, title.soundtrack_url = trailer, soundtrack
        self._cache.set(key, title)
        return title

    async def _trailer(self, title: str) -> str | None:
        try:
            page = await self._get_text(
                "https://www.youtube.com/results",
                params={"search_query": f"{title} official trailer netflix"},
            )
            raw = _first(r"var ytInitialData = (\{.*?\});</script>", page)
            return pick_trailer(json.loads(raw), title) if raw else None
        # The trailer is a bonus button: a slow or changed YouTube page only
        # means the card goes out without it.
        except (httpx.HTTPError, ValueError, NetflixLookupError):
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
                    raise NetflixLookupError("Page is too large.")
            return body.decode(response.encoding or "utf-8", errors="replace")
