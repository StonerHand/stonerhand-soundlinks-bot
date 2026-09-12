from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from music_links_bot.bot_storage import remember_bounded
from music_links_bot.durable_state import (
    delete_value,
    read_json,
    read_text,
    write_json,
    write_text,
)
from music_links_bot.kvstore import KVStore
from music_links_bot.state_mutations import StateConflictError, mutate_json

CRATE_TTL_SECONDS = 14 * 24 * 3600
MAX_CRATE_ITEMS = 10
MAX_MEMORY_CRATES = 500
CRATE_SCHEMA_VERSION = 2
CRATE_TITLE_TTL_SECONDS = CRATE_TTL_SECONDS


def _memory_crates(bot_data: dict) -> dict[int, list[dict[str, Any]]]:
    return bot_data.setdefault("bot_crates", {})


def _memory_titles(bot_data: dict) -> dict[int, str]:
    return bot_data.setdefault("bot_crate_titles", {})


async def load_crate_title(bot_data: dict, user_id: int) -> str:
    memory = _memory_titles(bot_data)
    kv: KVStore | None = bot_data.get("kv_store")
    if kv is None and user_id in memory:
        return memory[user_id]
    value = await read_text(kv, f"bot-crate-title:v1:{user_id}") if kv else None
    title = str(value or "")[:72]
    remember_bounded(memory, user_id, title, max_size=MAX_MEMORY_CRATES)
    return title


async def save_crate_title(bot_data: dict, user_id: int, title: str) -> None:
    value = str(title or "")[:72]
    kv: KVStore | None = bot_data.get("kv_store")
    if kv is not None:
        if value:
            await write_text(
                kv,
                f"bot-crate-title:v1:{user_id}",
                value,
                ttl_seconds=CRATE_TITLE_TTL_SECONDS,
            )
        else:
            await delete_value(kv, f"bot-crate-title:v1:{user_id}")

    remember_bounded(
        _memory_titles(bot_data), user_id, value, max_size=MAX_MEMORY_CRATES
    )


async def load_crate(bot_data: dict, user_id: int) -> list[dict[str, Any]]:
    memory = _memory_crates(bot_data)
    kv: KVStore | None = bot_data.get("kv_store")
    if kv is None and user_id in memory:
        return deepcopy(memory[user_id])

    payload = await read_json(kv, f"bot-crate:v2:{user_id}") if kv else None
    if isinstance(payload, dict):
        payload = payload.get("items")
    migrated = False
    if payload is None and kv is not None:
        payload = await read_json(kv, f"bot-crate:v1:{user_id}")
        migrated = isinstance(payload, list)
    items = (
        [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, list)
        else []
    )
    remember_bounded(
        memory,
        user_id,
        items[:MAX_CRATE_ITEMS],
        max_size=MAX_MEMORY_CRATES,
    )
    result = deepcopy(memory[user_id])
    if migrated:
        stored = await mutate_json(
            kv,
            f"bot-crate:v2:{user_id}",
            lambda current: (
                current
                if current is not None
                else {"v": CRATE_SCHEMA_VERSION, "items": result}
            ),
            ttl_seconds=CRATE_TTL_SECONDS,
        )
        result = deepcopy(stored.get("items", []))
    return result


async def save_crate(bot_data: dict, user_id: int, items: list[dict[str, Any]]) -> None:
    normalized = items[:MAX_CRATE_ITEMS]
    kv: KVStore | None = bot_data.get("kv_store")
    if kv is not None:
        await write_json(
            kv,
            f"bot-crate:v2:{user_id}",
            {"v": CRATE_SCHEMA_VERSION, "items": normalized},
            ttl_seconds=CRATE_TTL_SECONDS,
        )

    remember_bounded(
        _memory_crates(bot_data),
        user_id,
        normalized,
        max_size=MAX_MEMORY_CRATES,
    )


async def clear_crate(bot_data: dict, user_id: int) -> None:
    _memory_crates(bot_data).pop(user_id, None)
    _memory_titles(bot_data).pop(user_id, None)
    kv: KVStore | None = bot_data.get("kv_store")
    if kv is not None:
        await delete_value(kv, f"bot-crate:v2:{user_id}")
        await delete_value(kv, f"bot-crate:v1:{user_id}")
        await delete_value(kv, f"bot-crate-title:v1:{user_id}")


async def add_to_crate(
    bot_data: dict, user_id: int, *, draft_id: str, item: dict[str, Any]
) -> tuple[list[dict[str, Any]], bool]:
    items, added_count = await add_many_to_crate(
        bot_data,
        user_id,
        entries=[(draft_id, item)],
    )
    return items, added_count == 1


