from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
import hashlib
import json
import logging
from time import monotonic
from typing import Any

from music_links_bot.cache import TTLCache
from music_links_bot.kvstore import KVStore

LOGGER = logging.getLogger(__name__)
PROVIDER_TIMEOUT_SECONDS = 9.0
LOOKUP_CACHE_TTL_SECONDS = 15 * 60
_LOOKUP_CACHE: TTLCache[dict[str, Any]] = TTLCache(
    ttl_seconds=LOOKUP_CACHE_TTL_SECONDS,
    max_size=512,
)


@dataclass(slots=True)
class ProviderTask:
    name: str
    awaitable: Awaitable[Any]
    fallback: Any


async def run_provider_tasks(
    bot_data: dict,
    tasks: list[ProviderTask],
    *,
    timeout_seconds: float = PROVIDER_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run independent providers concurrently and keep successful partial data."""

    async def run(task: ProviderTask) -> tuple[str, Any]:
        started = monotonic()
        error: BaseException | None = None
        try:
            value = await asyncio.wait_for(task.awaitable, timeout=timeout_seconds)
        except (Exception, asyncio.CancelledError) as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            error = exc
            value = task.fallback
            LOGGER.warning(
                "Provider %s returned a partial fallback: %s",
                task.name,
                type(exc).__name__,
            )
        runtime = bot_data.get("runtime")
        if runtime is not None and hasattr(runtime, "record_provider"):
            runtime.record_provider(
                task.name,
                ok=error is None,
                latency_ms=int((monotonic() - started) * 1000),
                error=error,
            )
        return task.name, value

    pairs = await asyncio.gather(*(run(task) for task in tasks))
    return dict(pairs)


def lookup_cache_key(source_urls: list[str]) -> str:
    canonical = json.dumps(
        sorted(dict.fromkeys(source_urls)),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return "lookup:v2:" + hashlib.sha256(canonical.encode()).hexdigest()


async def get_cached_lookup(bot_data: dict, source_urls: list[str]) -> dict | None:
    key = lookup_cache_key(source_urls)
    cached = _LOOKUP_CACHE.get(key)
    if isinstance(cached, dict):
        return cached

    kv: KVStore | None = bot_data.get("kv_store")
    cached = await kv.get_json(key) if kv is not None else None
    if isinstance(cached, dict):
        _LOOKUP_CACHE.set(key, cached)
        return cached
    return None


async def set_cached_lookup(
    bot_data: dict,
    source_urls: list[str],
    payload: dict[str, Any],
) -> None:
    key = lookup_cache_key(source_urls)
    _LOOKUP_CACHE.set(key, payload)
    kv: KVStore | None = bot_data.get("kv_store")
    if kv is not None:
        await kv.set_json(key, payload, ttl_seconds=LOOKUP_CACHE_TTL_SECONDS)
