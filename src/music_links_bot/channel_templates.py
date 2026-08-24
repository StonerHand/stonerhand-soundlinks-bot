from __future__ import annotations

import hashlib

from music_links_bot.bot_storage import remember_bounded
from music_links_bot.constants import PLATFORM_LABELS
from music_links_bot.kvstore import KVStore
from music_links_bot.release_presentation import apply_preset, normalize_preset

CHANNEL_TEMPLATE_TTL_SECONDS = 180 * 24 * 3600
MAX_MEMORY_TEMPLATES = 100
TEMPLATE_SCHEMA_VERSION = 2
_TEMPLATE_FIELDS = (
    "hashtags",
    "quote",
    "large_preview",
    "as_photo",
    "platforms",
    "preset",
    "publication_mode",
    "delivery_mode",
)


def _template_key(target: int | str, *, version: int = TEMPLATE_SCHEMA_VERSION) -> str:
    digest = hashlib.sha256(str(target).casefold().encode()).hexdigest()[:20]
    return f"channel:template:v{version}:{digest}"


def _sanitize_template(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    template: dict = {}
    for flag in ("hashtags", "quote", "large_preview", "as_photo"):
        if isinstance(value.get(flag), bool):
            template[flag] = value[flag]
    platforms = value.get("platforms")
    if isinstance(platforms, list):
        template["platforms"] = [
            key
            for key in platforms[:6]
            if isinstance(key, str) and key in PLATFORM_LABELS
        ]
    preset = value.get("preset")
    if isinstance(preset, str):
        template["preset"] = normalize_preset(preset, value)
    publication_mode = value.get("publication_mode")
    if publication_mode in {"card", "longread"}:
        template["publication_mode"] = publication_mode
    delivery_mode = value.get("delivery_mode")
    if delivery_mode in {"auto", "classic"}:
        template["delivery_mode"] = delivery_mode
    return template


def template_from_draft(draft: dict) -> dict:
    return _sanitize_template(
        {key: draft.get(key) for key in _TEMPLATE_FIELDS if key in draft}
    )


async def load_channel_template(context, target: int | str) -> dict:
    key = _template_key(target)
    memory = context.application.bot_data.setdefault("channel_templates", {})
    cached = memory.get(key)
    if isinstance(cached, dict):
        return dict(cached)
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    stored = await kv.get_json(key) if kv is not None else None
    if isinstance(stored, dict) and isinstance(stored.get("template"), dict):
        stored = stored["template"]
    migrated = False
    if stored is None and kv is not None:
        stored = await kv.get_json(_template_key(target, version=1))
        migrated = isinstance(stored, dict)
    template = _sanitize_template(stored)
    if template:
        remember_bounded(
            memory,
            key,
            template,
            max_size=MAX_MEMORY_TEMPLATES,
        )
    if migrated and template:
        await kv.set_json(
            key,
            {"v": TEMPLATE_SCHEMA_VERSION, "template": template},
            ttl_seconds=CHANNEL_TEMPLATE_TTL_SECONDS,
        )
    return template


def apply_template(draft: dict, template: dict) -> bool:
    template = _sanitize_template(template)
    if "preset" in template:
        apply_preset(draft, template["preset"])
    for key, value in template.items():
        if key == "preset":
            continue
        draft[key] = list(value) if isinstance(value, list) else value
    return bool(template)


async def apply_channel_template(context, target: int | str, draft: dict) -> None:
    template = await load_channel_template(context, target)
    draft["last_template"] = dict(template)
    applied = apply_template(draft, template)
    draft["channel_template_applied"] = applied
    draft["last_template_available"] = applied
    draft["last_template_applied"] = applied


async def save_channel_template(context, target: int | str, draft: dict) -> None:
    template = template_from_draft(draft)
    if not template:
        return
    key = _template_key(target)
    remember_bounded(
        context.application.bot_data.setdefault("channel_templates", {}),
        key,
        template,
        max_size=MAX_MEMORY_TEMPLATES,
    )
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        await kv.set_json(
            key,
            {"v": TEMPLATE_SCHEMA_VERSION, "template": template},
            ttl_seconds=CHANNEL_TEMPLATE_TTL_SECONDS,
        )