def crate_contains_item(items: list[dict[str, Any]], item: dict[str, Any]) -> bool:
    fingerprint = _fingerprint(item)
    return any(
        _fingerprint(existing.get("item") or {}) == fingerprint for existing in items
    )


def crate_item_key(entry: dict) -> str:
    return hashlib.sha256(_fingerprint(entry.get("item") or {}).encode()).hexdigest()[
        :16
    ]


def crate_revision(items: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(items, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]


def item_index(items, reference):
    if isinstance(reference, int):
        return reference
    return next(
        (i for i, entry in enumerate(items) if crate_item_key(entry) == reference), -1
    )


async def edit_crate(bot_data, user_id, transform):
    """Apply a pure list edit atomically, resolving a moved item by identity."""
    initial = await load_crate(bot_data, user_id)
    outcome = None

    def update(payload):
        nonlocal outcome
        items = deepcopy(
            payload.get("items", []) if isinstance(payload, dict) else initial
        )
        outcome = transform(items)
        return {"v": CRATE_SCHEMA_VERSION, "items": items[:MAX_CRATE_ITEMS]}

    kv = bot_data.get("kv_store")
    if kv is None:
        stored = update({"items": initial})
    else:
        stored = await mutate_json(
            kv, f"bot-crate:v2:{user_id}", update, ttl_seconds=CRATE_TTL_SECONDS
        )
    items = stored["items"]
    remember_bounded(
        _memory_crates(bot_data), user_id, deepcopy(items), max_size=MAX_MEMORY_CRATES
    )
    return items, outcome


async def add_many_to_crate(bot_data, user_id, *, entries):
    def add(items):
        fingerprints = {_fingerprint(entry.get("item") or {}) for entry in items}
        added = 0
        for draft_id, item in entries:
            fingerprint = _fingerprint(item)
            if len(items) < MAX_CRATE_ITEMS and fingerprint not in fingerprints:
                items.append({"draft_id": draft_id, "item": deepcopy(item)})
                fingerprints.add(fingerprint)
                added += 1
        return added

    return await edit_crate(bot_data, user_id, add)


async def move_crate_item(bot_data, user_id, index, direction):
    def move(items):
        source = item_index(items, index)
        target = source + direction
        if 0 <= source < len(items) and 0 <= target < len(items):
            items[source], items[target] = items[target], items[source]

    return (await edit_crate(bot_data, user_id, move))[0]


async def pop_crate_item(bot_data, user_id, reference):
    def remove(items):
        index = item_index(items, reference)
        return (index, items.pop(index)) if 0 <= index < len(items) else (-1, None)

    return await edit_crate(bot_data, user_id, remove)


async def remove_crate_item(bot_data, user_id, index):
    return (await pop_crate_item(bot_data, user_id, index))[0]


async def restore_crate_item(bot_data, user_id, *, index, entry):
    def restore(items):
        item = entry.get("item") if isinstance(entry, dict) else None
        if (
            not isinstance(item, dict)
            or len(items) >= MAX_CRATE_ITEMS
            or crate_contains_item(items, item)
        ):
            return False
        items.insert(max(0, min(index, len(items))), deepcopy(entry))
        return True

    return await edit_crate(bot_data, user_id, restore)


async def clear_crate_items(bot_data, user_id, expected):
    def clear(items):
        if not expected or crate_revision(items) != expected:
            raise StateConflictError("Collection changed after confirmation was shown")
        previous = list(items)
        items.clear()
        return previous

    return await edit_crate(bot_data, user_id, clear)


async def restore_crate_items(bot_data, user_id, entries):
    def restore(items):
        additions = [
            e for e in entries if not crate_contains_item(items, e.get("item") or {})
        ]
        if len(items) + len(additions) > MAX_CRATE_ITEMS:
            return False
        items[:0] = deepcopy(additions)
        return bool(additions)

    return await edit_crate(bot_data, user_id, restore)


def _fingerprint(item: dict[str, Any]) -> str:
    links = item.get("links") if isinstance(item.get("links"), dict) else {}
    first_url = next(iter(links.values()), "")
    return "|".join(
        str(value).casefold().strip()
        for value in (
            item.get("artist"),
            item.get("title"),
            item.get("kind", "song"),
            item.get("release_format"),
            first_url,
        )
    )


async def replace_crate_item(bot_data, user_id, reference, item):
    def replace(items):
        index = item_index(items, reference)
        if index < 0:
            raise StateConflictError("The collection item was removed")
        if any(
            i != index and _fingerprint(entry.get("item") or {}) == _fingerprint(item)
            for i, entry in enumerate(items)
        ):
            raise StateConflictError("The replacement already exists in the collection")
        items[index] = {"draft_id": "", "item": deepcopy(item)}

    return (await edit_crate(bot_data, user_id, replace))[0]
