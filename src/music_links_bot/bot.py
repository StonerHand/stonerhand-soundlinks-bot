from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from urllib.parse import quote

from telegram import (
    Bot,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from music_links_bot.artist import ArtistClient, ArtistLookupError
from music_links_bot.config import Settings
from music_links_bot.constants import INPUT_PLATFORM_HINT, PLATFORM_LABELS
from music_links_bot.formatter import (
    format_artist_collection_message,
    format_artist_message,
    format_collection_message,
    format_mixed_collection_message,
    format_playlist_collection_message,
    format_playlist_message,
    format_radio_collection_message,
    format_radio_message,
    format_track_message,
    format_video_collection_message,
    format_video_message,
    prepend_user_text,
)
from music_links_bot.models import (
    ArtistMatch,
    PlaylistMatch,
    RadioMatch,
    TrackMatch,
    VideoMatch,
)
from music_links_bot.nts import NTSClient, NTSLookupError, build_nts_fallback
from music_links_bot.phrases import pick_phrase
from music_links_bot.playlist import PlaylistClient, PlaylistLookupError
from music_links_bot.songlink import SonglinkClient, SonglinkError, SonglinkLookupError
from music_links_bot.soundcloud import (
    SoundCloudClient,
    SoundCloudLookupError,
    build_soundcloud_fallback,
)
from music_links_bot.stats import (
    format_stats_message,
    load_stats,
    record_artists,
    record_matches,
    record_mixed,
    record_playlists,
    record_radios,
    record_videos,
)
from music_links_bot.url_utils import (
    apple_podcasts_url_type,
    extract_supported_urls,
    is_nts_url,
    is_spotify_artist_url,
    is_spotify_playlist_url,
    is_youtube_video_url,
    spotify_url_type,
    strip_supported_urls,
)
from music_links_bot.youtube import YouTubeClient, YouTubeLookupError

LOGGER = logging.getLogger(__name__)
CHANNEL_USERNAME = "stonerhand"
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME}"
MAX_BUTTON_TEXT_LENGTH = 64
MAX_LINKS_PER_MESSAGE = 12
MAX_USER_NOTE_LENGTH = 700
DEFAULT_PLATFORM_ORDER = (
    "spotify",
    "appleMusic",
    "applePodcasts",
    "youtubeMusic",
    "soundcloud",
    "deezer",
    "tidal",
    "yandexMusic",
)
PUBLIC_BOT_COMMANDS = (
    BotCommand("start", "что умеет бот"),
    BotCommand("help", "короткая инструкция"),
    BotCommand("platforms", "поддерживаемые сервисы"),
    BotCommand("channel", "открыть StonerHand"),
    BotCommand("stats", "статистика"),
)


def build_application(settings: Settings) -> Application:
    songlink_client = SonglinkClient(
        user_countries=settings.songlink_user_countries,
        api_key=settings.songlink_api_key,
    )
    youtube_client = YouTubeClient()
    nts_client = NTSClient()
    soundcloud_client = SoundCloudClient()
    playlist_client = PlaylistClient()
    artist_client = ArtistClient()
    application = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.bot_data["songlink_client"] = songlink_client
    application.bot_data["youtube_client"] = youtube_client
    application.bot_data["nts_client"] = nts_client
    application.bot_data["soundcloud_client"] = soundcloud_client
    application.bot_data["playlist_client"] = playlist_client
    application.bot_data["artist_client"] = artist_client
    application.bot_data["admin_chat_id"] = settings.admin_chat_id
    application.bot_data["platform_order"] = _build_platform_order(settings.primary_platform)

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("guide", guide_command))
    application.add_handler(CommandHandler("platforms", platforms_command))
    application.add_handler(CommandHandler("channel", channel_command))
    application.add_handler(CommandHandler("id", id_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
            track_lookup_message,
        )
    )
    return application


async def sync_application_commands(application: Application) -> None:
    try:
        await application.bot.set_my_commands(PUBLIC_BOT_COMMANDS)
    except TelegramError:
        LOGGER.info("Could not sync bot command menu")


async def close_application_resources(application: Application) -> None:
    client: SonglinkClient | None = application.bot_data.get("songlink_client")
    if client is not None:
        await client.aclose()

    youtube_client: YouTubeClient | None = application.bot_data.get("youtube_client")
    if youtube_client is not None:
        await youtube_client.aclose()

    nts_client: NTSClient | None = application.bot_data.get("nts_client")
    if nts_client is not None:
        await nts_client.aclose()

    soundcloud_client: SoundCloudClient | None = application.bot_data.get(
        "soundcloud_client"
    )
    if soundcloud_client is not None:
        await soundcloud_client.aclose()

    playlist_client: PlaylistClient | None = application.bot_data.get("playlist_client")
    if playlist_client is not None:
        await playlist_client.aclose()

    artist_client: ArtistClient | None = application.bot_data.get("artist_client")
    if artist_client is not None:
        await artist_client.aclose()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    text = (
        "🎧 Кидай ссылку на музыку, YouTube или NTS Radio\n\n"
        "Я соберу аккуратный пост: название, preview и кнопки площадок\n\n"
        "Можно отправить трек, альбом, плейлист, артиста, подкаст, "
        "NTS-эфир или несколько ссылок сразу\n\n"
        "В группах и каналах могу заменить исходную ссылку готовым постом, если у меня есть права админа"
    )
    await update.message.reply_text(text, reply_markup=_build_intro_keyboard(context.bot.username))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    text = (
        "Как пользоваться:\n\n"
        "1. Пришли ссылку на трек, альбом, плейлист, артиста, подкаст, "
        "NTS-эфир или YouTube-видео\n"
        "2. Добавь свой текст над ссылкой, если нужна подводка\n"
        "3. Получи чистую карточку с preview, хэштегами и кнопками\n\n"
        "Несколько ссылок одним сообщением станут подборкой"
    )
    await update.message.reply_text(text, reply_markup=_build_intro_keyboard(context.bot.username))


