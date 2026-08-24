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


def _is_admin(context, user_id: int) -> bool:
    return bool(
        user_id and context.application.bot_data.get("admin_chat_id") == user_id
    )


async def render_queue(context, *, lang: str) -> tuple[str, InlineKeyboardMarkup]:
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
    lines = [get_text(lang, "queue_title").format(count=len(jobs))]
    rows: list[list[InlineKeyboardButton]] = []
    if not jobs:
        lines.extend(["", get_text(lang, "queue_empty")])
    for index, job in enumerate(jobs[:10], start=1):
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
                        "queue", "cancel", str(job.get("id") or "")
                    ),
                )
            ]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    get_text(lang, "queue_refresh"),
                    callback_data=encode_callback("queue", "open"),
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
    if action.action == "cancel" and action.payload:
        try:
            removed = await remove_job(context, action.payload)
        except (QueueBusyError, QueueStorageError):
            await query.answer(get_text(lang, "queue_unavailable"), show_alert=True)
            return
        await query.answer(
            get_text(lang, "queue_cancelled" if removed else "queue_missing")
        )
    else:
        await query.answer()
    text, keyboard = await render_queue(context, lang=lang)
    await query.edit_message_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
