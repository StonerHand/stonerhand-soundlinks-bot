from __future__ import annotations

from html import escape

from telegram import InlineKeyboardMarkup
from telegram.constants import ParseMode

from music_links_bot.bot_builder import format_schedule_datetime
from music_links_bot.bot_runtime import CallbackAction, encode_callback
from music_links_bot.i18n import get_text, resolve_lang
from music_links_bot.publish_queue import (
    QueueBusyError,
    QueueStorageError,
    load_jobs,
    remove_job,
)
from music_links_bot.telegram_buttons import button as InlineKeyboardButton

QUEUE_PAGE_SIZE = 8


def _is_admin(context, user_id: int) -> bool:
    return bool(
        user_id and context.application.bot_data.get("admin_chat_id") == user_id
    )


def _page_number(value: str | None) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


async def render_queue(
    context,
    *,
    lang: str,
    page: int = 0,
) -> tuple[str, InlineKeyboardMarkup]:
    try:
        jobs = await load_jobs(context)
    except QueueStorageError:
        return (
            get_text(lang, "queue_unavailable"),
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            get_text(lang, "home_back"),
                            callback_data=encode_callback("menu", "start"),
                        )
                    ]
                ]
            ),
        )
    timezone_name = str(
        context.application.bot_data.get("timezone_name") or "Europe/Moscow"
    )
    page_count = max(1, (len(jobs) + QUEUE_PAGE_SIZE - 1) // QUEUE_PAGE_SIZE)
    page = min(max(0, page), page_count - 1)
    page_start = page * QUEUE_PAGE_SIZE
    visible_jobs = jobs[page_start : page_start + QUEUE_PAGE_SIZE]
    lines = [get_text(lang, "queue_title").format(count=len(jobs))]
    if page_count > 1:
        lines.append(
            "\n" + get_text(lang, "queue_page").format(page=page + 1, pages=page_count)
        )
    rows: list[list[InlineKeyboardButton]] = []
    if not jobs:
        lines.extend(["", get_text(lang, "queue_empty")])
    for index, job in enumerate(visible_jobs, start=page_start + 1):
        draft = job.get("draft") if isinstance(job.get("draft"), dict) else {}
        item = draft.get("item") if isinstance(draft.get("item"), dict) else {}
        label = " — ".join(
            part
            for part in (
                str(item.get("artist") or "").strip(),
                str(item.get("title") or "").strip(),
            )
            if part
        ) or get_text(lang, "queue_unknown")
        try:
            when = format_schedule_datetime(
                int(job.get("publish_at") or 0), timezone_name=timezone_name
            )
        except (TypeError, ValueError, OverflowError):
            when = "—"
        lines.append(
            f"\n\n<b>{index}. {escape(label[:120])}</b>\n<code>{escape(when)}</code>"
        )
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "queue_cancel_item").format(index=index),
                    callback_data=encode_callback(
                        "queue", "cancel", f"{page}:{job.get('id') or ''}"
                    ),
                )
            ]
        )
    if page_count > 1:
        navigation: list[InlineKeyboardButton] = []
        if page > 0:
            navigation.append(
                InlineKeyboardButton(
                    "‹",
                    callback_data=encode_callback("queue", "open", str(page - 1)),
                )
            )
        navigation.append(
            InlineKeyboardButton(
                f"{page + 1} / {page_count}",
                callback_data=encode_callback("queue", "open", str(page)),
            )
        )
        if page + 1 < page_count:
            navigation.append(
                InlineKeyboardButton(
                    "›",
                    callback_data=encode_callback("queue", "open", str(page + 1)),
                )
            )
        rows.append(navigation)
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    get_text(lang, "queue_refresh"),
                    callback_data=encode_callback("queue", "open", str(page)),
                )
            ],
            [
                InlineKeyboardButton(
                    get_text(lang, "home_back"),
                    callback_data=encode_callback("menu", "start"),
                )
            ],
        ]
    )
    return "".join(lines), InlineKeyboardMarkup(rows)


async def dispatch_queue_action(query, context, action: CallbackAction) -> None:
    user = query.from_user
    lang = resolve_lang(user.language_code if user else None)
    if user is None or not _is_admin(context, user.id):
        await query.answer(get_text(lang, "ed_admin_only"), show_alert=True)
        return
    page = _page_number(action.payload if action.action == "open" else None)
    if action.action == "cancel" and action.payload:
        raw_page, separator, job_id = action.payload.partition(":")
        if separator:
            page = _page_number(raw_page)
        else:
            job_id = action.payload
        try:
            removed = await remove_job(context, job_id)
        except (QueueBusyError, QueueStorageError):
            await query.answer(get_text(lang, "queue_unavailable"), show_alert=True)
            return
        await query.answer(
            get_text(lang, "queue_cancelled" if removed else "queue_missing")
        )
    else:
        await query.answer()
    text, keyboard = await render_queue(context, lang=lang, page=page)
    await query.edit_message_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