async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return

    guide = (
        "StonerHand guide\n\n"
        "1. Одна ссылка становится чистым постом с кнопками\n"
        "2. Несколько ссылок становятся подборкой\n"
        "3. Текст над ссылкой превращается в цитату\n"
        "4. Для автозамены в чате нужны права админа на удаление сообщений"
    )
    sent_message = await message.reply_text(
        guide,
        reply_markup=_build_intro_keyboard(context.bot.username),
    )

    if message.chat.type in {"group", "supergroup", "channel"}:
        try:
            await sent_message.pin(disable_notification=True)
        except (BadRequest, Forbidden):
            LOGGER.info("Could not pin guide in chat %s", message.chat_id)


async def platforms_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if not update.message:
        return

    text = (
        "Что можно кидать:\n\n"
        f"{INPUT_PLATFORM_HINT}\n\n"
        "Что вернется:\n"
        "Spotify, Apple Music, Apple Podcasts, YouTube Music, SoundCloud, Deezer, "
        "Tidal, Yandex Music и Song.link, если площадки нашлись\n\n"
        "YouTube оформляю как видео-пост, NTS Radio - как радио-пост, "
        "SoundCloud - как музыкальный пост, Spotify playlist - как плейлист, "
        "Spotify artist - как карточку артиста"
    )
    await update.message.reply_text(text)


async def channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if not update.message:
        return

    await update.message.reply_text(
        "StonerHand рядом",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)]]
        ),
    )


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    message = update.effective_message
    if not message:
        return

    await message.reply_text(f"Chat ID: {message.chat_id}")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return

    admin_chat_id: int | None = context.application.bot_data.get("admin_chat_id")
    include_private = admin_chat_id is not None and message.chat_id == admin_chat_id
    await message.reply_text(
        format_stats_message(load_stats(), include_private=include_private)
    )


