from __future__ import annotations

from typing import Final

from music_links_bot.models import TrackMatch

PRESENTATION_VERSION: Final = 1
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


def release_emoji(track: TrackMatch) -> str:
    if track.kind == "video":
        return "📺"
    if track.kind == "podcast":
        return "🎙️"
    if track.kind == "album":
        return "💿"
    return "🎧"


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


def build_release_presentation(
    track: TrackMatch,
    draft: dict,
    *,
    hashtags: str,
    platform_keys: list[str],
) -> dict:
    """Stable presentation contract shared by the bot and Telegram Mini App."""
    preset = normalize_preset(draft.get("preset"), draft)
    mode = "longread" if preset == "longread" else "card"
    return {
        "version": PRESENTATION_VERSION,
        "preset": preset,
        "mode": mode,
        "artist": track.artist,
        "title": track.title,
        "emoji": release_emoji(track),
        "show_cover": preset != "minimal" and bool(track.thumbnail_url),
        "show_hashtags": bool(draft.get("hashtags") and hashtags),
        "hashtags": hashtags,
        "platform_keys": platform_keys,
    }
