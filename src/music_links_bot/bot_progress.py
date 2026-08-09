from __future__ import annotations

import contextvars
from dataclasses import dataclass
import logging

from telegram import Message
from telegram.error import TelegramError

from music_links_bot.i18n import get_text

LOGGER = logging.getLogger(__name__)
@dataclass(slots=True)
class ProgressState:
    message: Message
    stage: int = 0


_STAGES = {
    "progress_search": 1,
    "progress_links": 2,
    "progress_card": 3,
}
_PLACEHOLDER: contextvars.ContextVar[ProgressState | None] = contextvars.ContextVar(
    "bot_progress_message",
    default=None,
)


def adopt_progress_message(message: Message | None) -> None:
    """Reuse an existing bot message when a callback starts a new action."""
    _PLACEHOLDER.set(ProgressState(message) if message is not None else None)


async def start_progress(message: Message, lang: str = "ru") -> None:
    """Create at most one visible progress message for the active request."""
    if _PLACEHOLDER.get() is not None:
        return
    try:
        placeholder = await message.reply_text(get_text(lang, "progress_search"))
    except TelegramError:
        LOGGER.debug("Could not send progress message", exc_info=True)
        return
    _PLACEHOLDER.set(ProgressState(placeholder, stage=1))


async def update_progress(lang: str, key: str) -> None:
    state = _PLACEHOLDER.get()
    if state is None:
        return
    next_stage = _STAGES.get(key, state.stage)
    if next_stage <= state.stage:
        return
    try:
        await state.message.edit_text(get_text(lang, key))
        state.stage = next_stage
    except TelegramError:
        LOGGER.debug("Could not update progress message", exc_info=True)


def take_progress(chat_id: int) -> Message | None:
    """Detach the progress message so the final result can replace it."""
    state = _PLACEHOLDER.get()
    if state is None or state.message.chat_id != chat_id:
        return None
    _PLACEHOLDER.set(None)
    return state.message


async def cancel_progress(chat_id: int, lang: str = "ru") -> None:
    """Remove a superseded progress indicator or mark it as cancelled."""
    placeholder = take_progress(chat_id)
    if placeholder is None:
        return
    try:
        await placeholder.delete()
        return
    except TelegramError:
        LOGGER.debug("Could not delete cancelled progress message", exc_info=True)
    try:
        await placeholder.edit_text(get_text(lang, "progress_cancelled"))
    except TelegramError:
        LOGGER.debug("Could not retire cancelled progress message", exc_info=True)
