from __future__ import annotations

import asyncio
import unicodedata
from collections.abc import Mapping

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.constants import HTTP_USER_AGENT
from music_links_bot.url_utils import cache_key_for_url, spotify_url_type

MUSICBRAINZ_CACHE_TTL_SECONDS = 7 * 24 * 3600
MUSICBRAINZ_MISS_TTL_SECONDS = 6 * 3600
MUSICBRAINZ_REQUEST_INTERVAL_SECONDS = 1.05
MUSICBRAINZ_MIN_SCORE = 95


class MusicBrainzLookupError(RuntimeError):
    """Raised when MusicBrainz cannot be queried safely."""


class MusicBrainzClient:
    """Resolve exact MusicBrainz URL relations to direct Spotify releases.

    MusicBrainz is deliberately used as a strict enrichment source, not as a
    fuzzy replacement for the user's release. A Spotify URL is accepted only
    when both artist and title match the selected Apple result exactly.
    """

    def __init__(self, *, timeout: float = 4.0) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://musicbrainz.org/ws/2",
            headers={"User-Agent": HTTP_USER_AGENT, "Accept": "application/json"},
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
            timeout=httpx.Timeout(timeout, connect=3.0),
        )
        self._cache: TTLCache[str] = TTLCache(ttl_seconds=MUSICBRAINZ_CACHE_TTL_SECONDS)
        self._miss_cache: TTLCache[bool] = TTLCache(
            ttl_seconds=MUSICBRAINZ_MISS_TTL_SECONDS
        )
        self._inflight: dict[str, asyncio.Task[str | None]] = {}
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def aclose(self) -> None:
        pending = list(self._inflight.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._inflight.clear()
        await self._client.aclose()

    async def lookup_spotify_release(
        self,
        artist: str,
        title: str,
        *,
        kind: str = "song",
    ) -> str | None:
        entity_type = "release-group" if kind == "album" else "recording"
        expected_spotify_type = "album" if kind == "album" else "track"
        artist_key = _match_key(artist)
        title_key = _match_key(title)
        if not artist_key or not title_key:
            return None

        cache_key = f"{entity_type}:{artist_key}:{title_key}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        if self._miss_cache.get(cache_key):
            return None

        pending = self._inflight.get(cache_key)
        if pending is not None:
            return await pending

        task = asyncio.create_task(
            self._lookup_and_cache(
                cache_key=cache_key,
                artist=artist,
                title=title,
                entity_type=entity_type,
                expected_spotify_type=expected_spotify_type,
            )
        )
        self._inflight[cache_key] = task
        task.add_done_callback(
            lambda completed, key=cache_key: self._finish_inflight(key, completed)
        )
        try:
            return await task
        finally:
            if task.done():
                self._finish_inflight(cache_key, task)

    def _finish_inflight(
        self,
        cache_key: str,
        task: asyncio.Task[str | None],
    ) -> None:
        if self._inflight.get(cache_key) is task:
            self._inflight.pop(cache_key, None)
        if task.done() and not task.cancelled():
            task.exception()

    async def _lookup_and_cache(
        self,
        *,
        cache_key: str,
        artist: str,
        title: str,
        entity_type: str,
        expected_spotify_type: str,
    ) -> str | None:
        entity_id = await self._find_exact_entity_id(
            artist=artist,
            title=title,
            entity_type=entity_type,
        )
        if entity_id is None:
            self._miss_cache.set(cache_key, True)
            return None

        payload = await self._get_json(
            f"/{entity_type}/{entity_id}",
            params={"inc": "url-rels", "fmt": "json"},
        )
        spotify_url = _extract_spotify_url(
            payload,
            expected_type=expected_spotify_type,
        )
        if spotify_url is None:
            self._miss_cache.set(cache_key, True)
            return None

        self._cache.set(cache_key, spotify_url)
        return spotify_url

    async def _find_exact_entity_id(
        self,
        *,
        artist: str,
        title: str,
        entity_type: str,
    ) -> str | None:
        title_field = "releasegroup" if entity_type == "release-group" else "recording"
        result_field = (
            "release-groups" if entity_type == "release-group" else "recordings"
        )
        query = (
            f'artist:"{_escape_lucene_phrase(artist)}" AND '
            f'{title_field}:"{_escape_lucene_phrase(title)}"'
        )
        payload = await self._get_json(
            f"/{entity_type}",
            params={"query": query, "fmt": "json", "limit": 5},
        )
        return _extract_exact_entity_id(
            payload,
            result_field=result_field,
            artist=artist,
            title=title,
        )

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str | int],
    ) -> Mapping[str, object]:
        for attempt in range(2):
            retry = False
            async with self._request_lock:
                loop = asyncio.get_running_loop()
                wait_seconds = MUSICBRAINZ_REQUEST_INTERVAL_SECONDS - (
                    loop.time() - self._last_request_at
                )
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                try:
                    response = await self._client.get(path, params=params)
                    response.raise_for_status()
                    payload = response.json()
                except httpx.HTTPStatusError as exc:
                    retry = attempt == 0 and _is_transient_status(
                        exc.response.status_code
                    )
                    if not retry:
                        raise MusicBrainzLookupError(
                            "MusicBrainz metadata is unavailable."
                        ) from exc
                except (httpx.HTTPError, ValueError) as exc:
                    raise MusicBrainzLookupError(
                        "MusicBrainz metadata is unavailable."
                    ) from exc
                finally:
                    self._last_request_at = loop.time()

            if retry:
                continue
            if not isinstance(payload, Mapping):
                raise MusicBrainzLookupError("MusicBrainz returned invalid metadata.")
            return payload

        raise MusicBrainzLookupError("MusicBrainz metadata is unavailable.")