async def track_lookup_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    message_text = _message_text(message)
    source_urls = extract_supported_urls(message_text)[:MAX_LINKS_PER_MESSAGE]
    user_prefix = _build_user_prefix(message)
    include_channel_button = _should_include_channel_button(message)
    include_hashtags = _should_include_hashtags(message)
    if not source_urls:
        if message.chat.type != "private":
            return

        no_url_text = pick_phrase("no_url", message_text or str(message.chat_id))
        await message.reply_text(
            f"{no_url_text}\n\n"
            "пришли ссылку на трек, альбом, плейлист, артиста, подкаст, "
            "YouTube-видео или NTS Radio"
        )
        return

    (
        artist_urls,
        playlist_urls,
        youtube_urls,
        nts_urls,
        music_urls,
    ) = _split_source_urls(source_urls)

    if (
        artist_urls
        and not playlist_urls
        and not youtube_urls
        and not nts_urls
        and not music_urls
    ):
        artist_client: ArtistClient = context.application.bot_data["artist_client"]
        artists = await _lookup_artists(artist_client, artist_urls)
        await _send_artist_result(
            context.bot,
            message,
            artists,
            user_prefix=user_prefix,
            include_channel_button=include_channel_button,
            include_hashtags=include_hashtags,
        )
        _record_artists_safely(artists, message)
        return

    if (
        playlist_urls
        and not artist_urls
        and not youtube_urls
        and not nts_urls
        and not music_urls
    ):
        playlist_client: PlaylistClient = context.application.bot_data["playlist_client"]
        playlists = await _lookup_playlists(playlist_client, playlist_urls)
        await _send_playlist_result(
            context.bot,
            message,
            playlists,
            user_prefix=user_prefix,
            include_channel_button=include_channel_button,
            include_hashtags=include_hashtags,
        )
        _record_playlists_safely(playlists, message)
        return

    if (
        youtube_urls
        and not artist_urls
        and not playlist_urls
        and not nts_urls
        and not music_urls
    ):
        youtube_client: YouTubeClient = context.application.bot_data["youtube_client"]
        videos = await _lookup_youtube_videos(youtube_client, youtube_urls)
        await _send_youtube_result(
            context.bot,
            message,
            videos,
            user_prefix=user_prefix,
            include_channel_button=include_channel_button,
            include_hashtags=include_hashtags,
        )
        _record_videos_safely(videos, message)
        return

    if (
        nts_urls
        and not artist_urls
        and not playlist_urls
        and not youtube_urls
        and not music_urls
    ):
        nts_client: NTSClient = context.application.bot_data["nts_client"]
        radios = await _lookup_nts_radios(nts_client, nts_urls)
        await _send_nts_result(
            context.bot,
            message,
            radios,
            user_prefix=user_prefix,
            include_channel_button=include_channel_button,
            include_hashtags=include_hashtags,
        )
        _record_radios_safely(radios, message)
        return

    if youtube_urls or nts_urls or playlist_urls or artist_urls:
        client: SonglinkClient = context.application.bot_data["songlink_client"]
        youtube_client: YouTubeClient = context.application.bot_data["youtube_client"]
        nts_client: NTSClient = context.application.bot_data["nts_client"]
        soundcloud_client: SoundCloudClient = context.application.bot_data[
            "soundcloud_client"
        ]
        playlist_client: PlaylistClient = context.application.bot_data["playlist_client"]
        artist_client: ArtistClient = context.application.bot_data["artist_client"]
        lookup_result, videos, radios, playlists, artists = await asyncio.gather(
            _lookup_tracks(
                client,
                music_urls,
                soundcloud_client=soundcloud_client,
            )
            if music_urls
            else _empty_track_lookup(),
            _lookup_youtube_videos(youtube_client, youtube_urls)
            if youtube_urls
            else _empty_video_lookup(),
            _lookup_nts_radios(nts_client, nts_urls)
            if nts_urls
            else _empty_radio_lookup(),
            _lookup_playlists(playlist_client, playlist_urls)
            if playlist_urls
            else _empty_playlist_lookup(),
            _lookup_artists(artist_client, artist_urls)
            if artist_urls
            else _empty_artist_lookup(),
        )
        tracks, unavailable_urls = lookup_result
        tracks = [track for track in tracks if track.links]

        if unavailable_urls:
            await _notify_admin(
                context,
                "Song.link недоступен при обработке: " + ", ".join(unavailable_urls),
                only_for_channel_message=message,
            )

        item_count = (
            len(tracks)
            + len(videos)
            + len(radios)
            + len(playlists)
            + len(artists)
        )
        if item_count == 0:
            if message.chat.type == "channel":
                return
            await message.reply_text(
                _format_not_found_message(source_urls)
            )
            return

        if item_count == 1 and tracks:
            track = tracks[0]
            await _send_track_result(
                context.bot,
                message,
                user_prefix
                + format_track_message(
                    track,
                    include_hashtags=include_hashtags,
                ),
                preview_url=_select_preview_url(track.links, context),
                reply_markup=_build_link_keyboard(
                    track.links,
                    context=context,
                    include_channel_button=include_channel_button,
                    release_page_url=track.page_url,
                    release_kind=track.kind,
                    release_format=track.release_format,
                ),
                prefer_large_preview=True,
            )
            _record_matches_safely([track], message)
            return

        if item_count == 1 and videos:
            await _send_youtube_result(
                context.bot,
                message,
                videos,
                user_prefix=user_prefix,
                include_channel_button=include_channel_button,
                include_hashtags=include_hashtags,
            )
            _record_videos_safely(videos, message)
            return

        if item_count == 1 and radios:
            await _send_nts_result(
                context.bot,
                message,
                radios,
                user_prefix=user_prefix,
                include_channel_button=include_channel_button,
                include_hashtags=include_hashtags,
            )
            _record_radios_safely(radios, message)
            return

        if item_count == 1 and playlists:
            await _send_playlist_result(
                context.bot,
                message,
                playlists,
                user_prefix=user_prefix,
                include_channel_button=include_channel_button,
                include_hashtags=include_hashtags,
            )
            _record_playlists_safely(playlists, message)
            return

        if item_count == 1 and artists:
            await _send_artist_result(
                context.bot,
                message,
                artists,
                user_prefix=user_prefix,
                include_channel_button=include_channel_button,
                include_hashtags=include_hashtags,
            )
            _record_artists_safely(artists, message)
            return

        if item_count > 1:
            await _send_mixed_result(
                context.bot,
                message,
                tracks,
                videos,
                radios,
                playlists,
                artists,
                user_prefix=user_prefix,
                include_channel_button=include_channel_button,
                include_hashtags=include_hashtags,
                context=context,
            )
            _record_mixed_safely(tracks, videos, radios, playlists, artists, message)
            return

    client: SonglinkClient = context.application.bot_data["songlink_client"]
    soundcloud_client: SoundCloudClient = context.application.bot_data[
        "soundcloud_client"
    ]
    tracks, unavailable_urls = await _lookup_tracks(
        client,
        music_urls,
        soundcloud_client=soundcloud_client,
    )

    if unavailable_urls and not tracks:
        await _notify_admin(
            context,
            "Song.link недоступен при обработке: " + ", ".join(unavailable_urls),
            only_for_channel_message=message,
        )
        if message.chat.type == "channel":
            return
        await message.reply_text(
            pick_phrase("service_unavailable", unavailable_urls[0])
        )
        return

    tracks = [track for track in tracks if track.links]
    if not tracks:
        await _notify_admin(
            context,
            f"Не нашел платформы для ссылок в чате {message.chat_id}: {', '.join(source_urls)}",
            only_for_channel_message=message,
        )
        if message.chat.type == "channel":
            return
        await message.reply_text(
            _format_not_found_message(source_urls)
        )
        return

    if len(tracks) == 1:
        track = tracks[0]
        await _send_track_result(
            context.bot,
            message,
            user_prefix
            + format_track_message(
                track,
                include_hashtags=include_hashtags,
            ),
            preview_url=_select_preview_url(track.links, context),
            reply_markup=_build_link_keyboard(
                track.links,
                context=context,
                include_channel_button=include_channel_button,
                release_page_url=track.page_url,
                release_kind=track.kind,
                release_format=track.release_format,
            ),
            prefer_large_preview=True,
        )
        _record_matches_safely([track], message)
        return

    await _send_track_result(
        context.bot,
        message,
        user_prefix
        + format_collection_message(
            tracks,
            include_hashtags=include_hashtags,
        ),
        preview_url=_select_preview_url(tracks[0].links, context),
        reply_markup=_build_collection_keyboard(
            tracks,
            include_channel_button=include_channel_button,
        ),
        prefer_large_preview=True,
    )
    _record_matches_safely(tracks, message)


