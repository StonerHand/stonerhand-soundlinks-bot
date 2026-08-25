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
    build_auto_hashtags,
    format_artist_message,
    format_playlist_message,
    format_radio_message,
    format_track_message,
    format_video_message,
)
from music_links_bot.i18n import get_text, resolve_lang
from music_links_bot.inline_storage import (
    load_cached_search,
    load_inline_history,
    remember_inline_urls,
    store_cached_search,
)
from music_links_bot.keyboards import (
    _build_artist_keyboard,
    _build_link_keyboard,
    _build_link_preview_options,
    _build_nts_keyboard,
    _build_playlist_keyboard,
    _build_youtube_keyboard,
    _select_preview_url,
)
from music_links_bot.rich_publications import (
    RICH_MESSAGE_CAPABILITY,
    build_rich_inline_card_html,
    rich_api_unavailable,
    rich_messages_enabled,
)
from music_links_bot.search import (
    SearchClient,
    SearchLookupError,
    normalize_search_query,
)
from music_links_bot.sharing import (
    add_share_button,
    build_share_query,
    make_channel_safe_keyboard,
    parse_share_query,
    render_inline_share_card,
)
from music_links_bot.telegram_gateway import (
    record_capability_failure,
    record_capability_success,
)
from music_links_bot.telegram_media_cache import get_cached_file_id
from music_links_bot.url_utils import (
    extract_supported_urls,
    is_nts_url,
    is_playlist_url,
    is_spotify_artist_url,
    is_youtube_video_url,
)

LOGGER = logging.getLogger(__name__)
INLINE_CACHE_SECONDS = 1800
INLINE_COLLECTION_RESULT_VERSION = "v2"


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
    user_id = inline_query.from_user.id if inline_query.from_user else 0
    channel_safe = getattr(inline_query, "chat_type", None) == "channel"
    shared_urls = parse_share_query(query_text)
    source_urls = extract_supported_urls(query_text)[:MAX_LINKS_PER_MESSAGE]
    is_direct_collection = shared_urls is None and len(source_urls) > 1
    collection_urls = (
        shared_urls
        if shared_urls is not None
        else source_urls
        if is_direct_collection
        else None
    )
    if collection_urls is not None:
        await _answer_inline_collection(
            inline_query,
            context,
            collection_urls,
            lang=lang,
            is_direct=is_direct_collection,
            channel_safe=channel_safe,
        )
        return

    personal_results = channel_safe
    history_mode = False
    if not source_urls:
        search_query = normalize_search_query(query_text)
        if search_query is None:
            source_urls = await load_inline_history(
                context.application.bot_data,
                user_id,
            )
            personal_results = True
            history_mode = True
            if not source_urls:
                await _answer_inline_hint(
                    inline_query,
                    get_text(lang, "inline_hint_empty"),
                )
                return
        else:
            source_urls = await _search_source_urls(
                context,
                inline_query,
                search_query,
                lang=lang,
            )
            personal_results = True
        if not source_urls:
            return
    else:
        source_urls = source_urls[:1]

    await remember_inline_urls(
        context.application.bot_data,
        user_id,
        source_urls,
    )
    try:
        offset = max(0, int(getattr(inline_query, "offset", "") or 0))
    except (TypeError, ValueError):
        offset = 0
    page_urls = source_urls[offset : offset + 6]
    next_offset = str(offset + 6) if offset + 6 < len(source_urls) else ""

    outcomes = await asyncio.gather(
        *(
            _build_inline_result(
                source_url,
                context,
                lang=lang,
                channel_safe=channel_safe,
                history=history_mode,
            )
            for source_url in page_urls
        ),
        return_exceptions=True,
    )
    results: list[InlineQueryResultArticle] = []
    for source_url, outcome in zip(page_urls, outcomes, strict=True):
        if isinstance(outcome, InlineQueryResultArticle):
            results.append(outcome)
        elif isinstance(outcome, Exception):
            LOGGER.error(
                "Inline lookup failed source=%s",
                hashlib.sha256(source_url.encode()).hexdigest()[:12],
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
            results,
            cache_time=0 if channel_safe else INLINE_CACHE_SECONDS,
            is_personal=personal_results,
            next_offset=next_offset,
        )
        if any(_result_uses_rich(result) for result in results):
            record_capability_success(RICH_MESSAGE_CAPABILITY)
    except TelegramError as exc:
        if any(_result_uses_rich(result) for result in results):
            record_capability_failure(
                RICH_MESSAGE_CAPABILITY,
                exc,
                unsupported=rich_api_unavailable(exc),
            )
            classic_outcomes = await asyncio.gather(
                *(
                    _build_inline_result(
                        source_url,
                        context,
                        lang=lang,
                        channel_safe=channel_safe,
                        history=history_mode,
                        force_classic=True,
                    )
                    for source_url in page_urls
                ),
                return_exceptions=True,
            )
            classic_results = [
                outcome
                for outcome in classic_outcomes
                if isinstance(outcome, InlineQueryResultArticle)
            ]
            if classic_results:
                try:
                    await inline_query.answer(
                        classic_results,
                        cache_time=0 if channel_safe else INLINE_CACHE_SECONDS,
                        is_personal=personal_results,
                        next_offset=next_offset,
                    )
                    return
                except TelegramError:
                    pass
        LOGGER.debug("Could not answer inline query", exc_info=True)


