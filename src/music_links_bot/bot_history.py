from __future__ import annotations

import logging
import time

from music_links_bot.bot_storage import remember_bounded
from music_links_bot.durable_state import delete_value, read_json
from music_links_bot.formatter import pick_track_emoji
from music_links_bot.kvstore import KVStore, KVUnavailableError
from music_links_bot.models import TrackMatch
from music_links_bot.publication_state import release_fingerprint
from music_links_bot.state_mutations import mutate_json

LOGGER = logging.getLogger(__name__)
MAX_HISTORY_ITEMS = 10
HISTORY_TTL_SECONDS = 90 * 24 * 3600
MAX_MEMORY_USERS = 500


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

    def prepend(previous) -> list[dict]:
        items = [
            item
            for item in (previous if isinstance(previous, list) else [])
            if isinstance(item, dict)
            and release_fingerprint(
                str(item.get("artist") or ""), str(item.get("title") or "")
            )
            != fingerprint
        ]
        return [entry, *items][:MAX_HISTORY_ITEMS]

    histories: dict = context.application.bot_data.setdefault("bot_history", {})
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is None:
        items = prepend(histories.get(user_id))
    else:
        # Compare-and-set replaces the old lock/read/write/unlock sequence:
        # two Redis round trips instead of four, and no lock to leak.
        try:
            items = await mutate_json(
                kv, f"hist:{user_id}", prepend, ttl_seconds=HISTORY_TTL_SECONDS
            )
        except KVUnavailableError:
            # History is a convenience; it must never fail the lookup itself.
            LOGGER.debug("Could not record history", exc_info=True)
            return
    remember_bounded(histories, user_id, items, max_size=MAX_MEMORY_USERS)


async def load_history_items(context, user_id: int) -> list[dict]:
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        items = await read_json(kv, f"hist:{user_id}")
        if not isinstance(items, list):
            return []
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)][
                :MAX_HISTORY_ITEMS
            ]
    histories: dict = context.application.bot_data.setdefault("bot_history", {})
    return list(histories.get(user_id) or [])


async def clear_history(context, user_id: int) -> None:
    context.application.bot_data.setdefault("bot_history", {}).pop(user_id, None)
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        await delete_value(kv, f"hist:{user_id}")
