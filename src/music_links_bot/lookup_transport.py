from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from telegram import Bot, InlineKeyboardMarkup, LinkPreviewOptions, Message
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError

from music_links_bot.bot_builder import fit_telegram_html
from music_links_bot.bot_progress import take_progress
from music_links_bot.ephemeral import (
    ephemeral_group_replies_enabled,
    send_ephemeral_message,
)
from music_links_bot.keyboards import (
    _build_link_preview_options,
    _select_preview_url,
)
from music_links_bot.mixed_post import send_track_video_album
from music_links_bot.models import TrackMatch, VideoMatch
from music_links_bot.publication_contract import (
    RenderedPublication,
    require_valid_publication,
)
from music_links_bot.sharing import make_channel_safe_keyboard
from music_links_bot.telegram_messages import delete_message_safely

LOGGER = logging.getLogger(__name__)


async def send_track_result(
    bot: Bot,
    message: Message,
    text: str,
    *,
    preview_url: str | None,
    reply_markup: InlineKeyboardMarkup | None,
    prefer_large_preview: bool = True,
    found_count: int = 1,
    requested_count: int = 1,
    source_urls: tuple[str, ...] = (),
    content_kind: str = "track",
) -> None:
    text = fit_telegram_html(text)
    if message.chat.type in {"group", "supergroup", "channel"}:
        if message.chat.type == "channel":
            reply_markup = make_channel_safe_keyboard(reply_markup)
        _validate_transport_contract(
            text,
            reply_markup=reply_markup,
            preview_url=preview_url,
            found_count=found_count,
            requested_count=requested_count,
            source_urls=source_urls,
            content_kind=content_kind,
        )
        preview_options = _build_link_preview_options(
            preview_url,
            prefer_large_media=prefer_large_preview,
        )
        if (
            message.chat.type in {"group", "supergroup"}
            and ephemeral_group_replies_enabled()
            and getattr(message, "from_user", None) is not None
        ):
            delivered = await send_ephemeral_message(
                getattr(bot, "token", None),
                message.chat_id,
                message.from_user.id,
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                link_preview_options=preview_options,
                reply_to_message_id=getattr(message, "message_id", None),
            )
            if delivered:
                return

        await _send_card(
            bot.send_message,
            link_preview_options=preview_options,
            chat_id=message.chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
        await delete_message_safely(message)
        return

    await reply_with_track(
        message,
        text,
        preview_url=preview_url,
        reply_markup=reply_markup,
        prefer_large_preview=prefer_large_preview,
        found_count=found_count,
        requested_count=requested_count,
        source_urls=source_urls,
        content_kind=content_kind,
    )


async def send_track_video_pair_result(
    bot: Bot,
    message: Message,
    text: str,
    *,
    track: TrackMatch,
    video: VideoMatch,
    reply_markup: InlineKeyboardMarkup | None,
) -> bool:
    source_urls = (*track.links.values(), video.url)
    preview_url = _select_preview_url(track.links) or track.thumbnail_url
    if (
        message.chat.type in {"group", "supergroup"}
        and ephemeral_group_replies_enabled()
        and getattr(message, "from_user", None) is not None
    ):
        await send_track_result(
            bot,
            message,
            text,
            preview_url=preview_url,
            reply_markup=reply_markup,
            found_count=2,
            requested_count=2,
            source_urls=source_urls,
            content_kind="track_video",
        )
        return True

    placeholder = take_progress(message.chat_id)
    if placeholder is not None:
        try:
            await placeholder.delete()
        except TelegramError:
            LOGGER.debug("Could not remove mixed-post placeholder", exc_info=True)

    channel_keyboard = (
        make_channel_safe_keyboard(reply_markup)
        if message.chat.type == "channel"
        else reply_markup
    )
    _validate_transport_contract(
        text,
        reply_markup=channel_keyboard,
        preview_url=preview_url,
        found_count=2,
        requested_count=2,
        source_urls=source_urls,
        content_kind="track_video",
    )
    sent = await send_track_video_album(
        bot,
        chat_id=message.chat_id,
        track=track,
        video_title=video.title,
        video_url=video.url,
        video_thumbnail_url=video.thumbnail_url,
        caption=text,
        reply_markup=channel_keyboard,
    )
    if sent is None:
        await send_track_result(
            bot,
            message,
            text,
            preview_url=preview_url,
            reply_markup=reply_markup,
            found_count=2,
            requested_count=2,
            source_urls=source_urls,
            content_kind="track_video",
        )
        return True

    if message.chat.type in {"group", "supergroup", "channel"}:
        await delete_message_safely(message)
    return True


async def reply_with_track(
    message: Message,
    text: str,
    *,
    preview_url: str | None,
    reply_markup: InlineKeyboardMarkup | None,
    prefer_large_preview: bool = True,
    found_count: int = 1,
    requested_count: int = 1,
    source_urls: tuple[str, ...] = (),
    content_kind: str = "track",
) -> Message:
    text = fit_telegram_html(text)
    _validate_transport_contract(
        text,
        reply_markup=reply_markup,
        preview_url=preview_url,
        found_count=found_count,
        requested_count=requested_count,
        source_urls=source_urls,
        content_kind=content_kind,
    )
    link_preview_options = _build_link_preview_options(
        preview_url,
        prefer_large_media=prefer_large_preview,
    )
    placeholder = take_progress(message.chat_id)
    if placeholder is not None:
        try:
            return await placeholder.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                link_preview_options=link_preview_options,
                reply_markup=reply_markup,
            )
        except TelegramError:
            LOGGER.debug("Could not edit loading placeholder", exc_info=True)
            await delete_message_safely(placeholder)

    return await _send_card(
        message.reply_text,
        link_preview_options=link_preview_options,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )


async def _send_card(
    send: Callable[..., Awaitable[Any]],
    *,
    link_preview_options: LinkPreviewOptions,
    **message: Any,
) -> Any:
    """Send a card; if Telegram refuses it with its link preview, send it bare.

    A preview Telegram cannot build (a blocked or age-restricted video, a page
    that times out) must not cost the user the whole card.
    """
    try:
        return await send(link_preview_options=link_preview_options, **message)
    except BadRequest as exc:
        if link_preview_options.is_disabled:
            raise
        LOGGER.warning(
            "Telegram refused a card with its preview, sending it without: %s",
            exc.message,
        )
        return await send(
            link_preview_options=LinkPreviewOptions(is_disabled=True), **message
        )


def _validate_transport_contract(
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None,
    preview_url: str | None,
    found_count: int,
    requested_count: int,
    source_urls: tuple[str, ...],
    content_kind: str,
) -> None:
    require_valid_publication(
        RenderedPublication(
            text=text,
            keyboard=reply_markup,
            preview_url=preview_url,
            source_urls=source_urls,
            found_count=found_count,
            requested_count=requested_count,
            mode="classic",
            content_kind=content_kind,
        )
    )
