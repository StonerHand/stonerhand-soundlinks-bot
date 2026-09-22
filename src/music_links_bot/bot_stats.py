from __future__ import annotations

import asyncio
import logging
import re
import secrets
from collections.abc import Callable
from datetime import datetime, timezone

from telegram import Message, MessageEntity
from telegram.ext import ContextTypes

from music_links_bot.constants import STATS_KV_KEY
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
    STATS_PATH,
    record_artists,
    record_matches,
    record_mixed,
    record_playlists,
    record_radios,
    record_videos,
)
from music_links_bot.telegram_text import format_user_note_html
from music_links_bot.url_utils import (
    URL_RE,
    cache_key_for_url,
    clean_url_token,
    is_supported_music_url,
)

LOGGER = logging.getLogger(__name__)
MAX_USER_NOTE_LENGTH = 3_000


def message_text(message: Message) -> str | None:
    return message.text or message.caption


def message_entities(message: Message) -> tuple[MessageEntity, ...]:
    if message.text is not None:
        return tuple(getattr(message, "entities", None) or ())
    return tuple(getattr(message, "caption_entities", None) or ())


def message_source_urls(message: Message, *, text: str | None = None) -> list[str]:
    """Return every visible or entity-backed music URL in message order.

    Telegram can hide a URL behind linked text. Looking only at ``text`` or
    ``caption`` silently misses those sources, so merge explicit text links
    with URLs visible in the message and deduplicate tracking variants.
    """
    source_text = text if text is not None else (message_text(message) or "")
    candidates: list[tuple[int, str]] = [
        (
            len(source_text[: match.start()].encode("utf-16-le")) // 2,
            clean_url_token(match.group(0)),
        )
        for match in URL_RE.finditer(source_text)
    ]
    for entity in message_entities(message):
        if entity.type != MessageEntity.TEXT_LINK or not entity.url:
            continue
        candidates.append((entity.offset, str(entity.url).strip()))

    urls: list[str] = []
    seen: set[str] = set()
    for _offset, candidate in sorted(candidates, key=lambda item: item[0]):
        key = cache_key_for_url(candidate)
        if key in seen or not is_supported_music_url(candidate):
            continue
        urls.append(candidate)
        seen.add(key)
    return urls


def build_user_prefix(message: Message, *, bot_username: str | None = None) -> str:
    body_html = format_user_note_html(
        message_text(message),
        message_entities(message),
        max_length=MAX_USER_NOTE_LENGTH,
    )
    if bot_username:
        body_html = re.sub(
            rf"^@{re.escape(bot_username)}\b[\s,:;—–-]*",
            "",
            body_html,
            flags=re.IGNORECASE,
        ).strip()
    if not body_html:
        return ""

    user = message.from_user
    author_label = None
    if user is not None:
        author_label = f"@{user.username}" if user.username else user.full_name
    return prepend_user_html(body_html, author_label=author_label)


async def record_tracks(
    tracks: list[TrackMatch],
    message: Message,
    *,
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> None:
    if tracks:
        await _record(
            "track",
            lambda: record_matches(
                tracks,
                path=_stats_path(context),
                user=_user_entry(message),
                chat=_chat_entry(message),
            ),
            context,
            event_id=_event_id(message),
        )


async def record_video_items(
    videos: list[VideoMatch],
    message: Message,
    *,
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> None:
    if videos:
        await _record(
            "video",
            lambda: record_videos(
                videos,
                path=_stats_path(context),
                user=_user_entry(message),
                chat=_chat_entry(message),
            ),
            context,
            event_id=_event_id(message),
        )


async def record_radio_items(
    radios: list[RadioMatch],
    message: Message,
    *,
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> None:
    if radios:
        await _record(
            "radio",
            lambda: record_radios(
                radios,
                path=_stats_path(context),
                user=_user_entry(message),
                chat=_chat_entry(message),
            ),
            context,
            event_id=_event_id(message),
        )


async def record_playlist_items(
    playlists: list[PlaylistMatch],
    message: Message,
    *,
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> None:
    if playlists:
        await _record(
            "playlist",
            lambda: record_playlists(
                playlists,
                path=_stats_path(context),
                user=_user_entry(message),
                chat=_chat_entry(message),
            ),
            context,
            event_id=_event_id(message),
        )


async def record_artist_items(
    artists: list[ArtistMatch],
    message: Message,
    *,
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> None:
    if artists:
        await _record(
            "artist",
            lambda: record_artists(
                artists,
                path=_stats_path(context),
                user=_user_entry(message),
                chat=_chat_entry(message),
            ),
            context,
            event_id=_event_id(message),
        )


async def record_mixed_items(
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
        await _record(
            "mixed",
            lambda: record_mixed(
                tracks,
                videos,
                playlists,
                artists=artists,
                radios=radios,
                path=_stats_path(context),
                user=_user_entry(message),
                chat=_chat_entry(message),
            ),
            context,
            event_id=_event_id(message),
        )


async def _record(
    label: str,
    callback: Callable[[], object],
    context: ContextTypes.DEFAULT_TYPE | None,
    *,
    event_id: str,
) -> None:
    try:
        stats_data = await asyncio.to_thread(callback)
    except Exception:
        LOGGER.exception("Could not update %s stats", label)
        return

    kv: KVStore | None = (
        context.application.bot_data.get("kv_store") if context is not None else None
    )
    if kv is None or not isinstance(stats_data, dict):
        return
    try:
        await _persist(kv, stats_data, event_id=f"{label}:{event_id}")
    except Exception:
        LOGGER.warning("Could not persist activity event", exc_info=True)


async def _persist(kv: KVStore, stats_data: dict, *, event_id: str) -> None:
    await kv.record_activity_event(STATS_KV_KEY, event_id, stats_data)


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


def _event_id(message):
    message_id = getattr(message, "message_id", None)
    return f"{message.chat_id}:{message_id}" if message_id else secrets.token_hex(12)


def _stats_path(context):
    # None builds one pure event delta; only standalone polling needs a file.
    if context is not None and context.application.bot_data.get("kv_store") is not None:
        return None
    return STATS_PATH
