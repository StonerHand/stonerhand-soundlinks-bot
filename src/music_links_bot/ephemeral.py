from __future__ import annotations

import logging

from telegram.error import TelegramError

from music_links_bot.telegram_gateway import TelegramApiGateway, feature_enabled

LOGGER = logging.getLogger(__name__)


def ephemeral_group_replies_enabled() -> bool:
    """Opt-in flag for invisible (ephemeral) replies in groups.

    Off by default: the feature rides very new Bot API surface, so it only
    activates when the operator sets EPHEMERAL_GROUP_REPLIES and Telegram
    actually supports it for the bot. When it can't deliver, the caller falls
    back to the normal public reply.
    """
    return feature_enabled("EPHEMERAL_GROUP_REPLIES", default=False)


async def send_ephemeral_message(
    bot_token: str | None,
    chat_id: int | str,
    receiver_user_id: int | None,
    text: str,
    *,
    parse_mode: object | None = None,
    reply_markup: object | None = None,
    link_preview_options: object | None = None,
    reply_to_message_id: int | None = None,
    callback_query_id: str | None = None,
    replace_callback_query_message: bool = False,
    timeout: float = 8.0,
) -> bool:
    """Reply in a group so only `receiver_user_id` sees it — Telegram's
    "invisible messages". Called over raw HTTP so it works regardless of the
    installed python-telegram-bot version; never raises and returns False when
    the feature is unavailable, so callers can fall back to a public reply.
    """
    if not bot_token or not receiver_user_id:
        return False

    try:
        return await TelegramApiGateway(
            token=bot_token, timeout=timeout
        ).send_ephemeral_message(
            chat_id=chat_id,
            receiver_user_id=receiver_user_id,
            text=text,
            callback_query_id=callback_query_id,
            replace_callback_query_message=replace_callback_query_message,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            link_preview_options=link_preview_options,
            reply_to_message_id=reply_to_message_id,
        )
    except TelegramError:
        LOGGER.debug("Ephemeral send failed", exc_info=True)
        return False
