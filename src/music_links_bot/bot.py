from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Awaitable, Callable
from dataclasses import asdict
import hashlib
import logging
import secrets
from urllib.parse import quote

from telegram import (
    Bot,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InlineQueryResultsButton,
    InputTextMessageContent,
    MenuButtonWebApp,
    Message,
    Update,
    WebAppInfo,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.ext import CallbackQueryHandler, InlineQueryHandler

from music_links_bot.artist import ArtistClient
from music_links_bot.branding import (
    brand_label,
    brand_logo_url,
    build_branded_cover,
    photo_branding_enabled,
)
from music_links_bot.bot_stats import (
    build_user_prefix as _build_user_prefix,
    message_text as _message_text,
    record_artist_items as _record_artists_safely,
    record_mixed_items as _record_mixed_safely,
    record_playlist_items as _record_playlists_safely,
    record_radio_items as _record_radios_safely,
    record_tracks as _record_matches_safely,
    record_video_items as _record_videos_safely,
)

from music_links_bot import bot_lookup as _bot_lookup

_split_source_urls = _bot_lookup._split_source_urls
_format_not_found_message = _bot_lookup._format_not_found_message
_strip_bot_mention = _bot_lookup._strip_bot_mention
_format_no_url_message = _bot_lookup._format_no_url_message
_format_service_unavailable_message = _bot_lookup._format_service_unavailable_message
_has_recovery_hint = _bot_lookup._has_recovery_hint
_lookup_playlists = _bot_lookup._lookup_playlists
_lookup_artists = _bot_lookup._lookup_artists
_empty_track_lookup = _bot_lookup._empty_track_lookup
_empty_video_lookup = _bot_lookup._empty_video_lookup
_empty_radio_lookup = _bot_lookup._empty_radio_lookup
_empty_playlist_lookup = _bot_lookup._empty_playlist_lookup
_empty_artist_lookup = _bot_lookup._empty_artist_lookup
_lookup_youtube_videos = _bot_lookup._lookup_youtube_videos
_lookup_nts_radios = _bot_lookup._lookup_nts_radios
_send_youtube_result = _bot_lookup._send_youtube_result
_send_nts_result = _bot_lookup._send_nts_result
_send_playlist_result = _bot_lookup._send_playlist_result
_send_artist_result = _bot_lookup._send_artist_result
_send_mixed_result = _bot_lookup._send_mixed_result
_select_mixed_preview_url = _bot_lookup._select_mixed_preview_url
_lookup_tracks = _bot_lookup._lookup_tracks
_fill_genres = _bot_lookup._fill_genres
_ensure_spotify_link = _bot_lookup._ensure_spotify_link
_build_lookup_fallback = _bot_lookup._build_lookup_fallback
_songlink_page_url = _bot_lookup._songlink_page_url
_build_podcast_fallback = _bot_lookup._build_podcast_fallback

from music_links_bot.config import Settings
from music_links_bot.ephemeral import (
    ephemeral_group_replies_enabled,
    send_ephemeral_message,
)
from music_links_bot.i18n import get_text, resolve_lang

from music_links_bot import keyboards as _keyboards

_select_preview_url = _keyboards._select_preview_url
_build_link_preview_options = _keyboards._build_link_preview_options
_build_link_keyboard = _keyboards._build_link_keyboard
_platform_button_label = _keyboards._platform_button_label
_build_collection_keyboard = _keyboards._build_collection_keyboard
_build_youtube_keyboard = _keyboards._build_youtube_keyboard
_build_nts_keyboard = _keyboards._build_nts_keyboard
_build_playlist_keyboard = _keyboards._build_playlist_keyboard
_build_artist_keyboard = _keyboards._build_artist_keyboard
_build_youtube_collection_keyboard = _keyboards._build_youtube_collection_keyboard
_build_nts_collection_keyboard = _keyboards._build_nts_collection_keyboard
_build_playlist_collection_keyboard = _keyboards._build_playlist_collection_keyboard
_build_artist_collection_keyboard = _keyboards._build_artist_collection_keyboard
_build_mixed_collection_keyboard = _keyboards._build_mixed_collection_keyboard
_should_include_channel_button = _keyboards._should_include_channel_button
_should_include_hashtags = _keyboards._should_include_hashtags
_build_platform_order = _keyboards._build_platform_order
_normalize_platform_key = _keyboards._normalize_platform_key
_shorten_button_text = _keyboards._shorten_button_text
_track_button_icon = _keyboards._track_button_icon
_release_hub_button_label = _keyboards._release_hub_button_label
_get_ui_mode = _keyboards._get_ui_mode
_button_rows = _keyboards._button_rows
_keyboard_with_optional_channel = _keyboards._keyboard_with_optional_channel
_single_url_keyboard = _keyboards._single_url_keyboard
_channel_button = _keyboards._channel_button
_url_button = _keyboards._url_button
_get_platform_order = _keyboards._get_platform_order

from music_links_bot.kvstore import KVStore
from music_links_bot.bot_crate import (
    add_to_crate,
    load_crate,
    move_crate_item,
    remove_crate_item,
)
from music_links_bot.bot_runtime import (
    BotErrorCode,
    BotFlowError,
    BotRuntime,
    CallbackAction,
    decode_callback,
    detect_action,
    encode_callback,
)
from music_links_bot.bot_ui import (
    build_onboarding_keyboard as _build_onboarding_keyboard,
    build_start_keyboard as _build_start_keyboard,
    editor_more_rows as _editor_more_rows,
    editor_rows as _editor_rows,
    render_crate as _render_bot_crate,
)
from music_links_bot.search import (
    SearchClient,
    SearchLookupError,
    normalize_search_query,
)
from music_links_bot.constants import PLATFORM_LABELS
from music_links_bot.formatter import (
    format_artist_message,
    format_collection_message,
    format_playlist_message,
    format_radio_message,
    format_track_message,
    format_video_message,
)
from music_links_bot.models import (
    TrackMatch,
)
from music_links_bot.nts import NTSClient
from music_links_bot.publication_state import (
    find_posted_date as _find_posted_date,
    mark_posted as _schedule_mark_posted,
    release_fingerprint as _release_fingerprint,
    webapp_url as _webapp_url,
)
from music_links_bot.playlist import PlaylistClient
from music_links_bot.songlink import SonglinkClient
from music_links_bot.soundcloud import (
    SoundCloudClient,
)
from music_links_bot.stats import (
    format_stats_message,
    load_stats,
    merge_stats,
)
from music_links_bot.text_utils import normalize_hashtag
from music_links_bot.url_utils import (
    extract_supported_urls,
    is_nts_url,
    is_spotify_artist_url,
    is_spotify_playlist_url,
    is_youtube_video_url,
)
from music_links_bot.youtube import YouTubeClient

LOGGER = logging.getLogger(__name__)
__all__ = ["_release_fingerprint"]
CHANNEL_USERNAME = "stonerhand"
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME}"
CHANNEL_BUTTON_TEXT = "🪨 Открыть канал"
MENU_START = "menu:start"
MENU_HELP = "menu:help"
MENU_GUIDE = "menu:guide"
MENU_PLATFORMS = "menu:platforms"
MENU_DEMO = "menu:demo"
MENU_KEYS = frozenset((MENU_START, MENU_HELP, MENU_GUIDE, MENU_PLATFORMS, MENU_DEMO))
DEFAULT_UI_MODE = "stonerhand"
MAX_BUTTON_TEXT_LENGTH = 64
MAX_LINKS_PER_MESSAGE = 12
INLINE_CACHE_SECONDS = 1800
DRAFT_TTL_SECONDS = 48 * 3600
MAX_MEMORY_DRAFTS = 300
STATS_KV_KEY = "stats:v1"

