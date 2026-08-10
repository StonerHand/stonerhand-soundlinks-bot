from __future__ import annotations

from typing import Any

from music_links_bot.bot_storage import remember_bounded
from music_links_bot.kvstore import KVStore

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
    if user_id in memory:
        return memory[user_id]
    kv: KVStore | None = bot_data.get("kv_store")
    value = await kv.get(f"bot-crate-title:v1:{user_id}") if kv else None
    title = str(value or "")[:72]
    remember_bounded(memory, user_id, title, max_size=MAX_MEMORY_CRATES)
    return title


async def save_crate_title(bot_data: dict, user_id: int, title: str) -> None:
    value = str(title or "")[:72]
    remember_bounded(
        _memory_titles(bot_data), user_id, value, max_size=MAX_MEMORY_CRATES
    )
    kv: KVStore | None = bot_data.get("kv_store")
    if kv is not None:
        if value:
            await kv.set(
                f"bot-crate-title:v1:{user_id}",
                value,
                ttl_seconds=CRATE_TITLE_TTL_SECONDS,
            )
        else:
            await kv.delete(f"bot-crate-title:v1:{user_id}")


async def load_crate(bot_data: dict, user_id: int) -> list[dict[str, Any]]:
    memory = _memory_crates(bot_data)
    if user_id in memory:
        return list(memory[user_id])

    kv: KVStore | None = bot_data.get("kv_store")
    payload = await kv.get_json(f"bot-crate:v2:{user_id}") if kv else None
    if isinstance(payload, dict):
        payload = payload.get("items")
    migrated = False
    if payload is None and kv is not None:
        payload = await kv.get_json(f"bot-crate:v1:{user_id}")
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
    result = list(memory[user_id])
    if migrated:
        await save_crate(bot_data, user_id, result)
    return result


async def save_crate(bot_data: dict, user_id: int, items: list[dict[str, Any]]) -> None:
    normalized = items[:MAX_CRATE_ITEMS]
    remember_bounded(
        _memory_crates(bot_data),
        user_id,
        normalized,
        max_size=MAX_MEMORY_CRATES,
    )
    kv: KVStore | None = bot_data.get("kv_store")
    if kv is not None:
        await kv.set_json(
            f"bot-crate:v2:{user_id}",
            {"v": CRATE_SCHEMA_VERSION, "items": normalized},
            ttl_seconds=CRATE_TTL_SECONDS,
        )


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


async def add_many_to_crate(
    bot_data: dict,
    user_id: int,
    *,
    entries: list[tuple[str, dict[str, Any]]],
) -> tuple[list[dict[str, Any]], int]:
    """Add several releases with one crate load and at most one Redis write."""
    items = await load_crate(bot_data, user_id)
    fingerprints = {_fingerprint(existing.get("item") or {}) for existing in items}
    added_count = 0
    for draft_id, item in entries:
        if len(items) >= MAX_CRATE_ITEMS:
            break
        fingerprint = _fingerprint(item)
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        items.append({"draft_id": draft_id, "item": item})
        added_count += 1

    if added_count:
        await save_crate(bot_data, user_id, items)
    return items, added_count


async def move_crate_item(
    bot_data: dict, user_id: int, index: int, direction: int
) -> list[dict[str, Any]]:
    items = await load_crate(bot_data, user_id)
    target = index + direction
    if 0 <= index < len(items) and 0 <= target < len(items):
        items[index], items[target] = items[target], items[index]
        await save_crate(bot_data, user_id, items)
    return items


async def remove_crate_item(
    bot_data: dict, user_id: int, index: int
) -> list[dict[str, Any]]:
    items = await load_crate(bot_data, user_id)
    if 0 <= index < len(items):
        items.pop(index)
        await save_crate(bot_data, user_id, items)
    return items


async def restore_crate_item(
    bot_data: dict,
    user_id: int,
    *,
    index: int,
    entry: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    """Restore one recently removed item without creating duplicates."""
    items = await load_crate(bot_data, user_id)
    item = entry.get("item") if isinstance(entry, dict) else None
    if not isinstance(item, dict) or len(items) >= MAX_CRATE_ITEMS:
        return items, False
    fingerprint = _fingerprint(item)
    if any(
        _fingerprint(existing.get("item") or {}) == fingerprint for existing in items
    ):
        return items, False
    items.insert(max(0, min(index, len(items))), entry)
    await save_crate(bot_data, user_id, items)
    return items, True


def _fingerprint(item: dict[str, Any]) -> str:
    links = item.get("links") if isinstance(item.get("links"), dict) else {}
    first_url = next(iter(links.values()), "")
    return "|".join(
        str(value).casefold().strip()
        for value in (item.get("artist"), item.get("title"), first_url)
    )
