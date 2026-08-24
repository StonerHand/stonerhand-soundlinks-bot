from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, TypedDict

from music_links_bot.constants import PLATFORM_LABELS
from music_links_bot.models import TrackMatch
from music_links_bot.release_presentation import normalize_preset

CURRENT_DRAFT_VERSION = 5


def _safe_int(value: object, *, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


class DraftTrackItem(TypedDict, total=False):
    title: str
    artist: str
    links: dict[str, str]
    page_url: str | None
    kind: str
    release_format: str | None
    release_year: int | None
    thumbnail_url: str | None


class DraftUndoState(TypedDict, total=False):
    expires_at: int
    values: dict[str, Any]


class TrackDraft(TypedDict, total=False):
    """Durable editor state shared by callbacks, queue and publications."""

    v: int
    type: str
    item: DraftTrackItem
    prefix: str
    hashtags: bool
    custom_tags: list[str]
    quote: bool
    large_preview: bool
    as_photo: bool
    chat_id: int
    lang: str
    search_query: str
    can_publish: bool
    preset: str
    publication_mode: str
    delivery_mode: str
    custom_cover_file_id: str
    custom_cover_unique_id: str
    source_audio_file_id: str
    source_audio_unique_id: str
    source_audio_duration: int
    platforms: list[str]
    channel_template_applied: bool
    in_crate: bool
    crate_count: int
    deleted_at: int
    duplicate_record: dict[str, Any]
    undo_state: DraftUndoState
    undo_stack: list[DraftUndoState]
    created_at: int
    intro_length: int
    intro_limit: int
    intro_truncated: bool
    last_template_available: bool
    last_template_applied: bool
    last_template: dict[str, Any]


def new_track_draft(
    track: TrackMatch,
    *,
    chat_id: int,
    lang: str,
    prefix: str = "",
    can_publish: bool = False,
    search_query: str = "",
) -> TrackDraft:
    return {
        "v": CURRENT_DRAFT_VERSION,
        "type": "track",
        "item": asdict(track),
        "prefix": prefix,
        "hashtags": True,
        "quote": bool(prefix),
        "large_preview": True,
        "as_photo": False,
        "chat_id": int(chat_id),
        "lang": "en" if lang == "en" else "ru",
        "search_query": search_query.strip()[:120],
        "can_publish": bool(can_publish),
        "preset": "cover",
        "publication_mode": "card",
        "delivery_mode": "auto",
        "intro_length": 0,
        "intro_limit": 0,
        "intro_truncated": False,
        "created_at": int(time.time()),
    }


def normalize_track_draft(value: object) -> TrackDraft | None:
    """Upgrade a stored draft without discarding newer optional fields."""
    if not isinstance(value, dict) or value.get("type") != "track":
        return None
    item = value.get("item")
    if not isinstance(item, dict):
        return None
    required = ("title", "artist", "links")
    if any(key not in item for key in required) or not isinstance(
        item.get("links"), dict
    ):
        return None

    draft: TrackDraft = dict(value)
    draft["v"] = CURRENT_DRAFT_VERSION
    draft["type"] = "track"
    draft["prefix"] = str(value.get("prefix") or "")[:3500]
    draft["hashtags"] = bool(value.get("hashtags", True))
    draft["quote"] = bool(value.get("quote", bool(draft["prefix"])))
    draft["large_preview"] = bool(value.get("large_preview", True))
    draft["as_photo"] = bool(value.get("as_photo", False))
    draft["lang"] = "en" if value.get("lang") == "en" else "ru"
    draft["search_query"] = str(value.get("search_query") or "")[:120]
    draft["can_publish"] = bool(value.get("can_publish", False))
    draft["preset"] = normalize_preset(value.get("preset"), value)
    draft["publication_mode"] = (
        "longread" if value.get("publication_mode") == "longread" else "card"
    )
    draft["delivery_mode"] = (
        "classic" if value.get("delivery_mode") == "classic" else "auto"
    )
    for field in (
        "custom_cover_file_id",
        "custom_cover_unique_id",
        "source_audio_file_id",
        "source_audio_unique_id",
    ):
        stored_value = value.get(field)
        if isinstance(stored_value, str) and stored_value:
            draft[field] = stored_value[:512]
        else:
            draft.pop(field, None)
    draft["source_audio_duration"] = max(
        0, _safe_int(value.get("source_audio_duration"))
    )
    draft["created_at"] = _safe_int(
        value.get("created_at"),
        default=int(time.time()),
    )
    draft["intro_length"] = max(0, _safe_int(value.get("intro_length")))
    draft["intro_limit"] = max(0, _safe_int(value.get("intro_limit")))
    draft["intro_truncated"] = bool(value.get("intro_truncated", False))
    draft["last_template_available"] = bool(value.get("last_template_available", False))
    draft["last_template_applied"] = bool(value.get("last_template_applied", False))
    last_template = value.get("last_template")
    if isinstance(last_template, dict):
        draft["last_template"] = dict(last_template)
    else:
        draft.pop("last_template", None)
    platforms = value.get("platforms")
    if isinstance(platforms, list):
        selected = [
            key
            for key in platforms[:6]
            if isinstance(key, str) and key in PLATFORM_LABELS
        ]
        draft["platforms"] = selected
    undo_state = value.get("undo_state")
    if isinstance(undo_state, dict):
        draft["undo_state"] = dict(undo_state)
    else:
        draft.pop("undo_state", None)
    undo_stack = value.get("undo_stack")
    if isinstance(undo_stack, list):
        draft["undo_stack"] = [
            dict(state) for state in undo_stack[-5:] if isinstance(state, dict)
        ]
    else:
        draft.pop("undo_stack", None)
    return draft
