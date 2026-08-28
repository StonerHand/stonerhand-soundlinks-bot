from __future__ import annotations

import re
import unicodedata
from dataclasses import replace

from music_links_bot.models import TrackMatch
from music_links_bot.url_utils import (
    cache_key_for_url,
    direct_platform_links,
    is_direct_platform_url,
)

_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)


def _identity_text(value: str | None) -> str:
    """Normalize display metadata only for safe cross-service comparison."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return _NON_WORD_RE.sub(" ", normalized).strip()


def release_identity(track: TrackMatch) -> tuple[str, str, str]:
    return (
        _identity_text(track.artist),
        _identity_text(track.title),
        _identity_text(track.kind or "song"),
    )


def coalesce_equivalent_tracks(tracks: list[TrackMatch]) -> list[TrackMatch]:
    """Merge the same release resolved from several music services.

    Source accounting remains untouched in ``LookupBundle.statuses``. Only the
    presentation list is collapsed, so six service links for one song produce
    one card with the union of all available platform buttons.
    """
    merged: list[TrackMatch] = []
    for track in tracks:
        identity = release_identity(track)
        position = next(
            (
                index
                for index, current in enumerate(merged)
                if release_identity(current) == identity
                and _same_release_destination(current, track)
            ),
            None,
        )
        if not identity[0] or not identity[1] or position is None:
            merged.append(replace(track, links=direct_platform_links(track.links)))
            continue

        current = merged[position]
        links = direct_platform_links(current.links)
        for key, value in track.links.items():
            if not is_direct_platform_url(value):
                continue
            existing = links.get(key)
            if not existing:
                links[key] = value
        merged[position] = replace(
            current,
            links=links,
            page_url=current.page_url or track.page_url,
            thumbnail_url=current.thumbnail_url or track.thumbnail_url,
            release_year=current.release_year or track.release_year,
            release_format=current.release_format or track.release_format,
            genre=current.genre or track.genre,
        )
    return merged


def _same_release_destination(first: TrackMatch, second: TrackMatch) -> bool:
    if (
        first.page_url
        and second.page_url
        and cache_key_for_url(first.page_url) == cache_key_for_url(second.page_url)
    ):
        return True
    first_links = {
        key: value
        for key, value in first.links.items()
        if is_direct_platform_url(value)
    }
    second_links = {
        key: value
        for key, value in second.links.items()
        if is_direct_platform_url(value)
    }
    shared_platforms = set(first_links) & set(second_links)
    if any(
        cache_key_for_url(first_links[key]) == cache_key_for_url(second_links[key])
        for key in shared_platforms
    ):
        return True
    # A Spotify URL and an Apple Music URL with matching metadata are a safe
    # cross-service match. Two different URLs from the same service are not.
    return bool(first_links and second_links and not shared_platforms)
