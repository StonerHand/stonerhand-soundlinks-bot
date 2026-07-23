from __future__ import annotations

from music_links_bot.constants import PLATFORM_BUTTON_STYLES, PLATFORM_LABELS
from music_links_bot.formatter import build_auto_hashtags, pick_track_emoji
from music_links_bot.models import TrackMatch
from music_links_bot.phrases import pick_phrase


def build_draft_response(
    draft_id: str,
    draft: dict,
    *,
    is_admin: bool,
    ttl_seconds: int,
) -> dict:
    """Convert an internal draft into the stable public Studio contract."""
    track = TrackMatch(**draft["item"])
    cta_key = {
        "album": "album_cta",
        "podcast": "podcast_cta",
    }.get(track.kind, "track_cta")
    custom_cta = draft.get("custom_cta")
    custom_tags = draft.get("custom_tags")

    available = [key for key in PLATFORM_LABELS if track.links.get(key)]
    selection = [
        key
        for key in (draft.get("platforms") or [])
        if isinstance(key, str) and key in available
    ]
    if selection:
        ordered = [*selection, *(key for key in available if key not in selection)]
        enabled = set(selection)
    else:
        ordered = available
        enabled = set(available)

    platforms = [
        {
            "key": platform_key,
            "label": PLATFORM_LABELS[platform_key],
            "url": track.links[platform_key],
            "style": PLATFORM_BUTTON_STYLES.get(platform_key, "primary"),
            "enabled": platform_key in enabled,
        }
        for platform_key in ordered
    ]
    auto_hashtags = build_auto_hashtags(track)
    hashtags = (
        " ".join(custom_tags)
        if isinstance(custom_tags, list)
        else auto_hashtags
    )
    return {
        "ok": True,
        "draft_id": draft_id,
        "ttl": ttl_seconds,
        "flags": {
            "hashtags": bool(draft.get("hashtags")),
            "quote": bool(draft.get("quote")),
            "large_preview": bool(draft.get("large_preview")),
            "as_photo": bool(draft.get("as_photo")),
            "has_prefix": bool(draft.get("prefix")),
        },
        "can_publish": bool(is_admin and draft.get("can_publish", True)),
        "release": {
            "artist": track.artist,
            "title": track.title,
            "kind": track.kind,
            "emoji": pick_track_emoji(track),
            "year": track.release_year,
            "genre": track.genre,
            "artwork": track.thumbnail_url,
            "page_url": track.page_url,
            "preview": draft.get("preview"),
            "preview_pending": bool(draft.get("preview_pending")),
            "cta": custom_cta
            or pick_phrase(cta_key, f"{track.artist}:{track.title}:{track.kind}"),
            "cta_custom": bool(custom_cta),
            "hashtags": hashtags,
            "auto_hashtags": auto_hashtags,
            "tags_custom": isinstance(custom_tags, list),
            "platforms": platforms,
        },
    }
