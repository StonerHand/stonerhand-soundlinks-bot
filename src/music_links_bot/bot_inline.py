from __future__ import annotations

import asyncio
import hashlib
import logging

from telegram import (
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InlineQueryResultsButton,
    InputTextMessageContent,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from music_links_bot import bot_lookup
from music_links_bot.constants import MAX_LINKS_PER_MESSAGE
from music_links_bot.formatter import (
    format_artist_message,
    format_playlist_message,
    format_radio_message,
    format_track_message,
    format_video_message,
)
from music_links_bot.i18n import get_text, resolve_lang
from music_links_bot.keyboards import (
    _build_artist_keyboard,
    _build_link_keyboard,
    _build_link_preview_options,
    _build_nts_keyboard,
    _build_playlist_keyboard,
    _build_youtube_keyboard,
    _select_preview_url,
)
from music_links_bot.search import SearchClient, SearchLookupError, normalize_search_query
from music_links_bot.sharing import (
    add_share_button,
    build_share_query,
    parse_share_query,
    render_inline_share_card,
)
from music_links_bot.url_utils import (
    extract_supported_urls,
    is_nts_url,
    is_spotify_artist_url,
    is_spotify_playlist_url,
    is_youtube_video_url,
)

LOGGER = logging.getLogger(__name__)
INLINE_CACHE_SECONDS = 1800


async def inline_query_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    inline_query = update.inline_query
    if inline_query is None:
        return

    lang = resolve_lang(
        inline_query.from_user.language_code if inline_query.from_user else None
    )
    query_text = inline_query.query or ""
    shared_urls = parse_share_query(query_text)
    source_urls = extract_supported_urls(query_text)[:MAX_LINKS_PER_MESSAGE]
    is_direct_collection = shared_urls is None and len(source_urls) > 1
    collection_urls = (
        shared_urls
        if shared_urls is not None
        else source_urls if is_direct_collection else None
    )
    if collection_urls is not None:
        await _answer_inline_collection(
            inline_query,
            context,
            collection_urls,
            lang=lang,
            is_direct=is_direct_collection,
        )
        return

    source_urls = source_urls[:1]
    if not source_urls:
        search_query = normalize_search_query(query_text)
        if search_query is None:
            await _answer_inline_hint(
                inline_query,
                get_text(lang, "inline_hint_empty"),
            )
            return

        source_urls = await _search_source_urls(
            context,
            inline_query,
            search_query,
            lang=lang,
        )
        if not source_urls:
            return

    outcomes = await asyncio.gather(
        *(
            _build_inline_result(source_url, context, lang=lang)
            for source_url in source_urls
        ),
        return_exceptions=True,
    )
    results: list[InlineQueryResultArticle] = []
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
        await _answer_inline_hint(
            inline_query,
            get_text(lang, "inline_hint_not_found"),
        )
        return

    try:
        await inline_query.answer(
            results[:6],
            cache_time=INLINE_CACHE_SECONDS,
            is_personal=False,
            button=_studio_button(lang),
        )
    except TelegramError:
        LOGGER.debug("Could not answer inline query", exc_info=True)


async def _answer_inline_collection(
    inline_query,
    context: ContextTypes.DEFAULT_TYPE,
    source_urls: list[str],
    *,
    lang: str,
    is_direct: bool,
) -> None:
    if not source_urls:
        await _answer_inline_hint(
            inline_query,
            get_text(lang, "inline_hint_not_found"),
        )
        return

    try:
        result = await _build_inline_collection_result(
            source_urls,
            context,
            lang=lang,
        )
    except Exception as exc:
        LOGGER.error(
            "Inline collection lookup failed",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        result = None

    if result is None:
        await _answer_inline_hint(
            inline_query,
            get_text(lang, "inline_hint_not_found"),
        )
        return

    try:
        await inline_query.answer(
            [result],
            cache_time=0 if is_direct else INLINE_CACHE_SECONDS,
            is_personal=is_direct,
            button=_studio_button(lang),
        )
    except TelegramError:
        LOGGER.debug("Could not answer inline collection query", exc_info=True)


async def _search_source_urls(
    context: ContextTypes.DEFAULT_TYPE,
    inline_query,
    search_query: str,
    *,
    lang: str,
) -> list[str]:
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
                    {"url": source_url},
                )()
            ]
    except SearchLookupError:
        await _answer_inline_hint(
            inline_query,
            get_text(lang, "inline_hint_not_found"),
        )
        return []

    return [candidate.url for candidate in candidates]


def _studio_button(lang: str) -> InlineQueryResultsButton:
    return InlineQueryResultsButton(
        text=get_text(lang, "open_studio"),
        start_parameter="studio",
    )


