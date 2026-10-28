from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from music_links_bot.bot_crate import (
    clear_crate_items,
    item_index,
    load_crate,
    load_crate_title,
    move_crate_item,
    pop_crate_item,
    restore_crate_item,
    restore_crate_items,
)
from music_links_bot.bot_menu import runtime_for, safe_edit, update_lang
from music_links_bot.bot_runtime import CallbackAction, encode_callback
from music_links_bot.bot_storage import remember_bounded
from music_links_bot.constants import channel_target
from music_links_bot.crate_view import render_crate
from music_links_bot.i18n import get_text, resolve_lang
from music_links_bot.input_routing import input_prompt_markup
from music_links_bot.models import TrackMatch
from music_links_bot.release_preferences import release_preference_key
from music_links_bot.sharing import add_share_button, build_crate_share_query
from music_links_bot.telegram_buttons import button as InlineKeyboardButton

CRATE_UNDO_SECONDS = 15
MAX_CRATE_UNDO_RECORDS = 300


async def crate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    user_id = update.effective_user.id if update.effective_user else message.chat_id
    text, keyboard = await load_crate_view(context, user_id, lang=update_lang(update))
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


def is_publisher(context, user_id: int) -> bool:
    admin_chat_id = context.application.bot_data.get("admin_chat_id")
    return admin_chat_id is not None and admin_chat_id == user_id


def crate_view(context, user_id: int, items: list, *, lang: str, title, **options):
    """The collection screen with this user's share and publish buttons."""
    return render_crate(
        items,
        lang=lang,
        title=title,
        share_query=build_crate_share_query(items),
        can_publish=is_publisher(context, user_id),
        **options,
    )


async def load_crate_view(context, user_id: int, *, lang: str, items=None):
    bot_data = context.application.bot_data
    if items is None:
        items = await load_crate(bot_data, user_id)
    title = await load_crate_title(bot_data, user_id)
    return crate_view(context, user_id, items, lang=lang, title=title)


@dataclass(slots=True)
class _CrateTap:
    """One button press on the collection screen and what it acts on."""

    query: Any
    context: Any
    action: CallbackAction
    lang: str
    user_id: int
    title: str
    items: list[dict]
    undo_map: dict
    undo: dict | None

    @property
    def bot_data(self) -> dict:
        return self.context.application.bot_data

    @property
    def reference(self) -> str:
        return self.action.payload


@dataclass(slots=True)
class _CrateChange:
    items: list[dict]
    selected: int | None = None
    notice: str | None = None
    undo: dict | None = None


async def dispatch_crate_action(query, context, action: CallbackAction) -> None:
    if query.from_user is None:
        await query.answer()
        return
    user_id = query.from_user.id
    bot_data = context.application.bot_data
    undo_map = bot_data.setdefault("crate_undo", {})
    tap = _CrateTap(
        query=query,
        context=context,
        action=action,
        lang=resolve_lang(query.from_user.language_code),
        user_id=user_id,
        title=await load_crate_title(bot_data, user_id),
        items=await load_crate(bot_data, user_id),
        undo_map=undo_map,
        undo=_active_undo(undo_map, user_id),
    )
    if (
        action.action in {"up", "down", "remove", "select"}
        and tap.reference.isdigit()
        and len(tap.reference) < 3
    ):
        # Old positional controls cannot safely identify an item after reordering.
        await query.answer(get_text(tap.lang, "state_conflict"), show_alert=True)
        await _show_list(tap, _CrateChange(tap.items, undo=tap.undo))
        return
    screen = _CRATE_SCREENS.get(action.action)
    if screen is not None:
        await screen(tap)
        return
    change = _CRATE_CHANGES.get(action.action)
    if change is None:
        await query.answer()
        return
    result = await change(tap)
    await query.answer(result.notice)
    await _show_list(tap, result)


async def _show_list(tap: _CrateTap, change: _CrateChange) -> None:
    text, keyboard = crate_view(
        tap.context,
        tap.user_id,
        change.items,
        lang=tap.lang,
        title=tap.title,
        selected_index=change.selected,
        can_undo=change.undo is not None,
    )
    await safe_edit(tap.query, text, keyboard)


async def _set_pending(tap: _CrateTap, pending: dict) -> None:
    runtime = runtime_for(tap.context)
    session = await runtime.get_session(tap.user_id, lang=tap.lang)
    session.pending_input = pending
    await runtime.save_session(session)


# Screens: actions that answer with a screen of their own.


async def _ask_for_links(tap: _CrateTap) -> None:
    replacing = tap.action.action == "replace"
    if replacing and item_index(tap.items, tap.reference) < 0:
        await tap.query.answer(get_text(tap.lang, "ed_expired"), show_alert=True)
        return
    if tap.query.message is None:
        await tap.query.answer()
        return
    await _set_pending(
        tap,
        {
            "kind": "collection_replace" if replacing else "collection_links",
            "release_key": tap.reference,
            "created_at": int(time.time()),
        },
    )
    await tap.query.answer()
    back = InlineKeyboardButton(
        get_text(tap.lang, "cancel"), callback_data=encode_callback("crate", "open")
    )
    await safe_edit(
        tap.query,
        get_text(
            tap.lang, "crate_replace_prompt" if replacing else "crate_links_prompt"
        ),
        InlineKeyboardMarkup([[back]]),
    )


