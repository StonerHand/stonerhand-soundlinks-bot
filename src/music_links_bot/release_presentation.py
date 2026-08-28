from __future__ import annotations

import re
from typing import Final

from music_links_bot.models import TrackMatch

PRESET_ORDER: Final = ("minimal", "cover", "longread")
LEGACY_PRESET_ALIASES: Final = {
    "clean": "cover",
    "editorial": "minimal",
    "poster": "cover",
}
PRESET_PROFILES: Final = {
    "minimal": {
        "large_preview": False,
        "as_photo": False,
        "publication_mode": "card",
    },
    "cover": {
        "large_preview": True,
        "as_photo": False,
        "publication_mode": "card",
    },
    "longread": {
        "large_preview": True,
        "as_photo": False,
        "publication_mode": "longread",
    },
}

_REMASTER_SUFFIX: Final = re.compile(
    r"(?:\s*[-–—]\s*|\s*\()"
    r"(?:(?:19|20)\d{2}\s+)?re-?master(?:ed)?"
    r"(?:\s+(?:19|20)\d{2})?\)?$",
    re.IGNORECASE,
)


def release_emoji(track: TrackMatch) -> str:
    if track.kind == "video":
        return "📺"
    if track.kind == "podcast":
        return "🎙️"
    if track.kind == "album":
        return "💿"
    return "🎧"


def compact_release_title(value: str) -> str:
    """Hide provider remaster suffixes without changing stored metadata."""
    title = value.strip()
    compact = _REMASTER_SUFFIX.sub("", title).strip()
    return compact or title


def shared_collection_artist(tracks: list[TrackMatch]) -> str | None:
    """Return the display artist when every collection item uses the same one."""
    if len(tracks) < 2:
        return None
    artists = [track.artist.strip() for track in tracks]
    if not all(artists):
        return None
    return artists[0] if len({artist.casefold() for artist in artists}) == 1 else None


def normalize_preset(value: object, draft: dict | None = None) -> str:
    raw = str(value or "").casefold()
    if raw in PRESET_ORDER:
        return raw
    if draft and draft.get("publication_mode") == "longread":
        return "longread"
    if raw in LEGACY_PRESET_ALIASES:
        return LEGACY_PRESET_ALIASES[raw]
    if draft and not draft.get("large_preview", True):
        return "minimal"
    return "cover"


def apply_preset(draft: dict, value: object) -> str:
    preset = normalize_preset(value, draft)
    draft["preset"] = preset
    draft.update(PRESET_PROFILES[preset])
    return preset
