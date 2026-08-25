from __future__ import annotations

import contextvars
import logging
from dataclasses import dataclass

from telegram import InlineKeyboardMarkup, Message
from telegram.error import TelegramError

from music_links_bot.bot_runtime import encode_callback
from music_links_bot.i18n import get_text
from music_links_bot.rich_publications import send_rich_progress_draft
from music_links_bot.telegram_buttons import (
    ButtonTone,
    callback_button,
    disabled_button,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ProgressState:
    message: Message | None
    chat_id: int
    stage: int = 0
    bot: object | None = None
    draft_id: int = 0


_STAGES = {
    "progress_search": 1,
    "progress_links": 2,
    "progress_card": 3,
}
_PLACEHOLDER: contextvars.ContextVar[ProgressState | None] = contextvars.ContextVar(
    "bot_progress_message",
    default=None,
)


def _progress_keyboard(text: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [disabled_button(text[:64], tone=ButtonTone.PRIMARY)],
            [
                callback_button(
                    get_text(lang, "request_cancel"),
                    encode_callback("progress", "cancel"),
                )
            ],
        ]
    )


def _progress_fallback_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                callback_button(
                    get_text(lang, "request_cancel"),
                    encode_callback("progress", "cancel"),
                )
            ]
        ]
    )


async def _send_progress_message(message: Message, text: str, lang: str) -> Message:
    """Prefer the native disabled state and degrade on older Bot API nodes."""
    try:
        return await message.reply_text(
            text,
            reply_markup=_progress_keyboard(text, lang),
        )
    except (TelegramError, TypeError):
        try:
            return await message.reply_text(
                text,
                reply_markup=_progress_fallback_keyboard(lang),
            )
        except TypeError:
            return await message.reply_text(text)


async def _edit_progress_message(message: Message, text: str, lang: str) -> None:
    try:
        await message.edit_text(text, reply_markup=_progress_keyboard(text, lang))
    except (TelegramError, TypeError):
        try:
            await message.edit_text(
                text,
                reply_markup=_progress_fallback_keyboard(lang),
            )
        except TypeError:
            await message.edit_text(text)


def adopt_progress_message(message: Message | None) -> None:
    """Reuse an existing bot message when a callback starts a new action."""
    _PLACEHOLDER.set(
        ProgressState(message, chat_id=message.chat_id) if message is not None else None
    )


async def start_progress(
    message: Message,
    lang: str = "ru",
    *,
    total: int = 1,
) -> None:
    """Create at most one visible progress message for the active request."""
    if _PLACEHOLDER.get() is not None:
        return
    try:
        text = (
            get_text(lang, "progress_batch_start").format(total=total)
            if total > 1
            else get_text(lang, "progress_search")
        )
        chat = getattr(message, "chat", None)
        get_bot = getattr(message, "get_bot", None)
        try:
            bot = get_bot() if callable(get_bot) else None
        except RuntimeError:
            # Hand-built Message objects and lightweight test doubles are not
            # necessarily bound to a Bot. The classic progress message still
            # works and remains the lossless fallback.
            bot = None
        draft_id = max(1, int(getattr(message, "message_id", 0) or 1))
        if (
            getattr(chat, "type", None) == "private"
            and bot is not None
            and await send_rich_progress_draft(
                bot,
                chat_id=message.chat_id,
                draft_id=draft_id,
                text=text,
            )
        ):
            _PLACEHOLDER.set(
                ProgressState(
                    None,
                    chat_id=message.chat_id,
                    stage=1,
                    bot=bot,
                    draft_id=draft_id,
                )
            )
            return
        placeholder = await _send_progress_message(message, text, lang)
    except TelegramError:
        LOGGER.debug("Could not send progress message", exc_info=True)
        return
    _PLACEHOLDER.set(ProgressState(placeholder, chat_id=message.chat_id, stage=1))


async def update_progress(lang: str, key: str) -> None:
    state = _PLACEHOLDER.get()
    if state is None:
        return
    next_stage = _STAGES.get(key, state.stage)
    if next_stage <= state.stage:
        return
    try:
        text = get_text(lang, key)
        if state.message is not None:
            await _edit_progress_message(state.message, text, lang)
        elif state.bot is not None:
            await send_rich_progress_draft(
                state.bot,
                chat_id=state.chat_id,
                draft_id=state.draft_id,
                text=text,
            )
        state.stage = next_stage
    except TelegramError:
        LOGGER.debug("Could not update progress message", exc_info=True)


async def update_progress_text(text: str, *, stage: int = 3, lang: str = "ru") -> None:
    state = _PLACEHOLDER.get()
    if state is None or stage <= state.stage:
        return
    try:
        if state.message is not None:
            await _edit_progress_message(state.message, text, lang)
        elif state.bot is not None:
            await send_rich_progress_draft(
                state.bot,
                chat_id=state.chat_id,
                draft_id=state.draft_id,
                text=text,
            )
        state.stage = stage
    except TelegramError:
        LOGGER.debug("Could not update custom progress message", exc_info=True)


def take_progress(chat_id: int) -> Message | None:
    """Detach the progress message so the final result can replace it."""
    state = _PLACEHOLDER.get()
    if state is None or state.chat_id != chat_id:
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
