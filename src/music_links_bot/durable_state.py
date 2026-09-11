"""Confirmed user-state operations, with compatibility for older adapters."""

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