def _select_preview_url(
    links: dict[str, str],
    context: ContextTypes.DEFAULT_TYPE | None = None,
) -> str | None:
    platform_order = _get_platform_order(context)
    for platform in platform_order:
        url = links.get(platform)
        if url:
            return url

    return None


def _split_source_urls(
    source_urls: list[str],
) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    artist_urls: list[str] = []
    playlist_urls: list[str] = []
    youtube_urls: list[str] = []
    nts_urls: list[str] = []
    music_urls: list[str] = []

    for source_url in source_urls:
        if is_spotify_artist_url(source_url):
            artist_urls.append(source_url)
        elif is_spotify_playlist_url(source_url):
            playlist_urls.append(source_url)
        elif is_youtube_video_url(source_url):
            youtube_urls.append(source_url)
        elif is_nts_url(source_url):
            nts_urls.append(source_url)
        else:
            music_urls.append(source_url)

    return artist_urls, playlist_urls, youtube_urls, nts_urls, music_urls


def _format_not_found_message(source_urls: list[str]) -> str:
    seed = ",".join(source_urls)
    return (
        f"{pick_phrase('not_found', seed)}\n\n"
        "проверь, что это ссылка на трек, альбом, плейлист, артиста, "
        "подкаст, YouTube-видео или NTS Radio"
    )


async def _lookup_playlists(
    client: PlaylistClient,
    source_urls: list[str],
) -> list[PlaylistMatch]:
    results = await asyncio.gather(
        *(client.lookup_playlist(source_url) for source_url in source_urls),
        return_exceptions=True,
    )

    playlists: list[PlaylistMatch] = []
    for source_url, result in zip(source_urls, results, strict=False):
        if isinstance(result, PlaylistMatch):
            playlists.append(result)
            continue

        if isinstance(result, PlaylistLookupError):
            LOGGER.info("Could not fetch playlist metadata for %s", source_url)
        elif isinstance(result, Exception):
            LOGGER.error(
                "Unexpected error while fetching playlist metadata for %s",
                source_url,
                exc_info=(type(result), result, result.__traceback__),
            )

        playlists.append(
            PlaylistMatch(title="Spotify playlist", platform="Spotify", url=source_url)
        )

    return playlists


async def _lookup_artists(
    client: ArtistClient,
    source_urls: list[str],
) -> list[ArtistMatch]:
    results = await asyncio.gather(
        *(client.lookup_artist(source_url) for source_url in source_urls),
        return_exceptions=True,
    )

    artists: list[ArtistMatch] = []
    for source_url, result in zip(source_urls, results, strict=False):
        if isinstance(result, ArtistMatch):
            artists.append(result)
            continue

        if isinstance(result, ArtistLookupError):
            LOGGER.info("Could not fetch artist metadata for %s", source_url)
        elif isinstance(result, Exception):
            LOGGER.error(
                "Unexpected error while fetching artist metadata for %s",
                source_url,
                exc_info=(type(result), result, result.__traceback__),
            )

        artists.append(
            ArtistMatch(title="Spotify artist", platform="Spotify", url=source_url)
        )

    return artists


async def _empty_track_lookup() -> tuple[list[TrackMatch], list[str]]:
    return [], []


async def _empty_video_lookup() -> list[VideoMatch]:
    return []


async def _empty_radio_lookup() -> list[RadioMatch]:
    return []


async def _empty_playlist_lookup() -> list[PlaylistMatch]:
    return []


async def _empty_artist_lookup() -> list[ArtistMatch]:
    return []


async def _lookup_youtube_videos(
    client: YouTubeClient,
    source_urls: list[str],
) -> list[VideoMatch]:
    results = await asyncio.gather(
        *(client.lookup_video(source_url) for source_url in source_urls),
        return_exceptions=True,
    )

    videos: list[VideoMatch] = []
    for source_url, result in zip(source_urls, results, strict=False):
        if isinstance(result, VideoMatch):
            videos.append(result)
            continue

        if isinstance(result, YouTubeLookupError):
            LOGGER.info("Could not fetch YouTube metadata for %s", source_url)
        elif isinstance(result, Exception):
            LOGGER.error(
                "Unexpected error while fetching YouTube metadata for %s",
                source_url,
                exc_info=(type(result), result, result.__traceback__),
            )

        videos.append(VideoMatch(title="YouTube video", author="YouTube", url=source_url))

    return videos


async def _lookup_nts_radios(
    client: NTSClient,
    source_urls: list[str],
) -> list[RadioMatch]:
    results = await asyncio.gather(
        *(client.lookup_radio(source_url) for source_url in source_urls),
        return_exceptions=True,
    )

    radios: list[RadioMatch] = []
    for source_url, result in zip(source_urls, results, strict=False):
        if isinstance(result, RadioMatch):
            radios.append(result)
            continue

        if isinstance(result, NTSLookupError):
            LOGGER.info("Could not fetch NTS metadata for %s", source_url)
        elif isinstance(result, Exception):
            LOGGER.error(
                "Unexpected error while fetching NTS metadata for %s",
                source_url,
                exc_info=(type(result), result, result.__traceback__),
            )

        fallback_radio = build_nts_fallback(source_url)
        if fallback_radio is not None:
            radios.append(fallback_radio)

    return radios


