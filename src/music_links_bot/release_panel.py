"""Public release metadata only; personal editor state never enters shared panels."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from time import time

from telegram import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
)
from telegram.error import TelegramError

from music_links_bot.bot_storage import remember_bounded
from music_links_bot.formatter import format_track_message
from music_links_bot.i18n import get_text, resolve_lang
from music_links_bot.keyboards import _build_link_keyboard
from music_links_bot.models import TrackMatch
from music_links_bot.sharing import track_share_url
from music_links_bot.telegram_gateway import TelegramApiGateway
from music_links_bot.telegram_text import telegram_text_length
from music_links_bot.telegram_updates import native_field
from music_links_bot.url_utils import direct_platform_links

PANEL_TTL = 180 * 24 * 3600
TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")


def copy_rows(track, *, lang):
    label = f"{track.artist} — {track.title}" if track.artist else track.title
    link = track_share_url(track)
    return [
        [InlineKeyboardButton(get_text(lang, key), copy_text=CopyTextButton(value))]
        for key, value in (("copy_release_name", label), ("copy_release_link", link))
        if value and telegram_text_length(value) <= 256
    ]


async def add_release_panel(keyboard, context, track, *, inline=False, lang="ru"):
    if not track.links or track.kind not in {"song", "album", "podcast"}:
        return keyboard
    payload = asdict(track)
    payload["links"] = direct_platform_links(track.links)
    token = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[
        :32
    ]
    bot_data = context.application.bot_data
    cache = bot_data.setdefault("release_panels", {})
    cached = cache.get(token)
    if cached is None or cached[0] <= time():
        kv = bot_data.get("kv_store")
        if kv is not None and not await kv.set_json(
            "release-panel:v1:" + token, payload, ttl_seconds=PANEL_TTL
        ):
            return keyboard
        remember_bounded(cache, token, (time() + PANEL_TTL, payload), max_size=500)
    label = get_text(lang, "release_panel_open")
    if inline:
        username = getattr(context.bot, "username", None)
        if not username:
            return keyboard
        button = InlineKeyboardButton(
            label, url=f"https://t.me/{username}?start=release_{token}"
        )
    else:
        button = InlineKeyboardButton(label, callback_data="release:open:" + token)
    rows = [list(row) for row in keyboard.inline_keyboard]
    if rows and len(rows[-1]) == 1 and rows[-1][0].switch_inline_query is not None:
        rows[-1].append(button)
    else:
        rows.append([button])
    return InlineKeyboardMarkup(rows)


async def load_panel(context, token):
    if not TOKEN_RE.fullmatch(token):
        return None
    data = context.application.bot_data
    cached = data.get("release_panels", {}).get(token)
    payload = cached[1] if cached and cached[0] > time() else None
    kv = data.get("kv_store")
    if payload is None and kv is not None:
        payload = await kv.get_json("release-panel:v1:" + token)
    if not isinstance(payload, dict):
        return None
    try:
        return TrackMatch(**payload)
    except (TypeError, ValueError):
        return None


def panel_view(track, *, lang, close=False):
    keyboard = _build_link_keyboard(
        track.links,
        release_page_url=track.page_url,
        release_kind=track.kind,
        release_format=track.release_format,
        max_visible_platforms=len(track.links),
    )
    rows = [
        *[list(row) for row in keyboard.inline_keyboard],
        *copy_rows(track, lang=lang),
    ]
    if close:
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "release_panel_close"), callback_data="release:close"
                )
            ]
        )
    return format_track_message(track, include_hashtags=False), InlineKeyboardMarkup(
        rows
    )


async def start_release_panel(update, context):
    message = update.effective_message
    if message is None or message.chat.type != "private":
        return False
    args = getattr(context, "args", None) or []
    if len(args) != 1 or not args[0].startswith("release_"):
        return False
    lang = resolve_lang(
        update.effective_user.language_code if update.effective_user else None
    )
    track = await load_panel(context, args[0][8:])
    if track is None:
        await message.reply_text(get_text(lang, "release_panel_expired"))
    else:
        text, keyboard = panel_view(track, lang=lang)
        await message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    return True


async def release_panel_callback(update, context):
    query = update.callback_query
    if query is None or query.from_user is None:
        return
    lang = resolve_lang(query.from_user.language_code)
    message = query.message
    ephemeral_id = native_field(message, "ephemeral_message_id") if message else None
    gateway = TelegramApiGateway(bot=context.bot)
    if query.data == "release:close":
        if ephemeral_id and message:
            await gateway.request(
                "deleteEphemeralMessage",
                {
                    "chat_id": message.chat_id,
                    "receiver_user_id": query.from_user.id,
                    "ephemeral_message_id": ephemeral_id,
                },
            )
        await query.answer()
        return
    token = (query.data or "").removeprefix("release:open:")
    track = await load_panel(context, token)
    if track is None:
        await query.answer(get_text(lang, "release_panel_expired"), show_alert=True)
        return
    if message is None:
        await query.answer(
            url=f"https://t.me/{context.bot.username}?start=release_{token}"
        )
        return
    text, keyboard = panel_view(track, lang=lang, close=True)
    data = {
        "chat_id": message.chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": keyboard.to_dict(),
        "link_preview_options": {"is_disabled": True},
    }
    try:
        if ephemeral_id:
            data.update(
                receiver_user_id=query.from_user.id, ephemeral_message_id=ephemeral_id
            )
            await gateway.request("editEphemeralMessageText", data)
        elif message.chat.type in {"group", "supergroup", "channel"}:
            data["ephemeral_message_parameters"] = {
                "receiver_user_id": query.from_user.id,
                "callback_query_id": query.id,
                "replace_callback_query_message": True,
            }
            await gateway.request("sendMessage", data)
        else:
            text, keyboard = panel_view(track, lang=lang)
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
    except TelegramError:
        # An unavailable private overlay must never become a public message.
        await query.answer(
            url=f"https://t.me/{context.bot.username}?start=release_{token}"
        )
        return
    await query.answer()
