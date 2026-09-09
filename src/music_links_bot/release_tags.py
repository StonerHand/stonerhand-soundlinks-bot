"""Deterministic tags: release type first, verified common genres second."""

from __future__ import annotations

import re

from music_links_bot.models import TrackMatch
from music_links_bot.release_preferences import (
    current_presentation,
    release_preference_key,
)
from music_links_bot.release_presentation import shared_collection_artist
from music_links_bot.text_utils import normalize_hashtag

MAX_AUTO_TAGS = 5
STRUCTURAL_TAGS = frozenset(
    {
        "#stonerhand",
        "#collection",
        "#track",
        "#album",
        "#ep",
        "#single",
        "#compilation",
        "#soundtrack",
        "#video",
        "#podcast",
        "#show",
        "#radio",
        "#playlist",
        "#artist",
    }
)
_GENRE_ALIASES = {"hiphoprap": "hiphop", "rhythmandblues": "rnb", "rnb": "rnb"}


def unique_tags(values, *, limit: int = MAX_AUTO_TAGS) -> list[str]:
    return list(
        dict.fromkeys(tag for value in values if (tag := normalize_hashtag(value)))
    )[:limit]


def genre_hashtags(genre: str | None, *, limit: int = 2) -> list[str]:
    if not isinstance(genre, str):
        return []
    genre = re.sub(r"hip[ -]?hop\s*/\s*rap", "hiphop", genre, flags=re.IGNORECASE)
    result = []
    for part in re.split(r"[/,;]", genre.replace("&", "n")):
        tag = normalize_hashtag(part)
        if not tag or tag in {"#music", "#музыка", "#unknown", "#other"}:
            continue
        tag = "#" + _GENRE_ALIASES.get(tag[1:], tag[1:])
        if tag not in result:
            result.append(tag)
    return result[:limit]


def release_type(track: TrackMatch) -> str:
    if track.kind in {"video", "podcast"}:
        return track.kind
    if track.kind == "album":
        return (
            track.release_format
            if track.release_format in {"ep", "single", "compilation", "soundtrack"}
            else "album"
        )
    return "track"


def suggested_track_tags(track: TrackMatch) -> list[str]:
    values = ["#stonerhand", "#" + release_type(track)]
    if track.kind == "song" and track.release_format == "single":
        values.append("#single")
    if track.kind == "podcast" and track.release_format == "show":
        values.append("#show")
    values.extend(genre_hashtags(track.genre))
    return unique_tags(values)


def build_auto_hashtags(track: TrackMatch) -> str:
    override = current_presentation.get().tags.get(release_preference_key(track))
    return " ".join(override if override is not None else suggested_track_tags(track))


def _common_genres(tracks: list[TrackMatch]) -> list[str]:
    if not tracks or any(
        track.kind not in {"song", "track", "album"} for track in tracks
    ):
        return []
    groups = []
    for track in tracks:
        saved = current_presentation.get().tags.get(release_preference_key(track))
        genres = (
            [tag for tag in saved if tag not in STRUCTURAL_TAGS]
            if saved is not None
            else genre_hashtags(track.genre)
        )
        # Missing metadata is not evidence that the other tracks' genre applies.
        if not genres:
            return []
        groups.append(genres)
    return [tag for tag in groups[0] if all(tag in group for group in groups[1:])][:2]


def build_collection_hashtags(tracks: list[TrackMatch]) -> str:
    values = ["#stonerhand", "#collection"]
    types = list(dict.fromkeys(release_type(track) for track in tracks))
    values.extend("#" + kind for kind in types[:2])
    values.extend(_common_genres(tracks))
    artist = shared_collection_artist(tracks)
    if artist and artist.casefold() not in {
        "various artists",
        "various",
        "разные исполнители",
    }:
        values.append(artist)
    return " ".join(unique_tags(values))


def build_mixed_collection_hashtags(
    tracks: list[TrackMatch],
    *,
    has_playlists: bool = False,
    has_artists: bool = False,
    has_radios: bool = False,
    has_videos: bool = True,
) -> str:
    values = ["#stonerhand", "#collection"]
    values.extend("#" + release_type(track) for track in tracks)
    values.extend(
        tag
        for enabled, tag in (
            (has_playlists, "#playlist"),
            (has_artists, "#artist"),
            (has_radios, "#radio"),
            (has_videos, "#video"),
        )
        if enabled
    )
    return " ".join(unique_tags(values))
