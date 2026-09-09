"""User-scoped rendering preferences shared by direct and inline publications."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from types import MappingProxyType

from music_links_bot.models import TrackMatch
from music_links_bot.text_utils import normalize_hashtag
from music_links_bot.url_utils import cache_key_for_url

MAX_RELEASE_PREFERENCES = 60


@dataclass(frozen=True, slots=True)
class PresentationPreferences:
    layout: str = "column"
    grouping: str = "none"
    artwork: str = "native"
    tags: Mapping[str, list[str]] = field(default_factory=lambda: MappingProxyType({}))
    annotations: Mapping[str, dict[str, str]] = field(
        default_factory=lambda: MappingProxyType({})
    )


_DEFAULT_PRESENTATION = PresentationPreferences()
current_presentation: ContextVar[PresentationPreferences] = ContextVar(
    "publication_preferences", default=_DEFAULT_PRESENTATION
)


def release_preference_key(track: TrackMatch) -> str:
    source = track.page_url or next(
        (track.links[key] for key in sorted(track.links) if track.links[key]), ""
    )
    identity = cache_key_for_url(source) if source else f"{track.artist}|{track.title}"
    return hashlib.sha256(f"{track.kind}|{identity}".encode()).hexdigest()[:24]


def normalize_release_tags(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, tags in list(value.items())[-MAX_RELEASE_PREFERENCES:]:
        if not isinstance(key, str) or len(key) != 24 or not isinstance(tags, list):
            continue
        result[key] = list(
            dict.fromkeys(
                tag for value in tags[:12] if (tag := normalize_hashtag(value))
            )
        )[:5]
    return result


def normalize_annotations(value: object) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in list(value.items())[-MAX_RELEASE_PREFERENCES:]:
        if not isinstance(key, str) or len(key) != 24 or not isinstance(item, dict):
            continue
        result[key] = {
            name: " ".join(str(item.get(name) or "").split())[:limit]
            for name, limit in (("note", 140), ("section", 64))
        }
    return result


def preferences_from_session(session) -> PresentationPreferences:
    return PresentationPreferences(
        layout=getattr(session, "collection_layout", "column"),
        grouping=getattr(session, "collection_grouping", "none"),
        artwork=getattr(session, "default_artwork", "native"),
        tags=normalize_release_tags(getattr(session, "release_tags", {})),
        annotations=normalize_annotations(
            getattr(session, "collection_annotations", {})
        ),
    )


@contextmanager
def presentation_context(preferences: PresentationPreferences | None = None):
    token = current_presentation.set(preferences or PresentationPreferences())
    try:
        yield
    finally:
        current_presentation.reset(token)


def remember_release_tags(session, track: TrackMatch, tags: list[str]) -> None:
    key = release_preference_key(track)
    session.release_tags.pop(key, None)
    session.release_tags[key] = tags
    session.release_tags = normalize_release_tags(session.release_tags)
    current_presentation.set(preferences_from_session(session))
