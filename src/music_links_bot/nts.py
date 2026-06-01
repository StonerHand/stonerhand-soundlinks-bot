from __future__ import annotations

from html.parser import HTMLParser

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.constants import HTTP_USER_AGENT
from music_links_bot.models import RadioMatch
from music_links_bot.url_utils import cache_key_for_url, is_nts_url

HTTP_HEADERS = {"User-Agent": HTTP_USER_AGENT}


class NTSLookupError(RuntimeError):
    """Raised when NTS metadata cannot be fetched."""


class NTSClient:
    def __init__(self, *, timeout: float = 5.0) -> None:
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            headers=HTTP_HEADERS,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            timeout=httpx.Timeout(timeout, connect=3.0),
        )
        self._cache: TTLCache[RadioMatch] = TTLCache()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup_radio(self, source_url: str) -> RadioMatch:
        if not is_nts_url(source_url):
            raise NTSLookupError("Unsupported NTS URL.")

        cache_key = cache_key_for_url(source_url)
        cached_radio = self._cache.get(cache_key)
        if cached_radio is not None:
            return cached_radio

        try:
            response = await self._client.get(source_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NTSLookupError("Could not fetch NTS metadata.") from exc

        radio = parse_nts_metadata(source_url, response.text)
        self._cache.set(cache_key, radio)
        return radio


def parse_nts_metadata(source_url: str, html: str) -> RadioMatch:
    parser = _NTSMetadataParser()
    parser.feed(html)

    title = _clean_nts_title(
        parser.meta.get("og:title")
        or parser.meta.get("twitter:title")
        or parser.title
        or ""
    )
    station = (
        parser.meta.get("og:site_name")
        or parser.meta.get("application-name")
        or "NTS Radio"
    )

    return RadioMatch(
        title=title or "NTS Radio",
        station=_clean_nts_station(station),
        url=source_url,
    )


def build_nts_fallback(source_url: str) -> RadioMatch | None:
    if not is_nts_url(source_url):
        return None

    return RadioMatch(title="NTS Radio", station="NTS Radio", url=source_url)


def _clean_nts_title(raw_title: str) -> str:
    title = " ".join(raw_title.split())
    for prefix in ("NTS | ", "NTS Radio | "):
        if title.startswith(prefix):
            title = title[len(prefix) :].strip()

    for suffix in (
        " | NTS",
        " | NTS Radio",
        " | Listen on NTS",
        " - NTS",
        " - NTS Radio",
    ):
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()

    return title


def _clean_nts_station(raw_station: str) -> str:
    station = " ".join(raw_station.split())
    if station.casefold() in {"nts", "nts live"}:
        return "NTS Radio"

    return station or "NTS Radio"


class _NTSMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self._inside_title = False
        self._title_parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag == "title":
            self._inside_title = True
            return

        if tag != "meta":
            return

        attr_map = {key.lower(): value or "" for key, value in attrs}
        key = (attr_map.get("property") or attr_map.get("name") or "").casefold()
        content = attr_map.get("content", "").strip()
        if key and content:
            self.meta.setdefault(key, content)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._inside_title = False
            self.title = " ".join("".join(self._title_parts).split())

    def handle_data(self, data: str) -> None:
        if self._inside_title:
            self._title_parts.append(data)
