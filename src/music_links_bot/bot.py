from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from urllib.parse import quote

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from music_links_bot.config import Settings
from music_links_bot.constants import INPUT_PLATFORM_HINT, PLATFORM_LABELS
from music_links_bot.formatter import (
    format_collection_message,
    format_track_message,
    format_video_collection_message,
    format_video_message,
    prepend_user_text,
)
from music_links_bot.models import TrackMatch, VideoMatch
from music_links_bot.phrases import pick_phrase
from music_links_bot.songlink import SonglinkClient, SonglinkError, SonglinkLookupError
from music_links_bot.stats import (
    format_stats_message,
    load_stats,
    record_matches,
    record_videos,
)
from music_links_bot.url_utils import (
    apple_podcasts_url_type,
    extract_supported_urls,
    is_youtube_video_url,
    spotify_url_type,
    strip_supported_urls,
)
from music_links_bot.youtube import YouTubeClient, YouTubeLookupError

LOGGER = logging.getLogger(__name__)
CHANNEL_URL = "https://t.me/stonerhand"
MAX_BUTTON_TEXT_LENGTH = 64
MAX_LINKS_PER_MESSAGE = 12
MAX_USER_NOTE_LENGTH = 700
DEFAULT_PLATFORM_ORDER = (
    "spotify",
    "appleMusic",
    "applePodcasts",
    "youtubeMusic",
    "deezer",
    "tidal",
    "yandexMusic",
)


def build_application(settings: Settings) -> Application:
    songlink_client = SonglinkClient(
        user_countries=settings.songlink_user_countries,
        api_key=settings.songlink_api_key,
    )
    youtube_client = YouTubeClient()
    application = (
        Application.builder()
        .token(settings.bot_token)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.bot_data["songlink_client"] = songlink_client
    application.bot_data["youtube_client"] = youtube_client
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


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    text = (
        "🎧 Кидай ссылку на трек, альбом, подкаст или YouTube-видео, а я оформлю ее в пост\n\n"
        f"Можно присылать ссылки из: {INPUT_PLATFORM_HINT}\n\n"
        "Если кинешь несколько ссылок одним сообщением, соберу подборку\n\n"
        "В групповых чатах могу удалить оригинальное сообщение и заменить его "
        "постом со всеми линками, если у меня есть права админа"
    )
    await update.message.reply_text(text, reply_markup=_build_intro_keyboard(context.bot.username))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    text = (
        "Как пользоваться:\n\n"
        "1. Пришли ссылку на трек, альбом, подкаст или YouTube-видео\n"
        "2. Я найду релиз на других платформах или оформлю видео отдельным постом\n"
        "3. Верну пост в стиле StonerHand с кнопками\n\n"
        "Если в сообщении несколько ссылок, соберу подборку\n\n"
        "В группах могу удалить оригинальное сообщение со ссылкой и заменить его "
        "постом со всеми линками, если у меня есть права админа"
    )
    await update.message.reply_text(text, reply_markup=_build_intro_keyboard(context.bot.username))


async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return

    guide = (
        "StonerHand guide\n\n"
        "1. Кидай ссылку на трек, альбом, подкаст или YouTube-видео\n"
        "2. Несколько ссылок одним сообщением станут подборкой\n"
        "3. В канале бот заменит исходный пост красивым постом с кнопками\n"
        "4. Для удаления оригинала нужны права админа на управление сообщениями"
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
        "Поддерживаю входящие ссылки из:\n\n"
        f"{INPUT_PLATFORM_HINT}\n\n"
        "А в ответе показываю найденные ссылки на Spotify, Apple Music, "
        "Apple Podcasts, YouTube Music, Deezer, Tidal и Yandex Music\n\n"
        "Обычные YouTube-ссылки оформляю отдельным видео-постом"
    )
    await update.message.reply_text(text)


async def channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if not update.message:
        return

    await update.message.reply_text(
        "Канал StonerHand",
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
    if not source_urls:
        if message.chat.type != "private":
            return

        no_url_text = pick_phrase("no_url", message_text or str(message.chat_id))
        await message.reply_text(
            f"{no_url_text}\n\n"
            f"Пришлите ссылку из сервисов: {INPUT_PLATFORM_HINT}"
        )
        return

    youtube_urls = [
        source_url for source_url in source_urls if is_youtube_video_url(source_url)
    ]
    if youtube_urls and len(youtube_urls) == len(source_urls):
        youtube_client: YouTubeClient = context.application.bot_data["youtube_client"]
        videos = await _lookup_youtube_videos(youtube_client, youtube_urls)
        await _send_youtube_result(context.bot, message, videos, user_prefix=user_prefix)
        _record_videos_safely(videos, message)
        return

    client: SonglinkClient = context.application.bot_data["songlink_client"]
    tracks, unavailable_urls = await _lookup_tracks(client, source_urls)

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
            f"{pick_phrase('not_found', ','.join(source_urls))}.\n"
            "Проверьте, что это ссылка именно на трек, альбом или подкаст"
        )
        return

    if len(tracks) == 1:
        track = tracks[0]
        await _send_track_result(
            context.bot,
            message,
            f"{user_prefix}{format_track_message(track)}",
            preview_url=_select_preview_url(track.links, context),
            reply_markup=_build_link_keyboard(track.links, context=context),
        )
        _record_matches_safely([track], message)
        return

    await _send_track_result(
        context.bot,
        message,
        f"{user_prefix}{format_collection_message(tracks)}",
        preview_url=_select_preview_url(tracks[0].links, context),
        reply_markup=_build_collection_keyboard(tracks),
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


async def _send_youtube_result(
    bot: Bot,
    message: Message,
    videos: list[VideoMatch],
    *,
    user_prefix: str,
) -> None:
    if not videos:
        return

    if len(videos) == 1:
        video = videos[0]
        await _send_track_result(
            bot,
            message,
            f"{user_prefix}{format_video_message(video)}",
            preview_url=video.url,
            reply_markup=_build_youtube_keyboard(video.url),
            prefer_large_preview=True,
        )
        return

    await _send_track_result(
        bot,
        message,
        f"{user_prefix}{format_video_collection_message(videos)}",
        preview_url=videos[0].url,
        reply_markup=_build_youtube_collection_keyboard(videos),
        prefer_large_preview=True,
    )


async def _lookup_tracks(
    client: SonglinkClient,
    source_urls: list[str],
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
            fallback_track = _build_podcast_fallback(source_url)
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
        show_above_text=False,
        **media_preferences,
    )


def _build_link_keyboard(
    links: dict[str, str],
    *,
    prefix: str = "",
    context: ContextTypes.DEFAULT_TYPE | None = None,
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
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)])
    return InlineKeyboardMarkup(rows)


