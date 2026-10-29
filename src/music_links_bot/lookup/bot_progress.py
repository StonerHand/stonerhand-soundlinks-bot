from __future__ import annotations

import asyncio
import contextvars
import hashlib
import logging
from dataclasses import dataclass

from telegram import InlineKeyboardMarkup, Message
from telegram.error import TelegramError

from music_links_bot.core.i18n import get_text
from music_links_bot.lookup.lookup_control import current_control
from music_links_bot.state.bot_runtime import encode_callback
from music_links_bot.tg.telegram_buttons import (
    callback_button,
)
from music_links_bot.tg.telegram_messages import delete_message_safely

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ProgressState:
    message: Message | None
    chat_id: int
    stage: int = 0
    last_text: str = ""
    seed: str = ""
    # A delayed progress line: the task that will send it, whether it is
    # being sent right now, and whether the result already took its place.
    pending: asyncio.Task | None = None
    sending: bool = False
    taken: bool = False


# A result faster than this never shows a progress line: no flicker.
PROGRESS_DELAY_SECONDS = 1.0


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
    """What is happening, a real count for collections and a phrase for the
    mood. No progress bar: a percentage would be invented.

    The phrase is picked from the request seed, so one lookup keeps a
    consistent voice while the next one sounds different.
    """
    _stage, _percent, pool, with_status = _STEPS[key]
    phrases = get_text(lang, pool).splitlines()
    digest = hashlib.sha256(f"{seed}:{pool}".encode()).digest()
    phrase = phrases[digest[0] % len(phrases)]
    if with_status:
        status = get_text(lang, key).format(**values)
        # "⚠️ 3 of 5 opened" keeps its own sign: never two in a row.
        return f"{status if not status[:1].isalnum() else '🔎 ' + status}\n{phrase}"
    return f"🔎 {phrase}"


def _seed(message) -> str:
    return f"{getattr(message, 'chat_id', '')}:{getattr(message, 'message_id', '')}"


def _stop_callback():
    control = current_control.get()
    return encode_callback(
        "progress", "cancel", str(control.draft_id) if control else ""
    )


def _progress_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[callback_button(get_text(lang, "request_cancel"), _stop_callback())]]
    )


async def _send_progress_message(message: Message, text: str, lang: str) -> Message:
    return await message.reply_text(text, reply_markup=_progress_keyboard(lang))


async def _edit_progress_message(message: Message, text: str, lang: str) -> None:
    await message.edit_text(text, reply_markup=_progress_keyboard(lang))


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
    delay: float = 0.0,
) -> None:
    """Create at most one visible progress message for the active request.

    ``key`` lets a lookup that already has its links open at the platform
    step: every skipped edit is a full round trip to Telegram. With
    ``delay`` the line appears only if the result is not ready by then.
    """
    if _PLACEHOLDER.get() is not None:
        return
    key = key or ("progress_batch_start" if total > 1 else "progress_search")
    seed = _seed(message)
    state = ProgressState(
        None,
        chat_id=message.chat_id,
        stage=_STEPS[key][0],
        last_text=progress_text(lang, key, seed=seed, total=total),
        seed=seed,
    )
    # Always a real message that the result is edited into. A Telegram draft
    # is a 30-second preview the bot cannot remove: after a quick answer it
    # could reach the chat after the card and hang below it.
    if delay > 0:
        _PLACEHOLDER.set(state)
        state.pending = asyncio.create_task(
            _send_when_slow(message, state, lang, delay)
        )
        return
    try:
        state.message = await _send_progress_message(message, state.last_text, lang)
    except TelegramError:
        LOGGER.debug("Could not send progress message", exc_info=True)
        return
    _PLACEHOLDER.set(state)


async def _send_when_slow(
    message: Message, state: ProgressState, lang: str, delay: float
) -> None:
    await asyncio.sleep(delay)
    from music_links_bot.lookup.lookup_control import published

    # The line carries Stop: another instance must be able to find the
    # lookup by the time it is shown.
    await published(current_control.get())
    if state.taken:
        return
    state.sending = True
    try:
        sent = await _send_progress_message(message, state.last_text, lang)
    except TelegramError:
        LOGGER.debug("Could not send progress message", exc_info=True)
        return
    finally:
        state.sending = False
    if state.taken:
        # The result went out while this line was being sent: remove it.
        await delete_message_safely(sent)
        return
    state.message = sent


def settle_progress() -> None:
    """At the end of a request: a progress line that was never needed must
    not appear afterwards. One already shown stays for its owner to handle."""
    state = _PLACEHOLDER.get()
    if state is not None and state.message is None:
        _abandon_pending(state)


def _abandon_pending(state: ProgressState) -> None:
    state.taken = True
    if state.pending is not None and not state.pending.done() and not state.sending:
        # Still waiting: nothing was sent, so cancelling is safe. A line being
        # sent right now removes itself when it lands (see _send_when_slow).
        state.pending.cancel()


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
        state.stage = next_stage
        state.last_text = text
    except TelegramError:
        LOGGER.debug("Could not update progress message", exc_info=True)


def take_progress(chat_id: int) -> Message | None:
    """Detach the progress message so the final result can replace it. A
    progress line not shown yet never will be."""
    state = _PLACEHOLDER.get()
    if state is None or state.chat_id != chat_id:
        return None
    _PLACEHOLDER.set(None)
    _abandon_pending(state)
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
