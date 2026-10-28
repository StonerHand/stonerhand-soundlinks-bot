from __future__ import annotations

import logging

from telegram.error import BadRequest, Forbidden

from music_links_bot.telegram_gateway import TelegramApiGateway, feature_enabled

LOGGER = logging.getLogger(__name__)


def ephemeral_group_replies_enabled() -> bool:
    """Use invisible (ephemeral) replies in groups when Telegram supports it.

    Bot API 10.3 makes this a stable native path. Operators can still disable
    it instantly, and every caller retains a normal public fallback.
    """
    return feature_enabled("EPHEMERAL_GROUP_REPLIES", default=True)


# Telegram's service account: the sender of channel posts auto-forwarded
# into a linked discussion group.
_TELEGRAM_SERVICE_USER_ID = 777000


def ephemeral_card_receiver(message: object) -> int | None:
    """The person a group card may be shown to invisibly, if anyone.

    Off by default: in a group a card replaces the link message publicly,
    as it always has. EPHEMERAL_GROUP_CARDS=1 shows the card to its sender
    only and keeps their message. A post made as a channel, or forwarded by
    Telegram from a linked channel, has no person to show it to.
    """
    chat = getattr(message, "chat", None)
    user = getattr(message, "from_user", None)
    if (
        getattr(chat, "type", None) not in {"group", "supergroup"}
        or not feature_enabled("EPHEMERAL_GROUP_CARDS", default=False)
        or user is None
        or getattr(user, "id", None) == _TELEGRAM_SERVICE_USER_ID
        or getattr(message, "sender_chat", None) is not None
        or getattr(message, "is_automatic_forward", False)
    ):
        return None
    return user.id


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
    http_timeout: float = 8.0,
) -> bool:
    """Reply in a group so only `receiver_user_id` sees it — Telegram's
    "invisible messages". Only definitive API rejections permit a public
    fallback; ambiguous transport failures propagate without a duplicate send.
    """
    if not bot_token or not receiver_user_id:
        return False

    try:
        return await TelegramApiGateway(
            token=bot_token, timeout=http_timeout
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
    except (BadRequest, Forbidden):
        LOGGER.debug("Ephemeral send failed", exc_info=True)
        return False
