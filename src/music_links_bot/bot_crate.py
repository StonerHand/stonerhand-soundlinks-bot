from __future__ import annotations

from typing import Any

from music_links_bot.kvstore import KVStore

CRATE_TTL_SECONDS = 14 * 24 * 3600
MAX_CRATE_ITEMS = 10


def _memory_crates(bot_data: dict) -> dict[int, list[dict[str, Any]]]:
    return bot_data.setdefault("bot_crates", {})


async def load_crate(bot_data: dict, user_id: int) -> list[dict[str, Any]]:
    memory = _memory_crates(bot_data)
    if user_id in memory:
        return list(memory[user_id])

    kv: KVStore | None = bot_data.get("kv_store")
    payload = await kv.get_json(f"bot-crate:v1:{user_id}") if kv else None
    items = [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    memory[user_id] = items[:MAX_CRATE_ITEMS]
    return list(memory[user_id])


async def save_crate(bot_data: dict, user_id: int, items: list[dict[str, Any]]) -> None:
    normalized = items[:MAX_CRATE_ITEMS]
    _memory_crates(bot_data)[user_id] = normalized
    kv: KVStore | None = bot_data.get("kv_store")
    if kv is not None:
        await kv.set_json(
            f"bot-crate:v1:{user_id}", normalized, ttl_seconds=CRATE_TTL_SECONDS
        )


async def add_to_crate(
    bot_data: dict, user_id: int, *, draft_id: str, item: dict[str, Any]
) -> tuple[list[dict[str, Any]], bool]:
    items = await load_crate(bot_data, user_id)
    fingerprint = _fingerprint(item)
    if any(_fingerprint(existing.get("item") or {}) == fingerprint for existing in items):
        return items, False
    if len(items) >= MAX_CRATE_ITEMS:
        return items, False
    items.append({"draft_id": draft_id, "item": item})
    await save_crate(bot_data, user_id, items)
    return items, True


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


def _fingerprint(item: dict[str, Any]) -> str:
    links = item.get("links") if isinstance(item.get("links"), dict) else {}
    first_url = next(iter(links.values()), "")
    return "|".join(
        str(value).casefold().strip()
        for value in (item.get("artist"), item.get("title"), first_url)
    )
