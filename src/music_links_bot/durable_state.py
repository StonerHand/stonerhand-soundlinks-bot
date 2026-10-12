"""Confirmed user-state operations, with compatibility for older adapters."""

import json
from contextlib import contextmanager
from contextvars import ContextVar

from music_links_bot.kvstore import KVUnavailableError

current_state: ContextVar[dict | None] = ContextVar("request_state", default=None)


@contextmanager
def state_scope():
    """Reuse a session within one update, never across warm-server requests."""
    token = current_state.set({})
    try:
        yield
    finally:
        current_state.reset(token)


async def read_json(kv, key):
    reader = getattr(kv, "get_json_required", None) or kv.get_json
    return await reader(key)


async def read_json_with_legacy(kv, key, legacy_key):
    """Read a current key and its pre-migration fallback in one round trip.

    Returns ``(current, legacy)``; ``legacy`` is only decoded when the current
    value is absent. A malformed current value is an outage (as in
    ``read_json``); a malformed legacy value is just a missing migration source.
    """
    batch = getattr(kv, "mget_required", None)
    if batch is None:  # Compatibility with local/test storage adapters.
        current = await read_json(kv, key)
        legacy = await read_json(kv, legacy_key) if current is None else None
        return current, legacy
    raw_current, raw_legacy = await batch([key, legacy_key])
    if raw_current is not None:
        try:
            return json.loads(raw_current), None
        except ValueError as exc:
            raise KVUnavailableError("Redis contains invalid JSON") from exc
    if raw_legacy is None:
        return None, None
    try:
        return None, json.loads(raw_legacy)
    except ValueError:
        return None, None


async def read_text(kv, key):
    reader = getattr(kv, "get_required", None) or kv.get
    return await reader(key)


async def write_json(kv, key, value, *, ttl_seconds):
    writer = getattr(kv, "set_json_required", None)
    if writer is not None:
        await writer(key, value, ttl_seconds=ttl_seconds)
    elif await kv.set_json(key, value, ttl_seconds=ttl_seconds) is False:
        raise KVUnavailableError("State write was not confirmed")


async def write_text(kv, key, value, *, ttl_seconds):
    writer = getattr(kv, "set_required", None) or kv.set
    if not await writer(key, value, ttl_seconds=ttl_seconds):
        raise KVUnavailableError("State write was not confirmed")


async def delete_value(kv, key):
    deleter = getattr(kv, "delete_required", None) or kv.delete
    await deleter(key)
