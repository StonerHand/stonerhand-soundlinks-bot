from __future__ import annotations

import asyncio
import contextvars
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

from music_links_bot.artist import ArtistClient, ArtistLookupError
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
from music_links_bot.config import Settings
from music_links_bot.ephemeral import (
    ephemeral_group_replies_enabled,
    send_ephemeral_message,
)
from music_links_bot.i18n import get_text, get_texts, resolve_lang

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
from music_links_bot.search import (
    SearchClient,
    SearchLookupError,
    normalize_search_query,
)
from music_links_bot.constants import PLATFORM_LABELS
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
from music_links_bot.publication_state import (
    find_posted_date as _find_posted_date,
    mark_posted as _schedule_mark_posted,
    release_fingerprint as _release_fingerprint,
    webapp_url as _webapp_url,
)
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
    merge_stats,
)
from music_links_bot.text_utils import normalize_hashtag
from music_links_bot.url_utils import (
    apple_podcasts_url_type,
    extract_supported_urls,
    is_nts_url,
    is_spotify_artist_url,
    is_spotify_playlist_url,
    is_youtube_video_url,
    spotify_url_type,
)
from music_links_bot.youtube import YouTubeClient, YouTubeLookupError

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

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("guide", guide_command))
    application.add_handler(CommandHandler("platforms", platforms_command))
    application.add_handler(CommandHandler("channel", channel_command))
    application.add_handler(CommandHandler("id", id_command))
    application.add_handler(CommandHandler("stats", stats_command))
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
        "Превращаю музыкальные ссылки в аккуратные посты: обложка, "
        "автохэштеги и кнопки всех площадок.\n\n"
        "• Ссылка, название трека или прослушка прямо в 🎛 Студии\n"
        "• Spotify, Apple Music, YouTube, SoundCloud, Deezer, Tidal, "
        "Yandex Music, NTS Radio\n"
        "• Inline: @StonerHandBot + запрос в любом чате\n"
        "• Студия: живой предпросмотр, подборки, отложенный постинг, "
        "фото-режим и публикация в канал"
    ),
    "en": (
        "I turn music links into clean posts: cover art, smart hashtags "
        "and buttons for every platform.\n\n"
        "• A link, a track name or a preview right in the 🎛 Studio\n"
        "• Spotify, Apple Music, YouTube, SoundCloud, Deezer, Tidal, "
        "Yandex Music, NTS Radio\n"
        "• Inline: @StonerHandBot + a query in any chat\n"
        "• Studio: live preview, crates, scheduled posting, photo mode "
        "and publish-to-channel"
    ),
}
BOT_SHORT_DESCRIPTIONS = {
    "": (
        "Кидай ссылку или название трека → пост с обложкой, хэштегами "
        "и кнопками всех площадок. Всё в 🎛 Студии"
    ),
    "en": (
        "Drop a link or a track name → a post with cover art, hashtags "
        "and buttons for every platform. All in the 🎛 Studio"
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

    await _reply_with_menu(update.message, context, MENU_START, lang=_update_lang(update))


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
            candidates = await search_client.search_release_candidates(search_query)
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
            results,
            cache_time=INLINE_CACHE_SECONDS,
            is_personal=False,
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


def _editor_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"
    state = lambda flag: get_text(lang, "ed_on" if draft.get(flag) else "ed_off")  # noqa: E731
    toggle_row = [
        InlineKeyboardButton(
            f"{get_text(lang, 'ed_hashtags')} {state('hashtags')}",
            callback_data=f"ed|h|{draft_id}",
        )
    ]
    if draft.get("prefix"):
        toggle_row.append(
            InlineKeyboardButton(
                f"{get_text(lang, 'ed_quote')} {state('quote')}",
                callback_data=f"ed|q|{draft_id}",
            )
        )

    preview_state = get_text(
        lang,
        "ed_preview_large" if draft.get("large_preview") else "ed_preview_small",
    )
    toggle_row.append(
        InlineKeyboardButton(
            f"{get_text(lang, 'ed_preview')} {preview_state}",
            callback_data=f"ed|v|{draft_id}",
        )
    )

    action_row = [
        InlineKeyboardButton(get_text(lang, "ed_done"), callback_data=f"ed|f|{draft_id}"),
        InlineKeyboardButton(get_text(lang, "ed_delete"), callback_data=f"ed|d|{draft_id}"),
    ]
    webapp_url = _webapp_url()
    if webapp_url:
        action_row.insert(
            0,
            InlineKeyboardButton(
                get_text(lang, "ed_studio"),
                web_app=WebAppInfo(url=f"{webapp_url}?draft={draft_id}"),
            ),
        )
    if draft.get("can_publish"):
        action_row.append(
            InlineKeyboardButton(
                get_text(lang, "ed_publish"),
                callback_data=f"ed|p|{draft_id}",
            )
        )

    return [toggle_row, action_row]


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


async def editor_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not query.data:
        return

    parts = query.data.split("|")
    if len(parts) != 3:
        await query.answer()
        return

    _, action, draft_id = parts
    user_lang = resolve_lang(query.from_user.language_code if query.from_user else None)
    draft = await _load_draft(context, draft_id)
    if draft is None:
        await query.answer(get_text(user_lang, "ed_expired"), show_alert=True)
        return

    lang = draft.get("lang") or user_lang

    if action == "d":
        await query.answer()
        if query.message is not None:
            await _try_delete_message(query.message)
        return

    if action == "p":
        admin_chat_id = context.application.bot_data.get("admin_chat_id")
        is_admin = (
            query.from_user is not None
            and admin_chat_id is not None
            and query.from_user.id == admin_chat_id
        )
        if not is_admin:
            await query.answer(get_text(lang, "ed_admin_only"), show_alert=True)
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
                return

        published = await _publish_draft(context, draft)
        if published:
            await _schedule_mark_posted(context, track)

        await query.answer(
            get_text(lang, "ed_published" if published else "ed_publish_failed"),
            show_alert=not published,
        )
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
    """Returns the sent message (so callers can offer undo), a bare True when
    the transport does not return one, or None on failure."""
    target = context.application.bot_data.get("publish_chat_id") or f"@{CHANNEL_USERNAME}"
    track = TrackMatch(**draft["item"])
    prefix = draft.get("prefix") or ""
    # Channel posts always carry hashtags — that is the channel house style —
    # unless the Studio explicitly replaced or emptied the list.
    include_hashtags, overrides = _draft_message_overrides(draft, include_hashtags=True)
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
        LOGGER.warning("Could not publish draft to %s", target, exc_info=True)
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

    await message.reply_text(
        format_stats_message(stats_data, include_private=include_private)
    )


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

    loading_texts = get_texts(lang, "loading")
    seed = _message_text(message) or str(message.chat_id)
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    loading_text = loading_texts[digest[0] % len(loading_texts)]
    try:
        placeholder = await message.reply_text(loading_text)
    except TelegramError:
        LOGGER.debug("Could not send loading placeholder", exc_info=True)
        return

    _PLACEHOLDER_MESSAGE.set(placeholder)


def _take_placeholder(chat_id: int) -> Message | None:
    placeholder = _PLACEHOLDER_MESSAGE.get()
    if placeholder is None or placeholder.chat_id != chat_id:
        return None

    _PLACEHOLDER_MESSAGE.set(None)
    return placeholder


async def track_lookup_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    # Posts inserted through this bot's own inline mode arrive as regular
    # messages; re-processing them would send their text into search.
    via_bot = getattr(message, "via_bot", None)
    if via_bot is not None and via_bot.id == getattr(context.bot, "id", None):
        return

    message_text = _message_text(message)
    source_urls = extract_supported_urls(message_text)[:MAX_LINKS_PER_MESSAGE]
    include_channel_button = _should_include_channel_button(message)
    include_hashtags = _should_include_hashtags(message)
    is_private = message.chat.type == "private"
    lang = _update_lang(update) if is_private else "ru"
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
            source_urls = [await search_client.search_release_url(search_query)]
            found_via_search = True
        except SearchLookupError:
            await _reply_with_error(
                message,
                context,
                get_text(lang, "search_not_found"),
                lang=lang,
            )
            return

    # The whole message was the search query, so quoting it back is noise.
    user_prefix = "" if found_via_search else _build_user_prefix(message)
    if is_private:
        await _send_loading_placeholder(message, lang)
    else:
        await _send_typing_action(context.bot, message)

    (
        artist_urls,
        playlist_urls,
        youtube_urls,
        nts_urls,
        music_urls,
    ) = _split_source_urls(source_urls)
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
            search_client=context.application.bot_data.get("search_client"),
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

    item_count = sum(
        len(items) for items in (tracks, videos, radios, playlists, artists)
    )
    if item_count == 0:
        if not unavailable_urls:
            await _notify_admin(
                context,
                f"Не нашел платформы для ссылок в чате {message.chat_id}: "
                + ", ".join(source_urls),
                only_for_channel_message=message,
            )

        if message.chat.type == "channel":
            return

        await _reply_with_error(
            message,
            context,
            _format_service_unavailable_message(unavailable_urls[0])
            if unavailable_urls
            else _format_not_found_message(source_urls),
            lang=lang,
        )
        return

    content_type_count = sum(
        bool(items) for items in (tracks, videos, radios, playlists, artists)
    )
    if content_type_count == 1 and tracks:
        if len(tracks) > 1:
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
                reply_markup=_build_collection_keyboard(
                    tracks,
                    include_channel_button=include_channel_button,
                ),
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
    phrase = pick_phrase("not_found", seed)
    if _has_recovery_hint(phrase):
        return phrase

    return f"{phrase}\n\n{NOT_FOUND_DETAIL}"


def _strip_bot_mention(text: str, bot_username: str | None) -> str:
    if not bot_username:
        return text

    mention = f"@{bot_username}"
    cleaned = " ".join(
        word for word in text.split() if word.casefold() != mention.casefold()
    )
    return cleaned


def _format_no_url_message(
    message_text: str | None,
    chat_id: int,
    *,
    lang: str = "ru",
) -> str:
    hint = get_text(lang, "no_url_hint")
    if lang != "ru":
        return hint

    seed = message_text or str(chat_id)
    return f"{pick_phrase('no_url', seed)}\n\n{hint}"


def _format_service_unavailable_message(seed: str) -> str:
    return (
        f"{pick_phrase('service_unavailable', seed)}\n\n"
        "Попробуй еще раз чуть позже или пришли другую ссылку на этот же релиз"
    )


def _has_recovery_hint(text: str) -> bool:
    lowered = text.casefold()
    return any(
        marker in lowered
        for marker in (
            "проверь",
            "попробуй",
            "похоже",
            "не трек",
            "не альбом",
        )
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
    search_client: SearchClient | None = None,
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

    tracks = [_ensure_spotify_link(track) for track in tracks]
    if search_client is not None:
        await _fill_genres(search_client, tracks)

    return tracks, unavailable_urls


async def _fill_genres(search_client: SearchClient, tracks: list[TrackMatch]) -> None:
    pending = [
        track
        for track in tracks
        if track.genre is None and track.kind in {"song", "album"}
    ]
    if not pending:
        return

    genres = await asyncio.gather(
        *(search_client.lookup_genre(track.artist, track.title) for track in pending),
        return_exceptions=True,
    )
    for track, genre in zip(pending, genres, strict=False):
        if isinstance(genre, str):
            track.genre = genre


SPOTIFY_SEARCH_URL = "https://open.spotify.com/search/"


def _ensure_spotify_link(track: TrackMatch) -> TrackMatch:
    """Every music card must have a Spotify button. When Song.link has no
    direct link, fall back to a Spotify search deep link for the release."""
    if track.links.get("spotify"):
        return track

    query = " ".join(part for part in (track.artist, track.title) if part).strip()
    if not query:
        return track

    track.links["spotify"] = SPOTIFY_SEARCH_URL + quote(query, safe="")
    return track


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


def _songlink_page_url(source_url: str) -> str:
    return f"https://song.link/{source_url}"


def _build_podcast_fallback(source_url: str) -> TrackMatch | None:
    spotify_type = spotify_url_type(source_url)
    if spotify_type == "episode":
        return TrackMatch(
            title="Podcast episode",
            artist="Spotify",
            links={"spotify": source_url},
            page_url=_songlink_page_url(source_url),
            kind="podcast",
        )

    if spotify_type == "show":
        return TrackMatch(
            title="Podcast show",
            artist="Spotify",
            links={"spotify": source_url},
            page_url=_songlink_page_url(source_url),
            kind="podcast",
            release_format="show",
        )

    apple_podcast_type = apple_podcasts_url_type(source_url)
    if apple_podcast_type == "episode":
        return TrackMatch(
            title="Podcast episode",
            artist="Apple Podcasts",
            links={"applePodcasts": source_url},
            page_url=_songlink_page_url(source_url),
            kind="podcast",
        )

    if apple_podcast_type == "show":
        return TrackMatch(
            title="Podcast show",
            artist="Apple Podcasts",
            links={"applePodcasts": source_url},
            page_url=_songlink_page_url(source_url),
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
