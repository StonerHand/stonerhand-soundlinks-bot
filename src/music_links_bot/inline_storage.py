from __future__ import annotations

import hashlib
from time import time

from music_links_bot.bot_storage import remember_bounded
from music_links_bot.kvstore import KVStore

INLINE_SEARCH_TTL_SECONDS = 30 * 60
INLINE_HISTORY_TTL_SECONDS = 30 * 24 * 3600
MAX_INLINE_CACHE = 300
MAX_INLINE_HISTORY = 8
MAX_INLINE_HISTORY_USERS = 500


def _query_key(query: str) -> str:
    digest = hashlib.sha256(query.casefold().encode("utf-8")).hexdigest()[:24]
    return f"inline:search:v1:{digest}"


async def load_cached_search(bot_data: dict, query: str) -> list[str] | None:
    cache: dict = bot_data.setdefault("inline_search_cache", {})
    key = _query_key(query)
    cached = cache.get(key)
    if isinstance(cached, dict) and int(cached.get("expires_at") or 0) > int(time()):
        return [str(url) for url in cached.get("urls", []) if isinstance(url, str)]

    kv: KVStore | None = bot_data.get("kv_store")
    payload = await kv.get_json(key) if kv is not None else None
    if isinstance(payload, list):
        urls = [str(url) for url in payload if isinstance(url, str)]
        remember_bounded(
            cache,
            key,
            {"urls": urls, "expires_at": int(time()) + INLINE_SEARCH_TTL_SECONDS},
            max_size=MAX_INLINE_CACHE,
        )
        return urls
    return None


async def store_cached_search(bot_data: dict, query: str, urls: list[str]) -> None:
    key = _query_key(query)
    clean = list(dict.fromkeys(str(url) for url in urls if url))[:24]
    cache: dict = bot_data.setdefault("inline_search_cache", {})
    remember_bounded(
        cache,
        key,
        {"urls": clean, "expires_at": int(time()) + INLINE_SEARCH_TTL_SECONDS},
        max_size=MAX_INLINE_CACHE,
    )
    kv: KVStore | None = bot_data.get("kv_store")
    if kv is not None:
        await kv.set_json(
            key,
            clean,
            ttl_seconds=INLINE_SEARCH_TTL_SECONDS,
        )


async def remember_inline_urls(
    bot_data: dict,
    user_id: int,
    urls: list[str],
) -> None:
    if user_id <= 0:
        return
    history = await load_inline_history(bot_data, user_id)
    clean = list(dict.fromkeys([*(str(url) for url in urls if url), *history]))[
        :MAX_INLINE_HISTORY
    ]
    remember_bounded(
        bot_data.setdefault("inline_history", {}),
        user_id,
        clean,
        max_size=MAX_INLINE_HISTORY_USERS,
    )
    kv: KVStore | None = bot_data.get("kv_store")
    if kv is not None:
        await kv.set_json(
            f"inline:history:v1:{user_id}",
            clean,
            ttl_seconds=INLINE_HISTORY_TTL_SECONDS,
        )


async def load_inline_history(bot_data: dict, user_id: int) -> list[str]:
    memory = bot_data.setdefault("inline_history", {})
    cached = memory.get(user_id)
    if isinstance(cached, list):
        return [str(url) for url in cached if isinstance(url, str)]
    kv: KVStore | None = bot_data.get("kv_store")
    payload = (
        await kv.get_json(f"inline:history:v1:{user_id}")
        if kv is not None and user_id > 0
        else None
    )
    urls = (
        [str(url) for url in payload if isinstance(url, str)]
        if isinstance(payload, list)
        else []
    )
    remember_bounded(
        memory,
        user_id,
        urls,
        max_size=MAX_INLINE_HISTORY_USERS,
    )
    return urls


async def clear_inline_history(bot_data: dict, user_id: int) -> None:
    bot_data.setdefault("inline_history", {}).pop(user_id, None)
    kv: KVStore | None = bot_data.get("kv_store")
    if kv is not None:
        await kv.delete(f"inline:history:v1:{user_id}")
