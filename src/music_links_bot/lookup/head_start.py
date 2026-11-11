"""Work that begins as soon as a release is named, while the rest of its
lookup is still running: the genre search and, for a channel post, the cover."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar

from music_links_bot.core.models import TrackMatch

# Set by a flow that already knows a photo post will follow.
cover_head_start: ContextVar[Callable[[TrackMatch], None] | None] = ContextVar(
    "cover_head_start", default=None
)


def release_identified(bot_data: dict, track: TrackMatch) -> None:
    """A provider has named a release; its details may still be loading."""
    if track.genre is None and track.kind in {"song", "album"}:
        warm_genre = getattr(bot_data.get("search_client"), "warm_genre", None)
        if callable(warm_genre):
            warm_genre(track.artist, track.title)
    start_cover(track)


def start_cover(track: TrackMatch) -> None:
    start = cover_head_start.get()
    if start is not None:
        start(track)