async def _answer_inline_collection(
    inline_query,
    context: ContextTypes.DEFAULT_TYPE,
    source_urls: list[str],
    *,
    lang: str,
    is_direct: bool,
    channel_safe: bool,
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
            channel_safe=channel_safe,
        )
    except Exception:
        LOGGER.exception("Inline collection lookup failed")
        result = None

    if result is None:
        await _answer_inline_hint(
            inline_query,
            get_text(lang, "inline_hint_not_found"),
        )
        return

    partial = result.title.startswith("⚠️")
    try:
        await inline_query.answer(
            [result],
            cache_time=(
                0 if (is_direct or channel_safe or partial) else INLINE_CACHE_SECONDS
            ),
            is_personal=is_direct or channel_safe or partial,
        )
        if _result_uses_rich(result):
            record_capability_success(RICH_MESSAGE_CAPABILITY)
    except TelegramError as exc:
        if _result_uses_rich(result):
            record_capability_failure(
                RICH_MESSAGE_CAPABILITY,
                exc,
                unsupported=rich_api_unavailable(exc),
            )
            classic_result = await _build_inline_collection_result(
                source_urls,
                context,
                lang=lang,
                channel_safe=channel_safe,
                force_classic=True,
            )
            if classic_result is not None:
                try:
                    await inline_query.answer(
                        [classic_result],
                        cache_time=(
                            0
                            if (is_direct or channel_safe or partial)
                            else INLINE_CACHE_SECONDS
                        ),
                        is_personal=is_direct or channel_safe or partial,
                    )
                    return
                except TelegramError:
                    pass
        LOGGER.debug("Could not answer inline collection query", exc_info=True)


