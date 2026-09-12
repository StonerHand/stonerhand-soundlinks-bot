"""Explicit routing for links arriving while another input is being edited."""

from __future__ import annotations

import secrets
import time
from contextvars import ContextVar

from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode

from music_links_bot.bot_runtime import encode_callback
from music_links_bot.durable_state import read_json, write_json
from music_links_bot.i18n import get_text
from music_links_bot.telegram_buttons import button
from music_links_bot.url_utils import extract_supported_urls

collection_input: ContextVar[str] = ContextVar("collection_input", default="")


async def guard_input(update, context, *, text):
    from music_links_bot.bot_menu import runtime_for, update_lang

    message, user = update.effective_message, update.effective_user
    if message is None or user is None or message.chat.type != "private":
        return False
    runtime = runtime_for(context)
    session = await runtime.get_session(user.id, lang=update_lang(update))
    pending = session.pending_input
    if not pending or int(pending.get("created_at") or 0) + 900 < time.time():
        return False
    urls = extract_supported_urls(text)
    kind = pending.get("kind")
    if kind in {"collection_links", "collection_replace"}:
        if not urls or (kind == "collection_replace" and len(urls) != 1):
            await message.reply_text(
                get_text(
                    update_lang(update),
                    "crate_links_prompt"
                    if kind == "collection_links"
                    else "crate_replace_prompt",
                )
            )
            return True
        collection_input.set(
            "add"
            if kind == "collection_links"
            else str(pending.get("release_key") or "")
        )
        session.pending_input = {}
        await runtime.save_session(session)
        return False
    reply = getattr(message, "reply_to_message", None)
    explicit_reply = reply is not None and getattr(
        reply, "message_id", None
    ) == pending.get("prompt_message_id")
    if (
        kind
        not in {
            "intro",
            "hashtags",
            "cover",
            "crate_title",
            "crate_note",
            "crate_section",
            "template_name",
            "schedule",
        }
        or not urls
        or explicit_reply
    ):
        return False
    choice_id = secrets.token_hex(8)
    payload = {"user_id": user.id, "text": text[:4096], "created_at": int(time.time())}
    kv = context.application.bot_data.get("kv_store")
    if kv:
        await write_json(kv, f"input-choice:v1:{choice_id}", payload, ttl_seconds=900)
    else:
        from music_links_bot.bot_storage import remember_bounded

        remember_bounded(
            context.application.bot_data.setdefault("input_choices", {}),
            choice_id,
            payload,
            max_size=300,
        )
    rows = [
        [
            button(
                get_text(update_lang(update), key),
                callback_data=encode_callback("input", action, choice_id),
                style="primary" if action == "new" else None,
            )
        ]
        for key, action in (
            ("input_new_post", "new"),
            ("input_add_crate", "add"),
            ("input_continue", "back"),
        )
    ]
    await message.reply_text(
        get_text(update_lang(update), "input_choose"),
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return True


async def dispatch_input_action(query, context, action):
    from music_links_bot import bot
    from music_links_bot.bot_menu import runtime_for, safe_edit, update_lang
    from music_links_bot.bot_storage import valid_state_id

    if (
        query.from_user is None
        or query.message is None
        or not valid_state_id(action.payload)
        or action.action not in {"new", "add", "back"}
    ):
        await query.answer()
        return
    lang = update_lang(Update(0, callback_query=query))
    kv = context.application.bot_data.get("kv_store")
    value = (
        await read_json(kv, f"input-choice:v1:{action.payload}")
        if kv
        else context.application.bot_data.get("input_choices", {}).get(action.payload)
    )
    if (
        not isinstance(value, dict)
        or value.get("user_id") != query.from_user.id
        or value.get("created_at", 0) + 900 < time.time()
    ):
        await query.answer(get_text(lang, "ed_expired"), show_alert=True)
        return
    from music_links_bot.state_mutations import StateConflictError, mutate_json

    def consume(current):
        if not isinstance(current, dict) or current.get("consumed"):
            raise StateConflictError("Input choice already handled")
        return {**current, "consumed": True}

    try:
        if kv:
            await mutate_json(
                kv, f"input-choice:v1:{action.payload}", consume, ttl_seconds=900
            )
        else:
            context.application.bot_data["input_choices"][action.payload] = consume(
                value
            )
    except StateConflictError:
        await query.answer(get_text(lang, "ed_expired"), show_alert=True)
        return
    if action.action == "back":
        await query.answer()
        await safe_edit(query, get_text(lang, "input_continue_hint"), None)
        return
    runtime = runtime_for(context)
    session = await runtime.get_session(query.from_user.id, lang=lang)
    session.pending_input = {}
    await runtime.save_session(session)
    await query.answer()
    input_token = bot._INPUT_OVERRIDE.set(value["text"])
    mode_token = collection_input.set("add" if action.action == "add" else "new")
    try:
        await bot.track_lookup_message(Update(0, callback_query=query), context)
    finally:
        collection_input.reset(mode_token)
        bot._INPUT_OVERRIDE.reset(input_token)


async def deliver_collection_input(message, context, tracks, *, user_id, lang):
    """Return True once an explicitly requested collection edit was handled."""
    from dataclasses import asdict

    from music_links_bot import bot
    from music_links_bot.bot_crate import load_crate_title, replace_crate_item
    from music_links_bot.bot_ui import render_crate
    from music_links_bot.sharing import build_crate_share_query

    mode = collection_input.get()
    if not mode or mode == "new":
        return False
    if mode == "add":
        items, count = await bot._add_track_drafts_to_crate(
            message, context, tracks, user_id=user_id, lang=lang
        )
        if count < len(tracks):
            await message.reply_text(
                get_text(lang, "crate_added_count").format(
                    added=count, total=len(tracks)
                )
            )
    else:
        if len(tracks) != 1:
            await message.reply_text(get_text(lang, "crate_replace_prompt"))
            return True
        items = await replace_crate_item(
            context.application.bot_data, user_id, mode, asdict(tracks[0])
        )
    title = await load_crate_title(context.application.bot_data, user_id)
    text, keyboard = render_crate(
        items, lang=lang, title=title, share_query=build_crate_share_query(items)
    )
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    return True
