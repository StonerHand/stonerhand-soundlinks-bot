from __future__ import annotations

import asyncio
import secrets
import time

from music_links_bot.bot_storage import remember_bounded
from music_links_bot.formatter import pick_track_emoji
from music_links_bot.kvstore import KVStore
from music_links_bot.models import TrackMatch
from music_links_bot.publication_state import release_fingerprint

MAX_HISTORY_ITEMS = 10
HISTORY_TTL_SECONDS = 90 * 24 * 3600
MAX_MEMORY_USERS = 500


async def _acquire_kv_lock(
    kv: KVStore, key: str, *, tries: int = 5, delay: float = 0.1, ttl: int = 10
) -> str | None:
    owner = secrets.token_hex(12)
    for attempt in range(tries):
        if await kv.set(key, owner, ttl_seconds=ttl, nx=True):
            return owner
        if attempt < tries - 1:
            await asyncio.sleep(delay)
    return None


async def record_history(
    context, user_id: int, track: TrackMatch, source_url: str
) -> None:
    entry = {
        "artist": track.artist,
        "title": track.title,
        "kind": track.kind,
        "emoji": pick_track_emoji(track),
        "artwork": track.thumbnail_url,
        "source_url": source_url,
        "ts": int(time.time()),
    }
    fingerprint = release_fingerprint(track.artist, track.title)
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    lock_key = f"hist:lock:{user_id}"
    lock_owner = await _acquire_kv_lock(kv, lock_key) if kv is not None else None
    if kv is not None and lock_owner is None:
        return
    try:
        items = await load_history_items(context, user_id)
        items = [
            item
            for item in items
            if release_fingerprint(
                str(item.get("artist") or ""), str(item.get("title") or "")
            )
            != fingerprint
        ]
        items = [entry, *items][:MAX_HISTORY_ITEMS]
        histories: dict = context.application.bot_data.setdefault("bot_history", {})
        remember_bounded(histories, user_id, items, max_size=MAX_MEMORY_USERS)
        if kv is not None:
            await kv.set_json(f"hist:{user_id}", items, ttl_seconds=HISTORY_TTL_SECONDS)
    finally:
        if lock_owner is not None and kv is not None:
            await kv.delete_if_value(lock_key, lock_owner)


async def load_history_items(context, user_id: int) -> list[dict]:
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        items = await kv.get_json(f"hist:{user_id}")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)][
                :MAX_HISTORY_ITEMS
            ]
    histories: dict = context.application.bot_data.setdefault("bot_history", {})
    return list(histories.get(user_id) or [])
