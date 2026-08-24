from __future__ import annotations

import logging
from html import escape

from telegram import Bot, InlineKeyboardMarkup, InputMediaPhoto, Message
from telegram.constants import ParseMode
from telegram.error import TelegramError

from music_links_bot.bot_builder import PHOTO_CAPTION_LIMIT, fit_telegram_html
from music_links_bot.models import TrackMatch, VideoMatch
from music_links_bot.rich_publications import (
    build_rich_track_video_html,
    rich_api_unavailable,
    rich_messages_enabled,
    send_rich_publication,
)

LOGGER = logging.getLogger(__name__)


def as_video_track(video: VideoMatch) -> TrackMatch:
    """Represent a video in the ordered collection model."""
    return TrackMatch(
        title=video.title,
        artist=video.author,
        links={},
        page_url=video.url,
        kind="video",
        thumbnail_url=video.thumbnail_url,
    )


def split_track_video_pair(
    items: list[TrackMatch],
) -> tuple[TrackMatch, TrackMatch] | None:
    if len(items) != 2 or {item.kind for item in items} != {"song", "video"}:
        return None
    return (
        next(item for item in items if item.kind == "song"),
        next(item for item in items if item.kind == "video"),
    )


async def send_track_video_album(
    bot: Bot,
    *,
    chat_id: int | str,
    track: TrackMatch,
    video_title: str,
    video_url: str,
    video_thumbnail_url: str | None,
    caption: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> list[Message] | None:
    """Send one Rich music/video card, with a classic album fallback.

    Rich Messages keep the artwork, clickable clip and all actions in a single
    publication.  Older Telegram clients or unavailable API capability fall
    back to the proven two-tile media group and compact action panel.
    """
    if not track.thumbnail_url or not video_thumbnail_url:
        return None

    if rich_messages_enabled():
        video = VideoMatch(
            title=video_title,
            author=track.artist,
            url=video_url,
            thumbnail_url=video_thumbnail_url,
        )
        rich_html = build_rich_track_video_html(
            track,
            video,
            body_html=(
                f"<b>{escape(track.artist)} — {escape(track.title)}</b><br>"
                f'Клип: <a href="{escape(video_url, quote=True)}">'
                f"{escape(video_title)}</a>"
            ),
            hashtags="#stonerhand #track #video",
            reply_markup=reply_markup,
        )
        try:
            sent = await send_rich_publication(
                bot,
                chat_id=chat_id,
                rich_html=rich_html,
            )
            return [sent] if isinstance(sent, Message) else []
        except TelegramError as exc:
            if rich_api_unavailable(exc):
                LOGGER.info("Rich track/video card unavailable; using album")
            else:
                LOGGER.info("Could not send rich track/video card", exc_info=True)

    try:
        media_messages = await bot.send_media_group(
            chat_id=chat_id,
            media=[
                InputMediaPhoto(
                    media=track.thumbnail_url,
                    caption=fit_telegram_html(caption, PHOTO_CAPTION_LIMIT),
                    parse_mode=ParseMode.HTML,
                ),
                InputMediaPhoto(
                    media=video_thumbnail_url,
                    caption=(
                        f'📺 <a href="{escape(video_url, quote=True)}">'
                        f"<b>{escape(video_title)}</b></a>"
                    ),
                    parse_mode=ParseMode.HTML,
                ),
            ],
        )
    except TelegramError:
        LOGGER.info(
            "Could not send track/video album; using card fallback", exc_info=True
        )
        return None

    try:
        action_message = await bot.send_message(
            chat_id=chat_id,
            text="<b>Песня + клип</b>\n<i>выбери, что включить</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    except TelegramError:
        # Both album captions remain tappable, so the post still works even if
        # Telegram rejects the optional action panel.
        LOGGER.info("Track/video album sent without action panel", exc_info=True)
        return list(media_messages)

    return [*media_messages, action_message]
