from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from telegram import Bot, InlineKeyboardMarkup, Message
from telegram.ext import ContextTypes

from music_links_bot.bot_runtime import encode_callback
from music_links_bot.collection_collage import (
    branded_frame_preview_url,
    media_collage_preview_url,
    video_collage_preview_url,
)
from music_links_bot.formatter import (
    format_artist_collection_message,
    format_artist_message,
    format_mixed_collection_message,
    format_playlist_collection_message,
    format_playlist_message,
    format_radio_collection_message,
    format_radio_message,
    format_title_message,
    format_video_collection_message,
    format_video_message,
)
from music_links_bot.i18n import get_text
from music_links_bot.keyboards import (
    _build_artist_collection_keyboard,
    _build_artist_keyboard,
    _build_mixed_collection_keyboard,
    _build_nts_collection_keyboard,
    _build_nts_keyboard,
    _build_playlist_collection_keyboard,
    _build_playlist_keyboard,
    _build_title_keyboard,
    _build_youtube_collection_keyboard,
    _build_youtube_keyboard,
    _select_preview_url,
)
from music_links_bot.models import (
    ArtistMatch,
    PlaylistMatch,
    RadioMatch,
    TitleMatch,
    TrackMatch,
    VideoMatch,
)
from music_links_bot.publication_budget import compose_with_intro
from music_links_bot.sharing import (
    add_share_button,
    build_share_query,
    collection_result_title,
    track_share_url,
)
from music_links_bot.telegram_buttons import button as InlineKeyboardButton
from music_links_bot.youtube import video_preview_url, video_still_url

SendTrackResult = Callable[..., Awaitable[Any]]
SendTrackVideoPairResult = Callable[..., Awaitable[bool]]


def _with_user_intro(user_prefix: str, body_html: str) -> str:
    text, _intro = compose_with_intro(
        {"quote": bool(user_prefix)},
        prefix_html=user_prefix,
        body_html=body_html,
    )
    return text


async def send_title_result(
    bot: Bot,
    message: Message,
    titles: list[TitleMatch],
    *,
    send_track_result: SendTrackResult,
    user_prefix: str,
    include_channel_button: bool,
    include_hashtags: bool,
    lang: str,
    allow_share: bool = True,
) -> None:
    """One card per film or series; the user's own text tops the first one."""
    for title in titles:
        keyboard = _build_title_keyboard(
            title,
            include_channel_button=include_channel_button,
            bot_username=getattr(bot, "username", None),
        )
        if allow_share:
            keyboard = add_share_button(
                keyboard,
                share_query=build_share_query([title.url]),
                label=get_text(lang, "share_post"),
            )
        await send_track_result(
            bot,
            message,
            _with_user_intro(
                user_prefix,
                format_title_message(title, include_hashtags=include_hashtags),
            ),
            preview_url=branded_frame_preview_url(title.image_url)
            or title.image_url
            or title.watch_url,
            reply_markup=keyboard,
            source_urls=(title.url,),
            content_kind="title",
        )
        user_prefix = ""


@dataclass(frozen=True, slots=True)
class _Cards:
    """How one kind of link becomes a single card or a collection post."""

    kind: str  # a single card's content kind and the collection's item kind
    keyboard: Callable[..., InlineKeyboardMarkup]
    collection_keyboard: Callable[..., InlineKeyboardMarkup]
    message: Callable[..., str]
    collection_message: Callable[..., str]
    # A collage of the frames (▶ on each) shows at a glance that the post
    # holds several videos; one native player preview would hide the rest.
    collage: Callable[[list], str | None] | None = None
    # A single card's preview (default: its own link) and a still image to
    # fall back to when Telegram cannot build that preview.
    preview: Callable[[Any], str] | None = None
    still: Callable[[Any], str | None] | None = None


_VIDEO_CARDS = _Cards(
    "video",
    _build_youtube_keyboard,
    _build_youtube_collection_keyboard,
    format_video_message,
    format_video_collection_message,
    collage=video_collage_preview_url,
    preview=video_preview_url,
    still=video_still_url,
)
_RADIO_CARDS = _Cards(
    "radio",
    _build_nts_keyboard,
    _build_nts_collection_keyboard,
    format_radio_message,
    format_radio_collection_message,
)
_PLAYLIST_CARDS = _Cards(
    "playlist",
    _build_playlist_keyboard,
    _build_playlist_collection_keyboard,
    format_playlist_message,
    format_playlist_collection_message,
)
_ARTIST_CARDS = _Cards(
    "artist",
    _build_artist_keyboard,
    _build_artist_collection_keyboard,
    format_artist_message,
    format_artist_collection_message,
)


