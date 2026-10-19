"""Telegram message effects (private chats only) with a safe plain fallback."""

from __future__ import annotations

import logging

from telegram.error import BadRequest, TelegramError

LOGGER = logging.getLogger(__name__)
# Built-in Telegram effects, available to every bot in private chats.
CELEBRATE = "5046509860389126442"  # 🎉


async def send_with_effect(send, *, effect_id: str = CELEBRATE, **kwargs):
    """Send with an effect; a rejected effect means nothing was sent, so retry."""
    try:
        return await send(message_effect_id=effect_id, **kwargs)
    except BadRequest as exc:
        if "effect" not in str(exc).casefold():
            raise
        LOGGER.info("Message effect rejected; sending without it")
        return await send(**kwargs)


async def celebrate(bot, query, *, edit, **send_kwargs) -> bool:
    """Show a success screen with confetti instead of a silent edit.

    Telegram adds effects only to new messages in private chats, so there the
    screen is sent anew and the old card removed. Anywhere else, or if the
    new message fails, the card is edited in place exactly as before.
    """
    message = getattr(query, "message", None)
    chat = getattr(message, "chat", None)
    if message is None or getattr(chat, "type", None) != "private":
        await edit()
        return False
    try:
        await send_with_effect(bot.send_message, chat_id=message.chat_id, **send_kwargs)
    except TelegramError:
        LOGGER.info("Celebration failed; editing the card instead", exc_info=True)
        await edit()
        return False
    try:
        await message.delete()
    except TelegramError:
        # Never leave live editor buttons on a card that was replaced.
        LOGGER.debug("Could not remove the replaced card", exc_info=True)
        try:
            await message.edit_reply_markup(reply_markup=None)
        except TelegramError:
            LOGGER.debug("Could not retire the replaced card", exc_info=True)
    return True
