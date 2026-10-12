"""Optimistic, bounded updates for durable user data across server instances."""

from __future__ import annotations

import json
from copy import deepcopy

from music_links_bot.durable_state import read_json, write_json
from music_links_bot.kvstore import KVUnavailableError


class StateConflictError(KVUnavailableError):
    """The visible edit was based on a version that has since changed."""


# Marks "the stored raw value is not known yet" (``None`` means "key missing").
UNKNOWN_RAW = object()


async def mutate_json(kv, key, transform, *, ttl_seconds, expected_raw=UNKNOWN_RAW):
    """Retry only pure state transforms; never repeat a Telegram side effect."""
    value, _raw = await mutate_json_raw(
        kv, key, transform, ttl_seconds=ttl_seconds, expected_raw=expected_raw
    )
    return value


async def mutate_json_raw(kv, key, transform, *, ttl_seconds, expected_raw=UNKNOWN_RAW):
    """Like ``mutate_json`` but also return the exact raw value now stored.

    A caller that already read ``key`` in this request passes that raw value as
    ``expected_raw``: the first compare-and-set then needs no extra GET, and a
    stale guess simply fails the compare and falls back to a fresh read.
    """
    compare = getattr(kv, "compare_set_required", None)
    if compare is None:  # Compatibility with local/test storage adapters.
        value = transform(deepcopy(await read_json(kv, key)))
        await write_json(kv, key, value, ttl_seconds=ttl_seconds)
        return value, UNKNOWN_RAW
    raw = expected_raw
    for _ in range(6):
        if raw is UNKNOWN_RAW:
            raw = await kv.get_required(key)
        try:
            previous = json.loads(raw) if raw is not None else None
        except (TypeError, ValueError) as exc:
            raise KVUnavailableError("Invalid durable state") from exc
        value = transform(previous)
        encoded = json.dumps(value, ensure_ascii=False)
        if await compare(key, raw, encoded, ttl_seconds=ttl_seconds):
            return value, encoded
        raw = UNKNOWN_RAW
    raise StateConflictError("State changed repeatedly; reopen the current view")


def merge_fields(current, baseline, desired):
    """Merge independent edits; reject conflicting changes instead of losing one."""
    merged = deepcopy(current)
    for key in baseline.keys() | desired.keys():
        if key == "updated_at" or baseline.get(key) == desired.get(key):
            continue
        before, latest, wanted = baseline.get(key), current.get(key), desired.get(key)
        if latest != before and latest != wanted:
            if (
                isinstance(before, dict)
                and isinstance(latest, dict)
                and isinstance(wanted, dict)
            ):
                wanted = merge_fields(latest, before, wanted)
            elif key == "recent_draft_ids":
                removed = set(before or []) - set(wanted or [])
                wanted = list(
                    dict.fromkeys(
                        [
                            *(wanted or []),
                            *(v for v in latest or [] if v not in removed),
                        ]
                    )
                )[:30]
            else:
                raise StateConflictError(f"Concurrent edit of {key}")
        if key in desired:
            merged[key] = deepcopy(wanted)
        else:
            merged.pop(key, None)
    if "updated_at" in desired:
        merged["updated_at"] = desired["updated_at"]
    return merged
