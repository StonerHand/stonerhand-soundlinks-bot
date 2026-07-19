from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from music_links_bot.kvstore import KVStore

IDEMPOTENCY_TTL_SECONDS = 24 * 3600
IDEMPOTENCY_LOCK_TTL_SECONDS = 30
MAX_IDEMPOTENCY_KEY_LENGTH = 96
_MEMORY_RATE_KEY = "request_rate_windows"
_MEMORY_IDEMPOTENCY_KEY = "request_idempotency"
_MEMORY_IDEMPOTENCY_LOCKS_KEY = "request_idempotency_locks"
_TRANSIENT_ERRORS = {
    "internal",
    "network",
    "queue_busy",
    "request_in_progress",
    "send failed",
    "timeout",
}


def _cacheable(result: dict) -> bool:
    """Do not pin a temporary failure to a request id for 24 hours."""
    return not (
        result.get("retryable") is True
        or result.get("error") in _TRANSIENT_ERRORS
    )


def _safe_key(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > MAX_IDEMPOTENCY_KEY_LENGTH:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


async def rate_limited(
    context,
    *,
    scope: str,
    subject: int | str,
    limit: int,
    window_seconds: int,
    now: float | None = None,
) -> bool:
    current = now if now is not None else time.time()
    bucket = int(current // window_seconds)
    key = f"rate:{scope}:{subject}:{bucket}"
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        count = await kv.increment_window(key, ttl_seconds=window_seconds + 2)
        if count is not None:
            return count > limit

    windows: dict[str, int] = context.application.bot_data.setdefault(
        _MEMORY_RATE_KEY, {}
    )
    windows[key] = windows.get(key, 0) + 1
    if len(windows) > 5000:
        active_suffix = f":{bucket}"
        for old_key in list(windows):
            if not old_key.endswith(active_suffix):
                windows.pop(old_key, None)
    return windows[key] > limit


async def run_idempotent(
    context,
    *,
    user_id: int,
    action: str,
    request_key: object,
    execute: Callable[[], Awaitable[dict]],
) -> dict:
    """Return the first completed result for a client-generated request key."""
    key_hash = _safe_key(request_key)
    if key_hash is None:
        return await execute()

    result_key = f"idem:result:{user_id}:{action}:{key_hash}"
    lock_key = f"idem:lock:{user_id}:{action}:{key_hash}"
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        cached = await kv.get_json(result_key)
        if isinstance(cached, dict):
            return cached

        owner = hashlib.sha256(f"{time.time_ns()}:{key_hash}".encode()).hexdigest()[:24]
        acquired = await kv.set(
            lock_key, owner, ttl_seconds=IDEMPOTENCY_LOCK_TTL_SECONDS, nx=True
        )
        if not acquired:
            for _ in range(8):
                await asyncio.sleep(0.1)
                cached = await kv.get_json(result_key)
                if isinstance(cached, dict):
                    return cached
            return {"ok": False, "error": "request_in_progress", "retryable": True}

        try:
            result = await execute()
            if _cacheable(result):
                await kv.set_json(
                    result_key, result, ttl_seconds=IDEMPOTENCY_TTL_SECONDS
                )
            return result
        finally:
            await kv.delete_if_value(lock_key, owner)

    cache: dict[str, dict] = context.application.bot_data.setdefault(
        _MEMORY_IDEMPOTENCY_KEY, {}
    )
    locks: dict[str, asyncio.Lock] = context.application.bot_data.setdefault(
        _MEMORY_IDEMPOTENCY_LOCKS_KEY, {}
    )
    lock = locks.setdefault(result_key, asyncio.Lock())
    async with lock:
        cached = cache.get(result_key)
        if cached is not None:
            return cached
        result = await execute()
        if _cacheable(result):
            cache[result_key] = result
        if len(cache) > 1000:
            oldest = next(iter(cache))
            cache.pop(oldest, None)
            locks.pop(oldest, None)
        return result
