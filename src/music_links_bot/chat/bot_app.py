from __future__ import annotations

import asyncio
import logging

from telegram import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    MenuButtonCommands,
    Update,
)
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChosenInlineResultHandler,
    CommandHandler,
    InlineQueryHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from music_links_bot.cards.keyboards import _build_platform_order
from music_links_bot.chat.bot_admin import id_command, stats_command, status_command
from music_links_bot.chat.bot_crate_handlers import crate_command
from music_links_bot.chat.bot_inline import inline_query_handler
from music_links_bot.chat.bot_menu import (
    cancel_command,
    channel_command,
    guide_command,
    help_command,
    legacy_menu_callback,
    platforms_command,
    privacy_command,
    settings_command,
    start_command,
)
from music_links_bot.chat.bot_native import native_update_handler
from music_links_bot.chat.bot_preferences import LocalizedApplication
from music_links_bot.chat.inline_feedback import chosen_inline_result_handler
from music_links_bot.chat.release_panel import release_panel_callback
from music_links_bot.core.config import Settings
from music_links_bot.core.lazy_client import LazyAsyncClient
from music_links_bot.core.logging_config import quiet_transport_logs
from music_links_bot.state.bot_runtime import BotRuntime
from music_links_bot.state.kvstore import KVStore

LOGGER = logging.getLogger(__name__)

PUBLIC_BOT_COMMANDS = (
    BotCommand("start", "🎧 Новый пост и меню"),
    BotCommand("crate", "🎶 Моя подборка"),
    BotCommand("settings", "⚙️ Язык, вид и подпись"),
    BotCommand("channel", "📣 Проверить бота в канале"),
    BotCommand("help", "❓ Как это работает"),
    BotCommand("privacy", "🔐 Мои данные"),
)
PUBLIC_BOT_COMMANDS_EN = (
    BotCommand("start", "🎧 New post and menu"),
    BotCommand("crate", "🎶 My collection"),
    BotCommand("settings", "⚙️ Language, look and signature"),
    BotCommand("channel", "📣 Check the bot in a channel"),
    BotCommand("help", "❓ How it works"),
    BotCommand("privacy", "🔐 My data"),
)
# In groups only the commands that answer privately: Telegram marks them with
# is_ephemeral (Bot API 10.2), so the sender knows nobody else sees the reply.
GROUP_BOT_COMMANDS = (
    BotCommand("help", "❓ Как это работает", api_kwargs={"is_ephemeral": True}),
    BotCommand("channel", "📣 Проверить права бота", api_kwargs={"is_ephemeral": True}),
)
GROUP_BOT_COMMANDS_EN = (
    BotCommand("help", "❓ How it works", api_kwargs={"is_ephemeral": True}),
    BotCommand(
        "channel", "📣 Check the bot's rights", api_kwargs={"is_ephemeral": True}
    ),
)
BOT_DESCRIPTIONS = {
    "": (
        "🎧 Музыка → красивый пост за секунды.\n\n"
        "Пришли ссылку или «артист — трек» — бот соберёт пост с обложкой "
        "и кнопками всех площадок.\n\n"
        "🎶 Несколько ссылок — подборка с коллажем\n"
        "🎬 Песня + клипы — одним постом\n"
        "✏️ Свой текст, теги и вид — в один тап\n"
        "📣 В любой чат или канал, сразу или по времени\n\n"
        "Spotify · Apple Music · YouTube · SoundCloud · Deezer · Tidal · "
        "Яндекс Музыка · Bandcamp · NTS"
    ),
    "en": (
        "🎧 Music → a beautiful post in seconds.\n\n"
        "Send a link or “artist — track” and get a post with the cover "
        "and buttons for every platform.\n\n"
        "🎶 Several links — a collection with a collage\n"
        "🎬 A song + clips — one post\n"
        "✏️ Your text, tags and look — one tap away\n"
        "📣 To any chat or channel, now or later\n\n"
        "Spotify · Apple Music · YouTube · SoundCloud · Deezer · Tidal · "
        "Yandex Music · Bandcamp · NTS"
    ),
}
BOT_SHORT_DESCRIPTIONS = {
    "": "🎧 Ссылка → красивый пост с обложкой и кнопками всех площадок. Подборки и клипы.",
    "en": "🎧 A link → a beautiful post with the cover and every platform. Collections and clips.",
}


