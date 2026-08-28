from __future__ import annotations

import asyncio
import logging

from telegram import BotCommand, MenuButtonCommands
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from music_links_bot.bot_admin import id_command, stats_command, status_command
from music_links_bot.bot_crate_handlers import crate_command
from music_links_bot.bot_inline import inline_query_handler
from music_links_bot.bot_menu import (
    cancel_command,
    channel_command,
    guide_command,
    help_command,
    legacy_menu_callback,
    platforms_command,
    privacy_command,
    start_command,
)
from music_links_bot.bot_runtime import BotRuntime
from music_links_bot.config import Settings
from music_links_bot.keyboards import _build_platform_order
from music_links_bot.kvstore import KVStore
from music_links_bot.lazy_client import LazyAsyncClient
from music_links_bot.logging_config import quiet_transport_logs

LOGGER = logging.getLogger(__name__)

PUBLIC_BOT_COMMANDS = (
    BotCommand("start", "меню и быстрый старт"),
    BotCommand("help", "как пользоваться"),
    BotCommand("crate", "моя подборка"),
    BotCommand("privacy", "данные и приватность"),
)
PUBLIC_BOT_COMMANDS_EN = (
    BotCommand("start", "menu and quick start"),
    BotCommand("help", "how to use the bot"),
    BotCommand("crate", "my music crate"),
    BotCommand("privacy", "data and privacy"),
)
BOT_DESCRIPTIONS = {
    "": (
        "Музыкальный редактор для Telegram.\n\n"
        "• Ссылка или «артист — трек» → обложка, точный релиз и кнопки площадок\n"
        "• Несколько ссылок → одна подборка без дублей\n"
        "• Свой текст над ссылкой → подводка к посту\n"
        "• Стиль, хэштеги, площадки и обложка — в конструкторе\n"
        "• Отправка себе, в чат, очередь или канал\n"
        "• Inline: @StonerHandBot + запрос прямо в переписке\n"
        "• История, шаблоны и управление данными — прямо в боте\n\n"
        "Spotify, Apple Music, YouTube, SoundCloud, Deezer, Tidal, "
        "Yandex Music, NTS Radio."
    ),
    "en": (
        "A music post editor for Telegram.\n\n"
        "• A link or artist — track → artwork, the exact release and platform buttons\n"
        "• Several links → one duplicate-free collection\n"
        "• Your text above a link → the post intro\n"
        "• Style, hashtags, platforms and artwork stay editable\n"
        "• Send to yourself, another chat, the queue or a channel\n"
        "• Inline: @StonerHandBot + query anywhere\n"
        "• History, templates and data controls live inside the bot\n\n"
        "Spotify, Apple Music, YouTube, SoundCloud, Deezer, Tidal, "
        "Yandex Music and NTS Radio."
    ),
}
BOT_SHORT_DESCRIPTIONS = {
    "": "Ссылка или «артист — трек» → готовый пост. Несколько ссылок → подборка.",
    "en": "A link or artist — track → a finished post. Several links → a collection.",
}


def build_application(settings: Settings) -> Application:
    """Assemble transports and handlers without burdening module import.

    Provider implementations are imported only when an application is actually
    built. Pure formatter/tests no longer pay that cold-start cost.
    """
    quiet_transport_logs()

    from music_links_bot import bot as handlers
    from music_links_bot.artist import ArtistClient
    from music_links_bot.nts import NTSClient
    from music_links_bot.playlist import PlaylistClient
    from music_links_bot.search import SearchClient
    from music_links_bot.songlink import SonglinkClient
    from music_links_bot.soundcloud import SoundCloudClient
    from music_links_bot.youtube import YouTubeClient

    kv_store = KVStore.from_env()
    application = (
        Application.builder()
        .token(settings.bot_token)
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

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
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
    application.add_handler(
        CallbackQueryHandler(handlers.editor_callback, pattern=r"^ed\|")
    )
    application.add_handler(InlineQueryHandler(inline_query_handler))
    application.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION | filters.PHOTO | filters.AUDIO)
            & ~filters.COMMAND,
            handlers.track_lookup_message,
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
    await asyncio.gather(
        *(client.aclose() for client in active_clients),
        return_exceptions=True,
    )