async def _send_cards(
    bot: Bot,
    message: Message,
    items: Sequence[Any],
    cards: _Cards,
    *,
    send_track_result: SendTrackResult,
    user_prefix: str,
    include_channel_button: bool,
    include_hashtags: bool,
    lang: str,
    allow_share: bool,
    requested_count: int | None,
    extra_single_row: list[InlineKeyboardButton] | None = None,
) -> None:
    """One card for one link, else one collection post with all of them."""
    if not items:
        return

    urls = [item.url for item in items]
    total = max(len(items), int(requested_count or len(items)))
    delivery: dict[str, Any]
    if total == 1:
        keyboard = cards.keyboard(
            urls[0], include_channel_button=include_channel_button
        )
        if extra_single_row:
            keyboard = InlineKeyboardMarkup(
                [*[list(row) for row in keyboard.inline_keyboard], extra_single_row]
            )
        body = cards.message(items[0], include_hashtags=include_hashtags)
        delivery = {
            "preview_url": cards.preview(items[0]) if cards.preview else urls[0],
            "source_urls": (urls[0],),
            "content_kind": cards.kind,
        }
        if cards.still and (still := cards.still(items[0])):
            delivery["fallback_preview_url"] = still
    else:
        keyboard = cards.collection_keyboard(
            items, include_channel_button=include_channel_button
        )
        body = cards.collection_message(
            items,
            include_hashtags=include_hashtags,
            title=collection_result_title(
                lang, found=len(items), total=total, item_kind=cards.kind
            ),
        )
        delivery = {
            "preview_url": (cards.collage and cards.collage(list(items))) or urls[0],
            "found_count": len(items),
            "requested_count": total,
            "source_urls": tuple(urls),
            "content_kind": "collection",
        }
    if allow_share:
        keyboard = add_share_button(
            keyboard,
            share_query=build_share_query(urls),
            label=get_text(lang, "share_post"),
        )
    await send_track_result(
        bot,
        message,
        _with_user_intro(user_prefix, body),
        reply_markup=keyboard,
        **delivery,
    )


async def send_youtube_result(
    bot: Bot,
    message: Message,
    videos: list[VideoMatch],
    *,
    send_track_result: SendTrackResult,
    user_prefix: str,
    include_channel_button: bool,
    include_hashtags: bool,
    lang: str,
    allow_share: bool = True,
    requested_count: int | None = None,
) -> None:
    await _send_cards(
        bot,
        message,
        videos,
        _VIDEO_CARDS,
        send_track_result=send_track_result,
        user_prefix=user_prefix,
        include_channel_button=include_channel_button,
        include_hashtags=include_hashtags,
        lang=lang,
        allow_share=allow_share,
        requested_count=requested_count,
    )


async def send_nts_result(
    bot: Bot,
    message: Message,
    radios: list[RadioMatch],
    *,
    send_track_result: SendTrackResult,
    user_prefix: str,
    include_channel_button: bool,
    include_hashtags: bool,
    lang: str,
    allow_share: bool = True,
    requested_count: int | None = None,
) -> None:
    await _send_cards(
        bot,
        message,
        radios,
        _RADIO_CARDS,
        send_track_result=send_track_result,
        user_prefix=user_prefix,
        include_channel_button=include_channel_button,
        include_hashtags=include_hashtags,
        lang=lang,
        allow_share=allow_share,
        requested_count=requested_count,
    )


async def send_playlist_result(
    bot: Bot,
    message: Message,
    playlists: list[PlaylistMatch],
    *,
    send_track_result: SendTrackResult,
    user_prefix: str,
    include_channel_button: bool,
    include_hashtags: bool,
    lang: str,
    allow_share: bool = True,
    requested_count: int | None = None,
    import_id: str | None = None,
) -> None:
    await _send_cards(
        bot,
        message,
        playlists,
        _PLAYLIST_CARDS,
        send_track_result=send_track_result,
        user_prefix=user_prefix,
        include_channel_button=include_channel_button,
        include_hashtags=include_hashtags,
        lang=lang,
        allow_share=allow_share,
        requested_count=requested_count,
        extra_single_row=[
            InlineKeyboardButton(
                get_text(lang, "playlist_import"),
                callback_data=encode_callback("playlist", "import", import_id),
                style="success",
            )
        ]
        if import_id
        else None,
    )


