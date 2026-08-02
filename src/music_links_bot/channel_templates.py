from __future__ import annotations

import hashlib

from music_links_bot.bot_storage import remember_bounded
from music_links_bot.constants import PLATFORM_LABELS
from music_links_bot.kvstore import KVStore
from music_links_bot.release_presentation import apply_preset, normalize_preset

CHANNEL_TEMPLATE_TTL_SECONDS = 180 * 24 * 3600
MAX_MEMORY_TEMPLATES = 100
_TEMPLATE_FIELDS = (
    "hashtags",
    "large_preview",
    "as_photo",
    "platforms",
    "preset",
    "publication_mode",
)


def _template_key(target: int | str) -> str:
    digest = hashlib.sha256(str(target).casefold().encode()).hexdigest()[:20]
    return f"channel:template:v1:{digest}"


def _sanitize_template(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    template: dict = {}
    for flag in ("hashtags", "large_preview", "as_photo"):
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
    return template


async def load_channel_template(context, target: int | str) -> dict:
    key = _template_key(target)
    memory = context.application.bot_data.setdefault("channel_templates", {})
    cached = memory.get(key)
    if isinstance(cached, dict):
        return dict(cached)
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    stored = await kv.get_json(key) if kv is not None else None
    template = _sanitize_template(stored)
    if template:
        remember_bounded(
            memory,
            key,
            template,
            max_size=MAX_MEMORY_TEMPLATES,
        )
    return template


async def apply_channel_template(context, target: int | str, draft: dict) -> None:
    template = await load_channel_template(context, target)
    if "preset" in template:
        apply_preset(draft, template["preset"])
    for key, value in template.items():
        if key == "preset":
            continue
        draft[key] = list(value) if isinstance(value, list) else value
    draft["channel_template_applied"] = bool(template)


async def save_channel_template(context, target: int | str, draft: dict) -> None:
    template = _sanitize_template(
        {key: draft.get(key) for key in _TEMPLATE_FIELDS if key in draft}
    )
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
            template,
            ttl_seconds=CHANNEL_TEMPLATE_TTL_SECONDS,
        )
