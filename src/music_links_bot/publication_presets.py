from __future__ import annotations

import hashlib
import time

from music_links_bot.bot_storage import remember_bounded
from music_links_bot.channel_templates import apply_template, template_from_draft
from music_links_bot.kvstore import KVStore

PRESET_TTL_SECONDS = 365 * 24 * 3600
MAX_USER_PRESETS = 8
MAX_MEMORY_USERS = 100


def _key(user_id: int) -> str:
    digest = hashlib.sha256(str(user_id).encode()).hexdigest()[:20]
    return f"publication:presets:v1:{digest}"


def normalize_preset_name(value: str) -> str:
    return " ".join(str(value or "").split())[:32].strip()


def _sanitize_presets(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    result: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = normalize_preset_name(str(item.get("name") or ""))
        template = item.get("template")
        if not name or not isinstance(template, dict):
            continue
        result.append(
            {
                "name": name,
                "template": dict(template),
                "updated_at": int(item.get("updated_at") or 0),
            }
        )
        if len(result) >= MAX_USER_PRESETS:
            break
    return result


async def load_presets(context, user_id: int) -> list[dict]:
    key = _key(user_id)
    memory = context.application.bot_data.setdefault("publication_presets", {})
    cached = memory.get(key)
    if isinstance(cached, list):
        return [dict(item) for item in cached]
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    stored = await kv.get_json(key) if kv is not None else None
    presets = _sanitize_presets(stored)
    remember_bounded(memory, key, presets, max_size=MAX_MEMORY_USERS)
    return [dict(item) for item in presets]


async def _save_all(context, user_id: int, presets: list[dict]) -> None:
    key = _key(user_id)
    clean = _sanitize_presets(presets)
    remember_bounded(
        context.application.bot_data.setdefault("publication_presets", {}),
        key,
        clean,
        max_size=MAX_MEMORY_USERS,
    )
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        await kv.set_json(key, clean, ttl_seconds=PRESET_TTL_SECONDS)


async def save_named_preset(
    context, user_id: int, name: str, draft: dict
) -> list[dict]:
    clean_name = normalize_preset_name(name)
    if not clean_name:
        return await load_presets(context, user_id)
    presets = await load_presets(context, user_id)
    entry = {
        "name": clean_name,
        "template": template_from_draft(draft),
        "updated_at": int(time.time()),
    }
    existing = next(
        (
            index
            for index, item in enumerate(presets)
            if str(item.get("name") or "").casefold() == clean_name.casefold()
        ),
        None,
    )
    if existing is None:
        presets = [entry, *presets][:MAX_USER_PRESETS]
    else:
        presets[existing] = entry
    await _save_all(context, user_id, presets)
    return presets


async def apply_named_preset(
    context, user_id: int, index: int, draft: dict
) -> str | None:
    presets = await load_presets(context, user_id)
    if not 0 <= index < len(presets):
        return None
    item = presets[index]
    return str(item["name"]) if apply_template(draft, item["template"]) else None


async def delete_named_preset(context, user_id: int, index: int) -> bool:
    presets = await load_presets(context, user_id)
    if not 0 <= index < len(presets):
        return False
    presets.pop(index)
    await _save_all(context, user_id, presets)
    return True
