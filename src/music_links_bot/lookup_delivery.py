from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from telegram import Bot, InlineKeyboardMarkup, Message
from telegram.ext import ContextTypes

from music_links_bot.bot_runtime import encode_callback
from music_links_bot.formatter import (
    format_artist_collection_message,
    format_artist_message,
    format_mixed_collection_message,
    format_playlist_collection_message,
    format_playlist_message,
    format_radio_collection_message,
    format_radio_message,
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
    _build_youtube_collection_keyboard,
    _build_youtube_keyboard,
    _select_preview_url,
)
from music_links_bot.models import (
    ArtistMatch,
    PlaylistMatch,
    RadioMatch,
    TrackMatch,
    VideoMatch,
)
from music_links_bot.sharing import (
    add_share_button,
    build_share_query,
    collection_result_title,
    track_share_url,
)
from music_links_bot.telegram_buttons import button as InlineKeyboardButton

SendTrackResult = Callable[..., Awaitable[Any]]
SendTrackVideoPairResult = Callable[..., Awaitable[bool]]


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
    if not videos:
        return

    total = max(len(videos), int(requested_count or len(videos)))
    if total == 1:
        video = videos[0]
        keyboard = _build_youtube_keyboard(
            video.url,
            include_channel_button=include_channel_button,
        )
        if allow_share:
            keyboard = add_share_button(
                keyboard,
                share_query=build_share_query([video.url]),
                label=get_text(lang, "share_post"),
            )
        await send_track_result(
            bot,
            message,
            user_prefix
            + format_video_message(video, include_hashtags=include_hashtags),
            preview_url=video.url,
            reply_markup=keyboard,
            source_urls=(video.url,),
            content_kind="video",
        )
        return

    collection_keyboard = _build_youtube_collection_keyboard(
        videos,
        include_channel_button=include_channel_button,
    )
    if allow_share:
        collection_keyboard = add_share_button(
            collection_keyboard,
            share_query=build_share_query([video.url for video in videos]),
            label=get_text(lang, "share_post"),
        )
    await send_track_result(
        bot,
        message,
        user_prefix
        + format_video_collection_message(
            videos,
            include_hashtags=include_hashtags,
            title=collection_result_title(
                lang, found=len(videos), total=total, item_kind="video"
            ),
        ),
        preview_url=videos[0].url,
        reply_markup=collection_keyboard,
        found_count=len(videos),
        requested_count=total,
        source_urls=tuple(video.url for video in videos),
        content_kind="collection",
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
    if not radios:
        return

    total = max(len(radios), int(requested_count or len(radios)))
    if total == 1:
        radio = radios[0]
        keyboard = _build_nts_keyboard(
            radio.url,
            include_channel_button=include_channel_button,
        )
        if allow_share:
            keyboard = add_share_button(
                keyboard,
                share_query=build_share_query([radio.url]),
                label=get_text(lang, "share_post"),
            )
        await send_track_result(
            bot,
            message,
            user_prefix
            + format_radio_message(radio, include_hashtags=include_hashtags),
            preview_url=radio.url,
            reply_markup=keyboard,
            source_urls=(radio.url,),
            content_kind="radio",
        )
        return

    collection_keyboard = _build_nts_collection_keyboard(
        radios,
        include_channel_button=include_channel_button,
    )
    if allow_share:
        collection_keyboard = add_share_button(
            collection_keyboard,
            share_query=build_share_query([radio.url for radio in radios]),
            label=get_text(lang, "share_post"),
        )
    await send_track_result(
        bot,
        message,
        user_prefix
        + format_radio_collection_message(
            radios,
            include_hashtags=include_hashtags,
            title=collection_result_title(
                lang, found=len(radios), total=total, item_kind="radio"
            ),
        ),
        preview_url=radios[0].url,
        reply_markup=collection_keyboard,
        found_count=len(radios),
        requested_count=total,
        source_urls=tuple(radio.url for radio in radios),
        content_kind="collection",
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
    if not playlists:
        return

    total = max(len(playlists), int(requested_count or len(playlists)))
    if total == 1:
        playlist = playlists[0]
        keyboard = _build_playlist_keyboard(
            playlist.url,
            include_channel_button=include_channel_button,
        )
        if import_id:
            keyboard = InlineKeyboardMarkup(
                [
                    *[list(row) for row in keyboard.inline_keyboard],
                    [
                        InlineKeyboardButton(
                            get_text(lang, "playlist_import"),
                            callback_data=encode_callback(
                                "playlist", "import", import_id
                            ),
                            style="success",
                        )
                    ],
                ]
            )
        if allow_share:
            keyboard = add_share_button(
                keyboard,
                share_query=build_share_query([playlist.url]),
                label=get_text(lang, "share_post"),
            )
        await send_track_result(
            bot,
            message,
            user_prefix
            + format_playlist_message(playlist, include_hashtags=include_hashtags),
            preview_url=playlist.url,
            reply_markup=keyboard,
            source_urls=(playlist.url,),
            content_kind="playlist",
        )
        return

    collection_keyboard = _build_playlist_collection_keyboard(
        playlists,
        include_channel_button=include_channel_button,
    )
    if allow_share:
        collection_keyboard = add_share_button(
            collection_keyboard,
            share_query=build_share_query([playlist.url for playlist in playlists]),
            label=get_text(lang, "share_post"),
        )
    await send_track_result(
        bot,
        message,
        user_prefix
        + format_playlist_collection_message(
            playlists,
            include_hashtags=include_hashtags,
            title=collection_result_title(
                lang, found=len(playlists), total=total, item_kind="playlist"
            ),
        ),
        preview_url=playlists[0].url,
        reply_markup=collection_keyboard,
        found_count=len(playlists),
        requested_count=total,
        source_urls=tuple(playlist.url for playlist in playlists),
        content_kind="collection",
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
    if not artists:
        return

    total = max(len(artists), int(requested_count or len(artists)))
    if total == 1:
        artist = artists[0]
        keyboard = _build_artist_keyboard(
            artist.url,
            include_channel_button=include_channel_button,
        )
        if allow_share:
            keyboard = add_share_button(
                keyboard,
                share_query=build_share_query([artist.url]),
                label=get_text(lang, "share_post"),
            )
        await send_track_result(
            bot,
            message,
            user_prefix
            + format_artist_message(artist, include_hashtags=include_hashtags),
            preview_url=artist.url,
            reply_markup=keyboard,
            source_urls=(artist.url,),
            content_kind="artist",
        )
        return

    collection_keyboard = _build_artist_collection_keyboard(
        artists,
        include_channel_button=include_channel_button,
    )
    if allow_share:
        collection_keyboard = add_share_button(
            collection_keyboard,
            share_query=build_share_query([artist.url for artist in artists]),
            label=get_text(lang, "share_post"),
        )
    await send_track_result(
        bot,
        message,
        user_prefix
        + format_artist_collection_message(
            artists,
            include_hashtags=include_hashtags,
            title=collection_result_title(
                lang, found=len(artists), total=total, item_kind="artist"
            ),
        ),
        preview_url=artists[0].url,
        reply_markup=collection_keyboard,
        found_count=len(artists),
        requested_count=total,
        source_urls=tuple(artist.url for artist in artists),
        content_kind="collection",
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
    text = user_prefix + format_mixed_collection_message(
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
    if (
        len(tracks) == 1
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
        source_urls=tuple(
            [
                *[url for track in tracks for url in track.links.values()],
                *[playlist.url for playlist in playlists],
                *[artist.url for artist in artists],
                *[radio.url for radio in radios],
                *[video.url for video in videos],
            ]
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
        return videos[0].url
    return None
