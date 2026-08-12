from __future__ import annotations

import asyncio

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

from music_links_bot.bot_runtime import BotRuntime
from music_links_bot.config import Settings
from music_links_bot.kvstore import KVStore
from music_links_bot.lazy_client import LazyAsyncClient
from music_links_bot.logging_config import quiet_transport_logs

PUBLIC_BOT_COMMANDS = (
    BotCommand("start", "меню и быстрый старт"),
    BotCommand("help", "как пользоваться"),
    BotCommand("crate", "моя подборка"),
)
PUBLIC_BOT_COMMANDS_EN = (
    BotCommand("start", "menu and quick start"),
    BotCommand("help", "how to use the bot"),
    BotCommand("crate", "my music crate"),
)
BOT_DESCRIPTIONS = {
    "": (
        "Музыкальный редактор для Telegram.\n\n"
        "• Ссылка или название → точный релиз и готовая карточка\n"
        "• Несколько ссылок → одна редактируемая подборка\n"
        "• Стиль, подводка, хэштеги и площадки — в понятном конструкторе\n"
        "• Чистое превью, история и именованные подборки без дублей\n"
        "• Нативная отправка поста с кнопками в любой чат\n"
        "• Inline: @StonerHandBot + запрос прямо в переписке\n"
        "• Отправка, очередь и публикация прямо в боте\n\n"
        "Spotify, Apple Music, YouTube, SoundCloud, Deezer, Tidal, "
        "Yandex Music, NTS Radio."
    ),
    "en": (
        "A music post editor for Telegram.\n\n"
        "• A link or title → the exact release and a finished card\n"
        "• Several links → one editable crate\n"
        "• Explicit style, intro, hashtag and platform controls\n"
        "• Clean preview, history and named duplicate-free crates\n"
        "• Native sharing that preserves buttons in any chat\n"
        "• Inline: @StonerHandBot + a query inside any conversation\n"
        "• Sending, queueing and publishing inside the bot\n\n"
        "Spotify, Apple Music, YouTube, SoundCloud, Deezer, Tidal, "
        "Yandex Music and NTS Radio."
    ),
}
BOT_SHORT_DESCRIPTIONS = {
    "": (
        "Ссылка или несколько треков → карточка или подборка. "
        "Обложка, площадки и публикация — прямо в боте."
    ),
    "en": (
        "A link or tracks → a card or crate. "
        "Artwork, platforms and publishing — directly in the bot."
    ),
}


def build_application(settings: Settings) -> Application:
    """Assemble transports and handlers without burdening module import.

    Provider implementations are imported only when an application is actually
    built. Pure formatter/tests no longer pay that cold-start cost.
    """
    quiet_transport_logs()

    from music_links_bot.artist import ArtistClient
    from music_links_bot import bot as handlers
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
            "drafts": {},
            "publish_chat_id": settings.publish_chat_id,
            "admin_chat_id": settings.admin_chat_id,
            "platform_order": handlers._build_platform_order(settings.primary_platform),
            "ui_mode": settings.ui_mode,
            "timezone_name": settings.timezone_name,
            "runtime": BotRuntime(kv_store),
            "search_selections": {},
            "retry_sources": {},
            "inline_search_cache": {},
            "inline_history": {},
        }
    )

    application.add_handler(CommandHandler("start", handlers.start_command))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("guide", handlers.guide_command))
    application.add_handler(CommandHandler("platforms", handlers.platforms_command))
    application.add_handler(CommandHandler("channel", handlers.channel_command))
    application.add_handler(CommandHandler("id", handlers.id_command))
    application.add_handler(CommandHandler("stats", handlers.stats_command))
    application.add_handler(CommandHandler("crate", handlers.crate_command))
    application.add_handler(CommandHandler("cancel", handlers.cancel_command))
    application.add_handler(CommandHandler("status", handlers.status_command))
    application.add_handler(
        CallbackQueryHandler(handlers.bot_callback, pattern=r"^v2\|")
    )
    application.add_handler(
        CallbackQueryHandler(handlers.menu_callback, pattern=r"^menu:")
    )
    application.add_handler(
        CallbackQueryHandler(handlers.editor_callback, pattern=r"^ed\|")
    )
    application.add_handler(InlineQueryHandler(handlers.inline_query_handler))
    application.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
            handlers.track_lookup_message,
        )
    )
    application.add_error_handler(handlers._application_error_handler)
    return application


async def sync_application_commands(application: Application) -> None:
    try:
        await application.bot.set_my_commands(PUBLIC_BOT_COMMANDS)
        await application.bot.set_my_commands(
            PUBLIC_BOT_COMMANDS_EN,
            language_code="en",
        )
        await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
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
        # The webhook remains usable even if command synchronization fails.
        return


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