async def _search_source_urls(
    context: ContextTypes.DEFAULT_TYPE,
    inline_query,
    search_query: str,
    *,
    lang: str,
) -> list[str]:
    bot_data = context.application.bot_data
    cached = await load_cached_search(bot_data, search_query)
    if cached is not None:
        return cached

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

    urls = [candidate.url for candidate in candidates[:3]]
    await store_cached_search(bot_data, search_query, urls)
    return urls


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
    channel_safe: bool = False,
    history: bool = False,
    force_classic: bool = False,
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
            description=_inline_description(
                (
                    f"Artist card · {artist.platform}"
                    if lang == "en"
                    else f"Карточка артиста · {artist.platform}"
                ),
                lang=lang,
                history=history,
            ),
            text=format_artist_message(artist, include_hashtags=True),
            keyboard=add_share_button(
                _build_artist_keyboard(artist.url),
                share_query=share_query,
                label=share_label,
            ),
            preview_url=artist.url,
            channel_safe=channel_safe,
        )

    if is_playlist_url(source_url):
        playlists = await bot_lookup._lookup_playlists(
            bot_data["playlist_client"],
            [source_url],
        )
        playlist = playlists[0]
        return _inline_article(
            source_url,
            title=playlist.title,
            description=_inline_description(
                (
                    f"Playlist · {playlist.platform}"
                    if lang == "en"
                    else f"Плейлист · {playlist.platform}"
                ),
                lang=lang,
                history=history,
            ),
            text=format_playlist_message(playlist, include_hashtags=True),
            keyboard=add_share_button(
                _build_playlist_keyboard(playlist.url),
                share_query=share_query,
                label=share_label,
            ),
            preview_url=playlist.url,
            channel_safe=channel_safe,
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
            description=_inline_description(
                (
                    f"Video · {video.author}"
                    if lang == "en"
                    else f"Видео · {video.author}"
                ),
                lang=lang,
                history=history,
            ),
            text=format_video_message(video, include_hashtags=True),
            keyboard=add_share_button(
                _build_youtube_keyboard(video.url),
                share_query=share_query,
                label=share_label,
            ),
            preview_url=video.url,
            channel_safe=channel_safe,
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
            description=_inline_description(
                (
                    f"Radio show · {radio.station}"
                    if lang == "en"
                    else f"Эфир · {radio.station}"
                ),
                lang=lang,
                history=history,
            ),
            text=format_radio_message(radio, include_hashtags=True),
            keyboard=add_share_button(
                _build_nts_keyboard(radio.url),
                share_query=share_query,
                label=share_label,
            ),
            preview_url=radio.url,
            channel_safe=channel_safe,
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
    keyboard = add_share_button(
        _build_link_keyboard(
            track.links,
            context=context,
            release_page_url=track.page_url,
            release_kind=track.kind,
            release_format=track.release_format,
        ),
        share_query=share_query,
        label=share_label,
    )
    cached_cover_file_id = await get_cached_file_id(context, track.thumbnail_url)
    rich_html = build_rich_inline_card_html(
        track,
        hashtags=build_auto_hashtags(track),
        reply_markup=keyboard,
        media_id="cover" if cached_cover_file_id else None,
    )
    rich_media = (
        [
            {
                "id": "cover",
                "media": {
                    "type": "photo",
                    "media": cached_cover_file_id,
                },
            }
        ]
        if cached_cover_file_id
        else None
    )
    return _inline_article(
        source_url,
        title=f"{track.artist} — {track.title}",
        description=_inline_description(
            (
                "Post with every platform button"
                if lang == "en"
                else "Пост с кнопками всех площадок"
            ),
            lang=lang,
            history=history,
        ),
        text=format_track_message(track, include_hashtags=True),
        keyboard=keyboard,
        preview_url=_select_preview_url(track.links, context) or track.thumbnail_url,
        thumbnail_url=track.thumbnail_url,
        channel_safe=channel_safe,
        rich_html=rich_html,
        rich_media=rich_media,
        force_classic=force_classic,
    )


def _inline_description(description: str, *, lang: str, history: bool) -> str:
    if not history:
        return description
    prefix = "Recent" if lang == "en" else "Недавнее"
    return f"{prefix} · {description}"


async def _build_inline_collection_result(
    source_urls: list[str],
    context: ContextTypes.DEFAULT_TYPE,
    *,
    lang: str,
    channel_safe: bool = False,
    force_classic: bool = False,
) -> InlineQueryResultArticle | None:
    if len(source_urls) == 1:
        return await _build_inline_result(
            source_urls[0],
            context,
            lang=lang,
            channel_safe=channel_safe,
            force_classic=force_classic,
        )

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
        requested_count=len(source_urls),
    )
    return _inline_article(
        INLINE_COLLECTION_RESULT_VERSION + "|" + "|".join(source_urls),
        title=card.title,
        description=card.description,
        text=card.text,
        keyboard=card.keyboard,
        preview_url=card.preview_url,
        channel_safe=channel_safe,
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
    channel_safe: bool = False,
    rich_html: str | None = None,
    rich_media: list[dict[str, object]] | None = None,
    force_classic: bool = False,
) -> InlineQueryResultArticle:
    if channel_safe:
        keyboard = make_channel_safe_keyboard(keyboard)
    use_rich = (
        bool(rich_html)
        and bool(rich_media)
        and rich_messages_enabled()
        and not channel_safe
        and not force_classic
    )
    rich_message: dict[str, object] = {"html": rich_html or ""}
    if rich_media:
        rich_message["media"] = rich_media
    input_message_content = (
        {"rich_message": rich_message}
        if use_rich
        else InputTextMessageContent(
            message_text=text,
            parse_mode=ParseMode.HTML,
            link_preview_options=_build_link_preview_options(
                preview_url,
                prefer_large_media=True,
            ),
        )
    )
    return InlineQueryResultArticle(
        id=hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:32],
        title=title,
        description=description,
        thumbnail_url=thumbnail_url,
        input_message_content=input_message_content,
        reply_markup=None if use_rich else keyboard,
    )


def _result_uses_rich(result: InlineQueryResultArticle) -> bool:
    content = getattr(result, "input_message_content", None)
    return isinstance(content, dict) and isinstance(content.get("rich_message"), dict)
