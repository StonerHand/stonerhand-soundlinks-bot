from __future__ import annotations

import logging

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.constants import HTTP_USER_AGENT

LOGGER = logging.getLogger(__name__)
MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 120


class SearchLookupError(RuntimeError):
    """Raised when a text query cannot be resolved to a release URL."""


class SearchClient:
    """Resolves free-text queries to a streaming URL via the iTunes Search API.

    The API is public and keyless; the returned Apple Music URL is then fed
    through the regular Song.link pipeline, so search results get the same
    cross-platform treatment as pasted links.
    """

    def __init__(self, *, timeout: float = 6.0, country: str = "US") -> None:
        self._country = country
        self._client = httpx.AsyncClient(
            base_url="https://itunes.apple.com",
            headers={"User-Agent": HTTP_USER_AGENT},
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            timeout=httpx.Timeout(timeout, connect=3.0),
        )
        self._cache: TTLCache[str] = TTLCache(ttl_seconds=6 * 3600)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search_release_url(self, query: str) -> str:
        normalized_query = normalize_search_query(query)
        if normalized_query is None:
            raise SearchLookupError("Query is too short to search.")

        cache_key = normalized_query.casefold()
        cached_url = self._cache.get(cache_key)
        if cached_url is not None:
            return cached_url

        try:
            response = await self._client.get(
                "/search",
                params={
                    "term": normalized_query,
                    "media": "music",
                    "entity": "song,album",
                    "limit": 5,
                    "country": self._country,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchLookupError("Music search is unavailable right now.") from exc

        url = _extract_release_url(payload)
        if url is None:
            raise SearchLookupError("No release matched the query.")

        self._cache.set(cache_key, url)
        return url


def normalize_search_query(query: str) -> str | None:
    normalized = " ".join(query.split()).strip()
    if len(normalized) < MIN_QUERY_LENGTH or normalized.startswith("/"):
        return None

    return normalized[:MAX_QUERY_LENGTH]


def _extract_release_url(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None

    results = payload.get("results")
    if not isinstance(results, list):
        return None

    for result in results:
        if not isinstance(result, dict):
            continue

        for field in ("trackViewUrl", "collectionViewUrl"):
            url = result.get(field)
            if isinstance(url, str) and url.startswith("http"):
                return url

    return None