async def _send_youtube_result(
    bot: Bot,
    message: Message,
    videos: list[VideoMatch],
    *,
    user_prefix: str,
    include_channel_button: bool,
    include_hashtags: bool,
) -> None:
    if not videos:
        return

    if len(videos) == 1:
        video = videos[0]
        await _send_track_result(
            bot,
            message,
            user_prefix + format_video_message(video, include_hashtags=include_hashtags),
            preview_url=video.url,
            reply_markup=_build_youtube_keyboard(
                video.url,
                include_channel_button=include_channel_button,
            ),
            prefer_large_preview=True,
        )
        return

    await _send_track_result(
        bot,
        message,
        user_prefix
        + format_video_collection_message(videos, include_hashtags=include_hashtags),
        preview_url=videos[0].url,
        reply_markup=_build_youtube_collection_keyboard(
            videos,
            include_channel_button=include_channel_button,
        ),
        prefer_large_preview=True,
    )


async def _send_nts_result(
    bot: Bot,
    message: Message,
    radios: list[RadioMatch],
    *,
    user_prefix: str,
    include_channel_button: bool,
    include_hashtags: bool,
) -> None:
    if not radios:
        return

    if len(radios) == 1:
        radio = radios[0]
        await _send_track_result(
            bot,
            message,
            user_prefix + format_radio_message(radio, include_hashtags=include_hashtags),
            preview_url=radio.url,
            reply_markup=_build_nts_keyboard(
                radio.url,
                include_channel_button=include_channel_button,
            ),
            prefer_large_preview=True,
        )
        return

    await _send_track_result(
        bot,
        message,
        user_prefix
        + format_radio_collection_message(radios, include_hashtags=include_hashtags),
        preview_url=radios[0].url,
        reply_markup=_build_nts_collection_keyboard(
            radios,
            include_channel_button=include_channel_button,
        ),
        prefer_large_preview=True,
    )


async def _send_playlist_result(
    bot: Bot,
    message: Message,
    playlists: list[PlaylistMatch],
    *,
    user_prefix: str,
    include_channel_button: bool,
    include_hashtags: bool,
) -> None:
    if not playlists:
        return

    if len(playlists) == 1:
        playlist = playlists[0]
        await _send_track_result(
            bot,
            message,
            user_prefix
            + format_playlist_message(playlist, include_hashtags=include_hashtags),
            preview_url=playlist.url,
            reply_markup=_build_playlist_keyboard(
                playlist.url,
                include_channel_button=include_channel_button,
            ),
            prefer_large_preview=True,
        )
        return

    await _send_track_result(
        bot,
        message,
        user_prefix
        + format_playlist_collection_message(
            playlists,
            include_hashtags=include_hashtags,
        ),
        preview_url=playlists[0].url,
        reply_markup=_build_playlist_collection_keyboard(
            playlists,
            include_channel_button=include_channel_button,
        ),
        prefer_large_preview=True,
    )


async def _send_artist_result(
    bot: Bot,
    message: Message,
    artists: list[ArtistMatch],
    *,
    user_prefix: str,
    include_channel_button: bool,
    include_hashtags: bool,
) -> None:
    if not artists:
        return

    if len(artists) == 1:
        artist = artists[0]
        await _send_track_result(
            bot,
            message,
            user_prefix + format_artist_message(artist, include_hashtags=include_hashtags),
            preview_url=artist.url,
            reply_markup=_build_artist_keyboard(
                artist.url,
                include_channel_button=include_channel_button,
            ),
            prefer_large_preview=True,
        )
        return

    await _send_track_result(
        bot,
        message,
        user_prefix
        + format_artist_collection_message(
            artists,
            include_hashtags=include_hashtags,
        ),
        preview_url=artists[0].url,
        reply_markup=_build_artist_collection_keyboard(
            artists,
            include_channel_button=include_channel_button,
        ),
        prefer_large_preview=True,
    )


