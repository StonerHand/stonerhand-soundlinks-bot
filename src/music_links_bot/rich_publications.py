from __future__ import annotations

import html
import logging
from typing import Any

from telegram import Message
from telegram.error import BadRequest, TelegramError

from music_links_bot.rich_rendering import (
    LONGREAD_MODE,
    MAX_FALLBACK_TEXT,
    MAX_LONGREAD_BLOCKS,
    MAX_RICH_HTML,
    RICH_MESSAGE_CAPABILITY,
    build_fallback_html,
    build_music_publication_html,
    build_rich_card_html,
    build_rich_collection_html,
    build_rich_html,
    build_rich_inline_card_html,
    build_rich_track_video_html,
    default_longread,
    is_longread,
    rich_button_rows_html,
    rich_messages_enabled,
    sanitize_longread,
    sanitize_rich_fragment,
)
from music_links_bot.telegram_gateway import (
    TelegramApiGateway,
    capability_available,
    feature_enabled,
    record_capability_failure,
    record_capability_success,
)

LOGGER = logging.getLogger(__name__)
RICH_DRAFT_CAPABILITY = "rich_drafts"

__all__ = (
    "LONGREAD_MODE",
    "MAX_FALLBACK_TEXT",
    "MAX_LONGREAD_BLOCKS",
    "MAX_RICH_HTML",
    "build_fallback_html",
    "build_music_publication_html",
    "build_rich_card_html",
    "build_rich_collection_html",
    "build_rich_html",
    "build_rich_inline_card_html",
    "build_rich_track_video_html",
    "default_longread",
    "edit_rich_publication",
    "is_longread",
    "rich_api_unavailable",
    "rich_button_rows_html",
    "rich_messages_enabled",
    "sanitize_longread",
    "sanitize_rich_fragment",
    "save_prepared_rich_publication",
    "send_rich_progress_draft",
    "send_rich_publication",
)


def _serialize_reply_markup(reply_markup: object) -> object:
    to_dict = getattr(reply_markup, "to_dict", None)
    return to_dict() if callable(to_dict) else reply_markup


async def send_rich_publication(
    bot,
    *,
    chat_id: int | str,
    rich_html: str,
    reply_markup=None,
    ephemeral_message_parameters: dict[str, object] | None = None,
) -> Message | bool:
    # The caller normally observes the warm-instance capability cooldown.
    # Keeping the transport retryable lets an explicit probe recover early.
    if not feature_enabled("RICH_MESSAGES_ENABLED", default=True):
        raise BadRequest("Rich Messages are temporarily unavailable")
    gateway = TelegramApiGateway(bot=bot)
    try:
        result = await gateway.send_rich_message(
            chat_id=chat_id,
            rich_message={"html": rich_html},
            reply_markup=reply_markup,
            ephemeral_message_parameters=ephemeral_message_parameters,
        )
    except TelegramError as exc:
        record_capability_failure(
            RICH_MESSAGE_CAPABILITY,
            exc,
            unsupported=rich_api_unavailable(exc),
        )
        raise
    record_capability_success(RICH_MESSAGE_CAPABILITY)
    if isinstance(result, dict):
        return Message.de_json(result, bot)
    return bool(result)


async def edit_rich_publication(
    bot,
    *,
    chat_id: int | str,
    message_id: int,
    rich_html: str,
    reply_markup=None,
) -> Message | bool:
    gateway = TelegramApiGateway(bot=bot)
    result = await gateway.edit_rich_message(
        chat_id=chat_id,
        message_id=message_id,
        rich_message={"html": rich_html},
        reply_markup=reply_markup,
    )
    if isinstance(result, dict):
        return Message.de_json(result, bot)
    return bool(result)


async def send_rich_progress_draft(
    bot,
    *,
    chat_id: int,
    draft_id: int,
    text: str,
    can_stop: bool = True,
) -> bool:
    if not feature_enabled(
        "RICH_DRAFTS_ENABLED", default=True
    ) or not capability_available(RICH_DRAFT_CAPABILITY):
        return False
    gateway = TelegramApiGateway(bot=bot)
    try:
        sent = await gateway.send_rich_draft(
            chat_id=chat_id,
            draft_id=draft_id,
            rich_message={"html": f"<tg-thinking>{html.escape(text)}</tg-thinking>"},
            can_stop=can_stop,
            keep_on_stop=False,
        )
    except TelegramError as exc:
        record_capability_failure(
            RICH_DRAFT_CAPABILITY,
            exc,
            unsupported=rich_api_unavailable(exc),
        )
        LOGGER.debug("Rich progress draft unavailable", exc_info=True)
        return False
    record_capability_success(RICH_DRAFT_CAPABILITY)
    return sent


def rich_api_unavailable(error: BaseException) -> bool:
    if not isinstance(error, (BadRequest, TelegramError)):
        return False
    message = str(error).casefold()
    markers = (
        "method not found",
        "unknown method",
        "sendrichmessage",
        "rich message is not supported",
        "can't parse rich message",
        "bot token is unavailable",
    )
    return any(marker in message for marker in markers)


async def save_prepared_rich_publication(
    bot,
    *,
    user_id: int,
    result_id: str,
    title: str,
    description: str,
    thumbnail_url: str | None,
    rich_html: str,
    reply_markup,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "article",
        "id": result_id,
        "title": title,
        "description": description,
        "input_message_content": {"rich_message": {"html": rich_html}},
        "reply_markup": _serialize_reply_markup(reply_markup),
    }
    if thumbnail_url:
        result["thumbnail_url"] = thumbnail_url
    prepared = await TelegramApiGateway(bot=bot).request(
        "savePreparedInlineMessage",
        {
            "user_id": user_id,
            "result": result,
            "allow_user_chats": True,
            "allow_bot_chats": True,
            "allow_group_chats": True,
            "allow_channel_chats": True,
        },
    )
    return prepared if isinstance(prepared, dict) else {}
