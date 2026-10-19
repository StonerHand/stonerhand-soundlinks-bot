"""Owner-editable cover signature text, shared by every bot instance."""

from __future__ import annotations

from music_links_bot.cover_style import (
    MAX_BRAND_LABEL_LENGTH,
    set_brand_label_override,
)
from music_links_bot.durable_state import delete_value, read_text, write_text

BRAND_LABEL_KEY = "settings:brand-label:v1"
BRAND_LABEL_TTL_SECONDS = 10 * 365 * 86400


def apply_stored_label(raw: object) -> None:
    """Apply a value read from Redis (``None`` means "use BRAND_LABEL")."""
    set_brand_label_override(raw if isinstance(raw, str) else None)


async def load_brand_label(kv) -> None:
    if kv is None:
        return
    apply_stored_label(await read_text(kv, BRAND_LABEL_KEY))


async def save_brand_label(kv, value: str) -> str:
    cleaned = " ".join(str(value or "").split())[:MAX_BRAND_LABEL_LENGTH]
    if kv is not None:
        if cleaned:
            await write_text(
                kv, BRAND_LABEL_KEY, cleaned, ttl_seconds=BRAND_LABEL_TTL_SECONDS
            )
        else:
            await delete_value(kv, BRAND_LABEL_KEY)
    set_brand_label_override(cleaned or None)
    return cleaned
