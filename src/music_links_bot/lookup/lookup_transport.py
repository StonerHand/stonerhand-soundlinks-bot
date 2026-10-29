from __future__ import annotations

import asyncio
import logging
import warnings
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from telegram import Bot, InlineKeyboardMarkup, LinkPreviewOptions, Message
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter, TelegramError, TimedOut

from music_links_bot.cards.keyboards import (
    _build_link_preview_options,
    _select_preview_url,
)
from music_links_bot.cards.sharing import make_channel_safe_keyboard
from music_links_bot.core.models import TrackMatch, VideoMatch
from music_links_bot.editor.bot_builder import fit_telegram_html
from music_links_bot.lookup.bot_progress import take_progress
from music_links_bot.lookup.mixed_post import send_track_video_album
from music_links_bot.publishing.publication_contract import (
    RenderedPublication,
    require_valid_publication,
)
from music_links_bot.tg.ephemeral import (
    ephemeral_card_receiver,
    send_ephemeral_message,
)
from music_links_bot.tg.telegram_gateway import (
    link_preview_capability,
    record_capability_failure,
)
from music_links_bot.tg.telegram_messages import delete_message_safely

LOGGER = logging.getLogger(__name__)
# Telegram builds a link preview before it answers. A YouTube player can take
# longer than the client's default five seconds; the waits stay well inside
# the webhook's 25-second budget even when every fallback is needed.
_PREVIEW_READ_TIMEOUT_SECONDS = 6.0
_STILL_READ_TIMEOUT_SECONDS = 6.0
# A new message cannot be retried after a timeout (it may have landed), so
# Telegram gets longer to build its preview: a YouTube one embeds the video.
# With a full flood wait before it (9 s) this still ends inside the budget.
_SEND_READ_TIMEOUT_SECONDS = 12.0
# Flood control names its wait; a short one is waited out once.
_MAX_FLOOD_WAIT_SECONDS = 9.0


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
    fallback_preview_url: str | None = None,
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
        receiver = ephemeral_card_receiver(message)
        if receiver is not None:
            delivered = await send_ephemeral_message(
                getattr(bot, "token", None),
                message.chat_id,
                receiver,
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
            fallback_preview_url=fallback_preview_url,
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
        fallback_preview_url=fallback_preview_url,
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
    if ephemeral_card_receiver(message) is not None:
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
    fallback_preview_url: str | None = None,
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
            # The progress line becomes the card. An edit is safe to repeat,
            # so a slow preview is retried on the same message with a plainer
            # one; a timed-out edit may already be the card and is never
            # deleted.
            return await _send_card(
                placeholder.edit_text,
                link_preview_options=link_preview_options,
                fallback_preview_url=fallback_preview_url,
                idempotent=True,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
        except BadRequest as exc:
            if "not modified" in exc.message.casefold():
                return placeholder  # an earlier, timed-out edit got through
            # The progress line is gone or cannot be edited: send anew.
            LOGGER.debug("Could not edit loading placeholder", exc_info=True)
            await delete_message_safely(placeholder)

    return await _send_card(
        message.reply_text,
        link_preview_options=link_preview_options,
        fallback_preview_url=fallback_preview_url,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )


async def _send_card(
    send: Callable[..., Awaitable[Any]],
    *,
    link_preview_options: LinkPreviewOptions,
    fallback_preview_url: str | None = None,
    idempotent: bool = False,
    **message: Any,
) -> Any:
    """Send or edit a card; if Telegram cannot build its preview, try a
    plainer one: the still image, then no preview at all.

    A refusal (BadRequest) means nothing was sent, so a plainer retry is safe.
    A timeout is ambiguous: an edit can be repeated, but a new message may
    already be in the chat, so a send is never retried after one.
    """
    attempts: list[tuple[LinkPreviewOptions, float]] = []
    if not link_preview_options.is_disabled:
        first_wait = (
            _PREVIEW_READ_TIMEOUT_SECONDS if idempotent else _SEND_READ_TIMEOUT_SECONDS
        )
        attempts.append((link_preview_options, first_wait))
        if fallback_preview_url and fallback_preview_url != link_preview_options.url:
            still = _build_link_preview_options(
                fallback_preview_url, prefer_large_media=True
            )
            attempts.append((still, _STILL_READ_TIMEOUT_SECONDS))
    for options, read_timeout in attempts:
        try:
            return await _flood_safe(
                send, link_preview_options=options, read_timeout=read_timeout, **message
            )
        except (BadRequest, TimedOut) as exc:
            LOGGER.warning(
                "Telegram could not send a card with its preview (%s): %s",
                type(exc).__name__,
                exc.message,
            )
            if options.url:
                # Later cards skip this site's preview for a few minutes.
                record_capability_failure(
                    link_preview_capability(options.url), exc, unsupported=True
                )
            if isinstance(exc, TimedOut) and not idempotent:
                raise
    return await _flood_safe(
        send, link_preview_options=LinkPreviewOptions(is_disabled=True), **message
    )


async def _flood_safe(send: Callable[..., Awaitable[Any]], **kwargs: Any) -> Any:
    try:
        return await send(**kwargs)
    except RetryAfter as exc:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            delay = exc.retry_after
        wait = delay.total_seconds() if isinstance(delay, timedelta) else float(delay)
        if wait > _MAX_FLOOD_WAIT_SECONDS:
            raise
        LOGGER.warning("Telegram flood control: resending a card in %.0f s", wait)
        await asyncio.sleep(wait)
        return await send(**kwargs)


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
