from __future__ import annotations

import hashlib
from typing import Any

from music_links_bot.bot_storage import remember_bounded
from music_links_bot.kvstore import KVStore

MEDIA_CACHE_TTL_SECONDS = 30 * 24 * 3600
MAX_MEMORY_MEDIA = 500


def _key(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return f"telegram-media:v1:{digest}"


async def get_cached_file_id(context: Any, url: str | None) -> str | None:
    """Return Telegram's reusable file_id for a previously uploaded cover."""
    if not url:
        return None
    bot_data = context.application.bot_data
    memory: dict[str, str] = bot_data.setdefault("telegram_media_cache", {})
    key = _key(url)
    cached = memory.get(key)
    if cached:
        return cached
    kv: KVStore | None = bot_data.get("kv_store")
    cached = await kv.get(key) if kv is not None else None
    if cached:
        remember_bounded(memory, key, cached, max_size=MAX_MEMORY_MEDIA)
    return cached


async def remember_photo_file_id(
    context: Any,
    url: str | None,
    message: Any,
) -> None:
    """Cache the largest returned Telegram photo variant without blocking UX."""
    photos = getattr(message, "photo", None)
    if not url or not photos:
        return
    file_id = str(getattr(photos[-1], "file_id", "") or "")
    if not file_id:
        return
    bot_data = context.application.bot_data
    memory: dict[str, str] = bot_data.setdefault("telegram_media_cache", {})
    key = _key(url)
    remember_bounded(memory, key, file_id, max_size=MAX_MEMORY_MEDIA)
    kv: KVStore | None = bot_data.get("kv_store")
    if kv is not None:
        await kv.set(key, file_id, ttl_seconds=MEDIA_CACHE_TTL_SECONDS)
