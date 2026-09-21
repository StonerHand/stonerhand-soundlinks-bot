"""Track owned random keys and fence writes from requests preceding deletion."""

from __future__ import annotations

import secrets
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar

from music_links_bot.durable_state import read_json, read_text
from music_links_bot.state_mutations import mutate_json

INDEX_TTL = 180 * 24 * 3600
GENERATION_TTL = 7 * 24 * 3600
_guard: ContextVar[tuple[object, int, str] | None] = ContextVar(
    "user_state_guard", default=None
)
_OWNED_PREFIXES = ("draft:", "selection:v1:", "retry:v1:", "input-choice:v1:")


def generation_key(user_id):
    return f"privacy-generation:v1:{user_id}"


@asynccontextmanager
async def user_state_scope(kv, user_id):
    generation = (
        await read_text(kv, generation_key(user_id)) if kv and user_id > 0 else None
    )
    token = _guard.set((kv, user_id, generation or "") if kv and user_id > 0 else None)
    try:
        yield
    finally:
        _guard.reset(token)


def guard_command(kv, command):
    """Check the generation in the same Redis script as the write itself."""
    guard = _guard.get()
    if (
        guard is None
        or guard[0] is not kv
        or command[0].upper()
        not in {
            "SET",
            "DEL",
            "EVAL",
            "INCR",
            "EXPIRE",
        }
    ):
        return command
    _, user_id, generation = guard
    check = (
        "if (redis.call('get', KEYS[#KEYS]) or '') ~= ARGV[#ARGV] then "
        "return redis.error_reply('USER_STATE_CHANGED') end; "
    )
    if command[0].upper() == "EVAL":
        count = int(command[2])
        return [
            "EVAL",
            check + command[1],
            str(count + 1),
            *command[3 : 3 + count],
            generation_key(user_id),
            *command[3 + count :],
            generation,
        ]
    return [
        "EVAL",
        check + "return redis.call(unpack(ARGV, 1, #ARGV - 1))",
        "1",
        generation_key(user_id),
        *command,
        generation,
    ]


async def invalidate_previous_requests(kv, user_id):
    if kv is None:
        return
    value = secrets.token_hex(16)
    setter = getattr(kv, "set_required", None) or getattr(kv, "set", None)
    if setter is None:  # Small in-memory test adapters do not run remote requests.
        return
    if not await setter(generation_key(user_id), value, ttl_seconds=GENERATION_TTL):
        from music_links_bot.kvstore import KVUnavailableError

        raise KVUnavailableError("Could not fence deleted user state")
    if _guard.get() is not None:
        _guard.set((kv, user_id, value))


async def register_owned_key(kv, user_id, key, *, ttl_seconds):
    if kv is None or not isinstance(user_id, int) or user_id <= 0:
        return
    now = int(time.time())

    def update(previous):
        previous = previous if isinstance(previous, dict) else {}
        return {
            **{
                name: expiry
                for name, expiry in previous.items()
                if isinstance(expiry, (int, float)) and expiry > now
            },
            key: now + ttl_seconds,
        }

    await mutate_json(kv, f"user-keys:v1:{user_id}", update, ttl_seconds=INDEX_TTL)


async def owned_keys(kv, user_id):
    if kv is None:
        return set()
    index = await read_json(kv, f"user-keys:v1:{user_id}")
    keys = {
        key
        for key in index or {}
        if isinstance(key, str) and key.startswith(_OWNED_PREFIXES)
    }
    # Legacy records predate the index. A privacy request must still find them,
    # including drafts evicted from the UI's 30-item list. SCAN never blocks Redis
    # like KEYS; every candidate is checked for ownership before deletion.
    scanner = getattr(kv, "scan_keys_required", None)
    if scanner is not None:
        async for batch in scanner("*"):
            candidates = [key for key in batch if key.startswith(_OWNED_PREFIXES)]
            if not candidates:
                continue
            values = await kv.mget_json_required(candidates)
            for key, value in zip(candidates, values, strict=True):
                if (
                    isinstance(value, dict)
                    and value.get("chat_id" if key.startswith("draft:") else "user_id")
                    == user_id
                ):
                    keys.add(key)
    return keys