async def send_artist_result(
    bot: Bot,
    message: Message,
    artists: list[ArtistMatch],
    *,
    send_track_result: SendTrackResult,
    user_prefix: str,
    include_channel_button: bool,
    include_hashtags: bool,
    lang: str,
    allow_share: bool = True,
    requested_count: int | None = None,
) -> None:
    await _send_cards(
        bot,
        message,
        artists,
        _ARTIST_CARDS,
        send_track_result=send_track_result,
        user_prefix=user_prefix,
        include_channel_button=include_channel_button,
        include_hashtags=include_hashtags,
        lang=lang,
        allow_share=allow_share,
        requested_count=requested_count,
    )


async def send_mixed_result(
    bot: Bot,
    message: Message,
    tracks: list[TrackMatch],
    videos: list[VideoMatch],
    radios: list[RadioMatch],
    playlists: list[PlaylistMatch],
    artists: list[ArtistMatch],
    *,
    send_track_result: SendTrackResult,
    send_track_video_pair_result: SendTrackVideoPairResult,
    user_prefix: str,
    include_channel_button: bool,
    include_hashtags: bool,
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
    allow_share: bool = True,
    requested_count: int | None = None,
) -> None:
    preview_url = select_mixed_preview_url(
        tracks,
        playlists,
        artists,
        radios,
        videos,
        context,
    )
    found_count = (
        len(tracks) + len(videos) + len(radios) + len(playlists) + len(artists)
    )
    total = max(found_count, int(requested_count or found_count))
    text = _with_user_intro(
        user_prefix,
        format_mixed_collection_message(
            tracks,
            videos,
            playlists,
            artists,
            radios,
            include_hashtags=include_hashtags,
            title=(
                collection_result_title(
                    lang,
                    found=found_count,
                    total=total,
                    item_kind="item",
                )
                if found_count < total
                else None
            ),
        ),
    )
    keyboard = _build_mixed_collection_keyboard(
        tracks,
        videos,
        playlists,
        artists,
        radios,
        include_channel_button=include_channel_button,
    )
    if allow_share:
        keyboard = add_share_button(
            keyboard,
            share_query=build_share_query(
                [
                    *[track_share_url(track) or "" for track in tracks],
                    *[playlist.url for playlist in playlists],
                    *[artist.url for artist in artists],
                    *[radio.url for radio in radios],
                    *[video.url for video in videos],
                ]
            ),
            label=get_text(lang, "share_post"),
        )
    videos_in_post = False
    if tracks and videos and not playlists and not artists and not radios:
        # One post: release covers beside the clip frames (▶ on each frame)
        # instead of a single platform preview or an album plus a button panel.
        collage = (
            video_collage_preview_url(videos, track=tracks[0])
            if len(tracks) == 1
            else media_collage_preview_url(tracks, videos)
        )
        if collage:
            preview_url = collage
            videos_in_post = True
    if (
        not videos_in_post
        and len(tracks) == 1
        and len(videos) == 1
        and not playlists
        and not artists
        and not radios
        and await send_track_video_pair_result(
            bot,
            message,
            text,
            track=tracks[0],
            video=videos[0],
            reply_markup=keyboard,
        )
    ):
        return

    await send_track_result(
        bot,
        message,
        text,
        preview_url=preview_url,
        reply_markup=keyboard,
        found_count=found_count,
        requested_count=total,
        source_urls=(
            *[url for track in tracks for url in track.links.values()],
            *[playlist.url for playlist in playlists],
            *[artist.url for artist in artists],
            *[radio.url for radio in radios],
            *[video.url for video in videos],
        ),
        content_kind="collection",
    )


def select_mixed_preview_url(
    tracks: list[TrackMatch],
    playlists: list[PlaylistMatch],
    artists: list[ArtistMatch],
    radios: list[RadioMatch],
    videos: list[VideoMatch],
    context: ContextTypes.DEFAULT_TYPE,
) -> str | None:
    if tracks:
        return _select_preview_url(tracks[0].links, context)
    if playlists:
        return playlists[0].url
    if artists:
        return artists[0].url
    if radios:
        return radios[0].url
    if videos:
        return video_preview_url(videos[0])
    return None
