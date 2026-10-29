"""Telegram message effects (private chats only) with a safe plain fallback."""

from __future__ import annotations

import logging

from telegram.error import BadRequest, TelegramError

LOGGER = logging.getLogger(__name__)
# Built-in Telegram effects, available to every bot in private chats.
CELEBRATE = "5046509860389126442"  # 🎉
PUBLISHED_REACTION = "🎉"


async def send_with_effect(send, *, effect_id: str = CELEBRATE, **kwargs):
    """Send with an effect; a rejected effect means nothing was sent, so retry."""
    try:
        return await send(message_effect_id=effect_id, **kwargs)
    except BadRequest as exc:
        if "effect" not in str(exc).casefold():
            raise
        LOGGER.info("Message effect rejected; sending without it")
        return await send(**kwargs)


async def celebrate(bot, query, *, edit) -> bool:
    """Turn the card into its success screen in place and mark it with 🎉.

    The card stays where it is: nothing in the chat disappears and comes
    back as a new message. Telegram's confetti exists only on new messages,
    so the reaction is the celebration. Returns whether it was added.
    """
    await edit()
    message = getattr(query, "message", None)
    message_id = getattr(message, "message_id", None)
    if message is None or not isinstance(message_id, int):
        return False
    from telegram import ReactionTypeEmoji

    try:
        await bot.set_message_reaction(
            chat_id=message.chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(PUBLISHED_REACTION)],
        )
    except TelegramError:
        LOGGER.debug("Could not mark the published card", exc_info=True)
        return False
    return True