async def _answer_inline_hint(inline_query, button_text: str) -> None:
    try:
        await inline_query.answer(
            [],
            cache_time=10,
            button=InlineQueryResultsButton(
                text=button_text,
                start_parameter="inline",
            ),
        )
    except TelegramError:
        LOGGER.debug("Could not answer inline query with hint", exc_info=True)


async def _build_inline_result(
    source_url: str,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    lang: str = "ru",
) -> InlineQueryResultArticle | None:
    bot_data = context.application.bot_data
    share_query = build_share_query([source_url])
    share_label = get_text(lang, "share_post")

    if is_spotify_artist_url(source_url):
        artists = await bot_lookup._lookup_artists(
            bot_data["artist_client"],
            [source_url],
        )
        artist = artists[0]
        return _inline_article(
            source_url,
            title=artist.title,
            description=(
                f"Artist card · {artist.platform}"
                if lang == "en"
                else f"Карточка артиста · {artist.platform}"
            ),
            text=format_artist_message(artist, include_hashtags=True),
            keyboard=add_share_button(
                _build_artist_keyboard(artist.url),
                share_query=share_query,
                label=share_label,
            ),
            preview_url=artist.url,
        )

    if is_spotify_playlist_url(source_url):
        playlists = await bot_lookup._lookup_playlists(
            bot_data["playlist_client"],
            [source_url],
        )
        playlist = playlists[0]
        return _inline_article(
            source_url,
            title=playlist.title,
            description=(
                f"Playlist · {playlist.platform}"
                if lang == "en"
                else f"Плейлист · {playlist.platform}"
            ),
            text=format_playlist_message(playlist, include_hashtags=True),
            keyboard=add_share_button(
                _build_playlist_keyboard(playlist.url),
                share_query=share_query,
                label=share_label,
            ),
            preview_url=playlist.url,
        )

    if is_youtube_video_url(source_url):
        videos = await bot_lookup._lookup_youtube_videos(
            bot_data["youtube_client"],
            [source_url],
        )
        video = videos[0]
        return _inline_article(
            source_url,
            title=video.title,
            description=(
                f"Video · {video.author}"
                if lang == "en"
                else f"Видео · {video.author}"
            ),
            text=format_video_message(video, include_hashtags=True),
            keyboard=add_share_button(
                _build_youtube_keyboard(video.url),
                share_query=share_query,
                label=share_label,
            ),
            preview_url=video.url,
        )

    if is_nts_url(source_url):
        radios = await bot_lookup._lookup_nts_radios(
            bot_data["nts_client"],
            [source_url],
        )
        if not radios:
            return None

        radio = radios[0]
        return _inline_article(
            source_url,
            title=radio.title,
            description=(
                f"Radio show · {radio.station}"
                if lang == "en"
                else f"Эфир · {radio.station}"
            ),
            text=format_radio_message(radio, include_hashtags=True),
            keyboard=add_share_button(
                _build_nts_keyboard(radio.url),
                share_query=share_query,
                label=share_label,
            ),
            preview_url=radio.url,
        )

    tracks, _unavailable = await bot_lookup._lookup_tracks(
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
        description=(
            "Post with every platform button"
            if lang == "en"
            else "Пост с кнопками всех площадок"
        ),
        text=format_track_message(track, include_hashtags=True),
        keyboard=add_share_button(
            _build_link_keyboard(
                track.links,
                context=context,
                release_page_url=track.page_url,
                release_kind=track.kind,
                release_format=track.release_format,
            ),
            share_query=share_query,
            label=share_label,
        ),
        preview_url=_select_preview_url(track.links, context) or track.thumbnail_url,
        thumbnail_url=track.thumbnail_url,
    )


async def _build_inline_collection_result(
    source_urls: list[str],
    context: ContextTypes.DEFAULT_TYPE,
    *,
    lang: str,
) -> InlineQueryResultArticle | None:
    if len(source_urls) == 1:
        return await _build_inline_result(source_urls[0], context, lang=lang)

    bundle = await bot_lookup.resolve_sources(
        context.application.bot_data,
        source_urls,
    )
    if bundle.item_count == 0:
        return None

    share_query = build_share_query(source_urls)
    card = render_inline_share_card(
        bundle,
        context=context,
        lang=lang,
        share_query=share_query,
        share_label=get_text(lang, "share_post"),
    )
    return _inline_article(
        "|".join(source_urls),
        title=card.title,
        description=card.description,
        text=card.text,
        keyboard=card.keyboard,
        preview_url=card.preview_url,
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
