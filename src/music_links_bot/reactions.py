"""Quiet, live feedback on the user's own message: 👀 while working, 🔥 when done."""

from __future__ import annotations

import asyncio
import logging

from telegram import ReactionTypeEmoji

LOGGER = logging.getLogger(__name__)
WORKING = "👀"
DONE = "🔥"


async def _set(bot, message, emoji: str | None) -> None:
    chat_id = getattr(message, "chat_id", None)
    message_id = getattr(message, "message_id", None)
    setter = getattr(bot, "set_message_reaction", None)
    if not callable(setter) or not isinstance(message_id, int) or chat_id is None:
        return
    try:
        await setter(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji)] if emoji else [],
        )
    # A reaction is decoration: never let it affect the lookup itself.
    except Exception:
        LOGGER.debug("Could not set reaction", exc_info=True)


def start_reaction(bot, message) -> asyncio.Task:
    """Mark the message as "being worked on" without delaying the lookup."""
    return asyncio.create_task(_set(bot, message, WORKING))


async def finish_reaction(task: asyncio.Task, bot, message, *, success: bool) -> None:
    await asyncio.gather(task, return_exceptions=True)
    await _set(bot, message, DONE if success else None)
