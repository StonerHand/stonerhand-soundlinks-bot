"""Telegram message effects (private chats only) with a safe plain fallback."""

from __future__ import annotations

import logging

from telegram.error import BadRequest

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
