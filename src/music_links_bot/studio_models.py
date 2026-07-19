from __future__ import annotations

from music_links_bot.constants import PLATFORM_LABELS
from music_links_bot.formatter import pick_track_emoji
from music_links_bot.models import TrackMatch
from music_links_bot.publication_state import release_fingerprint
from music_links_bot.text_utils import normalize_hashtag

MAX_CUSTOM_CTA_LENGTH = 200
MAX_CUSTOM_TAGS = 8
MAX_CRATE_ITEMS = 10


def is_web_url(value: object) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def compact_track_data(item: dict) -> dict:
    links = item.get("links") if isinstance(item.get("links"), dict) else {}
    page_url = item.get("page_url")
    if not is_web_url(page_url):
        page_url = None
    if not page_url:
        page_url = next((value for value in links.values() if is_web_url(value)), None)
    return {
        "title": str(item.get("title") or ""),
        "artist": str(item.get("artist") or ""),
        "kind": str(item.get("kind") or "song"),
        "release_format": item.get("release_format") or None,
        "genre": item.get("genre") or None,
        "page_url": page_url or None,
        "release_year": item.get("release_year") or None,
        "thumbnail_url": item.get("thumbnail_url") or None,
    }


def track_from_item(item: dict) -> TrackMatch:
    return TrackMatch(
        title=str(item.get("title") or ""),
        artist=str(item.get("artist") or ""),
        links=item.get("links") if isinstance(item.get("links"), dict) else {},
        page_url=item.get("page_url"),
        release_year=item.get("release_year"),
        kind=str(item.get("kind") or "song"),
        release_format=item.get("release_format"),
        thumbnail_url=item.get("thumbnail_url"),
        genre=item.get("genre"),
    )


def coerce_crate_items(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    items: list[dict] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        compact = compact_track_data(entry)
        if not (compact["artist"] or compact["title"]):
            continue
        fingerprint = release_fingerprint(compact["artist"], compact["title"])
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        items.append(compact)
        if len(items) >= MAX_CRATE_ITEMS:
            break
    return items


def crate_view(items: list[dict]) -> dict:
    views = []
    for item in items:
        compact = compact_track_data(item)
        views.append(
            {
                "artist": compact["artist"],
                "title": compact["title"],
                "emoji": pick_track_emoji(track_from_item(compact)),
                "artwork": compact["thumbnail_url"],
                "data": compact,
            }
        )
    return {"ok": True, "count": len(items), "max": MAX_CRATE_ITEMS, "items": views}


def apply_draft_patch(draft: dict, body: dict) -> None:
    for flag in ("hashtags", "quote", "large_preview", "as_photo"):
        if isinstance(body.get(flag), bool):
            draft[flag] = body[flag]
    if "cta" in body:
        cta = body.get("cta")
        if isinstance(cta, str) and cta.strip():
            draft["custom_cta"] = " ".join(cta.split())[:MAX_CUSTOM_CTA_LENGTH]
        else:
            draft.pop("custom_cta", None)
    if "tags" in body:
        tags = body.get("tags")
        if isinstance(tags, list):
            draft["custom_tags"] = [
                tag
                for tag in (normalize_hashtag(value) for value in tags[:MAX_CUSTOM_TAGS])
                if tag
            ]
        else:
            draft.pop("custom_tags", None)
    if "platforms" in body:
        platforms = body.get("platforms")
        selection = [
            key
            for key in (platforms if isinstance(platforms, list) else [])
            if isinstance(key, str) and key in PLATFORM_LABELS
        ]
        if selection:
            draft["platforms"] = selection
        else:
            draft.pop("platforms", None)


def top_entries(value: object, *, limit: int = 8) -> list[dict]:
    if not isinstance(value, dict):
        return []
    entries = [entry for entry in value.values() if isinstance(entry, dict)]
    entries.sort(key=lambda item: int(item.get("count") or 0), reverse=True)
    return [
        {"label": str(entry.get("label") or "?"), "count": int(entry.get("count") or 0)}
        for entry in entries[:limit]
    ]


def upscale_artwork(url: str | None) -> str | None:
    if not url:
        return None
    return url.replace("100x100", "300x300").replace("60x60", "300x300")
