"""Apple Music radio-show pages bypass track/album matching entirely."""

from __future__ import annotations

import re

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.constants import HTTP_HEADERS
from music_links_bot.models import RadioMatch
from music_links_bot.playlist import _PageTitleParser
from music_links_bot.url_utils import cache_key_for_url, is_apple_music_radio_url


class AppleRadioLookupError(RuntimeError):
    """An Apple page could not be confirmed as a radio show or station."""


def parse_apple_radio(source_url, html):
    parser = _PageTitleParser()
    parser.feed(html)
    document_title = " ".join(parser.document_title.split())
    if "/station/" not in source_url and not re.search(
        r"\bRadio Show\b|\bRadio Station\b",
        document_title,
        re.I,
    ):
        raise AppleRadioLookupError("This curator is not a confirmed radio show")
    title = " ".join((parser.open_graph_title or document_title).split()).lstrip(
        "\u200e\u200f\ufeff"
    )
    title = re.sub(
        r"(?: on Apple Music| - (?:Radio Show|Radio Station) - Apple Music| - Apple Music)$",
        "",
        title,
        flags=re.I,
    ).strip()
    if not title or title.casefold() == "apple music":
        raise AppleRadioLookupError("Radio title is unavailable")
    return RadioMatch(title=title, station="Apple Music", url=source_url)


class AppleRadioClient:
    def __init__(self, *, timeout=5.0):
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=3.0),
            follow_redirects=False,
            headers={**HTTP_HEADERS, "Accept-Language": "en-US,en;q=0.9"},
        )
        self._cache = TTLCache()

    async def aclose(self):
        await self._client.aclose()

    async def lookup_radio(self, source_url):
        if not is_apple_music_radio_url(source_url):
            raise AppleRadioLookupError("Unsupported Apple Music radio URL")
        key = cache_key_for_url(source_url)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        target = httpx.URL(source_url).copy_merge_params({"l": "en"})
        try:
            for _ in range(4):
                async with self._client.stream("GET", target) as response:
                    if response.is_redirect:
                        target = response.url.join(response.headers.get("location", ""))
                        if not is_apple_music_radio_url(str(target)):
                            raise AppleRadioLookupError("Unexpected radio redirect")
                        continue
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 4 * 1024 * 1024:
                            raise AppleRadioLookupError("Radio page is too large")
                    radio = parse_apple_radio(
                        source_url, body.decode("utf-8", errors="replace")
                    )
                    self._cache.set(key, radio)
                    return radio
        except httpx.HTTPError as exc:
            raise AppleRadioLookupError("Apple Music radio is unavailable") from exc
        raise AppleRadioLookupError("Too many radio redirects")
