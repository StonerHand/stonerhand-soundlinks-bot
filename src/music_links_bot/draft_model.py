from __future__ import annotations

from dataclasses import asdict
import time
from typing import Any, TypedDict

from music_links_bot.constants import PLATFORM_LABELS
from music_links_bot.models import TrackMatch
from music_links_bot.release_presentation import normalize_preset

CURRENT_DRAFT_VERSION = 3


class TrackDraft(TypedDict, total=False):
    """Durable editor state shared by callbacks, queue and publications."""

    v: int
    type: str
    item: dict[str, Any]
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
    platforms: list[str]
    channel_template_applied: bool
    in_crate: bool
    crate_count: int
    deleted_at: int
    duplicate_record: dict[str, Any]
    created_at: int


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
    draft["created_at"] = int(value.get("created_at") or time.time())
    platforms = value.get("platforms")
    if isinstance(platforms, list):
        selected = [
            key
            for key in platforms[:6]
            if isinstance(key, str) and key in PLATFORM_LABELS
        ]
        draft["platforms"] = selected
    return draft
