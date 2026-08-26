from __future__ import annotations

import asyncio
import logging
import unicodedata
from dataclasses import dataclass

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.constants import HTTP_USER_AGENT

LOGGER = logging.getLogger(__name__)
MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 120
MAX_CANDIDATES = 3
GENRE_SEARCH_LIMIT = 12


class SearchLookupError(RuntimeError):
    """Raised when a text query cannot be resolved to a release URL."""


@dataclass(slots=True)
class SearchCandidate:
    url: str
    title: str
    artist: str
    artwork_url: str | None = None
    preview_url: str | None = None
    album: str | None = None
    year: str | None = None
    kind: str | None = None


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
        self._miss_cache: TTLCache[bool] = TTLCache(ttl_seconds=10 * 60)
        self._genre_cache: TTLCache[str] = TTLCache(ttl_seconds=24 * 3600)
        self._preview_cache: TTLCache[str] = TTLCache(ttl_seconds=24 * 3600)
        self._inflight: dict[str, asyncio.Task[list[SearchCandidate]]] = {}

    async def aclose(self) -> None:
        pending = list(self._inflight.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._inflight.clear()
        await self._client.aclose()

    async def search_release_url(self, query: str) -> str:
        candidates = await self.search_release_candidates(query)
        return candidates[0].url

    async def lookup_genre(self, artist: str, title: str) -> str | None:
        """Return a genre only for an exact artist/release match.

        iTunes search is relevance-ranked and can put an unrelated release
        first when punctuation changes (for example ``Don't`` vs ``Don’t``).
        A wrong genre is worse than no genre tag, so enrichment is accepted
        only after both the artist and track/collection title match.
        Empty cache entries mark safe misses and avoid repeated lookups.
        """
        query = normalize_search_query(f"{artist} {title}")
        if query is None:
            return None

        cache_key = query.casefold()
        cached_genre = self._genre_cache.get(cache_key)
        if cached_genre is not None:
            return cached_genre or None

        try:
            response = await self._client.get(
                "/search",
                params={
                    "term": query,
                    "media": "music",
                    "entity": "song,album",
                    "limit": GENRE_SEARCH_LIMIT,
                    "country": self._country,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            LOGGER.debug("Genre lookup failed for %s", query, exc_info=True)
            return None

        genre = _extract_matching_genre(payload, artist=artist, title=title)
        self._genre_cache.set(cache_key, genre or "")
        return genre

    async def lookup_preview(self, artist: str, title: str) -> str | None:
        """Best-effort 30-second audio preview URL for a release; empty-string
        cache entries mark known misses so they are not retried."""
        query = normalize_search_query(f"{artist} {title}")
        if query is None:
            return None

        cache_key = query.casefold()
        cached_preview = self._preview_cache.get(cache_key)
        if cached_preview is not None:
            return cached_preview or None

        try:
            response = await self._client.get(
                "/search",
                params={
                    "term": query,
                    "media": "music",
                    "entity": "song",
                    "limit": 3,
                    "country": self._country,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            LOGGER.debug("Preview lookup failed for %s", query, exc_info=True)
            return None

        preview_url = _extract_preview_url(payload)
        self._preview_cache.set(cache_key, preview_url or "")
        return preview_url

    async def search_release_candidates(self, query: str) -> list[SearchCandidate]:
        normalized_query = normalize_search_query(query)
        if normalized_query is None:
            raise SearchLookupError("Query is too short to search.")

        cache_key = normalized_query.casefold()
        cached_candidates = self._cache.get(cache_key)
        if cached_candidates is not None:
            return cached_candidates
        if self._miss_cache.get(cache_key):
            raise SearchLookupError("No release matched the query.")

        pending = self._inflight.get(cache_key)
        if pending is not None:
            return await asyncio.shield(pending)

        task = asyncio.create_task(self._search_and_cache(normalized_query, cache_key))
        self._inflight[cache_key] = task
        task.add_done_callback(
            lambda completed, key=cache_key: self._finish_inflight(key, completed)
        )
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                self._finish_inflight(cache_key, task)

    def _finish_inflight(
        self,
        cache_key: str,
        task: asyncio.Task[list[SearchCandidate]],
    ) -> None:
        if self._inflight.get(cache_key) is task:
            self._inflight.pop(cache_key, None)
        if task.done() and not task.cancelled():
            task.exception()

    async def _search_and_cache(
        self,
        normalized_query: str,
        cache_key: str,
    ) -> list[SearchCandidate]:

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
            self._miss_cache.set(cache_key, True)
            raise SearchLookupError("No release matched the query.")

        self._cache.set(cache_key, candidates)
        return candidates


def normalize_search_query(query: str) -> str | None:
    normalized = " ".join(query.split()).strip()
    if len(normalized) < MIN_QUERY_LENGTH or normalized.startswith("/"):
        return None

    return normalized[:MAX_QUERY_LENGTH]


def _extract_preview_url(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None

    results = payload.get("results")
    if not isinstance(results, list):
        return None

    for result in results:
        if isinstance(result, dict):
            preview = result.get("previewUrl")
            if isinstance(preview, str) and preview.startswith("http"):
                return preview

    return None


def _extract_matching_genre(
    payload: object,
    *,
    artist: str,
    title: str,
) -> str | None:
    if not isinstance(payload, dict):
        return None

    results = payload.get("results")
    if not isinstance(results, list):
        return None

    artist_key = _metadata_match_key(artist)
    title_key = _metadata_match_key(title)
    if not artist_key or not title_key:
        return None

    for result in results:
        if not isinstance(result, dict):
            continue
        if _metadata_match_key(result.get("artistName")) != artist_key:
            continue
        candidate_titles = (
            result.get("trackName"),
            result.get("collectionName"),
        )
        if title_key not in {
            key for value in candidate_titles if (key := _metadata_match_key(value))
        }:
            continue
        genre = result.get("primaryGenreName")
        if isinstance(genre, str) and genre.strip():
            return genre.strip()

    return None


def _metadata_match_key(value: object) -> str:
    """Compare metadata across punctuation and Unicode accent variants."""
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKD", value).casefold()
    return "".join(
        character
        for character in normalized
        if character.isalnum() and not unicodedata.combining(character)
    )


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
        preview = result.get("previewUrl")
        candidates.append(
            SearchCandidate(
                url=url,
                title=str(
                    result.get("trackName") or result.get("collectionName") or ""
                ),
                artist=str(result.get("artistName") or ""),
                artwork_url=artwork if isinstance(artwork, str) else None,
                preview_url=preview if isinstance(preview, str) else None,
                album=(
                    str(result["collectionName"])
                    if result.get("trackName") and result.get("collectionName")
                    else None
                ),
                year=(
                    str(result["releaseDate"])[:4]
                    if str(result.get("releaseDate") or "")[:4].isdigit()
                    else None
                ),
                kind=(
                    "album"
                    if result.get("wrapperType") == "collection"
                    else str(result.get("kind") or "track")
                ),
            )
        )
        if len(candidates) >= MAX_CANDIDATES:
            break

    return candidates
