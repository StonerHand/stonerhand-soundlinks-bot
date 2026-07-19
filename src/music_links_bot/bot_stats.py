from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import logging

from telegram import Message, MessageEntity
from telegram.ext import ContextTypes

from music_links_bot.formatter import prepend_user_html
from music_links_bot.kvstore import KVStore
from music_links_bot.models import (
    ArtistMatch,
    PlaylistMatch,
    RadioMatch,
    TrackMatch,
    VideoMatch,
)
from music_links_bot.stats import (
    merge_stats,
    record_artists,
    record_matches,
    record_mixed,
    record_playlists,
    record_radios,
    record_videos,
)
from music_links_bot.telegram_text import format_user_note_html

LOGGER = logging.getLogger(__name__)
STATS_KV_KEY = "stats:v1"
MAX_USER_NOTE_LENGTH = 700


def message_text(message: Message) -> str | None:
    return message.text or message.caption


def message_entities(message: Message) -> tuple[MessageEntity, ...]:
    if message.text is not None:
        return tuple(getattr(message, "entities", None) or ())
    return tuple(getattr(message, "caption_entities", None) or ())


def build_user_prefix(message: Message) -> str:
    body_html = format_user_note_html(
        message_text(message),
        message_entities(message),
        max_length=MAX_USER_NOTE_LENGTH,
    )
    if not body_html:
        return ""

    user = message.from_user
    author_label = None
    if user is not None:
        author_label = f"@{user.username}" if user.username else user.full_name
    return prepend_user_html(body_html, author_label=author_label)


def record_tracks(
    tracks: list[TrackMatch],
    message: Message,
    *,
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> None:
    if tracks:
        _record(
            "track",
            lambda: record_matches(
                tracks,
                user=_user_entry(message),
                chat=_chat_entry(message),
            ),
            context,
        )


def record_video_items(
    videos: list[VideoMatch],
    message: Message,
    *,
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> None:
    if videos:
        _record(
            "video",
            lambda: record_videos(
                videos,
                user=_user_entry(message),
                chat=_chat_entry(message),
            ),
            context,
        )


def record_radio_items(
    radios: list[RadioMatch],
    message: Message,
    *,
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> None:
    if radios:
        _record(
            "radio",
            lambda: record_radios(
                radios,
                user=_user_entry(message),
                chat=_chat_entry(message),
            ),
            context,
        )


def record_playlist_items(
    playlists: list[PlaylistMatch],
    message: Message,
    *,
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> None:
    if playlists:
        _record(
            "playlist",
            lambda: record_playlists(
                playlists,
                user=_user_entry(message),
                chat=_chat_entry(message),
            ),
            context,
        )


def record_artist_items(
    artists: list[ArtistMatch],
    message: Message,
    *,
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> None:
    if artists:
        _record(
            "artist",
            lambda: record_artists(
                artists,
                user=_user_entry(message),
                chat=_chat_entry(message),
            ),
            context,
        )


def record_mixed_items(
    tracks: list[TrackMatch],
    videos: list[VideoMatch],
    radios: list[RadioMatch],
    playlists: list[PlaylistMatch],
    artists: list[ArtistMatch],
    message: Message,
    *,
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> None:
    if any((tracks, videos, radios, playlists, artists)):
        _record(
            "mixed",
            lambda: record_mixed(
                tracks,
                videos,
                playlists,
                artists=artists,
                radios=radios,
                user=_user_entry(message),
                chat=_chat_entry(message),
            ),
            context,
        )


def _record(
    label: str,
    callback: Callable[[], object],
    context: ContextTypes.DEFAULT_TYPE | None,
) -> None:
    try:
        stats_data = callback()
    except Exception:
        LOGGER.exception("Could not update %s stats", label)
        return

    kv: KVStore | None = (
        context.application.bot_data.get("kv_store") if context is not None else None
    )
    if kv is None or not isinstance(stats_data, dict):
        return
    try:
        asyncio.get_running_loop().create_task(_persist(kv, stats_data))
    except RuntimeError:
        LOGGER.debug("No running loop to persist stats to KV")


async def _persist(kv: KVStore, stats_data: dict) -> None:
    try:
        existing = await kv.get_json(STATS_KV_KEY)
        await kv.set_json(STATS_KV_KEY, merge_stats(stats_data, existing))
    except Exception:
        LOGGER.debug("Could not persist stats to KV", exc_info=True)


def _user_entry(message: Message) -> dict[str, object] | None:
    user = message.from_user
    if user is None:
        return None
    return {
        "id": user.id,
        "label": f"@{user.username}" if user.username else user.full_name,
        "last_seen": _now(),
    }


def _chat_entry(message: Message) -> dict[str, object]:
    chat = message.chat
    label = chat.title or chat.username or str(chat.id)
    if chat.username:
        label = f"@{chat.username}"
    return {
        "id": chat.id,
        "label": f"{label} ({chat.type})",
        "last_seen": _now(),
    }


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
