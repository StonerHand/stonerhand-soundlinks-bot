from __future__ import annotations

import asyncio
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram import InlineKeyboardMarkup

from music_links_bot.bot_builder import active_card_label
from music_links_bot.bot_history import load_history_items
from music_links_bot.bot_runtime import MAX_RECENT_DRAFTS, encode_callback
from music_links_bot.i18n import get_text
from music_links_bot.publish_queue import QueueStorageError, load_jobs
from music_links_bot.telegram_buttons import button as InlineKeyboardButton

PAGE_SIZE = 5


def _page(items: list, page: int):
    pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    return items[page * PAGE_SIZE : (page + 1) * PAGE_SIZE], page, pages


def _navigation(rows: list, *, lang: str, action: str, page: int, pages: int) -> None:
    navigation = []
    for target, key in ((page - 1, "queue_previous"), (page + 1, "queue_next")):
        if 0 <= target < pages:
            navigation.append(
                InlineKeyboardButton(
                    get_text(lang, key),
                    callback_data=encode_callback("menu", action, str(target)),
                )
            )
    if navigation:
        rows.append(navigation)
    rows.append([_home_button(lang)])


async def render_drafts_view(
    context, *, user_id: int, lang: str, draft_ids: list[str], load_draft, page: int = 0
) -> tuple[str, InlineKeyboardMarkup]:
    ids = list(dict.fromkeys(draft_ids[:MAX_RECENT_DRAFTS]))
    values = await asyncio.gather(*(load_draft(context, draft_id) for draft_id in ids))
    drafts = [
        (draft_id, draft)
        for draft_id, draft in zip(ids, values, strict=True)
        if isinstance(draft, dict)
        and isinstance(draft.get("item"), dict)
        and not draft.get("deleted_at")
        and draft.get("chat_id") == user_id
    ]
    if not drafts:
        return _empty_view(lang, "drafts_empty")
    queued: dict[str, dict] = {}
    queue_available = True
    if context.application.bot_data.get("admin_chat_id") == user_id:
        try:
            queued = {
                str(job.get("draft", {}).get("editor_draft_id")): job
                for job in await load_jobs(context)
                if isinstance(job.get("draft"), dict)
                and job["draft"].get("chat_id") == user_id
            }
        except QueueStorageError:
            queue_available = False
    visible, page, pages = _page(drafts, page)
    lines = [
        get_text(lang, "drafts_title"),
        get_text(lang, "queue_page").format(page=page + 1, pages=pages),
    ]
    rows = []
    zone = str(context.application.bot_data.get("timezone_name") or "Europe/Moscow")
    for index, (draft_id, draft) in enumerate(visible, start=page * PAGE_SIZE + 1):
        item = dict(draft["item"])
        item.setdefault("ts", draft.get("created_at"))
        _append_recent_line(lines, index, item, lang=lang, timezone_name=zone)
        job = queued.get(draft_id)
        if job:
            status_key = {
                "processing": "draft_sending",
                "delivering": "draft_sending",
                "uncertain": "draft_uncertain",
            }.get(job.get("status"), "draft_scheduled")
        elif draft.get("scheduled_at") and not queue_available:
            status_key = "draft_queue_unknown"
        elif draft.get("published_at"):
            status_key = "draft_published"
        else:
            status_key = "draft_editable"
        lines.append(f"<i>{escape(get_text(lang, status_key))}</i>")
        rows.append(
            [
                InlineKeyboardButton(
                    active_card_label(draft, get_text(lang, "drafts_open")),
                    callback_data=encode_callback("editor", "b", draft_id),
                )
            ]
        )
    _navigation(rows, lang=lang, action="drafts", page=page, pages=pages)
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def render_recent_view(
    context, *, user_id: int, lang: str, page: int = 0
) -> tuple[str, InlineKeyboardMarkup]:
    history = await load_history_items(context, user_id)
    if not history:
        return _empty_view(lang, "recent_empty")
    visible, page, pages = _page(history, page)
    lines = [
        get_text(lang, "recent_title"),
        get_text(lang, "queue_page").format(page=page + 1, pages=pages),
    ]
    rows = []
    zone = str(context.application.bot_data.get("timezone_name") or "Europe/Moscow")
    for index, item in enumerate(visible, start=page * PAGE_SIZE + 1):
        _append_recent_line(lines, index, item, lang=lang, timezone_name=zone)
        rows.append(
            [
                InlineKeyboardButton(
                    active_card_label({"item": item}, get_text(lang, "recent_repeat")),
                    switch_inline_query_current_chat=str(item.get("source_url") or "")[
                        :256
                    ],
                )
            ]
        )
    _navigation(rows, lang=lang, action="recent", page=page, pages=pages)
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _append_recent_line(
    lines: list[str],
    index: int,
    item: dict,
    *,
    lang: str,
    timezone_name: str = "Europe/Moscow",
) -> None:
    when = ""
    timestamp = item.get("ts")
    if isinstance(timestamp, (int, float)) and 0 < timestamp < 253402300800:
        try:
            zone = ZoneInfo(timezone_name)
            moment = datetime.fromtimestamp(timestamp, zone)
            today = datetime.now(zone).date()
            when = moment.strftime(
                ("today" if lang == "en" else "сегодня") + " · %H:%M"
                if moment.date() == today
                else "%d.%m · %H:%M"
            )
        except (ValueError, OverflowError, OSError, ZoneInfoNotFoundError):
            pass
    label = " — ".join(str(item.get(key) or "—")[:180] for key in ("artist", "title"))
    lines.append(
        f"\n<b>{index}. {escape(label)}</b>"
        + (f"\n<i>{escape(when)}</i>" if when else "")
    )


def _empty_view(lang: str, key: str) -> tuple[str, InlineKeyboardMarkup]:
    return get_text(lang, key), InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    get_text(lang, "home_create"),
                    callback_data=encode_callback("menu", "create"),
                    style="primary",
                )
            ],
            [_home_button(lang)],
        ]
    )


def _home_button(lang: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        get_text(lang, "home_back"), callback_data=encode_callback("menu", "start")
    )
