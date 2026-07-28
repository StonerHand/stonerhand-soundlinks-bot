from __future__ import annotations

import contextvars
import logging

from telegram import Message
from telegram.error import TelegramError

from music_links_bot.i18n import get_text

LOGGER = logging.getLogger(__name__)
_PLACEHOLDER: contextvars.ContextVar[Message | None] = contextvars.ContextVar(
    "bot_progress_message",
    default=None,
)


def adopt_progress_message(message: Message | None) -> None:
    """Reuse an existing bot message when a callback starts a new action."""
    _PLACEHOLDER.set(message)


async def start_progress(message: Message, lang: str = "ru") -> None:
    """Create at most one visible progress message for the active request."""
    if _PLACEHOLDER.get() is not None:
        return
    try:
        placeholder = await message.reply_text(get_text(lang, "progress_search"))
    except TelegramError:
        LOGGER.debug("Could not send progress message", exc_info=True)
        return
    _PLACEHOLDER.set(placeholder)


async def update_progress(lang: str, key: str) -> None:
    placeholder = _PLACEHOLDER.get()
    if placeholder is None:
        return
    try:
        await placeholder.edit_text(get_text(lang, key))
    except TelegramError:
        LOGGER.debug("Could not update progress message", exc_info=True)


def take_progress(chat_id: int) -> Message | None:
    """Detach the progress message so the final result can replace it."""
    placeholder = _PLACEHOLDER.get()
    if placeholder is None or placeholder.chat_id != chat_id:
        return None
    _PLACEHOLDER.set(None)
    return placeholder
