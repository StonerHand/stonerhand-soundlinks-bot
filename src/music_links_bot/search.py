from __future__ import annotations

from dataclasses import dataclass
import logging

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.constants import HTTP_USER_AGENT

LOGGER = logging.getLogger(__name__)
MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 120
MAX_CANDIDATES = 3


class SearchLookupError(RuntimeError):
    """Raised when a text query cannot be resolved to a release URL."""


@dataclass(slots=True)
class SearchCandidate:
    url: str
    title: str
    artist: str
    artwork_url: str | None = None


class SearchClient:
    """Resolves free-text queries to streaming URLs via the iTunes Search API.

    The API is public and keyless; the returned Apple Music URLs are then fed
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
        self._cache: TTLCache[list[SearchCandidate]] = TTLCache(ttl_seconds=6 * 3600)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search_release_url(self, query: str) -> str:
        candidates = await self.search_release_candidates(query)
        return candidates[0].url

    async def search_release_candidates(self, query: str) -> list[SearchCandidate]:
        normalized_query = normalize_search_query(query)
        if normalized_query is None:
            raise SearchLookupError("Query is too short to search.")

        cache_key = normalized_query.casefold()
        cached_candidates = self._cache.get(cache_key)
        if cached_candidates is not None:
            return cached_candidates

        try:
            response = await self._client.get(
                "/search",
                params={
                    "term": normalized_query,
                    "media": "music",
                    "entity": "song,album",
                    "limit": 8,
                    "country": self._country,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchLookupError("Music search is unavailable right now.") from exc

        candidates = _extract_release_candidates(payload)
        if not candidates:
            raise SearchLookupError("No release matched the query.")

        self._cache.set(cache_key, candidates)
        return candidates


def normalize_search_query(query: str) -> str | None:
    normalized = " ".join(query.split()).strip()
    if len(normalized) < MIN_QUERY_LENGTH or normalized.startswith("/"):
        return None

    return normalized[:MAX_QUERY_LENGTH]


def _extract_release_candidates(payload: object) -> list[SearchCandidate]:
    if not isinstance(payload, dict):
        return []

    results = payload.get("results")
    if not isinstance(results, list):
        return []

    candidates: list[SearchCandidate] = []
    seen_urls: set[str] = set()
    for result in results:
        if not isinstance(result, dict):
            continue

        url = None
        for field in ("trackViewUrl", "collectionViewUrl"):
            value = result.get(field)
            if isinstance(value, str) and value.startswith("http"):
                url = value
                break

        if url is None or url in seen_urls:
            continue

        seen_urls.add(url)
        artwork = result.get("artworkUrl100") or result.get("artworkUrl60")
        candidates.append(
            SearchCandidate(
                url=url,
                title=str(result.get("trackName") or result.get("collectionName") or ""),
                artist=str(result.get("artistName") or ""),
                artwork_url=artwork if isinstance(artwork, str) else None,
            )
        )
        if len(candidates) >= MAX_CANDIDATES:
            break

    return candidates