# The "collecting the post" placeholder for the current update. ContextVars are
# task-local in asyncio, and PTB processes each update in its own task, so this
# never leaks between concurrent updates.
_PLACEHOLDER_MESSAGE: contextvars.ContextVar[Message | None] = contextvars.ContextVar(
    "placeholder_message",
    default=None,
)
_INPUT_OVERRIDE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "input_override", default=None
)
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
    BotCommand("start", "меню и быстрый старт"),
    BotCommand("help", "как пользоваться"),
    BotCommand("guide", "для групп и каналов"),
    BotCommand("platforms", "сервисы и типы ссылок"),
    BotCommand("channel", "канал StonerHand"),
    BotCommand("stats", "статистика бота"),
    BotCommand("crate", "моя подборка"),
)
PRIMARY_PLATFORM_ALIASES = {
    "spotify": "spotify",
    "apple": "appleMusic",
    "applemusic": "appleMusic",
    "itunes": "appleMusic",
    "applepodcasts": "applePodcasts",
    "podcasts": "applePodcasts",
    "youtube": "youtubeMusic",
    "youtubemusic": "youtubeMusic",
    "ytmusic": "youtubeMusic",
    "soundcloud": "soundcloud",
    "sc": "soundcloud",
    "deezer": "deezer",
    "tidal": "tidal",
    "yandex": "yandexMusic",
    "yandexmusic": "yandexMusic",
    "yamusic": "yandexMusic",
}
NOT_FOUND_DETAIL = (
    "Проверь, что это ссылка на трек, альбом, плейлист, артиста, "
    "подкаст, YouTube-видео или NTS Radio"
)


def build_application(settings: Settings) -> Application:
    kv_store = KVStore.from_env()
    songlink_client = SonglinkClient(
        user_countries=settings.songlink_user_countries,
        api_key=settings.songlink_api_key,
        kv=kv_store,
    )
    youtube_client = YouTubeClient()
    nts_client = NTSClient()
    soundcloud_client = SoundCloudClient()
    playlist_client = PlaylistClient()
    artist_client = ArtistClient()
    search_client = SearchClient()
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
    application.bot_data["search_client"] = search_client
    application.bot_data["kv_store"] = kv_store
    application.bot_data["drafts"] = {}
    application.bot_data["publish_chat_id"] = settings.publish_chat_id
    application.bot_data["admin_chat_id"] = settings.admin_chat_id
    application.bot_data["platform_order"] = _build_platform_order(settings.primary_platform)
    application.bot_data["ui_mode"] = settings.ui_mode
    application.bot_data["runtime"] = BotRuntime(kv_store)
    application.bot_data["search_selections"] = {}

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("guide", guide_command))
    application.add_handler(CommandHandler("platforms", platforms_command))
    application.add_handler(CommandHandler("channel", channel_command))
    application.add_handler(CommandHandler("id", id_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("crate", crate_command))
    application.add_handler(CallbackQueryHandler(bot_callback, pattern=r"^v2\|"))
    application.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu:"))
    application.add_handler(CallbackQueryHandler(editor_callback, pattern=r"^ed\|"))
    application.add_handler(InlineQueryHandler(inline_query_handler))
    application.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
            track_lookup_message,
        )
    )
    application.add_error_handler(_application_error_handler)
    return application


BOT_DESCRIPTIONS = {
    "": (
        "Музыкальный редактор для Telegram.\n\n"
        "• Ссылка или название → выбор точного релиза\n"
        "• Карточка с обложкой и кнопками площадок\n"
        "• Хэштеги, цитата, размер превью и отправка себе\n"
        "• Подборки /crate и перестановка треков\n"
        "• Inline: @StonerHandBot + запрос в любом чате\n"
        "• Studio: live-preview, очередь и публикация в канал\n\n"
        "Spotify, Apple Music, YouTube, SoundCloud, Deezer, Tidal, "
        "Yandex Music, NTS Radio."
    ),
    "en": (
        "A music post editor for Telegram.\n\n"
        "• Paste a link or title and choose the exact release\n"
        "• Get a card with cover art and platform buttons\n"
        "• Tune hashtags, quote, preview size and send to yourself\n"
        "• Build and reorder crates with /crate\n"
        "• Inline: @StonerHandBot + a query in any chat\n"
        "• Studio: live preview, queue and channel publishing\n\n"
        "Spotify, Apple Music, YouTube, SoundCloud, Deezer, Tidal, "
        "Yandex Music and NTS Radio."
    ),
}
BOT_SHORT_DESCRIPTIONS = {
    "": (
        "Ссылка или название → готовый музыкальный пост. "
        "Поиск, редактор, подборки и публикация в Studio."
    ),
    "en": (
        "A link or title → a finished music post. "
        "Search, editing, crates and publishing in Studio."
    ),
}


async def sync_application_commands(application: Application) -> None:
    try:
        await application.bot.set_my_commands(PUBLIC_BOT_COMMANDS)
        webapp_url = _webapp_url()
        if webapp_url:
            await application.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text=get_text("ru", "menu_button_studio"),
                    web_app=WebAppInfo(url=webapp_url),
                )
            )
        for language_code, description in BOT_DESCRIPTIONS.items():
            await application.bot.set_my_description(
                description,
                language_code=language_code or None,
            )
        for language_code, short_description in BOT_SHORT_DESCRIPTIONS.items():
            await application.bot.set_my_short_description(
                short_description,
                language_code=language_code or None,
            )
    except TelegramError:
        LOGGER.info("Could not sync bot command menu")


async def close_application_resources(application: Application) -> None:
    client_keys = (
        "songlink_client",
        "youtube_client",
        "nts_client",
        "soundcloud_client",
        "playlist_client",
        "artist_client",
        "search_client",
        "kv_store",
    )
    clients = [application.bot_data.get(key) for key in client_keys]
    active_clients = [client for client in clients if client is not None]
    if not active_clients:
        return

    results = await asyncio.gather(
        *(client.aclose() for client in active_clients),
        return_exceptions=True,
    )
    for client, result in zip(active_clients, results, strict=False):
        if isinstance(result, Exception):
            LOGGER.warning(
                "Could not close %s cleanly: %s",
                type(client).__name__,
                type(result).__name__,
            )


async def _application_error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    del update
    error = context.error
    if isinstance(error, BaseException):
        LOGGER.error(
            "Unhandled Telegram update error",
            exc_info=(type(error), error, error.__traceback__),
        )
        return

    LOGGER.error("Unhandled Telegram update error: %r", error)


