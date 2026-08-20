from __future__ import annotations

from html import escape

from telegram import InlineKeyboardMarkup
from telegram.constants import ParseMode

from music_links_bot.bot_runtime import encode_callback
from music_links_bot.bot_storage import store_retry_sources
from music_links_bot.i18n import get_text
from music_links_bot.telegram_buttons import ButtonTone, callback_button


async def send_partial_lookup_status(
    message,
    context,
    bundle,
    *,
    user_id: int,
    lang: str,
    notify_admin,
) -> None:
    """Keep successful cards clean while making partial failures recoverable."""
    statuses = bundle.statuses
    failed = [item for item in statuses if item.state != "success"]
    if not failed:
        return

    # Retry the original batch, not only failed members. The UI result is one
    # atomic collection; rebuilding all sources preserves order and avoids
    # making the user manually merge recovered items with the earlier partial.
    retry_urls = [item.source_url for item in statuses] if failed else []
    if message.chat.type == "channel":
        summary = ", ".join(f"{item.provider}:{item.state}" for item in failed)
        await notify_admin(
            context,
            f"Часть ссылок в канале не обработана ({summary}).",
            only_for_channel_message=message,
        )
        return
    if message.chat.type != "private":
        return

    successful = bundle.successful_source_count
    text = get_text(lang, "partial_result").format(
        ok=successful,
        total=len(statuses),
    )
    details = []
    for index, item in enumerate(statuses, start=1):
        if item.state == "success":
            marker = "✅"
            label = item.label or item.provider
        elif item.state == "unavailable":
            marker = "⚠️"
            label = get_text(
                lang,
                "partial_rate_limited"
                if item.reason == "rate_limited"
                else "partial_timeout"
                if item.reason == "timeout"
                else "partial_unavailable",
            )
        else:
            marker = "·"
            label = get_text(lang, "partial_not_found")
        details.append(f"{marker} {index}. {escape(label)}")
    text += "\n\n<blockquote>" + "\n".join(details) + "</blockquote>"

    keyboard = None
    if retry_urls:
        retry_id = await store_retry_sources(
            context,
            user_id=user_id,
            urls=retry_urls,
        )
        rows = [
            [
                callback_button(
                    get_text(lang, "retry_failed"),
                    encode_callback("retry", "failed", retry_id),
                    tone=ButtonTone.PRIMARY,
                )
            ]
        ]
        replace_buttons = [
            callback_button(
                get_text(lang, "replace_source").format(index=index),
                encode_callback("retry", "replace", f"{retry_id}:{index}"),
            )
            for index, item in enumerate(statuses, start=1)
            if item.state != "success"
        ]
        rows.extend(
            replace_buttons[index : index + 2]
            for index in range(0, len(replace_buttons), 2)
        )
        keyboard = InlineKeyboardMarkup(rows)
    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
