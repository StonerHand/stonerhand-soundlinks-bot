from __future__ import annotations

import contextvars
import hashlib
import logging
from dataclasses import dataclass

from telegram import InlineKeyboardMarkup, Message
from telegram.error import TelegramError

from music_links_bot.bot_runtime import encode_callback
from music_links_bot.i18n import get_text
from music_links_bot.lookup_control import current_control
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
    last_text: str = ""
    bot: object | None = None
    draft_id: int = 0
    seed: str = ""


# key -> (stage, percent, phrase pool, shows its own status line)
_STEPS = {
    "progress_search": (1, 20, "progress_fun_search", False),
    "progress_links": (2, 55, "progress_fun_links", False),
    "progress_batch_start": (1, 10, "progress_fun_search", True),
    "progress_batch_links": (2, 40, "progress_fun_links", True),
    "progress_batch": (3, 85, "progress_fun_card", True),
    "progress_batch_partial": (3, 85, "progress_fun_card", True),
}
_PLACEHOLDER: contextvars.ContextVar[ProgressState | None] = contextvars.ContextVar(
    "bot_progress_message",
    default=None,
)


def progress_text(lang: str, key: str, *, seed: str = "", **values) -> str:
    """A ten-step bar, a count for collections and a phrase for the mood.

    The phrase is picked from the request seed, so one lookup keeps a
    consistent voice while the next one sounds different.
    """
    _stage, percent, pool, with_status = _STEPS[key]
    filled = percent // 10
    lines = [f"{'▰' * filled}{'▱' * (10 - filled)} {percent}%"]
    if with_status:
        lines.append(get_text(lang, key).format(**values))
    phrases = get_text(lang, pool).splitlines()
    digest = hashlib.sha256(f"{seed}:{pool}".encode()).digest()
    lines.append(phrases[digest[0] % len(phrases)])
    return "\n".join(lines)


def _seed(message) -> str:
    return f"{getattr(message, 'chat_id', '')}:{getattr(message, 'message_id', '')}"


def _stop_callback():
    control = current_control.get()
    return encode_callback(
        "progress", "cancel", str(control.draft_id) if control else ""
    )


def _progress_keyboard(text: str, lang: str) -> InlineKeyboardMarkup:
    del text
    return InlineKeyboardMarkup(
        [
            [
                disabled_button(
                    get_text(lang, "progress_busy"),
                    tone=ButtonTone.PRIMARY,
                )
            ],
            [
                callback_button(
                    get_text(lang, "request_cancel"),
                    _stop_callback(),
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
                    _stop_callback(),
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
        ProgressState(message, chat_id=message.chat_id, seed=_seed(message))
        if message is not None
        else None
    )


async def start_progress(
    message: Message,
    lang: str = "ru",
    *,
    total: int = 1,
    key: str | None = None,
) -> None:
    """Create at most one visible progress message for the active request.

    ``key`` lets a lookup that already has its links open at the platform
    step: every skipped edit is a full round trip to Telegram.
    """
    if _PLACEHOLDER.get() is not None:
        return
    key = key or ("progress_batch_start" if total > 1 else "progress_search")
    stage = _STEPS[key][0]
    try:
        seed = _seed(message)
        text = progress_text(lang, key, seed=seed, total=total)
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
                can_stop=current_control.get() is not None,
            )
        ):
            _PLACEHOLDER.set(
                ProgressState(
                    None,
                    chat_id=message.chat_id,
                    stage=stage,
                    last_text=text,
                    bot=bot,
                    draft_id=draft_id,
                    seed=seed,
                )
            )
            return
        placeholder = await _send_progress_message(message, text, lang)
    except TelegramError:
        LOGGER.debug("Could not send progress message", exc_info=True)
        return
    _PLACEHOLDER.set(
        ProgressState(
            placeholder,
            chat_id=message.chat_id,
            stage=stage,
            last_text=text,
            seed=seed,
        )
    )


async def update_progress(lang: str, key: str, **values) -> None:
    state = _PLACEHOLDER.get()
    if state is None:
        return
    next_stage = _STEPS[key][0] if key in _STEPS else state.stage
    if next_stage <= state.stage:
        return
    try:
        text = progress_text(lang, key, seed=state.seed, **values)
        if text == state.last_text:
            state.stage = next_stage
            return
        if state.message is not None:
            await _edit_progress_message(state.message, text, lang)
        elif state.bot is not None:
            await send_rich_progress_draft(
                state.bot,
                chat_id=state.chat_id,
                draft_id=state.draft_id,
                text=text,
                can_stop=current_control.get() is not None,
            )
        state.stage = next_stage
        state.last_text = text
    except TelegramError:
        LOGGER.debug("Could not update progress message", exc_info=True)


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
