"""Guest replies and generation-stop updates, including newer raw PTB fields."""

from __future__ import annotations

import asyncio
import logging
import re

from telegram import (
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
)
from telegram.ext import ApplicationHandlerStop

from music_links_bot.bot_inline import _build_inline_collection_result
from music_links_bot.bot_menu import runtime_for
from music_links_bot.constants import MAX_LINKS_PER_MESSAGE
from music_links_bot.i18n import get_text, resolve_lang
from music_links_bot.lookup_control import stop_lookup
from music_links_bot.lookup_models import unique_source_urls
from music_links_bot.search import SearchLookupError, normalize_search_query
from music_links_bot.telegram_buttons import current_chat_button
from music_links_bot.telegram_gateway import TelegramApiGateway
from music_links_bot.telegram_updates import native_field
from music_links_bot.url_utils import extract_supported_urls

LOGGER = logging.getLogger(__name__)


async def native_update_handler(update, context):
    stopped = native_field(update, "stopped_message_generation")
    if stopped is not None:
        payload = stopped if isinstance(stopped, dict) else stopped.to_dict()
        chat = payload.get("chat") or {}
        if isinstance(chat, dict) and chat.get("type") == "private":
            await stop_lookup(
                context.application.bot_data,
                chat_id=chat.get("id"),
                draft_id=payload.get("draft_id"),
            )
        raise ApplicationHandlerStop
    guest = native_field(update, "guest_message")
    if guest is not None:
        message = (
            Message.de_json(guest, context.bot) if isinstance(guest, dict) else guest
        )
        await guest_message_handler(message, context)
        raise ApplicationHandlerStop


def guest_input(message, username):
    def extract(part):
        if part is None:
            return "", []
        text = part.text or part.caption or ""
        urls = extract_supported_urls(text)
        for entity in (*part.entities, *part.caption_entities):
            if entity.url:
                urls.extend(extract_supported_urls(entity.url))
        return text, unique_source_urls(urls)

    text, urls = extract(message)
    reply_text, reply_urls = extract(message.reply_to_message)
    cleaned = re.sub(r"@" + re.escape(username) + r"\b", "", text, flags=re.I).strip(
        " ,:;—-"
    )
    if urls:
        return cleaned, urls
    if reply_urls:
        return cleaned, reply_urls
    return cleaned or reply_text, []


def _hint(lang, key, *, choices=()):
    keyboard = (
        InlineKeyboardMarkup(
            [
                [
                    current_chat_button(
                        (
                            f"{choice.artist} — {choice.title}"
                            if choice.artist
                            else choice.title
                        )[:60],
                        choice.url,
                    )
                ]
                for choice in choices
            ]
        )
        if choices
        else None
    )
    return InlineQueryResultArticle(
        id="guest-hint",
        title=get_text(lang, key),
        input_message_content=InputTextMessageContent(get_text(lang, key)),
        reply_markup=keyboard,
    )


async def guest_message_handler(message, context):
    query_id = native_field(message, "guest_query_id")
    if not query_id:
        return
    user = message.from_user
    lang = resolve_lang(user.language_code if user else None)
    runtime = runtime_for(context)
    identity = user.id if user else message.chat_id
    allowed, _ = await runtime.allow_user_request(identity)
    if not allowed:
        result = _hint(lang, "guest_rate_limit")
    else:
        try:
            result = await asyncio.wait_for(
                _guest_result(message, context, lang), timeout=18
            )
        except (TimeoutError, SearchLookupError):
            result = _hint(lang, "guest_not_found")
        except Exception:
            LOGGER.warning("Guest lookup failed", exc_info=True)
            result = _hint(lang, "guest_not_found")
    # Never retry this send on an ambiguous transport error: it may be delivered.
    await TelegramApiGateway(bot=context.bot).request(
        "answerGuestQuery", {"guest_query_id": query_id, "result": result.to_dict()}
    )


async def _guest_result(message, context, lang):
    query, urls = guest_input(message, context.bot.username)
    if len(urls) > MAX_LINKS_PER_MESSAGE:
        return _hint(lang, "guest_too_many")
    if not urls:
        normalized = normalize_search_query(query)
        if normalized is None:
            return _hint(lang, "guest_help")
        client = context.application.bot_data["search_client"]
        candidates = await client.search_release_candidates(normalized)
        if not candidates:
            return _hint(lang, "guest_not_found")
        if len(candidates) > 1:
            return _hint(lang, "guest_choose", choices=candidates[:3])
        urls = [candidates[0].url]
    result = await _build_inline_collection_result(
        urls,
        context,
        lang=lang,
        force_classic=True,
    )
    return result or _hint(lang, "guest_not_found")
