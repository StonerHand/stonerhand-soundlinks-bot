"""The draft card itself: one editor action, and how the card is drawn and edited."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape
from typing import Any

from telegram import (
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from music_links_bot.bot_builder import (
    fit_telegram_html,
)
from music_links_bot.bot_runtime import (
    encode_callback,
)
from music_links_bot.editor_view import (
    render_track_draft as _render_track_draft,
)
from music_links_bot.i18n import get_text
from music_links_bot.keyboards import (
    _build_link_preview_options,
)
from music_links_bot.models import (
    TrackMatch,
)
from music_links_bot.publication_view import editor_preview_url
from music_links_bot.telegram_buttons import (
    ButtonTone,
    callback_button,
    disabled_button,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class EditorActionRequest:
    # A CallbackQuery, or any object with the same answer/message surface.
    query: Any
    context: ContextTypes.DEFAULT_TYPE
    action: str
    draft_id: str
    draft: dict
    lang: str
    track: TrackMatch
    schedule_at: int | None = None

    @property
    def user_id(self) -> int:
        user = getattr(self.query, "from_user", None)
        return int(user.id) if user is not None else 0


async def _restore_editor_card(request: EditorActionRequest) -> None:
    text, keyboard = _render_track_draft(
        request.draft,
        request.context,
        draft_id=request.draft_id,
    )
    await _edit_editor_message(
        request.query,
        request.context,
        request.draft,
        text,
        keyboard,
    )


def _editor_success_text(request: EditorActionRequest, title_key: str) -> str:
    return (
        f"{get_text(request.lang, title_key)}\n\n"
        f"<blockquote><b>{escape(request.track.artist)}</b> — "
        f"{escape(request.track.title)}</blockquote>"
    )


async def _show_action_busy(query, lang: str) -> None:
    try:
        await query.edit_message_reply_markup(
            InlineKeyboardMarkup(
                [
                    [
                        disabled_button(
                            get_text(lang, "progress_busy"),
                            tone=ButtonTone.PRIMARY,
                        )
                    ]
                ]
            )
        )
    except (AttributeError, TelegramError, TypeError):
        try:
            await query.edit_message_reply_markup(
                InlineKeyboardMarkup(
                    [
                        [
                            callback_button(
                                get_text(lang, "progress_busy"),
                                encode_callback("noop", "busy"),
                                tone=ButtonTone.PRIMARY,
                            )
                        ]
                    ]
                )
            )
        except (AttributeError, TelegramError, TypeError):
            LOGGER.debug("Could not mark editor action busy", exc_info=True)


def _editor_message(context, draft: dict, text: str, keyboard) -> dict:
    from music_links_bot.bot_ui import version_editor_keyboard

    track = TrackMatch(**draft["item"])
    return {
        "text": fit_telegram_html(text),
        "parse_mode": ParseMode.HTML,
        "link_preview_options": _build_link_preview_options(
            editor_preview_url(draft, track, context),
            prefer_large_media=bool(draft.get("large_preview")),
        ),
        "reply_markup": version_editor_keyboard(keyboard, draft),
    }


async def _edit_editor_message(
    query, context, draft: dict, text: str, keyboard
) -> None:
    try:
        await query.edit_message_text(**_editor_message(context, draft, text, keyboard))
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise
