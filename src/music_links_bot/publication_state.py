from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os

from music_links_bot.kvstore import KVStore
from music_links_bot.models import TrackMatch


def webapp_url() -> str | None:
    explicit = os.getenv("WEBAPP_URL", "").strip()
    if explicit:
        return explicit

    domain = os.getenv("VERCEL_PROJECT_PRODUCTION_URL", "").strip()
    return f"https://{domain}/app" if domain else None


def release_fingerprint(artist: str, title: str) -> str:
    normalized = f"{artist}|{title}".casefold()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"posted:{digest}"


async def find_posted_date(context, track: TrackMatch) -> str | None:
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is None:
        return None
    return await kv.get(release_fingerprint(track.artist, track.title))


async def mark_posted(context, track: TrackMatch) -> None:
    """Persist duplicate-guard state before a serverless invocation can freeze."""
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is None:
        return

    posted_date = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    await kv.set(release_fingerprint(track.artist, track.title), posted_date)
