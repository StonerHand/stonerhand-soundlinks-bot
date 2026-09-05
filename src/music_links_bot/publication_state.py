from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from music_links_bot.kvstore import KVStore
from music_links_bot.models import TrackMatch
from music_links_bot.url_utils import cache_key_for_url, direct_platform_links


def release_fingerprint(artist: str, title: str) -> str:
    normalized = f"{artist}|{title}".casefold()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"posted:{digest}"


def publication_key(context, track: TrackMatch, target=None) -> str:
    destination = (
        target or context.application.bot_data.get("publish_chat_id") or "stonerhand"
    )
    links = direct_platform_links(track.links)
    source = next(
        (
            links[key]
            for key in ("spotify", "appleMusic", "soundcloud", "youtubeMusic")
            if key in links
        ),
        next(iter(links.values()), ""),
    )
    identity = [
        str(destination).lstrip("@").casefold(),
        track.kind.casefold(),
        " ".join(track.artist.casefold().split()),
        " ".join(track.title.casefold().split()),
        cache_key_for_url(source),
    ]
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False).encode()
    ).hexdigest()[:32]
    return f"posted:v3:{digest}"


async def find_posted_date(context, track: TrackMatch) -> str | None:
    record = await find_posted_record(context, track)
    if record is None:
        return None
    return str(record.get("date") or "") or None


async def find_posted_record(context, track: TrackMatch) -> dict[str, Any] | None:
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is None:
        return None
    raw = await kv.get(publication_key(context, track))
    if not raw:
        # Read the pre-v3 key during the migration window. New records use the
        # stronger channel/kind/source identity below.
        raw = await kv.get(release_fingerprint(track.artist, track.title))
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        # Records written before v2 contained only a display date.
        return {"date": str(raw)}
    return payload if isinstance(payload, dict) else {"date": str(raw)}


async def mark_posted(
    context,
    track: TrackMatch,
    *,
    message: object | None = None,
    target: int | str | None = None,
) -> None:
    """Persist duplicate-guard state before a serverless invocation can freeze."""
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is None:
        return

    posted_date = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    message_id = getattr(message, "message_id", None)
    target_value = target
    if target_value is None and message is not None:
        chat = getattr(message, "chat", None)
        target_value = getattr(chat, "username", None) or getattr(chat, "id", None)
    url = _message_url(target_value, message_id)
    await kv.set_json(
        publication_key(context, track, target_value),
        {
            "date": posted_date,
            "chat_id": target_value,
            "message_id": message_id,
            "url": url,
        },
    )


def _message_url(target: int | str | None, message_id: object) -> str | None:
    if not isinstance(message_id, int) or message_id <= 0 or target is None:
        return None
    username = str(target).lstrip("@")
    if username and not username.lstrip("-").isdigit():
        return f"https://t.me/{username}/{message_id}"
    return None
