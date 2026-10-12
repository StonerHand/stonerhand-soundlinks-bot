from __future__ import annotations

import asyncio
import time
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram import InlineKeyboardMarkup

from music_links_bot.bot_builder import active_card_label
from music_links_bot.bot_history import load_history_items
from music_links_bot.bot_runtime import encode_callback
from music_links_bot.human_time import human_date, human_datetime
from music_links_bot.i18n import get_text
from music_links_bot.publish_queue import QueueStorageError, load_jobs
from music_links_bot.telegram_buttons import button as InlineKeyboardButton

PAGE_SIZE = 6
EXPIRY_WARNING_SECONDS = 2 * 86400
STATUS_ICONS = {
    "draft_editable": "📝",
    "draft_scheduled": "🕒",
    "draft_sending": "⏳",
    "draft_uncertain": "⚠️",
    "draft_queue_unknown": "🕒",
    "draft_published": "✅",
}


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
    context,
    *,
    user_id: int,
    lang: str,
    draft_ids: list[str],
    load_draft,
    page: int = 0,
    filter_by: str = "all",
    search: str = "",
    load_many=None,
) -> tuple[str, InlineKeyboardMarkup]:
    from music_links_bot.bot_storage import valid_state_id

    ids = list(
        dict.fromkeys(value for value in draft_ids[:60] if valid_state_id(value))
    )
    values = (
        await load_many(context, ids)
        if load_many
        else await asyncio.gather(*(load_draft(context, draft_id) for draft_id in ids))
    )
    drafts = [
        (key, draft)
        for key, draft in zip(ids, values, strict=True)
        if isinstance(draft, dict)
        and isinstance(draft.get("item"), dict)
        and not draft.get("deleted_at")
        and draft.get("chat_id") == user_id
    ]
    queued = {}
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

    def status(key, draft):
        job = queued.get(key)
        if job:
            return {
                "processing": "draft_sending",
                "delivering": "draft_sending",
                "uncertain": "draft_uncertain",
            }.get(job.get("status"), "draft_scheduled")
        if draft.get("scheduled_at") and not queue_available:
            return "draft_queue_unknown"
        return "draft_published" if draft.get("published_at") else "draft_editable"

    def matches(key, draft):
        state = status(key, draft)
        category = (
            "draft"
            if state == "draft_editable"
            else "published"
            if state == "draft_published"
            else "scheduled"
        )
        return (
            filter_by == "all"
            or category == filter_by
            or (filter_by == "saved" and draft.get("saved_at"))
        ) and search.casefold() in (
            str(draft["item"].get("artist", ""))
            + " "
            + str(draft["item"].get("title", ""))
        ).casefold()

    drafts = [(key, draft) for key, draft in drafts if matches(key, draft)]
    drafts.sort(
        key=lambda pair: (
            bool(pair[1].get("saved_at")),
            int(pair[1].get("saved_at") or pair[1].get("created_at") or 0),
        ),
        reverse=True,
    )
    visible, page, pages = _page(drafts, page)
    heading = get_text(lang, "drafts_title")
    if pages > 1:
        heading += f" · {page + 1}/{pages}"
    lines = [heading]
    if search:
        lines.append("🔎 " + escape(search))
    lines.append(
        "<i>" + get_text(lang, "posts_hint" if visible else "posts_no_match") + "</i>"
        if visible or filter_by != "all" or search
        else get_text(lang, "drafts_empty")
    )
    rows = [
        [
            InlineKeyboardButton(
                ("✓ " if key == filter_by else "") + get_text(lang, "posts_" + key),
                callback_data=encode_callback("menu", "postfilter", key),
            )
            for key in ("all", "draft", "scheduled", "published", "saved")
        ]
    ]
    zone = str(context.application.bot_data.get("timezone_name") or "Europe/Moscow")
    now = time.time()
    for draft_id, draft in visible:
        state = status(draft_id, draft)
        moment = (
            queued.get(draft_id, {}).get("publish_at")
            if state == "draft_scheduled"
            else draft.get("published_at") or draft.get("created_at")
        )
        when = (
            human_date(moment, timezone_name=zone, lang=lang)
            if isinstance(moment, (int, float))
            else ""
        )
        if state == "draft_scheduled" and isinstance(moment, (int, float)):
            when = human_datetime(moment, timezone_name=zone, lang=lang)
        expires_at = draft.get("expires_at")
        if (
            not draft.get("saved_at")
            and isinstance(expires_at, (int, float))
            and 0 < expires_at - now < EXPIRY_WARNING_SECONDS
        ):
            when = "⏳ " + get_text(lang, "posts_expiring")
        icon = "🔖" if draft.get("saved_at") else STATUS_ICONS.get(state, "📝")
        label = f"{icon} " + active_card_label(
            draft, get_text(lang, "drafts_open"), max_length=34
        )
        if when:
            label += f" · {when}"
        rows.append(
            [
                InlineKeyboardButton(
                    label, callback_data=encode_callback("editor", "b", draft_id)
                )
            ]
        )
    if not visible:
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "home_create"),
                    callback_data=encode_callback("menu", "create"),
                    style="primary",
                )
            ]
        )
    search_row = [
        InlineKeyboardButton(
            get_text(lang, "posts_search"),
            callback_data=encode_callback("menu", "postsearch"),
        )
    ]
    if search:
        search_row.append(
            InlineKeyboardButton(
                get_text(lang, "posts_search_clear"),
                callback_data=encode_callback("menu", "postsearch_clear"),
            )
        )
    rows.append(search_row)
    _navigation(rows, lang=lang, action="drafts", page=page, pages=pages)
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def render_search_view(
    context, *, user_id: int, lang: str
) -> tuple[str, InlineKeyboardMarkup]:
    """Search screen: type a query, or reopen one of the latest releases."""
    history = (await load_history_items(context, user_id))[:5]
    lines = [get_text(lang, "posts_search_title")]
    rows = []
    if history:
        lines.extend(["", get_text(lang, "posts_recent_title")])
        rows.extend(
            [
                InlineKeyboardButton(
                    "🔁 " + active_card_label({"item": item}, "—", max_length=40),
                    switch_inline_query_current_chat=str(item.get("source_url") or "")[
                        :256
                    ],
                )
            ]
            for item in history
            if item.get("source_url")
        )
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "library_back"),
                callback_data=encode_callback("menu", "drafts"),
            )
        ]
    )
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
