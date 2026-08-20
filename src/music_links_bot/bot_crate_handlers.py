from __future__ import annotations

import time

from telegram import ForceReply, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from music_links_bot.bot_crate import (
    load_crate,
    load_crate_title,
    move_crate_item,
    remove_crate_item,
    restore_crate_item,
    save_crate,
)
from music_links_bot.bot_menu import runtime_for, safe_edit, update_lang
from music_links_bot.bot_runtime import CallbackAction, encode_callback
from music_links_bot.bot_storage import remember_bounded
from music_links_bot.bot_ui import render_crate
from music_links_bot.formatter import format_collection_message
from music_links_bot.i18n import get_text, resolve_lang
from music_links_bot.keyboards import _build_collection_keyboard
from music_links_bot.models import TrackMatch
from music_links_bot.telegram_buttons import button as InlineKeyboardButton

CRATE_UNDO_SECONDS = 15
MAX_CRATE_UNDO_RECORDS = 300


async def crate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    user_id = update.effective_user.id if update.effective_user else message.chat_id
    lang = update_lang(update)
    items = await load_crate(context.application.bot_data, user_id)
    title = await load_crate_title(context.application.bot_data, user_id)
    text, keyboard = render_crate(items, lang=lang, title=title)
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def dispatch_crate_action(query, context, action: CallbackAction) -> None:
    if query.from_user is None:
        await query.answer()
        return
    lang = resolve_lang(query.from_user.language_code)
    user_id = query.from_user.id
    bot_data = context.application.bot_data
    title = await load_crate_title(bot_data, user_id)
    undo_map = bot_data.setdefault("crate_undo", {})
    undo_record = _active_undo(undo_map, user_id)
    index = _item_index(action.payload)
    selected_index: int | None = None
    notice: str | None = None

    if action.action == "rename":
        await _start_rename(query, context, user_id=user_id, lang=lang)
        return
    if action.action == "preview":
        await _show_preview(query, context, user_id=user_id, lang=lang, title=title)
        return
    if action.action == "up":
        items = await move_crate_item(bot_data, user_id, index, -1)
        selected_index = max(0, index - 1)
    elif action.action == "down":
        items = await move_crate_item(bot_data, user_id, index, 1)
        selected_index = min(len(items) - 1, index + 1) if items else None
    elif action.action == "select":
        items = await load_crate(bot_data, user_id)
        selected_index = index
    elif action.action == "remove":
        items, undo_record, selected_index, notice = await _remove_item(
            bot_data,
            undo_map,
            user_id=user_id,
            index=index,
            lang=lang,
        )
    elif action.action == "undo":
        items, undo_record, selected_index, notice = await _restore_last(
            bot_data,
            undo_map,
            user_id=user_id,
            record=undo_record,
            lang=lang,
        )
    elif action.action == "clear":
        items = await load_crate(bot_data, user_id)
        await query.answer()
        text, keyboard = render_crate(items, lang=lang, confirm_clear=True, title=title)
        await safe_edit(query, text, keyboard)
        return
    elif action.action == "clear_confirm":
        previous_items = await load_crate(bot_data, user_id)
        await save_crate(bot_data, user_id, [])
        undo_record = {
            "kind": "clear",
            "items": previous_items,
            "index": 0,
            "expires_at": time.time() + CRATE_UNDO_SECONDS,
        }
        remember_bounded(
            undo_map,
            user_id,
            undo_record,
            max_size=MAX_CRATE_UNDO_RECORDS,
        )
        items = []
    elif action.action in {"clear_cancel", "open"}:
        items = await load_crate(bot_data, user_id)
    else:
        await query.answer()
        return

    await query.answer(notice)
    text, keyboard = render_crate(
        items,
        lang=lang,
        selected_index=selected_index,
        can_undo=undo_record is not None,
        title=title,
    )
    await safe_edit(query, text, keyboard)


def _active_undo(undo_map: dict, user_id: int) -> dict | None:
    now = time.time()
    for key, value in list(undo_map.items()):
        try:
            active = (
                isinstance(value, dict) and float(value.get("expires_at") or 0) > now
            )
        except (TypeError, ValueError):
            active = False
        if not active:
            undo_map.pop(key, None)
    value = undo_map.get(user_id)
    return value if isinstance(value, dict) else None


def _item_index(payload: str) -> int:
    try:
        return int(payload)
    except (TypeError, ValueError):
        return -1


async def _start_rename(query, context, *, user_id: int, lang: str) -> None:
    if query.message is None:
        await query.answer()
        return
    prompt = await query.message.reply_text(
        get_text(lang, "crate_name_prompt"),
        reply_markup=ForceReply(selective=True),
    )
    runtime = runtime_for(context)
    session = await runtime.get_session(user_id, lang=lang)
    session.pending_input = {
        "kind": "crate_title",
        "editor_chat_id": query.message.chat_id,
        "editor_message_id": query.message.message_id,
        "prompt_message_id": prompt.message_id,
        "created_at": int(time.time()),
    }
    await runtime.save_session(session)
    await query.answer()


async def _show_preview(query, context, *, user_id: int, lang: str, title: str) -> None:
    items = await load_crate(context.application.bot_data, user_id)
    tracks = [
        TrackMatch(**entry["item"])
        for entry in items
        if isinstance(entry.get("item"), dict)
    ]
    if not tracks:
        await query.answer()
        text, keyboard = render_crate([], lang=lang, title=title)
        await safe_edit(query, text, keyboard)
        return
    preview_keyboard = _build_collection_keyboard(
        tracks,
        include_channel_button=False,
    )
    keyboard = InlineKeyboardMarkup(
        [
            *[list(row) for row in preview_keyboard.inline_keyboard],
            [
                InlineKeyboardButton(
                    get_text(lang, "back"),
                    callback_data=encode_callback("crate", "open"),
                )
            ],
        ]
    )
    await query.answer()
    await safe_edit(
        query,
        format_collection_message(
            tracks,
            title=title or get_text(lang, "crate_preview_title"),
            include_hashtags=True,
        ),
        keyboard,
    )


async def _remove_item(
    bot_data: dict,
    undo_map: dict,
    *,
    user_id: int,
    index: int,
    lang: str,
) -> tuple[list[dict], dict | None, int | None, str | None]:
    before = await load_crate(bot_data, user_id)
    removed = before[index] if 0 <= index < len(before) else None
    items = await remove_crate_item(bot_data, user_id, index)
    record = None
    notice = None
    if removed is not None:
        record = {
            "entry": removed,
            "index": index,
            "expires_at": time.time() + CRATE_UNDO_SECONDS,
        }
        remember_bounded(
            undo_map,
            user_id,
            record,
            max_size=MAX_CRATE_UNDO_RECORDS,
        )
        notice = get_text(lang, "crate_removed")
    selected = min(index, len(items) - 1) if items else None
    return items, record, selected, notice


async def _restore_last(
    bot_data: dict,
    undo_map: dict,
    *,
    user_id: int,
    record: dict | None,
    lang: str,
) -> tuple[list[dict], dict | None, int | None, str | None]:
    if not record:
        return await load_crate(bot_data, user_id), None, None, None
    if record.get("kind") == "clear":
        items = list(record.get("items") or [])
        await save_crate(bot_data, user_id, items)
        restored = bool(items)
    else:
        items, restored = await restore_crate_item(
            bot_data,
            user_id,
            index=int(record.get("index") or 0),
            entry=record.get("entry") or {},
        )
    if not restored:
        return items, record, None, None
    selected = min(int(record.get("index") or 0), len(items) - 1)
    undo_map.pop(user_id, None)
    return items, None, selected, get_text(lang, "crate_restored")
