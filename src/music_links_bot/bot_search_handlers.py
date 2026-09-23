from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape
from typing import Callable

from telegram import InlineKeyboardMarkup, Message
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from music_links_bot.bot_lookup import _format_no_url_message, _strip_bot_mention
from music_links_bot.bot_runtime import BotErrorCode, BotFlowError, encode_callback
from music_links_bot.i18n import get_text
from music_links_bot.search import (
    SearchClient,
    SearchLookupError,
    normalize_search_query,
)
from music_links_bot.telegram_buttons import (
    ButtonTone,
    callback_button,
    current_chat_button,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkflowHooks:
    reply_with_error: Callable
    send_loading_placeholder: Callable
    store_search_selection: Callable
    take_placeholder: Callable
    try_delete_message: Callable
    reply_with_flow_error: Callable


async def _resolve_search_sources(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    message_text: str | None,
    *,
    hooks: WorkflowHooks,
    user_id: int,
    lang: str,
) -> tuple[list[str], bool, str] | None:
    """Resolve a private text query or finish the flow with a picker/error."""
    search_query = normalize_search_query(
        _strip_bot_mention(message_text or "", context.bot.username)
    )
    if search_query is None:
        await hooks.reply_with_error(
            message,
            context,
            _format_no_url_message(message_text, message.chat_id, lang=lang),
            lang=lang,
        )
        return None

    await hooks.send_loading_placeholder(message, lang)
    search_client: SearchClient = context.application.bot_data["search_client"]
    try:
        if hasattr(search_client, "search_release_candidates"):
            candidates = await search_client.search_release_candidates(search_query)
        else:
            source_url = await search_client.search_release_url(search_query)
            candidates = [
                type(
                    "SearchChoice",
                    (),
                    {"url": source_url, "artist": "", "title": search_query},
                )()
            ]
        if len(candidates) > 1:
            selection_id = await hooks.store_search_selection(
                context,
                user_id=user_id,
                query=search_query,
                urls=[candidate.url for candidate in candidates[:3]],
            )
            placeholder = hooks.take_placeholder(message.chat_id)
            lines = [
                get_text(lang, "search_choose").replace(
                    "{query}", escape(search_query)
                ),
                "",
            ]
            for index, candidate in enumerate(candidates[:3], start=1):
                artist = escape(str(getattr(candidate, "artist", "") or "—"))
                title = escape(str(getattr(candidate, "title", "") or "—"))
                meta = [
                    escape(str(value))
                    for value in (
                        getattr(candidate, "album", None),
                        getattr(candidate, "year", None),
                    )
                    if value
                ]
                suffix = f" <i>· {' · '.join(meta)}</i>" if meta else ""
                lines.append(f"<b>{index}.</b> {artist} — {title}{suffix}")
            text = "\n".join(lines)
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        callback_button(
                            (
                                f"{index + 1} · "
                                f"{getattr(candidate, 'artist', '')} — {candidate.title}"
                            )[:64],
                            encode_callback(
                                "select", "pick", f"{selection_id}:{index}"
                            ),
                            tone=ButtonTone.PRIMARY if index == 0 else None,
                        )
                    ]
                    for index, candidate in enumerate(candidates[:3])
                ]
                + [
                    [
                        current_chat_button(
                            get_text(lang, "search_change"),
                            search_query,
                        )
                    ],
                    [
                        callback_button(
                            get_text(lang, "home_back"),
                            encode_callback("menu", "start"),
                        )
                    ],
                ]
            )
            if placeholder is not None:
                try:
                    await placeholder.edit_text(
                        text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                    )
                    return None
                except TelegramError:
                    LOGGER.debug("Could not edit search progress", exc_info=True)
                    await hooks.try_delete_message(placeholder)
            await message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            return None
        return [candidates[0].url], True, search_query
    except (SearchLookupError, IndexError):
        await hooks.reply_with_flow_error(
            message,
            context,
            BotFlowError(BotErrorCode.SEARCH_NOT_FOUND, retryable=True),
            lang=lang,
            search_query=search_query,
        )
        return None
