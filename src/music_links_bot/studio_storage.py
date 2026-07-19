from __future__ import annotations

import asyncio
import secrets
import time

from music_links_bot.kvstore import KVStore
from music_links_bot.models import TrackMatch
from music_links_bot.formatter import pick_track_emoji
from music_links_bot.publication_state import release_fingerprint as _release_fingerprint
from music_links_bot.studio_models import (
    MAX_CRATE_ITEMS,
    coerce_crate_items as _coerce_crate_items,
    compact_track_data as _compact_track_data,
    crate_view as _crate_view,
)

MAX_HISTORY_ITEMS = 10
HISTORY_TTL_SECONDS = 90 * 24 * 3600
CRATE_TTL_SECONDS = 14 * 24 * 3600

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


async def _record_history(context, user_id: int, track: TrackMatch, source_url: str) -> None:
    entry = {
        "artist": track.artist,
        "title": track.title,
        "kind": track.kind,
        "emoji": pick_track_emoji(track),
        "artwork": track.thumbnail_url,
        "source_url": source_url,
        "ts": int(time.time()),
    }
    fingerprint = _release_fingerprint(track.artist, track.title)
    kv: KVStore | None = context.application.bot_data.get("kv_store")

    # Guard the load→modify→save against concurrent requests from the same user
    # racing on the shared Redis key (fallback: unlocked, single-instance memory).
    lock_key = f"hist:lock:{user_id}"
    lock_owner = await _acquire_kv_lock(kv, lock_key) if kv is not None else None
    if kv is not None and lock_owner is None:
        return  # history is non-critical; never risk clobbering a concurrent write
    try:
        items = await _load_history_items(context, user_id)
        items = [
            item
            for item in items
            if _release_fingerprint(str(item.get("artist") or ""), str(item.get("title") or ""))
            != fingerprint
        ]
        items = [entry, *items][:MAX_HISTORY_ITEMS]

        histories: dict = context.application.bot_data.setdefault("webapp_history", {})
        histories[user_id] = items
        if kv is not None:
            await kv.set_json(f"hist:{user_id}", items, ttl_seconds=HISTORY_TTL_SECONDS)
    finally:
        if lock_owner is not None and kv is not None:
            await kv.delete_if_value(lock_key, lock_owner)


async def _load_history_items(context, user_id: int) -> list[dict]:
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        items = await kv.get_json(f"hist:{user_id}")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)][:MAX_HISTORY_ITEMS]

    histories: dict = context.application.bot_data.setdefault("webapp_history", {})
    return list(histories.get(user_id) or [])


# The crate lives on the client: the Mini App keeps the authoritative list in
# CloudStorage and sends it with every request. The server still mirrors it into
# KV / instance memory as a convenience, but never depends on that copy being
# complete — which is what made collections lose every track but the last one on
# serverless (each warm instance saw only its own slice of memory).
_CRATE_ITEM_KEYS = (
    "title",
    "artist",
    "kind",
    "release_format",
    "genre",
    "page_url",
    "release_year",
    "thumbnail_url",
)


async def _load_crate(context, user_id: int) -> list[dict]:
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        items = await kv.get_json(f"crate:{user_id}")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)][:MAX_CRATE_ITEMS]

    crates: dict = context.application.bot_data.setdefault("webapp_crate", {})
    return list(crates.get(user_id) or [])


async def _save_crate(context, user_id: int, items: list[dict]) -> None:
    crates: dict = context.application.bot_data.setdefault("webapp_crate", {})
    crates[user_id] = items
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        await kv.set_json(f"crate:{user_id}", items, ttl_seconds=CRATE_TTL_SECONDS)


async def _crate_base_items(context, body: dict, user_id: int) -> list[dict]:
    """The authoritative crate for a request: the client's list when it sent one,
    otherwise the server-side mirror (Redis / instance memory)."""
    if "items" in body:
        return _coerce_crate_items(body.get("items"))
    return [_compact_track_data(item) for item in await _load_crate(context, user_id)]


async def _crate_response(context, user_id: int) -> dict:
    items = [_compact_track_data(item) for item in await _load_crate(context, user_id)]
    return _crate_view(items)
