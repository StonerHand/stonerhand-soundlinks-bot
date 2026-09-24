from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape
from typing import Callable

from telegram import InlineKeyboardMarkup, Message
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from music_links_bot.bot_runtime import BotErrorCode, BotFlowError
from music_links_bot.i18n import get_text

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkflowHooks:
    build_error_keyboard: Callable
    try_ephemeral_error: Callable
    take_placeholder: Callable
    try_delete_message: Callable
    ephemeral_group_replies_enabled: Callable
    send_ephemeral_message: Callable


async def _reply_with_error(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    hooks: WorkflowHooks,
    lang: str = "ru",
) -> None:
    reply_markup = hooks.build_error_keyboard(
        context.bot.username,
        lang=lang,
        recovery="platforms",
    )
    if await hooks.try_ephemeral_error(
        message,
        context,
        text,
        reply_markup,
    ):
        return
    placeholder = hooks.take_placeholder(message.chat_id)
    if placeholder is not None:
        try:
            await placeholder.edit_text(text, reply_markup=reply_markup)
            return
        except TelegramError:
            LOGGER.debug("Could not edit loading placeholder", exc_info=True)
            await hooks.try_delete_message(placeholder)

    await message.reply_text(text, reply_markup=reply_markup)


async def _reply_with_flow_error(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    error: BotFlowError,
    *,
    hooks: WorkflowHooks,
    lang: str,
    search_query: str | None = None,
    source_url: str | None = None,
) -> None:
    detail_key = {
        BotErrorCode.INVALID_INPUT: "no_url_hint",
        BotErrorCode.SEARCH_NOT_FOUND: "error_search",
        BotErrorCode.RELEASE_NOT_FOUND: "error_search",
        BotErrorCode.PROVIDER_UNAVAILABLE: "error_provider",
        BotErrorCode.RATE_LIMITED: "error_rate_limit",
    }.get(error.code, "no_url_hint")
    detail = get_text(lang, detail_key)
    if error.code == BotErrorCode.RATE_LIMITED:
        detail = detail.format(seconds=escape(error.detail or "60"))
    if error.code == BotErrorCode.PROVIDER_UNAVAILABLE and error.provider:
        provider_labels = {
            "songlink": "Song.link",
            "youtube": "YouTube",
            "nts": "NTS Radio",
            "apple": "Apple Music",
            "spotify": "Spotify",
        }
        provider = provider_labels.get(error.provider.casefold(), error.provider)
        detail = get_text(lang, "error_provider_named").format(
            provider=escape(provider)
        )
    title_key = {
        BotErrorCode.INVALID_INPUT: "error_title_invalid_input",
        BotErrorCode.SEARCH_NOT_FOUND: "error_title_not_found",
        BotErrorCode.RELEASE_NOT_FOUND: "error_title_not_found",
        BotErrorCode.PROVIDER_UNAVAILABLE: "error_title_provider",
        BotErrorCode.RATE_LIMITED: "error_title_rate_limit",
    }.get(error.code, "error_title")
    text = f"⚠️ <b>{get_text(lang, title_key)}</b>\n{detail}"
    if search_query and error.code in {
        BotErrorCode.SEARCH_NOT_FOUND,
        BotErrorCode.RELEASE_NOT_FOUND,
    }:
        text += f"\n\n<blockquote>{escape(search_query[:120])}</blockquote>"
    recovery = {
        BotErrorCode.INVALID_INPUT: "platforms",
        BotErrorCode.SEARCH_NOT_FOUND: "change",
        BotErrorCode.RELEASE_NOT_FOUND: "change",
        BotErrorCode.PROVIDER_UNAVAILABLE: "retry",
        BotErrorCode.RATE_LIMITED: "retry",
        BotErrorCode.LIMIT_EXCEEDED: "crate",
    }.get(error.code, "retry" if error.retryable else "search")
    keyboard = hooks.build_error_keyboard(
        context.bot.username,
        lang=lang,
        retryable=error.retryable,
        search_query=search_query,
        source_url=source_url,
        recovery=recovery,
    )
    if await hooks.try_ephemeral_error(
        message,
        context,
        text,
        keyboard,
        parse_mode=ParseMode.HTML,
    ):
        return
    placeholder = hooks.take_placeholder(message.chat_id)
    if placeholder is not None:
        try:
            await placeholder.edit_text(
                text, parse_mode=ParseMode.HTML, reply_markup=keyboard
            )
            return
        except TelegramError:
            LOGGER.debug("Could not edit flow-error placeholder", exc_info=True)
            await hooks.try_delete_message(placeholder)
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def _try_ephemeral_error(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    keyboard: InlineKeyboardMarkup,
    *,
    hooks: WorkflowHooks,
    parse_mode: object | None = None,
) -> bool:
    """Keep recovery private in groups and preserve the public fallback."""
    user = getattr(message, "from_user", None)
    if (
        getattr(message.chat, "type", None) not in {"group", "supergroup"}
        or user is None
        or not hooks.ephemeral_group_replies_enabled()
    ):
        return False
    delivered = await hooks.send_ephemeral_message(
        getattr(context.bot, "token", None),
        message.chat_id,
        user.id,
        text,
        parse_mode=parse_mode,
        reply_markup=keyboard,
        reply_to_message_id=getattr(message, "message_id", None),
    )
    if not delivered:
        return False
    placeholder = hooks.take_placeholder(message.chat_id)
    if placeholder is not None:
        await hooks.try_delete_message(placeholder)
    return True
