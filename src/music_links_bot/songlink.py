from __future__ import annotations

import asyncio
from dataclasses import asdict, fields
import re
from collections.abc import Mapping

import httpx

from music_links_bot.cache import TTLCache
from music_links_bot.constants import HTTP_USER_AGENT, PLATFORM_ALIASES
from music_links_bot.kvstore import KVStore
from music_links_bot.models import TrackMatch
from music_links_bot.url_utils import cache_key_for_url

HTTP_HEADERS = {"User-Agent": HTTP_USER_AGENT}
KV_TTL_SECONDS = 7 * 24 * 3600
MIN_COMPLETE_PLATFORM_COUNT = 4
_TRACK_FIELDS = {field.name for field in fields(TrackMatch)}


class SonglinkError(RuntimeError):
    """Base error for Song.link client failures."""


class SonglinkLookupError(SonglinkError):
    """Raised when a URL cannot be resolved to a track."""


class SonglinkClient:
    def __init__(
        self,
        *,
        user_countries: tuple[str, ...],
        api_key: str | None = None,
        timeout: float = 8.0,
        kv: KVStore | None = None,
    ) -> None:
        self._user_countries = user_countries
        self._api_key = api_key
        self._kv = kv
        self._client = httpx.AsyncClient(
            base_url="https://api.song.link/v1-alpha.1",
            headers=HTTP_HEADERS,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            timeout=httpx.Timeout(timeout, connect=3.0),
        )
        self._cache: TTLCache[TrackMatch] = TTLCache()
        self._inflight: dict[str, asyncio.Task[TrackMatch]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup_track(self, source_url: str) -> TrackMatch:
        cache_key = cache_key_for_url(source_url)
        cached_match = self._cache.get(cache_key)
        if cached_match is not None:
            return cached_match

        pending = self._inflight.get(cache_key)
        if pending is not None:
            return await asyncio.shield(pending)

        task = asyncio.create_task(self._lookup_and_cache(source_url, cache_key))
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
        self, cache_key: str, task: asyncio.Task[TrackMatch]
    ) -> None:
        """Forget completed single-flight tasks even if their waiter timed out."""
        if self._inflight.get(cache_key) is task:
            self._inflight.pop(cache_key, None)
        if task.done() and not task.cancelled():
            # Retrieve the exception so a caller cancellation cannot leave a
            # noisy "Task exception was never retrieved" warning behind.
            task.exception()

    async def _lookup_and_cache(self, source_url: str, cache_key: str) -> TrackMatch:
        shared_match = await self._get_shared_cache(cache_key)
        if shared_match is not None:
            self._cache.set(cache_key, shared_match)
            return shared_match

        countries = self._user_countries or ("US",)
        primary_result = await asyncio.gather(
            self._lookup_track_for_country(source_url, countries[0]),
            return_exceptions=True,
        )
        results: list[TrackMatch | BaseException] = list(primary_result)

        primary_match = primary_result[0]
        if len(countries) > 1 and (
            not isinstance(primary_match, TrackMatch)
            or len(primary_match.links) < MIN_COMPLETE_PLATFORM_COUNT
        ):
            # Most Song.link responses already contain every major platform.
            # Only fan out to extra regions when the primary response is sparse
            # or failed; this avoids multiplying upstream calls on cache misses.
            results.extend(
                await asyncio.gather(
                    *(
                        self._lookup_track_for_country(source_url, country)
                        for country in countries[1:]
                    ),
                    return_exceptions=True,
                )
            )
        matches = [result for result in results if isinstance(result, TrackMatch)]

        if not matches:
            service_error = next(
                (
                    result
                    for result in results
                    if isinstance(result, SonglinkError)
                    and not isinstance(result, SonglinkLookupError)
                ),
                None,
            )
            if service_error:
                raise service_error

            lookup_error = next(
                (result for result in results if isinstance(result, SonglinkLookupError)),
                None,
            )
            raise lookup_error or SonglinkLookupError("Song.link could not resolve the URL.")

        match = self._merge_matches(matches)
        self._cache.set(cache_key, match)
        await self._set_shared_cache(cache_key, match)
        return match

    async def _get_shared_cache(self, cache_key: str) -> TrackMatch | None:
        if self._kv is None:
            return None

        payload = await self._kv.get_json(f"sl:{cache_key}")
        if not isinstance(payload, dict):
            return None

        known_fields = {
            key: value for key, value in payload.items() if key in _TRACK_FIELDS
        }
        try:
            match = TrackMatch(**known_fields)
        except TypeError:
            return None

        if not match.title or not isinstance(match.links, dict):
            return None

        return match

    async def _set_shared_cache(self, cache_key: str, match: TrackMatch) -> None:
        if self._kv is None:
            return

        await self._kv.set_json(
            f"sl:{cache_key}",
            asdict(match),
            ttl_seconds=KV_TTL_SECONDS,
        )

    async def _lookup_track_for_country(self, source_url: str, user_country: str) -> TrackMatch:
        params = {
            "url": source_url,
            "userCountry": user_country,
        }
        if self._api_key:
            params["key"] = self._api_key

        try:
            response = await self._client.get("/links", params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if _is_transient_status(exc.response.status_code):
                raise SonglinkError("Song.link is unavailable right now.") from exc

            raise SonglinkLookupError("Song.link rejected the URL.") from exc
        except httpx.HTTPError as exc:
            raise SonglinkError("Song.link is unavailable right now.") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise SonglinkLookupError("Song.link returned an invalid response.") from exc

        entity_id = payload.get("entityUniqueId")
        entities = payload.get("entitiesByUniqueId")
        links = payload.get("linksByPlatform")

        if not entity_id or not isinstance(entities, Mapping) or not isinstance(links, Mapping):
            raise SonglinkLookupError("Song.link returned an unexpected response.")

        entity = entities.get(entity_id)
        if not isinstance(entity, Mapping):
            raise SonglinkLookupError("Track metadata is missing in Song.link response.")

        entity_type = self._normalize_entity_type(entity.get("type"))
        if entity_type not in {"song", "album", "podcast"}:
            raise SonglinkLookupError("The provided link does not point to a track, album or podcast.")

        title = str(entity.get("title", "")).strip()
        artist = str(
            entity.get("artistName")
            or entity.get("curatorName")
            or entity.get("ownerName")
            or ""
        ).strip()

        if not title or not artist:
            raise SonglinkLookupError("Track title or artist is missing in Song.link response.")

        resolved_links = self._extract_links(links)
        page_url = str(payload.get("pageUrl", "")).strip() or source_url
        release_year = self._extract_release_year(entity) or self._extract_release_year_from_entities(
            entities,
            entity_type,
        )
        release_format = self._extract_release_format(entity)
        thumbnail_url = self._extract_thumbnail_url(entity, entities, entity_type)
        return TrackMatch(
            title=title,
            artist=artist,
            links=resolved_links,
            page_url=page_url,
            release_year=release_year,
            kind=entity_type,
            release_format=release_format,
            thumbnail_url=thumbnail_url,
        )

    def _merge_matches(self, matches: list[TrackMatch]) -> TrackMatch:
        primary = matches[0]
        merged_links: dict[str, str] = {}

        for match in matches:
            merged_links.update(match.links)

        return TrackMatch(
            title=primary.title,
            artist=primary.artist,
            links=merged_links,
            page_url=primary.page_url or next(
                (match.page_url for match in matches if match.page_url),
                None,
            ),
            release_year=primary.release_year or next(
                (match.release_year for match in matches if match.release_year),
                None,
            ),
            kind=primary.kind,
            release_format=primary.release_format or next(
                (match.release_format for match in matches if match.release_format),
                None,
            ),
            thumbnail_url=primary.thumbnail_url or next(
                (match.thumbnail_url for match in matches if match.thumbnail_url),
                None,
            ),
        )

    def _extract_links(self, links_by_platform: Mapping[str, object]) -> dict[str, str]:
        resolved: dict[str, str] = {}

        for output_key, aliases in PLATFORM_ALIASES.items():
            for alias in aliases:
                raw_entry = links_by_platform.get(alias)
                if not isinstance(raw_entry, Mapping):
                    continue

                url = raw_entry.get("url")
                if isinstance(url, str) and url.strip():
                    resolved[output_key] = url.strip()
                    break

        return resolved

    def _normalize_entity_type(self, value: object) -> str:
        raw_type = str(value or "song").strip().lower()
        if raw_type in {"song", "track"}:
            return "song"

        if raw_type in {"album"}:
            return "album"

        if raw_type in {"podcast", "podcastepisode", "episode"}:
            return "podcast"

        return raw_type

    def _extract_release_year(self, entity: Mapping[str, object]) -> str | None:
        for field in ("releaseYear", "releaseDate", "datePublished"):
            value = entity.get(field)
            if value is None:
                continue

            match = re.search(r"\b(19|20)\d{2}\b", str(value))
            if match:
                return match.group(0)

        return None

    def _extract_release_year_from_entities(
        self,
        entities: Mapping[str, object],
        entity_type: str,
    ) -> str | None:
        for entity in entities.values():
            if not isinstance(entity, Mapping):
                continue

            current_type = self._normalize_entity_type(entity.get("type"))
            if current_type and current_type != entity_type:
                continue

            release_year = self._extract_release_year(entity)
            if release_year:
                return release_year

        return None

    def _extract_thumbnail_url(
        self,
        entity: Mapping[str, object],
        entities: Mapping[str, object],
        entity_type: str,
    ) -> str | None:
        thumbnail = str(entity.get("thumbnailUrl") or "").strip()
        if thumbnail.startswith("http"):
            return thumbnail

        for candidate in entities.values():
            if not isinstance(candidate, Mapping):
                continue

            candidate_type = self._normalize_entity_type(candidate.get("type"))
            if candidate_type and candidate_type != entity_type:
                continue

            thumbnail = str(candidate.get("thumbnailUrl") or "").strip()
            if thumbnail.startswith("http"):
                return thumbnail

        return None

    def _extract_release_format(self, entity: Mapping[str, object]) -> str | None:
        candidates = [
            entity.get("albumType"),
            entity.get("releaseType"),
            entity.get("productType"),
            entity.get("kind"),
            entity.get("subtitle"),
            entity.get("title"),
        ]

        for candidate in candidates:
            value = str(candidate or "").strip().lower()
            if not value:
                continue

            if re.search(r"\bep\b", value):
                return "ep"

            if re.search(r"\bsingle\b", value):
                return "single"

            if re.search(r"\balbum\b", value):
                return "album"

        return None


def _is_transient_status(status_code: int) -> bool:
    return status_code in {408, 429} or status_code >= 500
