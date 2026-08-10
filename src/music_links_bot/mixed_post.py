from __future__ import annotations

import logging
from html import escape

from telegram import Bot, InlineKeyboardMarkup, InputMediaPhoto, Message
from telegram.constants import ParseMode
from telegram.error import TelegramError

from music_links_bot.models import TrackMatch, VideoMatch
from music_links_bot.bot_builder import PHOTO_CAPTION_LIMIT, fit_telegram_html

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
    """Send a two-tile native preview plus one compact action panel.

    Telegram cannot attach a shared inline keyboard to a media group, so the
    actions live in a short message immediately below it. If either artwork is
    unavailable, callers can fall back to a regular link-preview post.
    """
    if not track.thumbnail_url or not video_thumbnail_url:
        return None

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
