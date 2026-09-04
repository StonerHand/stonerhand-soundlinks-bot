from __future__ import annotations

import asyncio
import logging
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.constants import HTTP_USER_AGENT
from music_links_bot.models import TrackMatch
from music_links_bot.musicbrainz import MusicBrainzClient, MusicBrainzLookupError
from music_links_bot.release_hubs import canonical_release_hub_url
from music_links_bot.url_utils import cache_key_for_url, normalize_host

LOGGER = logging.getLogger(__name__)
MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 120
MAX_CANDIDATES = 3
GENRE_SEARCH_LIMIT = 12
SPOTIFY_ENRICHMENT_TIMEOUT_SECONDS = 5.0


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

    The API is public and keyless. Returned Apple Music URLs normally continue
    through Song.link; verified iTunes metadata remains a single-platform
    fallback when the universal resolver is unavailable.
    """

    def __init__(
        self,
        *,
        timeout: float = 6.0,
        country: str = "US",
        musicbrainz_client: MusicBrainzClient | None = None,
    ) -> None:
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
        self._candidate_cache: TTLCache[SearchCandidate] = TTLCache(
            ttl_seconds=6 * 3600
        )
        self._inflight: dict[str, asyncio.Task[list[SearchCandidate]]] = {}
        self._musicbrainz_client = musicbrainz_client or MusicBrainzClient(
            timeout=min(timeout, 4.0)
        )
        self._owns_musicbrainz_client = musicbrainz_client is None

    async def aclose(self) -> None:
        pending = list(self._inflight.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._inflight.clear()
        await self._client.aclose()
        if self._owns_musicbrainz_client:
            await self._musicbrainz_client.aclose()

    async def search_release_url(self, query: str) -> str:
        candidates = await self.search_release_candidates(query)
        return candidates[0].url

    async def lookup_release_fallback(self, source_url: str) -> TrackMatch | None:
        """Build a verified Apple Music card when Song.link cannot resolve it.

        Search results already carry enough provider metadata for a complete
        single-platform post.  A direct Apple URL may arrive in a later
        serverless invocation, so a cache miss is repaired through the keyless
        iTunes lookup endpoint instead of depending on process memory.
        """
        cache_key = cache_key_for_url(source_url)
        candidate = self._candidate_cache.get(cache_key)
        if candidate is None:
            candidate = await self._lookup_apple_candidate(source_url)
        if candidate is None:
            return None

        kind = "album" if candidate.kind == "album" else "song"
        links = {"appleMusic": candidate.url}
        page_url = None
        try:
            spotify_url = await asyncio.wait_for(
                self._musicbrainz_client.lookup_spotify_release(
                    candidate.artist,
                    candidate.title,
                    kind=kind,
                ),
                timeout=SPOTIFY_ENRICHMENT_TIMEOUT_SECONDS,
            )
        except (MusicBrainzLookupError, asyncio.TimeoutError):
            LOGGER.debug(
                "Exact Spotify relation lookup failed for %s — %s",
                candidate.artist,
                candidate.title,
                exc_info=True,
            )
        else:
            if spotify_url:
                links["spotify"] = spotify_url
                page_url = canonical_release_hub_url(
                    spotify_url,
                    release_kind=kind,
                )
        return TrackMatch(
            title=candidate.title,
            artist=candidate.artist,
            links=links,
            page_url=page_url,
            release_year=candidate.year,
            kind=kind,
            release_format=candidate.album if kind == "song" else None,
            thumbnail_url=_large_artwork_url(candidate.artwork_url),
        )

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
        self._remember_candidates(candidates)
        return candidates

    def _remember_candidates(self, candidates: list[SearchCandidate]) -> None:
        for candidate in candidates:
            self._candidate_cache.set(cache_key_for_url(candidate.url), candidate)

    async def _lookup_apple_candidate(self, source_url: str) -> SearchCandidate | None:
        item_id = _apple_item_id(source_url)
        if item_id is None:
            return None
        try:
            response = await self._client.get(
                "/lookup",
                params={"id": item_id, "country": self._country},
            )
            response.raise_for_status()
            candidates = _extract_release_candidates(response.json())
        except (httpx.HTTPError, ValueError):
            LOGGER.debug("Apple Music metadata fallback failed", exc_info=True)
            return None
        self._remember_candidates(candidates)
        return candidates[0] if candidates else None


def normalize_search_query(query: str) -> str | None:
    normalized = " ".join(query.split()).strip()
    if len(normalized) < MIN_QUERY_LENGTH or normalized.startswith("/"):
        return None

    return normalized[:MAX_QUERY_LENGTH]


def _apple_item_id(source_url: str) -> str | None:
    parsed = urlparse(source_url)
    if normalize_host(parsed.hostname) != "music.apple.com":
        return None
    query_id = (parse_qs(parsed.query).get("i") or [""])[0]
    path_id = next(
        (part for part in reversed(parsed.path.split("/")) if part.isdigit()),
        "",
    )
    item_id = query_id or path_id
    return item_id if item_id.isdigit() else None


def _large_artwork_url(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace("100x100bb", "1200x1200bb").replace("60x60bb", "1200x1200bb")


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