def build_application(settings: Settings) -> Application:
    """Assemble transports and handlers without burdening module import.

    Provider implementations are imported only when an application is actually
    built. Pure formatter/tests no longer pay that cold-start cost.
    """
    quiet_transport_logs()

    from music_links_bot.chat import bot as handlers
    from music_links_bot.editor.bot_editor import editor_callback
    from music_links_bot.lookup.bot_lookup_flow import track_lookup_message
    from music_links_bot.providers.apple_radio import AppleRadioClient
    from music_links_bot.providers.artist import ArtistClient
    from music_links_bot.providers.nts import NTSClient
    from music_links_bot.providers.playlist import PlaylistClient
    from music_links_bot.providers.search import SearchClient
    from music_links_bot.providers.songlink import SonglinkClient
    from music_links_bot.providers.soundcloud import SoundCloudClient
    from music_links_bot.providers.titles import TitleClient
    from music_links_bot.providers.youtube import YouTubeClient
    from music_links_bot.tg.update_execution import DeliveryAwareBot

    kv_store = KVStore.from_env()
    application = (
        Application.builder()
        .application_class(LocalizedApplication)
        .concurrent_updates(8)
        .bot(DeliveryAwareBot(settings.bot_token))
        .post_init(sync_application_commands)
        .post_shutdown(close_application_resources)
        .build()
    )
    application.bot_data.update(
        {
            "songlink_client": LazyAsyncClient(
                lambda: SonglinkClient(
                    user_countries=settings.songlink_user_countries,
                    api_key=settings.songlink_api_key,
                    kv=kv_store,
                )
            ),
            "youtube_client": LazyAsyncClient(YouTubeClient),
            "nts_client": LazyAsyncClient(NTSClient),
            "title_client": LazyAsyncClient(TitleClient),
            "apple_radio_client": LazyAsyncClient(AppleRadioClient),
            "soundcloud_client": LazyAsyncClient(SoundCloudClient),
            "playlist_client": LazyAsyncClient(PlaylistClient),
            "artist_client": LazyAsyncClient(ArtistClient),
            "search_client": LazyAsyncClient(
                lambda: SearchClient(
                    country=(settings.songlink_user_countries or ("US",))[0]
                )
            ),
            "kv_store": kv_store,
            "lookup_cache_namespace": "production",
            "drafts": {},
            "publish_chat_id": settings.publish_chat_id,
            "admin_chat_id": settings.admin_chat_id,
            "platform_order": _build_platform_order(settings.primary_platform),
            "ui_mode": settings.ui_mode,
            "timezone_name": settings.timezone_name,
            "runtime": BotRuntime(kv_store),
            "search_selections": {},
            "retry_sources": {},
            "inline_search_cache": {},
            "inline_history": {},
        }
    )

    application.add_handler(TypeHandler(Update, native_update_handler), group=-1)
    application.add_handler(
        CallbackQueryHandler(release_panel_callback, pattern=r"^release:")
    )
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("guide", guide_command))
    application.add_handler(CommandHandler("platforms", platforms_command))
    application.add_handler(CommandHandler("channel", channel_command))
    application.add_handler(CommandHandler("id", id_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("crate", crate_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("privacy", privacy_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(
        CallbackQueryHandler(handlers.bot_callback, pattern=r"^v2\|")
    )
    application.add_handler(
        CallbackQueryHandler(legacy_menu_callback, pattern=r"^menu:")
    )
    application.add_handler(CallbackQueryHandler(editor_callback, pattern=r"^ed\|"))
    application.add_handler(InlineQueryHandler(inline_query_handler))
    application.add_handler(ChosenInlineResultHandler(chosen_inline_result_handler))
    application.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION | filters.PHOTO | filters.AUDIO)
            & ~filters.COMMAND,
            track_lookup_message,
        )
    )
    application.add_error_handler(handlers._application_error_handler)
    return application


async def sync_application_commands(application: Application) -> None:
    """Refresh every profile field independently after a cold start.

    A temporary failure in one localized scope must not leave the command menu,
    descriptions and remaining languages stale until the next deployment.
    """

    async def attempt(label: str, awaitable) -> None:
        try:
            await awaitable
        except TelegramError:
            LOGGER.warning("Telegram profile sync failed for %s", label, exc_info=True)

    await attempt(
        "commands:default", application.bot.set_my_commands(PUBLIC_BOT_COMMANDS)
    )
    await attempt(
        "commands:en",
        application.bot.set_my_commands(PUBLIC_BOT_COMMANDS_EN, language_code="en"),
    )
    await attempt(
        "commands:groups",
        application.bot.set_my_commands(
            GROUP_BOT_COMMANDS, scope=BotCommandScopeAllGroupChats()
        ),
    )
    await attempt(
        "commands:groups:en",
        application.bot.set_my_commands(
            GROUP_BOT_COMMANDS_EN,
            scope=BotCommandScopeAllGroupChats(),
            language_code="en",
        ),
    )
    await attempt(
        "menu_button",
        application.bot.set_chat_menu_button(menu_button=MenuButtonCommands()),
    )
    for language_code, description in BOT_DESCRIPTIONS.items():
        await attempt(
            f"description:{language_code or 'default'}",
            application.bot.set_my_description(
                description,
                language_code=language_code or None,
            ),
        )
    for language_code, short_description in BOT_SHORT_DESCRIPTIONS.items():
        await attempt(
            f"short_description:{language_code or 'default'}",
            application.bot.set_my_short_description(
                short_description,
                language_code=language_code or None,
            ),
        )


async def close_application_resources(application: Application) -> None:
    from music_links_bot.artwork.branding import close_cover_resources
    from music_links_bot.core.shared_http import close_shared_clients

    # Lookup cache writes finish after their cards; let them land first.
    pending = list(application.bot_data.get("cache_writes", ()))
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    await close_cover_resources()
    await close_shared_clients()
    client_keys = (
        "songlink_client",
        "youtube_client",
        "nts_client",
        "title_client",
        "apple_radio_client",
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
    await asyncio.gather(
        *(client.aclose() for client in active_clients),
        return_exceptions=True,
    )