async def _ask_for_annotation(tap: _CrateTap) -> None:
    message = tap.query.message
    if message is None or not any(
        release_preference_key(TrackMatch(**{"links": {}, **entry["item"]}))
        == tap.reference
        for entry in tap.items
        if isinstance(entry.get("item"), dict)
    ):
        await tap.query.answer(get_text(tap.lang, "ed_expired"), show_alert=True)
        return
    prompt = await message.reply_text(
        get_text(tap.lang, f"crate_{tap.action.action}_prompt"),
        reply_markup=input_prompt_markup(tap.lang),
    )
    await _set_pending(
        tap,
        {
            "kind": f"crate_{tap.action.action}",
            "release_key": tap.reference,
            "editor_chat_id": message.chat_id,
            "editor_message_id": message.message_id,
            "prompt_message_id": prompt.message_id,
            "created_at": int(time.time()),
        },
    )
    await tap.query.answer()


async def _rename(tap: _CrateTap) -> None:
    await _start_rename(tap.query, tap.context, user_id=tap.user_id, lang=tap.lang)


async def _preview(tap: _CrateTap) -> None:
    await _show_preview(
        tap.query, tap.context, user_id=tap.user_id, lang=tap.lang, title=tap.title
    )


async def _side_screen(tap: _CrateTap) -> None:
    await tap.query.answer()
    text, keyboard = render_crate(
        tap.items, lang=tap.lang, title=tap.title, screen=tap.action.action
    )
    await safe_edit(tap.query, text, keyboard)


async def _confirm_clear(tap: _CrateTap) -> None:
    await tap.query.answer()
    text, keyboard = render_crate(
        tap.items, lang=tap.lang, confirm_clear=True, title=tap.title
    )
    await safe_edit(tap.query, text, keyboard)


async def _publish(tap: _CrateTap) -> None:
    await _publish_crate(
        tap.query,
        tap.context,
        user_id=tap.user_id,
        lang=tap.lang,
        title=tap.title,
        revision=tap.reference,
    )


# Changes: actions that edit the collection and redraw the list.


async def _move(tap: _CrateTap) -> _CrateChange:
    step = -1 if tap.action.action == "up" else 1
    items = await move_crate_item(tap.bot_data, tap.user_id, tap.reference, step)
    return _CrateChange(
        items,
        selected=item_index(items, tap.reference) if items else None,
        notice=get_text(tap.lang, "crate_order_updated"),
        undo=tap.undo,
    )


async def _select(tap: _CrateTap) -> _CrateChange:
    return _CrateChange(
        tap.items, selected=item_index(tap.items, tap.reference), undo=tap.undo
    )


async def _remove(tap: _CrateTap) -> _CrateChange:
    items, undo, selected, notice = await _remove_item(
        tap.bot_data,
        tap.undo_map,
        user_id=tap.user_id,
        index=tap.reference,
        lang=tap.lang,
    )
    return _CrateChange(items, selected=selected, notice=notice, undo=undo)


async def _undo(tap: _CrateTap) -> _CrateChange:
    items, undo, selected, notice = await _restore_last(
        tap.bot_data, tap.undo_map, user_id=tap.user_id, record=tap.undo, lang=tap.lang
    )
    return _CrateChange(items, selected=selected, notice=notice, undo=undo)


async def _clear(tap: _CrateTap) -> _CrateChange:
    _, previous = await clear_crate_items(tap.bot_data, tap.user_id, tap.reference)
    undo = {
        "kind": "clear",
        "items": previous,
        "index": 0,
        "expires_at": time.time() + CRATE_UNDO_SECONDS,
    }
    remember_bounded(tap.undo_map, tap.user_id, undo, max_size=MAX_CRATE_UNDO_RECORDS)
    return _CrateChange([], notice=get_text(tap.lang, "crate_cleared"), undo=undo)


async def _open(tap: _CrateTap) -> _CrateChange:
    if tap.action.action == "open":
        await _set_pending(tap, {})
    return _CrateChange(tap.items, undo=tap.undo)


_CRATE_SCREENS = {
    "add": _ask_for_links,
    "replace": _ask_for_links,
    "note": _ask_for_annotation,
    "section": _ask_for_annotation,
    "rename": _rename,
    "preview": _preview,
    "style": _side_screen,
    "more": _side_screen,
    "clear": _confirm_clear,
    "publish": _publish,
}
_CRATE_CHANGES = {
    "up": _move,
    "down": _move,
    "select": _select,
    "remove": _remove,
    "undo": _undo,
    "clear_confirm": _clear,
    "clear_cancel": _open,
    "open": _open,
}


