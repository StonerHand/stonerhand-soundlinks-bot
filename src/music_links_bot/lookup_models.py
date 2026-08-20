from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from music_links_bot.models import (
    ArtistMatch,
    PlaylistMatch,
    RadioMatch,
    TrackMatch,
    VideoMatch,
)
from music_links_bot.provider_registry import DEFAULT_PROVIDER_REGISTRY
from music_links_bot.url_utils import cache_key_for_url


@dataclass(slots=True)
class SourceStatus:
    source_url: str
    provider: str
    state: str
    label: str = ""
    retryable: bool = False
    reason: str = ""


@dataclass(slots=True)
class LookupBundle:
    tracks: list[TrackMatch]
    unavailable_urls: list[str]
    videos: list[VideoMatch]
    radios: list[RadioMatch]
    playlists: list[PlaylistMatch]
    artists: list[ArtistMatch]
    statuses: list[SourceStatus] = field(default_factory=list)

    @property
    def item_count(self) -> int:
        return sum(
            len(items)
            for items in (
                self.tracks,
                self.videos,
                self.radios,
                self.playlists,
                self.artists,
            )
        )

    @property
    def content_type_count(self) -> int:
        return sum(
            bool(items)
            for items in (
                self.tracks,
                self.videos,
                self.radios,
                self.playlists,
                self.artists,
            )
        )

    @property
    def successful_source_count(self) -> int:
        return sum(status.state == "success" for status in self.statuses)

    def is_complete_for(self, source_urls: list[str]) -> bool:
        expected = [cache_key_for_url(url) for url in source_urls]
        actual = [cache_key_for_url(status.source_url) for status in self.statuses]
        return (
            bool(expected)
            and actual == expected
            and all(status.state == "success" for status in self.statuses)
            and self.item_count == len(expected)
        )

    def is_negative_for(self, source_urls: list[str]) -> bool:
        expected = [cache_key_for_url(url) for url in source_urls]
        actual = [cache_key_for_url(status.source_url) for status in self.statuses]
        return (
            bool(expected)
            and actual == expected
            and self.item_count == 0
            and all(status.state == "not_found" for status in self.statuses)
        )


def unique_source_urls(source_urls: list[str]) -> list[str]:
    """Deduplicate tracking variants while preserving the user's order."""
    unique: list[str] = []
    seen: set[str] = set()
    for source_url in source_urls:
        key = cache_key_for_url(source_url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(source_url)
    return unique


def bundle_to_cache(bundle: LookupBundle) -> dict[str, Any]:
    return {
        "tracks": [asdict(item) for item in bundle.tracks],
        "unavailable_urls": list(bundle.unavailable_urls),
        "videos": [asdict(item) for item in bundle.videos],
        "radios": [asdict(item) for item in bundle.radios],
        "playlists": [asdict(item) for item in bundle.playlists],
        "artists": [asdict(item) for item in bundle.artists],
        "statuses": [asdict(item) for item in bundle.statuses],
    }


def bundle_from_cache(payload: dict) -> LookupBundle | None:
    try:
        return LookupBundle(
            tracks=[TrackMatch(**item) for item in payload.get("tracks", [])],
            unavailable_urls=[
                str(url) for url in payload.get("unavailable_urls", [])
            ],
            videos=[VideoMatch(**item) for item in payload.get("videos", [])],
            radios=[RadioMatch(**item) for item in payload.get("radios", [])],
            playlists=[
                PlaylistMatch(**item) for item in payload.get("playlists", [])
            ],
            artists=[ArtistMatch(**item) for item in payload.get("artists", [])],
            statuses=[
                SourceStatus(**item) for item in payload.get("statuses", [])
            ],
        )
    except (TypeError, ValueError):
        return None


def ensure_source_accounting(
    bundle: LookupBundle,
    source_urls: list[str],
) -> LookupBundle:
    """Guarantee exactly one visible status for every accepted source."""
    by_key = {
        cache_key_for_url(status.source_url): status for status in bundle.statuses
    }
    bundle.statuses = [
        by_key.get(cache_key_for_url(source_url))
        or SourceStatus(
            source_url=source_url,
            provider=DEFAULT_PROVIDER_REGISTRY.provider_for(source_url),
            state="unavailable",
            retryable=True,
            reason="provider_status_missing",
        )
        for source_url in source_urls
    ]
    bundle.unavailable_urls = [
        status.source_url
        for status in bundle.statuses
        if status.state == "unavailable"
    ]
    return bundle


def item_label(item: object) -> str:
    if item is None:
        return ""
    title = str(getattr(item, "title", "") or "")
    artist = str(
        getattr(item, "artist", "")
        or getattr(item, "author", "")
        or getattr(item, "station", "")
        or ""
    )
    return " — ".join(part for part in (artist, title) if part)[:120]


def sort_statuses(
    statuses: list[SourceStatus],
    source_urls: list[str],
) -> list[SourceStatus]:
    positions = {
        cache_key_for_url(url): index for index, url in enumerate(source_urls)
    }
    return sorted(
        statuses,
        key=lambda item: positions.get(cache_key_for_url(item.source_url), 10_000),
    )