async def _send_mixed_result(
    bot: Bot,
    message: Message,
    tracks: list[TrackMatch],
    videos: list[VideoMatch],
    radios: list[RadioMatch],
    playlists: list[PlaylistMatch],
    artists: list[ArtistMatch],
    *,
    user_prefix: str,
    include_channel_button: bool,
    include_hashtags: bool,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    preview_url = _select_mixed_preview_url(
        tracks,
        playlists,
        artists,
        radios,
        videos,
        context,
    )
    await _send_track_result(
        bot,
        message,
        user_prefix
        + format_mixed_collection_message(
            tracks,
            videos,
            playlists,
            artists,
            radios,
            include_hashtags=include_hashtags,
        ),
        preview_url=preview_url,
        reply_markup=_build_mixed_collection_keyboard(
            tracks,
            videos,
            playlists,
            artists,
            radios,
            include_channel_button=include_channel_button,
        ),
        prefer_large_preview=True,
    )


def _select_mixed_preview_url(
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


async def _lookup_tracks(
    client: SonglinkClient,
    source_urls: list[str],
    *,
    soundcloud_client: SoundCloudClient | None = None,
) -> tuple[list[TrackMatch], list[str]]:
    results = await asyncio.gather(
        *(client.lookup_track(source_url) for source_url in source_urls),
        return_exceptions=True,
    )

    tracks: list[TrackMatch] = []
    unavailable_urls: list[str] = []

    for source_url, result in zip(source_urls, results, strict=False):
        if isinstance(result, TrackMatch):
            tracks.append(result)
            continue

        if isinstance(result, SonglinkError):
            fallback_track = await _build_lookup_fallback(
                source_url,
                soundcloud_client=soundcloud_client,
            )
            if fallback_track:
                tracks.append(fallback_track)
                continue

            if isinstance(result, SonglinkLookupError):
                LOGGER.info("Song.link could not resolve %s", source_url)
                continue

            LOGGER.error(
                "Song.link request failed for %s",
                source_url,
                exc_info=(type(result), result, result.__traceback__),
            )
            unavailable_urls.append(source_url)
            continue

        if isinstance(result, Exception):
            LOGGER.error(
                "Unexpected error while resolving %s",
                source_url,
                exc_info=(type(result), result, result.__traceback__),
            )
            unavailable_urls.append(source_url)

    return tracks, unavailable_urls


async def _build_lookup_fallback(
    source_url: str,
    *,
    soundcloud_client: SoundCloudClient | None,
) -> TrackMatch | None:
    podcast_fallback = _build_podcast_fallback(source_url)
    if podcast_fallback:
        return podcast_fallback

    generic_soundcloud_fallback = build_soundcloud_fallback(source_url)
    if generic_soundcloud_fallback is None:
        return None

    if soundcloud_client is None:
        return generic_soundcloud_fallback

    try:
        return await soundcloud_client.lookup_track(source_url)
    except SoundCloudLookupError:
        LOGGER.info("Could not fetch SoundCloud metadata for %s", source_url)
    except Exception:
        LOGGER.exception(
            "Unexpected error while fetching SoundCloud metadata for %s",
            source_url,
        )

    return generic_soundcloud_fallback


def _build_podcast_fallback(source_url: str) -> TrackMatch | None:
    spotify_type = spotify_url_type(source_url)
    if spotify_type == "episode":
        return TrackMatch(
            title="Podcast episode",
            artist="Spotify",
            links={"spotify": source_url},
            page_url=source_url,
            kind="podcast",
        )

    if spotify_type == "show":
        return TrackMatch(
            title="Podcast show",
            artist="Spotify",
            links={"spotify": source_url},
            page_url=source_url,
            kind="podcast",
            release_format="show",
        )

    apple_podcast_type = apple_podcasts_url_type(source_url)
    if apple_podcast_type == "episode":
        return TrackMatch(
            title="Podcast episode",
            artist="Apple Podcasts",
            links={"applePodcasts": source_url},
            page_url=source_url,
            kind="podcast",
        )

    if apple_podcast_type == "show":
        return TrackMatch(
            title="Podcast show",
            artist="Apple Podcasts",
            links={"applePodcasts": source_url},
            page_url=source_url,
            kind="podcast",
            release_format="show",
        )

    return None


async def _send_track_result(
    bot: Bot,
    message: Message,
    text: str,
    *,
    preview_url: str | None,
    reply_markup: InlineKeyboardMarkup | None,
    prefer_large_preview: bool = False,
) -> None:
    if message.chat.type in {"group", "supergroup", "channel"} and await _try_delete_message(message):
        await bot.send_message(
            chat_id=message.chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            link_preview_options=_build_link_preview_options(
                preview_url,
                prefer_large_media=prefer_large_preview,
            ),
            reply_markup=reply_markup,
        )
        return

    await _reply_with_track(
        message,
        text,
        preview_url=preview_url,
        reply_markup=reply_markup,
        prefer_large_preview=prefer_large_preview,
    )


async def _reply_with_track(
    message: Message,
    text: str,
    *,
    preview_url: str | None,
    reply_markup: InlineKeyboardMarkup | None,
    prefer_large_preview: bool = False,
) -> Message:
    return await message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
        link_preview_options=_build_link_preview_options(
            preview_url,
            prefer_large_media=prefer_large_preview,
        ),
        reply_markup=reply_markup,
    )


def _build_link_preview_options(
    preview_url: str | None,
    *,
    prefer_large_media: bool = False,
) -> LinkPreviewOptions:
    if not preview_url:
        return LinkPreviewOptions(is_disabled=True)

    media_preferences = (
        {"prefer_large_media": True}
        if prefer_large_media
        else {"prefer_small_media": True}
    )
    return LinkPreviewOptions(
        is_disabled=False,
        url=preview_url,
        show_above_text=prefer_large_media,
        **media_preferences,
    )


def _build_link_keyboard(
    links: dict[str, str],
    *,
    prefix: str = "",
    context: ContextTypes.DEFAULT_TYPE | None = None,
    include_channel_button: bool = True,
    release_page_url: str | None = None,
    release_kind: str = "song",
    release_format: str | None = None,
) -> InlineKeyboardMarkup:
    platform_order = _get_platform_order(context)
    ordered_platforms = [
        platform_key
        for platform_key in platform_order
        if links.get(platform_key) and platform_key in PLATFORM_LABELS
    ]
    remaining_platforms = [
        platform_key
        for platform_key in PLATFORM_LABELS
        if platform_key not in ordered_platforms and links.get(platform_key)
    ]
    buttons = [
        InlineKeyboardButton(
            text=f"{prefix}{PLATFORM_LABELS[platform_key]}",
            url=links[platform_key],
        )
        for platform_key in [*ordered_platforms, *remaining_platforms]
    ]
    rows: list[list[InlineKeyboardButton]] = []
    if release_page_url:
        rows.append(
            [
                InlineKeyboardButton(
                    _release_hub_button_label(release_kind, release_format),
                    url=release_page_url,
                )
            ]
        )

    rows.extend(_button_rows(buttons))
    if include_channel_button:
        rows.append([InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)])

    return InlineKeyboardMarkup(rows)


def _build_collection_keyboard(
    tracks: list[TrackMatch],
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []

    for index, track in enumerate(tracks, start=1):
        destination = track.page_url or _select_preview_url(track.links)
        if not destination:
            continue

        buttons.append(
            InlineKeyboardButton(
                text=_shorten_button_text(
                    f"{_track_button_icon(track)} {index}. {track.artist} - {track.title}"
                ),
                url=destination,
            )
        )

    rows = _button_rows(buttons)
    if include_channel_button:
        rows.append([InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)])

    return InlineKeyboardMarkup(rows)