async def _publish_crate(
    query, context, *, user_id: int, lang: str, title: str, revision: str
) -> None:
    """Post the whole collection to the channel in one tap (owner only)."""
    from telegram.error import TelegramError

    from music_links_bot.bot_crate import crate_revision
    from music_links_bot.collection_plan import build_collection_plan, collection_issues
    from music_links_bot.keyboards import _build_link_preview_options
    from music_links_bot.publication_contract import (
        RenderedPublication,
        require_valid_publication,
    )
    from music_links_bot.sharing import make_channel_safe_keyboard

    if not is_publisher(context, user_id):
        await query.answer(get_text(lang, "ed_admin_only"), show_alert=True)
        return
    items = await load_crate(context.application.bot_data, user_id)
    if not items or revision != crate_revision(items):
        await query.answer(get_text(lang, "state_conflict"), show_alert=True)
        return
    if any(issue.blocking for issue in collection_issues(items)):
        await query.answer(get_text(lang, "crate_fix_first"), show_alert=True)
        return
    tracks = [
        TrackMatch(**{"links": {}, **entry["item"]})
        for entry in items
        if isinstance(entry.get("item"), dict)
    ]
    plan = build_collection_plan(
        tracks,
        context=context,
        title=title or get_text(lang, "crate_preview_title"),
        include_channel_button=False,
    )
    keyboard = make_channel_safe_keyboard(plan.keyboard)
    require_valid_publication(
        RenderedPublication(
            text=plan.text,
            keyboard=keyboard,
            preview_url=plan.preview_url,
            source_urls=plan.source_urls,
            found_count=len(tracks),
            requested_count=len(tracks),
        )
    )
    target = channel_target(context.application.bot_data)
    try:
        sent = await context.bot.send_message(
            chat_id=target,
            text=plan.text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            link_preview_options=_build_link_preview_options(
                plan.preview_url, prefer_large_media=True
            ),
        )
    except TelegramError:
        await query.answer(get_text(lang, "ed_publish_failed"), show_alert=True)
        return
    await query.answer(get_text(lang, "ed_published_toast"))
    from music_links_bot.publication_state import _message_url

    url = _message_url(target, getattr(sent, "message_id", None))
    rows = []
    if url:
        rows.append(
            [InlineKeyboardButton(get_text(lang, "ed_open_publication"), url=url)]
        )
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "crate_back"),
                callback_data=encode_callback("crate", "open"),
            )
        ]
    )
    from music_links_bot.message_effects import celebrate

    text = get_text(lang, "crate_published").format(count=len(tracks))
    keyboard = InlineKeyboardMarkup(rows)
    await celebrate(context.bot, query, edit=lambda: safe_edit(query, text, keyboard))


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


async def _start_rename(query, context, *, user_id: int, lang: str) -> None:
    if query.message is None:
        await query.answer()
        return
    prompt = await query.message.reply_text(
        get_text(lang, "crate_name_prompt"),
        reply_markup=input_prompt_markup(lang),
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
    from music_links_bot.collection_plan import build_collection_plan, collection_issues

    if any(issue.blocking for issue in collection_issues(items)):
        await query.answer()
        text, keyboard = render_crate(items, lang=lang, title=title)
        await safe_edit(query, text, keyboard)
        return
    tracks = [
        TrackMatch(**{"links": {}, **entry["item"]})
        for entry in items
        if isinstance(entry.get("item"), dict)
    ]
    if not tracks:
        await query.answer()
        text, keyboard = render_crate([], lang=lang, title=title)
        await safe_edit(query, text, keyboard)
        return
    plan = build_collection_plan(
        tracks,
        context=context,
        title=title or get_text(lang, "crate_preview_title"),
        include_channel_button=False,
    )
    preview_keyboard = plan.keyboard
    preview_keyboard = add_share_button(
        preview_keyboard,
        share_query=build_crate_share_query(items),
        label=get_text(lang, "share_post"),
    )
    keyboard = InlineKeyboardMarkup(
        [
            *[list(row) for row in preview_keyboard.inline_keyboard],
            [
                InlineKeyboardButton(
                    get_text(lang, "crate_back"),
                    callback_data=encode_callback("crate", "open"),
                )
            ],
        ]
    )
    await query.answer()
    await safe_edit(
        query,
        plan.text,
        keyboard,
    )


async def _remove_item(
    bot_data: dict,
    undo_map: dict,
    *,
    user_id: int,
    index: str,
    lang: str,
) -> tuple[list[dict], dict | None, int | None, str | None]:
    items, (position, removed) = await pop_crate_item(bot_data, user_id, index)
    record = None
    notice = None
    if removed is not None:
        record = {
            "entry": removed,
            "index": position,
            "expires_at": time.time() + CRATE_UNDO_SECONDS,
        }
        remember_bounded(
            undo_map,
            user_id,
            record,
            max_size=MAX_CRATE_UNDO_RECORDS,
        )
        notice = get_text(lang, "crate_removed")
    selected = min(int(position), len(items) - 1) if items else None
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
        items, restored = await restore_crate_items(
            bot_data, user_id, list(record.get("items") or [])
        )
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