def _escape_lucene_phrase(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _match_key(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKD", value).casefold()
    return "".join(
        character
        for character in normalized
        if character.isalnum() and not unicodedata.combining(character)
    )


def _extract_exact_entity_id(
    payload: Mapping[str, object],
    *,
    result_field: str,
    artist: str,
    title: str,
) -> str | None:
    results = payload.get(result_field)
    if not isinstance(results, list):
        return None

    expected_artist = _match_key(artist)
    expected_title = _match_key(title)
    for result in results:
        if not isinstance(result, Mapping):
            continue
        try:
            score = int(str(result.get("score") or "0"))
        except ValueError:
            continue
        if score < MUSICBRAINZ_MIN_SCORE:
            continue
        if _match_key(result.get("title")) != expected_title:
            continue
        if expected_artist not in _artist_credit_keys(result.get("artist-credit")):
            continue
        entity_id = result.get("id")
        if isinstance(entity_id, str) and entity_id:
            return entity_id
    return None


def _artist_credit_keys(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()

    individual_names: list[str] = []
    credited_parts: list[str] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            continue
        artist = entry.get("artist")
        credited_name = entry.get("name")
        if not isinstance(credited_name, str) and isinstance(artist, Mapping):
            credited_name = artist.get("name")
        if not isinstance(credited_name, str) or not credited_name:
            continue
        individual_names.append(credited_name)
        credited_parts.append(credited_name)
        join_phrase = entry.get("joinphrase")
        if isinstance(join_phrase, str):
            credited_parts.append(join_phrase)

    keys = {_match_key(name) for name in individual_names}
    if credited_parts:
        keys.add(_match_key("".join(credited_parts)))
    return {key for key in keys if key}


def _extract_spotify_url(
    payload: Mapping[str, object],
    *,
    expected_type: str,
) -> str | None:
    relations = payload.get("relations")
    if not isinstance(relations, list):
        return None

    for relation in relations:
        if not isinstance(relation, Mapping):
            continue
        url_data = relation.get("url")
        if not isinstance(url_data, Mapping):
            continue
        resource = url_data.get("resource")
        if not isinstance(resource, str):
            continue
        clean_url = cache_key_for_url(resource)
        if spotify_url_type(clean_url) == expected_type:
            return clean_url
    return None


def _is_transient_status(status_code: int) -> bool:
    return status_code in {408, 429} or status_code >= 500