def _build_youtube_keyboard(
    url: str,
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("📺 Смотреть на YouTube", url=url)]]
    if include_channel_button:
        rows.append([InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)])

    return InlineKeyboardMarkup(rows)


def _build_nts_keyboard(
    url: str,
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("📡 Открыть на NTS", url=url)]]
    if include_channel_button:
        rows.append([InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)])

    return InlineKeyboardMarkup(rows)


def _build_playlist_keyboard(
    url: str,
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("🎛 Открыть плейлист", url=url)]]
    if include_channel_button:
        rows.append([InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)])

    return InlineKeyboardMarkup(rows)


def _build_artist_keyboard(
    url: str,
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("🧬 Открыть артиста", url=url)]]
    if include_channel_button:
        rows.append([InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)])

    return InlineKeyboardMarkup(rows)


def _build_youtube_collection_keyboard(
    videos: list[VideoMatch],
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    for index, video in enumerate(videos, start=1):
        buttons.append(
            InlineKeyboardButton(
                text=_shorten_button_text(f"📺 {index}. {video.title}"),
                url=video.url,
            )
        )

    rows = _button_rows(buttons)
    if include_channel_button:
        rows.append([InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)])

    return InlineKeyboardMarkup(rows)


def _build_nts_collection_keyboard(
    radios: list[RadioMatch],
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    for index, radio in enumerate(radios, start=1):
        buttons.append(
            InlineKeyboardButton(
                text=_shorten_button_text(f"📡 {index}. {radio.title}"),
                url=radio.url,
            )
        )

    rows = _button_rows(buttons)
    if include_channel_button:
        rows.append([InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)])

    return InlineKeyboardMarkup(rows)


def _build_playlist_collection_keyboard(
    playlists: list[PlaylistMatch],
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    for index, playlist in enumerate(playlists, start=1):
        buttons.append(
            InlineKeyboardButton(
                text=_shorten_button_text(f"🎛 {index}. {playlist.title}"),
                url=playlist.url,
            )
        )

    rows = _button_rows(buttons)
    if include_channel_button:
        rows.append([InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)])

    return InlineKeyboardMarkup(rows)


def _build_artist_collection_keyboard(
    artists: list[ArtistMatch],
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    for index, artist in enumerate(artists, start=1):
        buttons.append(
            InlineKeyboardButton(
                text=_shorten_button_text(f"🧬 {index}. {artist.title}"),
                url=artist.url,
            )
        )

    rows = _button_rows(buttons)
    if include_channel_button:
        rows.append([InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)])

    return InlineKeyboardMarkup(rows)


def _build_mixed_collection_keyboard(
    tracks: list[TrackMatch],
    videos: list[VideoMatch],
    playlists: list[PlaylistMatch] | None = None,
    artists: list[ArtistMatch] | None = None,
    radios: list[RadioMatch] | None = None,
    *,
    include_channel_button: bool = True,
) -> InlineKeyboardMarkup:
    playlists = playlists or []
    artists = artists or []
    radios = radios or []
    buttons: list[InlineKeyboardButton] = []
    index = 1

    for track in tracks:
        destination = track.page_url or _select_preview_url(track.links)
        if not destination:
            continue

        buttons.append(
            InlineKeyboardButton(
                text=_shorten_button_text(
                    f"{_track_button_icon(track)} {index}. {track.artist} - {track.title}"
                ),
                url=destination,
            )
        )
        index += 1

    for playlist in playlists:
        buttons.append(
            InlineKeyboardButton(
                text=_shorten_button_text(f"🎛 {index}. {playlist.title}"),
                url=playlist.url,
            )
        )
        index += 1

    for artist in artists:
        buttons.append(
            InlineKeyboardButton(
                text=_shorten_button_text(f"🧬 {index}. {artist.title}"),
                url=artist.url,
            )
        )
        index += 1

    for radio in radios:
        buttons.append(
            InlineKeyboardButton(
                text=_shorten_button_text(f"📡 {index}. {radio.title}"),
                url=radio.url,
            )
        )
        index += 1

    for video in videos:
        buttons.append(
            InlineKeyboardButton(
                text=_shorten_button_text(f"📺 {index}. {video.title}"),
                url=video.url,
            )
        )
        index += 1

    rows = _button_rows(buttons)
    if include_channel_button:
        rows.append([InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)])

    return InlineKeyboardMarkup(rows)


def _should_include_channel_button(message: Message) -> bool:
    username = message.chat.username
    return not (
        message.chat.type == "channel"
        and username is not None
        and username.casefold() == CHANNEL_USERNAME
    )


def _should_include_hashtags(message: Message) -> bool:
    return message.chat.type != "private"


def _build_platform_order(primary_platform: str | None) -> tuple[str, ...]:
    if not primary_platform:
        return DEFAULT_PLATFORM_ORDER

    normalized = primary_platform.strip()
    if normalized not in DEFAULT_PLATFORM_ORDER:
        return DEFAULT_PLATFORM_ORDER

    return (normalized, *(item for item in DEFAULT_PLATFORM_ORDER if item != normalized))


def _shorten_button_text(text: str) -> str:
    if len(text) <= MAX_BUTTON_TEXT_LENGTH:
        return text

    return text[: MAX_BUTTON_TEXT_LENGTH - 1].rstrip() + "…"