def _build_collection_keyboard(tracks: list[TrackMatch]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for index, track in enumerate(tracks, start=1):
        destination = track.page_url or _select_preview_url(track.links)
        if not destination:
            continue

        rows.append(
            [
                InlineKeyboardButton(
                    text=_shorten_button_text(f"{index}. {track.artist} - {track.title}"),
                    url=destination,
                )
            ]
        )

    rows.append([InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)])
    return InlineKeyboardMarkup(rows)


def _build_youtube_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("▶️ Смотреть на YouTube", url=url)],
            [InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)],
        ]
    )


def _build_youtube_collection_keyboard(videos: list[VideoMatch]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, video in enumerate(videos, start=1):
        rows.append(
            [
                InlineKeyboardButton(
                    text=_shorten_button_text(f"{index}. {video.title}"),
                    url=video.url,
                )
            ]
        )

    rows.append([InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)])
    return InlineKeyboardMarkup(rows)


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
    rows = [[InlineKeyboardButton("🪨 Открыть канал", url=CHANNEL_URL)]]
    if bot_username:
        bot_url = f"https://t.me/{bot_username}"
        share_url = "https://t.me/share/url?url=" + quote(bot_url, safe="")
        rows.append([InlineKeyboardButton("Поделиться ботом", url=share_url)])

    return InlineKeyboardMarkup(rows)


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


async def _post_shutdown(application: Application) -> None:
    client: SonglinkClient | None = application.bot_data.get("songlink_client")
    if client is not None:
        await client.aclose()

    youtube_client: YouTubeClient | None = application.bot_data.get("youtube_client")
    if youtube_client is not None:
        await youtube_client.aclose()
