from __future__ import annotations

import re
from collections.abc import Mapping

import httpx

from music_links_bot.constants import PLATFORM_ALIASES
from music_links_bot.models import TrackMatch


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
        timeout: float = 15.0,
    ) -> None:
        self._user_countries = user_countries
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url="https://api.song.link/v1-alpha.1",
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup_track(self, source_url: str) -> TrackMatch:
        matches: list[TrackMatch] = []
        last_lookup_error: SonglinkLookupError | None = None

        for user_country in self._user_countries:
            try:
                matches.append(await self._lookup_track_for_country(source_url, user_country))
            except SonglinkLookupError as exc:
                last_lookup_error = exc

        if not matches:
            raise last_lookup_error or SonglinkLookupError("Song.link could not resolve the URL.")

        return self._merge_matches(matches)

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
            raise SonglinkLookupError("Song.link rejected the URL.") from exc
        except httpx.HTTPError as exc:
            raise SonglinkError("Song.link is unavailable right now.") from exc

        payload = response.json()
        entity_id = payload.get("entityUniqueId")
        entities = payload.get("entitiesByUniqueId")
        links = payload.get("linksByPlatform")

        if not entity_id or not isinstance(entities, Mapping) or not isinstance(links, Mapping):
            raise SonglinkLookupError("Song.link returned an unexpected response.")

        entity = entities.get(entity_id)
        if not isinstance(entity, Mapping):
            raise SonglinkLookupError("Track metadata is missing in Song.link response.")

        entity_type = str(entity.get("type", "")).lower() or "song"
        if entity_type not in {"song", "album"}:
            raise SonglinkLookupError("The provided link does not point to a track or album.")

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
        return TrackMatch(
            title=title,
            artist=artist,
            links=resolved_links,
            page_url=page_url,
            release_year=release_year,
            kind=entity_type,
            release_format=release_format,
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

            current_type = str(entity.get("type", "")).lower()
            if current_type and current_type != entity_type:
                continue

            release_year = self._extract_release_year(entity)
            if release_year:
                return release_year

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