def _track_button_icon(track: TrackMatch) -> str:
    if track.kind == "album":
        return "💿"

    if track.kind == "podcast":
        return "🎙️"

    return "🎧"


def _release_hub_button_label(release_kind: str, release_format: str | None) -> str:
    if release_kind == "album":
        if release_format == "ep":
            return "💿 Весь EP"

        return "💿 Весь релиз"

    if release_kind == "podcast":
        return "🎙 Все площадки"

    return "🪩 Все платформы"


def _button_rows(buttons: list[InlineKeyboardButton]) -> list[list[InlineKeyboardButton]]:
    return [buttons[index : index + 2] for index in range(0, len(buttons), 2)]


def _get_platform_order(context: ContextTypes.DEFAULT_TYPE | None) -> tuple[str, ...]:
    if context is None:
        return DEFAULT_PLATFORM_ORDER

    platform_order = context.application.bot_data.get("platform_order")
    if isinstance(platform_order, tuple):
        return platform_order

    return DEFAULT_PLATFORM_ORDER


def _record_matches_safely(tracks: list[TrackMatch], message: Message) -> None:
    try:
        record_matches(
            tracks,
            user=_build_user_stats_entry(message),
            chat=_build_chat_stats_entry(message),
        )
    except Exception:
        LOGGER.exception("Could not update stats")


def _record_videos_safely(videos: list[VideoMatch], message: Message) -> None:
    if not videos:
        return

    try:
        record_videos(
            videos,
            user=_build_user_stats_entry(message),
            chat=_build_chat_stats_entry(message),
        )
    except Exception:
        LOGGER.exception("Could not update video stats")


def _record_radios_safely(radios: list[RadioMatch], message: Message) -> None:
    if not radios:
        return

    try:
        record_radios(
            radios,
            user=_build_user_stats_entry(message),
            chat=_build_chat_stats_entry(message),
        )
    except Exception:
        LOGGER.exception("Could not update radio stats")


def _record_playlists_safely(playlists: list[PlaylistMatch], message: Message) -> None:
    if not playlists:
        return

    try:
        record_playlists(
            playlists,
            user=_build_user_stats_entry(message),
            chat=_build_chat_stats_entry(message),
        )
    except Exception:
        LOGGER.exception("Could not update playlist stats")


def _record_artists_safely(artists: list[ArtistMatch], message: Message) -> None:
    if not artists:
        return

    try:
        record_artists(
            artists,
            user=_build_user_stats_entry(message),
            chat=_build_chat_stats_entry(message),
        )
    except Exception:
        LOGGER.exception("Could not update artist stats")


def _record_mixed_safely(
    tracks: list[TrackMatch],
    videos: list[VideoMatch],
    radios: list[RadioMatch],
    playlists: list[PlaylistMatch],
    artists: list[ArtistMatch],
    message: Message,
) -> None:
    try:
        record_mixed(
            tracks,
            videos,
            playlists,
            artists=artists,
            radios=radios,
            user=_build_user_stats_entry(message),
            chat=_build_chat_stats_entry(message),
        )
    except Exception:
        LOGGER.exception("Could not update mixed stats")


def _build_user_prefix(message: Message) -> str:
    body_text = _shorten_user_note(strip_supported_urls(_message_text(message)))
    if not body_text:
        return ""

    user = message.from_user
    author_label = None
    if user is not None:
        author_label = f"@{user.username}" if user.username else user.full_name

    return prepend_user_text(body_text, author_label=author_label)


def _message_text(message: Message) -> str | None:
    return message.text or message.caption


def _shorten_user_note(text: str) -> str:
    if len(text) <= MAX_USER_NOTE_LENGTH:
        return text

    return text[: MAX_USER_NOTE_LENGTH - 1].rstrip() + "…"


def _build_user_stats_entry(message: Message) -> dict[str, object] | None:
    user = message.from_user
    if user is None:
        return None

    label = f"@{user.username}" if user.username else user.full_name
    return {
        "id": user.id,
        "label": label,
        "last_seen": _current_stats_time(),
    }


def _build_chat_stats_entry(message: Message) -> dict[str, object]:
    chat = message.chat
    label = chat.title or chat.username or str(chat.id)
    if chat.username:
        label = f"@{chat.username}"

    return {
        "id": chat.id,
        "label": f"{label} ({chat.type})",
        "last_seen": _current_stats_time(),
    }


def _current_stats_time() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _build_intro_keyboard(bot_username: str | None) -> InlineKeyboardMarkup:
    main_row = [InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)]
    if bot_username:
        bot_url = f"https://t.me/{bot_username}"
        share_url = "https://t.me/share/url?url=" + quote(bot_url, safe="")
        main_row.append(InlineKeyboardButton("Поделиться ботом", url=share_url))

    return InlineKeyboardMarkup([main_row])


async def _notify_admin(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    only_for_channel_message: Message | None = None,
) -> None:
    if only_for_channel_message and only_for_channel_message.chat.type != "channel":
        return

    admin_chat_id: int | None = context.application.bot_data.get("admin_chat_id")
    if admin_chat_id is None:
        return

    try:
        await context.bot.send_message(chat_id=admin_chat_id, text=text)
    except TelegramError:
        LOGGER.info("Could not notify admin chat %s", admin_chat_id)


async def _try_delete_message(message: Message) -> bool:
    try:
        await message.delete()
    except TelegramError:
        return False

    return True


async def _post_init(application: Application) -> None:
    await sync_application_commands(application)


async def _post_shutdown(application: Application) -> None:
    await close_application_resources(application)