def _update_lang(update: Update) -> str:
    user = update.effective_user
    return resolve_lang(user.language_code if user else None)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    lang = _update_lang(update)
    user_id = update.effective_user.id if update.effective_user else update.message.chat_id
    session = await _runtime(context).get_session(user_id, lang=lang)
    await update.message.reply_text(
        get_text(lang, "start_returning" if session.onboarding_seen else "start_new"),
        parse_mode=ParseMode.HTML,
        reply_markup=_build_start_keyboard(context.bot.username, lang=lang),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await _reply_with_menu(update.message, context, MENU_HELP, lang=_update_lang(update))


async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return

    lang = _update_lang(update)
    sent_message = await message.reply_text(
        _menu_text(MENU_GUIDE, lang=lang),
        parse_mode=ParseMode.HTML,
        reply_markup=_build_intro_keyboard(
            context.bot.username,
            active=MENU_GUIDE,
            lang=lang,
        ),
    )

    if message.chat.type in {"group", "supergroup", "channel"}:
        try:
            await sent_message.pin(disable_notification=True)
        except (BadRequest, Forbidden):
            LOGGER.info("Could not pin guide in chat %s", message.chat_id)


async def platforms_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await _reply_with_menu(
        update.message,
        context,
        MENU_PLATFORMS,
        lang=_update_lang(update),
    )


async def channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if not update.message:
        return

    await update.message.reply_text(
        "StonerHand рядом",
        reply_markup=InlineKeyboardMarkup([[_channel_button()]]),
    )


def _runtime(context: ContextTypes.DEFAULT_TYPE) -> BotRuntime:
    runtime = context.application.bot_data.get("runtime")
    if not isinstance(runtime, BotRuntime):
        runtime = BotRuntime(context.application.bot_data.get("kv_store"))
        context.application.bot_data["runtime"] = runtime
    return runtime


async def bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Versioned callback dispatcher for all new interactive bot surfaces."""
    query = update.callback_query
    parsed = decode_callback(query.data if query else None)
    if query is None or parsed is None:
        return

    runtime = _runtime(context)
    callback_id = str(getattr(query, "id", "") or hashlib.sha256(query.data.encode()).hexdigest())
    if not await runtime.claim_callback(callback_id):
        lang = resolve_lang(query.from_user.language_code if query.from_user else None)
        await query.answer(get_text(lang, "action_duplicate"))
        return

    handlers: dict[str, Callable[[object, ContextTypes.DEFAULT_TYPE, CallbackAction], Awaitable[None]]] = {
        "menu": _dispatch_menu_action,
        "select": _dispatch_selection_action,
        "editor": _dispatch_editor_action,
        "crate": _dispatch_crate_action,
        "retry": _dispatch_retry_action,
        "noop": _dispatch_noop_action,
    }
    handler = handlers.get(parsed.scope)
    if handler is None:
        await query.answer()
        return
    await handler(query, context, parsed)


async def _dispatch_noop_action(query, context, action: CallbackAction) -> None:
    del context, action
    await query.answer()


async def _dispatch_menu_action(query, context, action: CallbackAction) -> None:
    lang = resolve_lang(query.from_user.language_code if query.from_user else None)
    if action.action.startswith("onboard"):
        step = action.action.removeprefix("onboard") or "1"
        if step == "done":
            session = await _runtime(context).get_session(query.from_user.id, lang=lang)
            session.onboarding_seen = True
            await _runtime(context).save_session(session)
            text = get_text(lang, "start_returning")
            keyboard = _build_start_keyboard(context.bot.username, lang=lang)
        else:
            step_number = max(1, min(3, int(step)))
            text = get_text(lang, f"onboarding_{step_number}")
            keyboard = _build_onboarding_keyboard(step_number, lang)
        await query.answer()
        await _safe_edit(query, text, keyboard)
        return

    menu_key = {
        "start": MENU_START,
        "help": MENU_HELP,
        "guide": MENU_GUIDE,
        "platforms": MENU_PLATFORMS,
        "demo": MENU_DEMO,
    }.get(action.action, MENU_START)
    await query.answer()
    await _safe_edit(
        query,
        _menu_text(menu_key, lang=lang),
        _build_intro_keyboard(context.bot.username, active=menu_key, lang=lang),
    )


async def _safe_edit(query, text: str, keyboard: InlineKeyboardMarkup | None) -> None:
    try:
        await query.edit_message_text(
            text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    await query.answer()
    lang = resolve_lang(query.from_user.language_code if query.from_user else None)
    menu_key = query.data if query.data in MENU_KEYS else MENU_START
    try:
        await query.edit_message_text(
            text=_menu_text(menu_key, lang=lang),
            parse_mode=ParseMode.HTML,
            reply_markup=_build_intro_keyboard(
                context.bot.username,
                active=menu_key,
                lang=lang,
            ),
        )
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            return
        raise


async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    inline_query = update.inline_query
    if inline_query is None:
        return

    lang = resolve_lang(
        inline_query.from_user.language_code if inline_query.from_user else None
    )
    query_text = inline_query.query or ""
    source_urls = extract_supported_urls(query_text)[:1]
    if not source_urls:
        search_query = normalize_search_query(query_text)
        if search_query is None:
            await _answer_inline_hint(inline_query, get_text(lang, "inline_hint_empty"))
            return

        search_client: SearchClient = context.application.bot_data["search_client"]
        try:
            if hasattr(search_client, "search_release_candidates"):
                candidates = await search_client.search_release_candidates(search_query)
            else:
                source_url = await search_client.search_release_url(search_query)
                candidates = [
                    type(
                        "SearchChoice",
                        (),
                        {"url": source_url, "artist": "", "title": search_query},
                    )()
                ]
        except SearchLookupError:
            await _answer_inline_hint(
                inline_query,
                get_text(lang, "inline_hint_not_found"),
            )
            return

        source_urls = [candidate.url for candidate in candidates]

    outcomes = await asyncio.gather(
        *(_build_inline_result(source_url, context) for source_url in source_urls),
        return_exceptions=True,
    )
    results = []
    for source_url, outcome in zip(source_urls, outcomes, strict=False):
        if isinstance(outcome, InlineQueryResultArticle):
            results.append(outcome)
        elif isinstance(outcome, Exception):
            LOGGER.error(
                "Inline lookup failed for %s",
                source_url,
                exc_info=(type(outcome), outcome, outcome.__traceback__),
            )

    if not results:
        await _answer_inline_hint(inline_query, get_text(lang, "inline_hint_not_found"))
        return

    try:
        await inline_query.answer(
            results[:6],
            cache_time=INLINE_CACHE_SECONDS,
            is_personal=False,
            button=InlineQueryResultsButton(
                text=get_text(lang, "open_studio"), start_parameter="studio"
            ),
        )
    except TelegramError:
        LOGGER.debug("Could not answer inline query", exc_info=True)


async def _answer_inline_hint(inline_query, button_text: str) -> None:
    try:
        await inline_query.answer(
            [],
            cache_time=10,
            button=InlineQueryResultsButton(text=button_text, start_parameter="inline"),
        )
    except TelegramError:
        LOGGER.debug("Could not answer inline query with hint", exc_info=True)


async def _build_inline_result(
    source_url: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> InlineQueryResultArticle | None:
    bot_data = context.application.bot_data

    if is_spotify_artist_url(source_url):
        artists = await _lookup_artists(bot_data["artist_client"], [source_url])
        artist = artists[0]
        return _inline_article(
            source_url,
            title=artist.title,
            description=f"Карточка артиста · {artist.platform}",
            text=format_artist_message(artist, include_hashtags=True),
            keyboard=_build_artist_keyboard(artist.url),
            preview_url=artist.url,
        )

    if is_spotify_playlist_url(source_url):
        playlists = await _lookup_playlists(bot_data["playlist_client"], [source_url])
        playlist = playlists[0]
        return _inline_article(
            source_url,
            title=playlist.title,
            description=f"Плейлист · {playlist.platform}",
            text=format_playlist_message(playlist, include_hashtags=True),
            keyboard=_build_playlist_keyboard(playlist.url),
            preview_url=playlist.url,
        )

    if is_youtube_video_url(source_url):
        videos = await _lookup_youtube_videos(bot_data["youtube_client"], [source_url])
        video = videos[0]
        return _inline_article(
            source_url,
            title=video.title,
            description=f"Видео · {video.author}",
            text=format_video_message(video, include_hashtags=True),
            keyboard=_build_youtube_keyboard(video.url),
            preview_url=video.url,
        )

    if is_nts_url(source_url):
        radios = await _lookup_nts_radios(bot_data["nts_client"], [source_url])
        if not radios:
            return None

        radio = radios[0]
        return _inline_article(
            source_url,
            title=radio.title,
            description=f"Эфир · {radio.station}",
            text=format_radio_message(radio, include_hashtags=True),
            keyboard=_build_nts_keyboard(radio.url),
            preview_url=radio.url,
        )

    tracks, _unavailable = await _lookup_tracks(
        bot_data["songlink_client"],
        [source_url],
        soundcloud_client=bot_data["soundcloud_client"],
        search_client=bot_data.get("search_client"),
    )
    tracks = [track for track in tracks if track.links]
    if not tracks:
        return None

    track = tracks[0]
    return _inline_article(
        source_url,
        title=f"{track.artist} — {track.title}",
        description="Пост с кнопками всех площадок",
        text=format_track_message(track, include_hashtags=True),
        keyboard=_build_link_keyboard(
            track.links,
            context=context,
            release_page_url=track.page_url,
            release_kind=track.kind,
            release_format=track.release_format,
        ),
        preview_url=_select_preview_url(track.links, context) or track.thumbnail_url,
        thumbnail_url=track.thumbnail_url,
    )


def _inline_article(
    source_url: str,
    *,
    title: str,
    description: str,
    text: str,
    keyboard: InlineKeyboardMarkup,
    preview_url: str | None,
    thumbnail_url: str | None = None,
) -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id=hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:32],
        title=title,
        description=description,
        thumbnail_url=thumbnail_url,
        input_message_content=InputTextMessageContent(
            message_text=text,
            parse_mode=ParseMode.HTML,
            link_preview_options=_build_link_preview_options(
                preview_url,
                prefer_large_media=True,
            ),
        ),
        reply_markup=keyboard,
    )


async def _send_track_draft(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    track: TrackMatch,
    *,
    user_prefix: str,
    lang: str,
) -> None:
    admin_chat_id = context.application.bot_data.get("admin_chat_id")
    draft_id = secrets.token_hex(8)
    draft = {
        "v": 1,
        "type": "track",
        "item": asdict(track),
        "prefix": user_prefix,
        "hashtags": False,
        "quote": bool(user_prefix),
        "large_preview": True,
        "chat_id": message.chat_id,
        "lang": lang,
        "can_publish": (
            message.from_user is not None
            and admin_chat_id is not None
            and message.from_user.id == admin_chat_id
        ),
    }

    text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
    await _reply_with_track(
        message,
        text,
        preview_url=_select_preview_url(track.links, context) or track.thumbnail_url,
        reply_markup=keyboard,
        prefer_large_preview=bool(draft.get("large_preview")),
    )
    await _store_draft(context, draft_id, draft)


def _render_track_draft(
    draft: dict,
    context: ContextTypes.DEFAULT_TYPE | None,
    *,
    draft_id: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    track = TrackMatch(**draft["item"])
    prefix = draft.get("prefix") or ""
    include_hashtags, overrides = _draft_message_overrides(
        draft, include_hashtags=bool(draft.get("hashtags"))
    )
    text = (prefix if draft.get("quote") and prefix else "") + format_track_message(
        track,
        include_hashtags=include_hashtags,
        **overrides,
    )
    keyboard = _build_link_keyboard(
        track.links,
        context=context,
        include_channel_button=True,
        release_page_url=track.page_url,
        release_kind=track.kind,
        release_format=track.release_format,
        platform_selection=_draft_platform_selection(draft),
    )
    if draft_id is None:
        return text, keyboard

    rows = [*keyboard.inline_keyboard, *_editor_rows(draft_id, draft)]
    return text, InlineKeyboardMarkup(rows)


def _draft_message_overrides(
    draft: dict,
    *,
    include_hashtags: bool,
) -> tuple[bool, dict]:
    """Custom CTA text and hashtags set in the Studio replace the generated
    ones; an explicitly emptied hashtag list wins over the house style."""
    overrides: dict = {}
    custom_cta = draft.get("custom_cta")
    if isinstance(custom_cta, str) and custom_cta.strip():
        overrides["cta_text"] = custom_cta.strip()

    custom_tags = draft.get("custom_tags")
    if isinstance(custom_tags, list):
        tags = [tag for tag in (normalize_hashtag(value) for value in custom_tags) if tag]
        if tags:
            overrides["hashtags"] = " ".join(tags)
        else:
            include_hashtags = False

    return include_hashtags, overrides


def _draft_platform_selection(draft: dict) -> list[str] | None:
    platforms = draft.get("platforms")
    if not isinstance(platforms, list):
        return None

    selection = [key for key in platforms if isinstance(key, str) and key in PLATFORM_LABELS]
    return selection or None


async def _store_draft(
    context: ContextTypes.DEFAULT_TYPE,
    draft_id: str,
    draft: dict,
) -> None:
    drafts: dict = context.application.bot_data.setdefault("drafts", {})
    while len(drafts) >= MAX_MEMORY_DRAFTS:
        drafts.pop(next(iter(drafts)))

    drafts[draft_id] = draft
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        # Fire-and-forget: the in-memory copy already serves this instance,
        # Redis only needs to catch up for other instances and restarts.
        asyncio.get_running_loop().create_task(
            kv.set_json(f"draft:{draft_id}", draft, ttl_seconds=DRAFT_TTL_SECONDS)
        )


async def _load_draft(
    context: ContextTypes.DEFAULT_TYPE,
    draft_id: str,
) -> dict | None:
    drafts: dict = context.application.bot_data.setdefault("drafts", {})
    draft = drafts.get(draft_id)
    if draft is not None:
        return draft

    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is None:
        return None

    draft = await kv.get_json(f"draft:{draft_id}")
    if isinstance(draft, dict) and draft.get("type") == "track":
        drafts[draft_id] = draft
        return draft

    return None


async def _store_search_selection(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    query: str,
    urls: list[str],
) -> str:
    selection_id = secrets.token_hex(5)
    payload = {"user_id": user_id, "query": query, "urls": urls}
    selections: dict = context.application.bot_data.setdefault("search_selections", {})
    while len(selections) >= 300:
        selections.pop(next(iter(selections)))
    selections[selection_id] = payload
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        await kv.set_json(
            f"selection:v1:{selection_id}", payload, ttl_seconds=15 * 60
        )
    return selection_id


async def _load_search_selection(
    context: ContextTypes.DEFAULT_TYPE, selection_id: str
) -> dict | None:
    selections: dict = context.application.bot_data.setdefault("search_selections", {})
    payload = selections.get(selection_id)
    if isinstance(payload, dict):
        return payload
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    payload = await kv.get_json(f"selection:v1:{selection_id}") if kv else None
    if isinstance(payload, dict):
        selections[selection_id] = payload
        return payload
    return None


async def _dispatch_selection_action(query, context, action: CallbackAction) -> None:
    lang = resolve_lang(query.from_user.language_code if query.from_user else None)
    if action.action != "pick" or ":" not in action.payload:
        await query.answer()
        return
    selection_id, raw_index = action.payload.rsplit(":", 1)
    payload = await _load_search_selection(context, selection_id)
    try:
        index = int(raw_index)
        urls = payload["urls"] if payload else []
        source_url = urls[index]
    except (IndexError, KeyError, TypeError, ValueError):
        await query.answer(get_text(lang, "ed_expired"), show_alert=True)
        return
    if query.from_user and int(payload.get("user_id") or 0) != query.from_user.id:
        await query.answer(get_text(lang, "ed_admin_only"), show_alert=True)
        return

    await query.answer(get_text(lang, "progress_links"))
    if query.message is None:
        return
    _PLACEHOLDER_MESSAGE.set(query.message)
    token = _INPUT_OVERRIDE.set(source_url)
    try:
        synthetic = Update(update_id=0, callback_query=query)
        await track_lookup_message(synthetic, context)
    finally:
        _INPUT_OVERRIDE.reset(token)


async def _dispatch_retry_action(query, context, action: CallbackAction) -> None:
    del action
    if query.from_user is None or query.message is None:
        await query.answer()
        return
    lang = resolve_lang(query.from_user.language_code)
    session = await _runtime(context).get_session(query.from_user.id, lang=lang)
    value = str(session.last_action.get("value") or "")
    if not value:
        await query.answer(get_text(lang, "ed_expired"), show_alert=True)
        return
    await query.answer(get_text(lang, "progress_search"))
    _PLACEHOLDER_MESSAGE.set(query.message)
    token = _INPUT_OVERRIDE.set(value)
    try:
        await track_lookup_message(Update(update_id=0, callback_query=query), context)
    finally:
        _INPUT_OVERRIDE.reset(token)


async def editor_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    parsed = decode_callback(query.data if query else None)
    if query is None or parsed is None or parsed.scope != "editor":
        return
    callback_id = str(
        getattr(query, "id", "")
        or hashlib.sha256((query.data or "").encode()).hexdigest()
    )
    if not await _runtime(context).claim_callback(callback_id):
        lang = resolve_lang(query.from_user.language_code if query.from_user else None)
        await query.answer(get_text(lang, "action_duplicate"))
        return
    await _handle_editor_action(query, context, parsed.action, parsed.payload)


async def _dispatch_editor_action(query, context, action: CallbackAction) -> None:
    await _handle_editor_action(query, context, action.action, action.payload)


async def _handle_editor_action(query, context, action: str, draft_id: str) -> None:
    user_lang = resolve_lang(query.from_user.language_code if query.from_user else None)
    draft = await _load_draft(context, draft_id)
    if draft is None:
        await query.answer(get_text(user_lang, "ed_expired"), show_alert=True)
        return

    lang = draft.get("lang") or user_lang

    if action == "m":
        await query.answer()
        text, base_keyboard = _render_track_draft(draft, context, draft_id=None)
        keyboard = InlineKeyboardMarkup(
            [*base_keyboard.inline_keyboard, *_editor_more_rows(draft_id, draft)]
        )
        await _edit_editor_message(query, context, draft, text, keyboard)
        return
    if action == "b":
        await query.answer()
        text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
        await _edit_editor_message(query, context, draft, text, keyboard)
        return

    if action == "d":
        await query.answer()
        if query.message is not None:
            await _try_delete_message(query.message)
        return

    if action in {"p", "s", "c"}:
        user_id = query.from_user.id if query.from_user else 0
        runtime = _runtime(context)
        lock_key = f"{user_id}:{action}:{draft_id}"
        token = await runtime.acquire_action(lock_key)
        if token is None:
            await query.answer(get_text(lang, "action_busy"), show_alert=True)
            return
        await _show_action_busy(query, lang)
        try:
            await _run_primary_editor_action(
                query, context, action, draft_id, draft, lang
            )
        finally:
            await runtime.release_action(lock_key, token)
        return

    if action == "h":
        draft["hashtags"] = not draft.get("hashtags")
    elif action == "q":
        draft["quote"] = not draft.get("quote")
    elif action == "v":
        draft["large_preview"] = not draft.get("large_preview")
    elif action != "f":
        await query.answer()
        return

    await query.answer()
    await _store_draft(context, draft_id, draft)
    editor_id = None if action == "f" else draft_id
    text, keyboard = _render_track_draft(draft, context, draft_id=editor_id)
    await _edit_editor_message(query, context, draft, text, keyboard)


async def _run_primary_editor_action(
    query, context, action: str, draft_id: str, draft: dict, lang: str
) -> None:
    user_id = query.from_user.id if query.from_user else 0
    if action == "c":
        items, added = await add_to_crate(
            context.application.bot_data,
            user_id,
            draft_id=draft_id,
            item=draft["item"],
        )
        await query.answer(
            get_text(lang, "ed_crate_added") if added else f"Уже в подборке · {len(items)}/10",
            show_alert=False,
        )
        text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
        await _edit_editor_message(query, context, draft, text, keyboard)
        return

    if action == "s":
        sent = await _deliver_draft(
            context, draft, target=user_id, channel_style=False
        )
        await query.answer(
            get_text(lang, "ed_sent" if sent else "ed_publish_failed"),
            show_alert=not bool(sent),
        )
        text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
        await _edit_editor_message(query, context, draft, text, keyboard)
        return

    admin_chat_id = context.application.bot_data.get("admin_chat_id")
    if not user_id or admin_chat_id is None or user_id != admin_chat_id:
        await query.answer(get_text(lang, "ed_admin_only"), show_alert=True)
        text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
        await _edit_editor_message(query, context, draft, text, keyboard)
        return

    track = TrackMatch(**draft["item"])
    if not draft.get("dup_ok"):
        posted_date = await _find_posted_date(context, track)
        if posted_date:
            draft["dup_ok"] = True
            await _store_draft(context, draft_id, draft)
            await query.answer(
                get_text(lang, "ed_duplicate").replace("{date}", posted_date),
                show_alert=True,
            )
            text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
            await _edit_editor_message(query, context, draft, text, keyboard)
            return

    published = await _publish_draft(context, draft)
    if published:
        await _schedule_mark_posted(context, track)
        success_keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        get_text(lang, "ed_published"),
                        callback_data=encode_callback("noop", "done"),
                        api_kwargs={"style": "success"},
                    )
                ],
                [_channel_button()],
            ]
        )
        text, _ = _render_track_draft(draft, context, draft_id=None)
        await _edit_editor_message(query, context, draft, text, success_keyboard)
    await query.answer(
        get_text(lang, "ed_published" if published else "ed_publish_failed"),
        show_alert=not bool(published),
    )
    if not published:
        text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
        await _edit_editor_message(query, context, draft, text, keyboard)


async def _show_action_busy(query, lang: str) -> None:
    try:
        await query.edit_message_reply_markup(
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("⏳ " + get_text(lang, "progress_card"), callback_data=encode_callback("noop", "busy"))]]
            )
        )
    except (AttributeError, TelegramError):
        LOGGER.debug("Could not mark editor action busy", exc_info=True)


async def _edit_editor_message(query, context, draft: dict, text: str, keyboard) -> None:
    track = TrackMatch(**draft["item"])
    try:
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            link_preview_options=_build_link_preview_options(
                _select_preview_url(track.links, context) or track.thumbnail_url,
                prefer_large_media=bool(draft.get("large_preview")),
            ),
            reply_markup=keyboard,
        )
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


async def _publish_draft(
    context: ContextTypes.DEFAULT_TYPE,
    draft: dict,
) -> Message | bool | None:
    target = context.application.bot_data.get("publish_chat_id") or f"@{CHANNEL_USERNAME}"
    return await _deliver_draft(context, draft, target=target, channel_style=True)


async def _deliver_draft(
    context: ContextTypes.DEFAULT_TYPE,
    draft: dict,
    *,
    target: int | str,
    channel_style: bool,
) -> Message | bool | None:
    """Single delivery pipeline for self-send, channel publish and API jobs."""
    track = TrackMatch(**draft["item"])
    prefix = draft.get("prefix") or ""
    include_hashtags, overrides = _draft_message_overrides(
        draft,
        include_hashtags=True if channel_style else bool(draft.get("hashtags")),
    )
    text = (prefix if draft.get("quote") and prefix else "") + format_track_message(
        track,
        include_hashtags=include_hashtags,
        **overrides,
    )
    include_channel_button = (
        str(target).lstrip("@").casefold() != CHANNEL_USERNAME
    )
    keyboard = _build_link_keyboard(
        track.links,
        context=context,
        include_channel_button=include_channel_button,
        release_page_url=track.page_url,
        release_kind=track.kind,
        release_format=track.release_format,
        platform_selection=_draft_platform_selection(draft),
    )
    try:
        if draft.get("as_photo") and track.thumbnail_url:
            # Photo posts pin the artwork on top on every Telegram client,
            # at the cost of the preview-size toggle.
            photo = track.thumbnail_url
            if photo_branding_enabled():
                branded = await build_branded_cover(
                    track.thumbnail_url,
                    label=brand_label(f"@{CHANNEL_USERNAME}"),
                    logo_url=brand_logo_url(),
                )
                if branded is not None:
                    photo = branded
            sent = await context.bot.send_photo(
                chat_id=target,
                photo=photo,
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            sent = await context.bot.send_message(
                chat_id=target,
                text=text,
                parse_mode=ParseMode.HTML,
                link_preview_options=_build_link_preview_options(
                    _select_preview_url(track.links, context) or track.thumbnail_url,
                    prefer_large_media=bool(draft.get("large_preview")),
                ),
                reply_markup=keyboard,
            )
    except TelegramError:
        LOGGER.warning("Could not deliver draft to %s", target, exc_info=True)
        return None

    return sent if sent is not None else True


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
    stats_data = load_stats()
    kv: KVStore | None = context.application.bot_data.get("kv_store")
    if kv is not None:
        stats_data = merge_stats(stats_data, await kv.get_json(STATS_KV_KEY))

    text = format_stats_message(stats_data, include_private=include_private)
    if include_private:
        diagnostics = _runtime(context).provider_snapshot()
        if diagnostics:
            lines = ["", "Провайдеры"]
            for item in diagnostics:
                marker = "✅" if item["ok"] else "⚠️"
                lines.append(
                    f"{marker} {item['provider']} · {item['latency_ms']} ms"
                    + (f" · {item['last_error']}" if item["last_error"] else "")
                )
            text += "\n".join(lines)
    await message.reply_text(text)


async def crate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    user_id = update.effective_user.id if update.effective_user else message.chat_id
    lang = _update_lang(update)
    items = await load_crate(context.application.bot_data, user_id)
    text, keyboard = _render_bot_crate(items, lang=lang)
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def _dispatch_crate_action(query, context, action: CallbackAction) -> None:
    if query.from_user is None:
        await query.answer()
        return
    lang = resolve_lang(query.from_user.language_code)
    user_id = query.from_user.id
    try:
        index = int(action.payload)
    except ValueError:
        index = -1
    if action.action == "up":
        items = await move_crate_item(context.application.bot_data, user_id, index, -1)
    elif action.action == "down":
        items = await move_crate_item(context.application.bot_data, user_id, index, 1)
    elif action.action == "remove":
        items = await remove_crate_item(context.application.bot_data, user_id, index)
    elif action.action == "open":
        items = await load_crate(context.application.bot_data, user_id)
    else:
        await query.answer()
        return
    await query.answer()
    text, keyboard = _render_bot_crate(items, lang=lang)
    await _safe_edit(query, text, keyboard)


async def _reply_with_menu(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    menu_key: str,
    *,
    lang: str = "ru",
) -> None:
    await message.reply_text(
        _menu_text(menu_key, lang=lang),
        parse_mode=ParseMode.HTML,
        reply_markup=_build_intro_keyboard(
            context.bot.username,
            active=menu_key,
            lang=lang,
        ),
    )


async def _reply_with_error(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    lang: str = "ru",
) -> None:
    reply_markup = _build_error_keyboard(context.bot.username, lang=lang)
    placeholder = _take_placeholder(message.chat_id)
    if placeholder is not None:
        try:
            await placeholder.edit_text(text, reply_markup=reply_markup)
            return
        except TelegramError:
            LOGGER.debug("Could not edit loading placeholder", exc_info=True)

    await message.reply_text(text, reply_markup=reply_markup)


async def _reply_with_flow_error(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    error: BotFlowError,
    *,
    lang: str,
) -> None:
    detail_key = {
        BotErrorCode.SEARCH_NOT_FOUND: "error_search",
        BotErrorCode.PROVIDER_UNAVAILABLE: "error_provider",
    }.get(error.code, "no_url_hint")
    text = f"<b>{get_text(lang, 'error_title')}</b>\n\n{get_text(lang, detail_key)}"
    rows: list[list[InlineKeyboardButton]] = []
    if error.retryable:
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "retry"),
                    callback_data=encode_callback("retry", "last"),
                    api_kwargs={"style": "primary"},
                )
            ]
        )
    rows.extend(_build_error_keyboard(context.bot.username, lang=lang).inline_keyboard)
    keyboard = InlineKeyboardMarkup(rows)
    placeholder = _take_placeholder(message.chat_id)
    if placeholder is not None:
        try:
            await placeholder.edit_text(
                text, parse_mode=ParseMode.HTML, reply_markup=keyboard
            )
            return
        except TelegramError:
            LOGGER.debug("Could not edit flow-error placeholder", exc_info=True)
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def _send_typing_action(bot: Bot, message: Message) -> None:
    if message.chat.type == "channel":
        return

    try:
        await bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
    except TelegramError:
        LOGGER.debug("Could not send typing action", exc_info=True)


async def _send_loading_placeholder(message: Message, lang: str = "ru") -> None:
    if _PLACEHOLDER_MESSAGE.get() is not None:
        return

    loading_text = get_text(lang, "progress_search")
    try:
        placeholder = await message.reply_text(loading_text)
    except TelegramError:
        LOGGER.debug("Could not send loading placeholder", exc_info=True)
        return

    _PLACEHOLDER_MESSAGE.set(placeholder)


async def _update_loading_placeholder(lang: str, key: str) -> None:
    placeholder = _PLACEHOLDER_MESSAGE.get()
    if placeholder is None:
        return
    try:
        await placeholder.edit_text(get_text(lang, key))
    except TelegramError:
        LOGGER.debug("Could not update loading placeholder", exc_info=True)


def _take_placeholder(chat_id: int) -> Message | None:
    placeholder = _PLACEHOLDER_MESSAGE.get()
    if placeholder is None or placeholder.chat_id != chat_id:
        return None

    _PLACEHOLDER_MESSAGE.set(None)
    return placeholder


async def track_lookup_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _track_lookup_message_impl(update, context)
    except asyncio.CancelledError:
        # A newer private-chat request superseded this one. Treat cancellation
        # as an expected UX event, not a failed Telegram webhook delivery.
        LOGGER.debug("Stale lookup cancelled in favor of a newer request")


async def _track_lookup_message_impl(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    if message is None:
        return

    # Posts inserted through this bot's own inline mode arrive as regular
    # messages; re-processing them would send their text into search.
    via_bot = getattr(message, "via_bot", None)
    if via_bot is not None and via_bot.id == getattr(context.bot, "id", None):
        return

    message_text = _INPUT_OVERRIDE.get() or _message_text(message)
    source_urls = extract_supported_urls(message_text)[:MAX_LINKS_PER_MESSAGE]
    include_channel_button = _should_include_channel_button(message)
    include_hashtags = _should_include_hashtags(message)
    is_private = message.chat.type == "private"
    lang = _update_lang(update) if is_private else "ru"
    user_id = update.effective_user.id if update.effective_user else message.chat_id
    runtime = _runtime(context)
    if is_private:
        runtime.register_request(user_id)
        action_kind = detect_action(message_text or "", source_urls, is_private=True)
        if action_kind == "help":
            await _reply_with_menu(message, context, MENU_HELP, lang=lang)
            runtime.finish_request(user_id)
            return
        await runtime.remember_action(
            user_id,
            kind="resolve" if source_urls else "search",
            value=(source_urls[0] if source_urls else message_text or ""),
            lang=lang,
        )
    found_via_search = False
    if not source_urls:
        if not is_private:
            return

        search_query = normalize_search_query(
            _strip_bot_mention(message_text or "", context.bot.username)
        )
        if search_query is None:
            await _reply_with_error(
                message,
                context,
                _format_no_url_message(message_text, message.chat_id, lang=lang),
                lang=lang,
            )
            return

        await _send_loading_placeholder(message, lang)
        search_client: SearchClient = context.application.bot_data["search_client"]
        try:
            if hasattr(search_client, "search_release_candidates"):
                candidates = await search_client.search_release_candidates(search_query)
            else:
                source_url = await search_client.search_release_url(search_query)
                candidates = [
                    type(
                        "SearchChoice",
                        (),
                        {"url": source_url, "artist": "", "title": search_query},
                    )()
                ]
            if len(candidates) > 1:
                selection_id = await _store_search_selection(
                    context,
                    user_id=user_id,
                    query=search_query,
                    urls=[candidate.url for candidate in candidates[:6]],
                )
                placeholder = _take_placeholder(message.chat_id)
                target = placeholder or message
                text = get_text(lang, "search_choose").replace("{query}", search_query)
                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                f"{index + 1}. {candidate.artist} — {candidate.title}"[:64],
                                callback_data=encode_callback(
                                    "select", "pick", f"{selection_id}:{index}"
                                ),
                            )
                        ]
                        for index, candidate in enumerate(candidates[:6])
                    ]
                    + [[InlineKeyboardButton(get_text(lang, "retry"), callback_data=encode_callback("retry", "last"))]]
                )
                if placeholder is not None:
                    await placeholder.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
                else:
                    await target.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
                runtime.finish_request(user_id)
                return
            source_urls = [candidates[0].url]
            found_via_search = True
        except (SearchLookupError, IndexError):
            await _reply_with_flow_error(
                message,
                context,
                BotFlowError(BotErrorCode.SEARCH_NOT_FOUND, retryable=True),
                lang=lang,
            )
            runtime.finish_request(user_id)
            return

    # The whole message was the search query, so quoting it back is noise.
    user_prefix = "" if found_via_search else _build_user_prefix(message)
    if is_private:
        await _send_loading_placeholder(message, lang)
        await _update_loading_placeholder(lang, "progress_links")
    else:
        await _send_typing_action(context.bot, message)

    bundle = await _bot_lookup.resolve_sources(
        context.application.bot_data, source_urls
    )
    if is_private:
        await _update_loading_placeholder(lang, "progress_card")
    tracks = bundle.tracks
    unavailable_urls = bundle.unavailable_urls
    videos = bundle.videos
    radios = bundle.radios
    playlists = bundle.playlists
    artists = bundle.artists

    if unavailable_urls:
        await _notify_admin(
            context,
            "Song.link недоступен при обработке: " + ", ".join(unavailable_urls),
            only_for_channel_message=message,
        )

    if bundle.item_count == 0:
        if not unavailable_urls:
            await _notify_admin(
                context,
                f"Не нашел платформы для ссылок в чате {message.chat_id}: "
                + ", ".join(source_urls),
                only_for_channel_message=message,
            )

        if message.chat.type == "channel":
            return

        if unavailable_urls:
            await _reply_with_flow_error(
                message,
                context,
                BotFlowError(
                    BotErrorCode.PROVIDER_UNAVAILABLE,
                    retryable=True,
                    provider="songlink",
                ),
                lang=lang,
            )
        else:
            await _reply_with_error(
                message,
                context,
                _format_not_found_message(source_urls),
                lang=lang,
            )
        runtime.finish_request(user_id)
        return

    content_type_count = bundle.content_type_count
    if content_type_count == 1 and tracks:
        if len(tracks) > 1:
            collection_keyboard = _build_collection_keyboard(
                tracks,
                include_channel_button=include_channel_button,
            )
            if is_private:
                crate_items = await load_crate(context.application.bot_data, user_id)
                for track in tracks:
                    draft_id = secrets.token_hex(8)
                    item = asdict(track)
                    draft = {
                        "v": 2,
                        "type": "track",
                        "item": item,
                        "prefix": "",
                        "hashtags": False,
                        "quote": False,
                        "large_preview": True,
                        "chat_id": message.chat_id,
                        "lang": lang,
                        "can_publish": False,
                    }
                    await _store_draft(context, draft_id, draft)
                    crate_items, _ = await add_to_crate(
                        context.application.bot_data,
                        user_id,
                        draft_id=draft_id,
                        item=item,
                    )
                collection_keyboard = InlineKeyboardMarkup(
                    [
                        *collection_keyboard.inline_keyboard,
                        [
                            InlineKeyboardButton(
                                f"Подборка · {len(crate_items)}/10",
                                callback_data=encode_callback("crate", "open"),
                                api_kwargs={"style": "success"},
                            )
                        ],
                    ]
                )
            await _send_track_result(
                context.bot,
                message,
                user_prefix
                + format_collection_message(
                    tracks,
                    include_hashtags=include_hashtags,
                ),
                preview_url=_select_preview_url(tracks[0].links, context)
                or tracks[0].thumbnail_url,
                reply_markup=collection_keyboard,
                )
            _record_matches_safely(tracks, message, context=context)
            return

        track = tracks[0]
        if is_private:
            await _send_track_draft(
                message,
                context,
                track,
                user_prefix=user_prefix,
                lang=lang,
            )
        else:
            await _send_track_result(
                context.bot,
                message,
                user_prefix
                + format_track_message(
                    track,
                    include_hashtags=include_hashtags,
                ),
                preview_url=_select_preview_url(track.links, context)
                or track.thumbnail_url,
                reply_markup=_build_link_keyboard(
                    track.links,
                    context=context,
                    include_channel_button=include_channel_button,
                    release_page_url=track.page_url,
                    release_kind=track.kind,
                    release_format=track.release_format,
                ),
                )
        _record_matches_safely([track], message, context=context)
        return

    if content_type_count == 1 and videos:
        await _send_youtube_result(
            context.bot,
            message,
            videos,
            user_prefix=user_prefix,
            include_channel_button=include_channel_button,
            include_hashtags=include_hashtags,
        )
        _record_videos_safely(videos, message, context=context)
        return

    if content_type_count == 1 and radios:
        await _send_nts_result(
            context.bot,
            message,
            radios,
            user_prefix=user_prefix,
            include_channel_button=include_channel_button,
            include_hashtags=include_hashtags,
        )
        _record_radios_safely(radios, message, context=context)
        return

    if content_type_count == 1 and playlists:
        await _send_playlist_result(
            context.bot,
            message,
            playlists,
            user_prefix=user_prefix,
            include_channel_button=include_channel_button,
            include_hashtags=include_hashtags,
        )
        _record_playlists_safely(playlists, message, context=context)
        return

    if content_type_count == 1 and artists:
        await _send_artist_result(
            context.bot,
            message,
            artists,
            user_prefix=user_prefix,
            include_channel_button=include_channel_button,
            include_hashtags=include_hashtags,
        )
        _record_artists_safely(artists, message, context=context)
        return

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
    _record_mixed_safely(
        tracks,
        videos,
        radios,
        playlists,
        artists,
        message,
        context=context,
    )


async def _send_track_result(
    bot: Bot,
    message: Message,
    text: str,
    *,
    preview_url: str | None,
    reply_markup: InlineKeyboardMarkup | None,
    prefer_large_preview: bool = True,
) -> None:
    if message.chat.type in {"group", "supergroup", "channel"}:
        preview_options = _build_link_preview_options(
            preview_url,
            prefer_large_media=prefer_large_preview,
        )
        # Invisible reply: in a group the card can be shown only to the person
        # who dropped the link, leaving the chat clean and their message intact.
        # Opt-in and best-effort — falls through to the public post if Telegram
        # does not deliver it.
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

        await bot.send_message(
            chat_id=message.chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            link_preview_options=preview_options,
            reply_markup=reply_markup,
        )
        await _try_delete_message(message)
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
    prefer_large_preview: bool = True,
) -> Message:
    link_preview_options = _build_link_preview_options(
        preview_url,
        prefer_large_media=prefer_large_preview,
    )
    placeholder = _take_placeholder(message.chat_id)
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

    return await message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
        link_preview_options=link_preview_options,
        reply_markup=reply_markup,
    )


_bot_lookup.configure_track_result_sender(_send_track_result)


def _build_intro_keyboard(
    bot_username: str | None,
    *,
    active: str | None = None,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    menu_rows = [
        [
            _menu_button(get_text(lang, "tab_start"), MENU_START, active),
            _menu_button(get_text(lang, "tab_help"), MENU_HELP, active),
        ],
        [
            _menu_button(get_text(lang, "tab_platforms"), MENU_PLATFORMS, active),
            _menu_button(get_text(lang, "tab_guide"), MENU_GUIDE, active),
        ],
        [_menu_button(get_text(lang, "tab_demo"), MENU_DEMO, active)],
    ]
    action_row = [_channel_button()]
    if bot_username:
        bot_url = f"https://t.me/{bot_username}"
        share_url = "https://t.me/share/url?url=" + quote(bot_url, safe="")
        action_row.append(
            _url_button(get_text(lang, "share_button"), url=share_url, style="primary")
        )

    return InlineKeyboardMarkup([*menu_rows, action_row])


def _build_error_keyboard(
    bot_username: str | None,
    *,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    rows = [[_menu_button(get_text(lang, "error_platforms_button"), MENU_PLATFORMS, None)]]
    if bot_username:
        bot_url = f"https://t.me/{bot_username}"
        share_url = "https://t.me/share/url?url=" + quote(bot_url, safe="")
        rows.append(
            [
                _channel_button(),
                _url_button(get_text(lang, "share_button"), url=share_url, style="primary"),
            ]
        )

    return InlineKeyboardMarkup(rows)


def _menu_button(label: str, callback_data: str, active: str | None) -> InlineKeyboardButton:
    prefix = "• " if callback_data == active else ""
    style = "success" if callback_data == active else "primary"
    return InlineKeyboardButton(
        f"{prefix}{label}",
        callback_data=callback_data,
        api_kwargs={"style": style},
    )


def _menu_text(menu_key: str, *, lang: str = "ru") -> str:
    key_map = {
        MENU_HELP: "menu_help",
        MENU_DEMO: "menu_demo",
        MENU_GUIDE: "menu_guide",
        MENU_PLATFORMS: "menu_platforms",
    }
    return get_text(lang, key_map.get(menu_key, "menu_start"))


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
