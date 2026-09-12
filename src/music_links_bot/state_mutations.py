"""Optimistic, bounded updates for durable user data across server instances."""

from __future__ import annotations

import json
from copy import deepcopy

from music_links_bot.durable_state import read_json, write_json
from music_links_bot.kvstore import KVUnavailableError


class StateConflictError(KVUnavailableError):
    """The visible edit was based on a version that has since changed."""


async def mutate_json(kv, key, transform, *, ttl_seconds):
    """Retry only pure state transforms; never repeat a Telegram side effect."""
    compare = getattr(kv, "compare_set_required", None)
    if compare is None:  # Compatibility with local/test storage adapters.
        value = transform(deepcopy(await read_json(kv, key)))
        await write_json(kv, key, value, ttl_seconds=ttl_seconds)
        return value
    for _ in range(6):
        raw = await kv.get_required(key)
        try:
            previous = json.loads(raw) if raw is not None else None
        except (TypeError, ValueError) as exc:
            raise KVUnavailableError("Invalid durable state") from exc
        value = transform(previous)
        if await compare(
            key, raw, json.dumps(value, ensure_ascii=False), ttl_seconds=ttl_seconds
        ):
            return value
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
