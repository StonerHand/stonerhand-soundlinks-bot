from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from telegram import Bot, Message
from telegram.ext import ContextTypes

from music_links_bot.artist import ArtistClient, ArtistLookupError
from music_links_bot.i18n import get_text
from music_links_bot.lookup_control import (
    current_control,
    live_sources,
    observe_source,
)
from music_links_bot.lookup_delivery import (
    send_artist_result as _send_artist_result_impl,
    send_mixed_result as _send_mixed_result_impl,
    send_nts_result as _send_nts_result_impl,
    send_playlist_result as _send_playlist_result_impl,
    send_title_result as _send_title_result_impl,
    send_youtube_result as _send_youtube_result_impl,
)
from music_links_bot.lookup_models import (
    LookupBundle,
    SourceStatus,
    bundle_from_cache as _bundle_from_cache,
    bundle_to_cache as _bundle_to_cache,
    ensure_source_accounting as _ensure_source_accounting,
    item_label as _item_label,
    sort_statuses as _sort_statuses,
    unique_source_urls as _unique_source_urls,
)
from music_links_bot.models import (
    ArtistMatch,
    PlaylistMatch,
    RadioMatch,
    TitleMatch,
    TrackMatch,
    VideoMatch,
)
from music_links_bot.nts import NTSClient, NTSLookupError, build_nts_fallback
from music_links_bot.phrases import pick_phrase
from music_links_bot.playlist import (
    PlaylistClient,
    PlaylistLookupError,
    build_playlist_fallback,
)
from music_links_bot.provider_registry import DEFAULT_PROVIDER_REGISTRY
from music_links_bot.provider_runtime import (
    ProviderTask,
    get_cached_lookup,
    lookup_cache_key,
    run_provider_tasks_detailed,
    set_cached_lookup,
    set_cached_negative_lookup,
)
from music_links_bot.songlink import SonglinkError
from music_links_bot.titles import (
    SERVICES,
    TitleClient,
    TitleLookupError,
    TitleUnavailableError,
)
from music_links_bot.track_lookup import (
    _lookup_tracks_detailed,
    _source_log_id,
)
from music_links_bot.url_utils import (
    cache_key_for_url,
)
from music_links_bot.youtube import YouTubeClient, YouTubeLookupError

LOGGER = logging.getLogger(__name__)
NOT_FOUND_DETAIL = (
    "Проверь, что это ссылка на трек, альбом, плейлист, артиста, "
    "подкаст, YouTube-видео или NTS Radio"
)
_track_result_sender: Callable[..., Awaitable[Any]] | None = None
_track_video_pair_sender: Callable[..., Awaitable[bool]] | None = None
_LOOKUP_REQUEST_BUDGET_SECONDS = 20.0


def configure_track_result_sender(sender: Callable[..., Awaitable[Any]]) -> None:
    global _track_result_sender
    _track_result_sender = sender


def configure_track_video_pair_sender(
    sender: Callable[..., Awaitable[bool]],
) -> None:
    global _track_video_pair_sender
    _track_video_pair_sender = sender


async def _send_track_result(*args, **kwargs):
    if _track_result_sender is None:
        raise RuntimeError("track result sender is not configured")
    return await _track_result_sender(*args, **kwargs)


async def _send_track_video_pair_result(*args, **kwargs) -> bool:
    if _track_video_pair_sender is None:
        return False
    return await _track_video_pair_sender(*args, **kwargs)


async def resolve_sources(bot_data: dict, source_urls: list[str]) -> LookupBundle:
    from time import monotonic

    from music_links_bot.operation_metrics import record_duration

    started = monotonic()
    try:
        return await _resolve_sources(bot_data, source_urls)
    finally:
        record_duration(bot_data, "lookup", (monotonic() - started) * 1000)


async def _resolve_sources(bot_data: dict, source_urls: list[str]) -> LookupBundle:
    source_urls = _unique_source_urls(source_urls)
    from music_links_bot.lookup_recovery import (
        capture_sources,
        completed_sources,
        merge_recovered,
        restore_source,
    )

    completed = completed_sources.get() or {}
    retained = {
        cache_key_for_url(url): completed[cache_key_for_url(url)]
        for url in source_urls
        if restore_source(completed.get(cache_key_for_url(url)), url)
    }
    if retained:
        missing = [url for url in source_urls if cache_key_for_url(url) not in retained]
        token = completed_sources.set({})
        try:
            fresh = (
                await resolve_sources(bot_data, missing)
                if missing
                else LookupBundle([], [], [], [], [], [])
            )
        finally:
            completed_sources.reset(token)
        result = merge_recovered(source_urls, retained, fresh)
        control = current_control.get()
        if control is not None:
            control.completed.update(capture_sources(result))
        return result
    cached = await get_cached_lookup(bot_data, source_urls)
    if cached is not None:
        restored = _bundle_from_cache(cached)
        if restored is not None:
            restored = _ensure_source_accounting(restored, source_urls)
            if restored.is_complete_for(source_urls) or restored.is_negative_for(
                source_urls
            ):
                control = current_control.get()
                if control is not None:
                    control.completed.update(capture_sources(restored))
                return restored

    key = lookup_cache_key(source_urls)
    inflight: dict[str, asyncio.Task[LookupBundle]] = bot_data.setdefault(
        "lookup_inflight", {}
    )
    pending = inflight.get(key)
    snapshots = bot_data.setdefault("lookup_snapshots", {})
    subscribers = bot_data.setdefault("lookup_subscribers", {})
    if pending is None:
        snapshot: dict = {}

        async def resolve():
            token = live_sources.set(snapshot)
            try:
                return await _resolve_sources_uncached(bot_data, source_urls)
            finally:
                live_sources.reset(token)

        task = asyncio.create_task(resolve())
        inflight[key] = task
        snapshots[task] = snapshot
    else:
        task = pending
        snapshot = snapshots.get(task, {})
    subscribers[task] = subscribers.get(task, 0) + 1

    def finish(completed: asyncio.Task[LookupBundle]) -> None:
        if inflight.get(key) is completed:
            inflight.pop(key, None)
        if completed.done() and not completed.cancelled():
            completed.exception()

    task.add_done_callback(finish)
    try:
        result = await asyncio.shield(task)
        control = current_control.get()
        if control is not None:
            control.completed.update(capture_sources(result))
        return result
    finally:
        control = current_control.get()
        if control is not None:
            control.completed.update(snapshot)
        subscribers[task] -= 1
        if subscribers[task] == 0:
            subscribers.pop(task, None)
            snapshots.pop(task, None)
            if not task.done():
                if inflight.get(key) is task:
                    inflight.pop(key, None)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        if task.done():
            finish(task)


async def _resolve_sources_uncached(
    bot_data: dict,
    source_urls: list[str],
) -> LookupBundle:
    """Resolve one canonical batch; concurrent callers share this task."""

    grouped = DEFAULT_PROVIDER_REGISTRY.group(source_urls)
    artist_urls = grouped["artists"]
    playlist_urls = grouped["playlists"]
    youtube_urls = grouped["youtube"]
    nts_urls = grouped["nts"]
    title_urls = {service: grouped[service] for service in SERVICES}
    apple_radio_urls = grouped["apple_radio"]
    music_urls = grouped["songlink"]
    tasks: list[ProviderTask] = []
    if apple_radio_urls:
        tasks.append(
            ProviderTask(
                "apple_radio",
                _lookup_nts_radios(bot_data["apple_radio_client"], apple_radio_urls),
                [],
            )
        )
    if music_urls:
        tasks.append(
            ProviderTask(
                "songlink",
                _lookup_tracks_detailed(
                    bot_data["songlink_client"],
                    music_urls,
                    soundcloud_client=bot_data["soundcloud_client"],
                    search_client=bot_data.get("search_client"),
                ),
                (
                    [],
                    list(music_urls),
                    [
                        SourceStatus(
                            source_url=url,
                            provider="songlink",
                            state="unavailable",
                            retryable=True,
                        )
                        for url in music_urls
                    ],
                ),
                # Individual music sources have their own timeouts below. Do
                # not let one slow URL cancel the entire batch and discard
                # siblings that have already completed successfully.
                timeout_seconds=19.0,
                respect_circuit=False,
            )
        )
    if youtube_urls:
        tasks.append(
            ProviderTask(
                "youtube",
                _lookup_youtube_videos(bot_data["youtube_client"], youtube_urls),
                [],
            )
        )
    if nts_urls:
        tasks.append(
            ProviderTask(
                "nts",
                _lookup_nts_radios(bot_data["nts_client"], nts_urls),
                [],
            )
        )
    tasks.extend(
        # One task per service, so a refusal names the service that refused.
        ProviderTask(
            service,
            _lookup_titles(bot_data["title_client"], urls, provider=service),
            [],
        )
        for service, urls in title_urls.items()
        if urls
    )
    if playlist_urls:
        tasks.append(
            ProviderTask(
                "playlists",
                _lookup_playlists(bot_data["playlist_client"], playlist_urls),
                [],
            )
        )
    if artist_urls:
        tasks.append(
            ProviderTask(
                "artists",
                _lookup_artists(bot_data["artist_client"], artist_urls),
                [],
            )
        )
    outcomes = await run_provider_tasks_detailed(
        bot_data,
        tasks,
        budget_seconds=_LOOKUP_REQUEST_BUDGET_SECONDS,
    )
    lookup_result = _outcome_value(outcomes, "songlink", ([], [], []))
    videos = _outcome_value(outcomes, "youtube", [])
    radios = [
        *_outcome_value(outcomes, "nts", []),
        *_outcome_value(outcomes, "apple_radio", []),
    ]
    radio_order = {
        cache_key_for_url(url): index for index, url in enumerate(source_urls)
    }
    radios.sort(
        key=lambda radio: radio_order.get(
            cache_key_for_url(radio.url), len(source_urls)
        )
    )
    playlists = _outcome_value(outcomes, "playlists", [])
    artists = _outcome_value(outcomes, "artists", [])
    titles = [
        title for service in SERVICES for title in _outcome_value(outcomes, service, [])
    ]
    tracks, unavailable_urls, track_statuses = lookup_result
    statuses = [
        *track_statuses,
        *_provider_statuses("youtube", youtube_urls, videos, outcomes),
        *_provider_statuses("nts", nts_urls, radios, outcomes),
        *_provider_statuses("apple_radio", apple_radio_urls, radios, outcomes),
        *_provider_statuses("playlists", playlist_urls, playlists, outcomes),
        *_provider_statuses("artists", artist_urls, artists, outcomes),
        *(
            status
            for service, urls in title_urls.items()
            for status in _provider_statuses(service, urls, titles, outcomes)
        ),
    ]
    if unavailable_urls:
        runtime = bot_data.get("runtime")
        if runtime is not None and hasattr(runtime, "record_provider"):
            runtime.record_provider(
                "songlink",
                ok=False,
                latency_ms=0,
                error=SonglinkError("lookup failed"),
                partial=True,
            )
    bundle = LookupBundle(
        tracks=[track for track in tracks if track.links],
        unavailable_urls=unavailable_urls,
        videos=videos,
        radios=radios,
        playlists=playlists,
        artists=artists,
        statuses=_sort_statuses(statuses, source_urls),
        titles=titles,
    )
    bundle = _ensure_source_accounting(bundle, source_urls)
    complete = bundle.is_complete_for(source_urls)
    if bundle.item_count and complete:
        await set_cached_lookup(bot_data, source_urls, _bundle_to_cache(bundle))
    elif (
        not bundle.item_count
        and bundle.statuses
        and all(status.state == "not_found" for status in bundle.statuses)
    ):
        await set_cached_negative_lookup(
            bot_data, source_urls, _bundle_to_cache(bundle)
        )
    return bundle


def _outcome_value(outcomes: dict, provider: str, fallback):
    outcome = outcomes.get(provider)
    return outcome.value if outcome is not None else fallback


def _provider_statuses(
    provider: str,
    source_urls: list[str],
    items: list,
    outcomes: dict,
) -> list[SourceStatus]:
    outcome = outcomes.get(provider)
    if outcome is not None and not outcome.ok:
        error_key = str(outcome.error or "provider_unavailable").casefold()
        reason = (
            "rate_limited"
            if "rate" in error_key or "429" in error_key
            else "timeout"
            if "timeout" in error_key
            else "provider_unavailable"
        )
        return [
            SourceStatus(
                source_url=url,
                provider=provider,
                state="unavailable",
                retryable=True,
                reason=reason,
            )
            for url in source_urls
        ]

    items_by_url = {
        cache_key_for_url(str(item_url)): item
        for item in items
        if (item_url := getattr(item, "url", None))
    }
    statuses: list[SourceStatus] = []
    for source_url in source_urls:
        item = items_by_url.get(cache_key_for_url(source_url))
        statuses.append(
            SourceStatus(
                source_url=source_url,
                provider=provider,
                state="success" if item is not None else "not_found",
                label=_item_label(item),
            )
        )
    return statuses


def _strip_bot_mention(text: str, bot_username: str | None) -> str:
    if not bot_username:
        return text

    mention = f"@{bot_username}"
    return " ".join(
        word for word in text.split() if word.casefold() != mention.casefold()
    )


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


async def _lookup_each(
    source_urls: list[str],
    fetch: Callable[[str], Awaitable[Any]],
    *,
    kind: type,
    expected_error: type[Exception],
    field_name: str,
    provider: str,
    label: str,
    fallback: Callable[[str], Any],
) -> list[Any]:
    """Fetch every link at once; a failed one becomes a plain fallback card."""
    results = await asyncio.gather(
        *(
            observe_source(fetch(url), url, field_name=field_name, provider=provider)
            for url in source_urls
        ),
        return_exceptions=True,
    )

    items: list[Any] = []
    for source_url, result in zip(source_urls, results, strict=True):
        if isinstance(result, kind):
            items.append(result)
            continue

        if isinstance(result, expected_error):
            LOGGER.info(
                "Could not fetch %s metadata source=%s",
                label,
                _source_log_id(source_url),
            )
        elif isinstance(result, Exception):
            LOGGER.error(
                "Unexpected error while fetching %s metadata source=%s",
                label,
                _source_log_id(source_url),
                exc_info=(type(result), result, result.__traceback__),
            )

        fallback_item = fallback(source_url)
        if fallback_item is not None:
            items.append(fallback_item)

    return items


async def _lookup_playlists(
    client: PlaylistClient,
    source_urls: list[str],
) -> list[PlaylistMatch]:
    return await _lookup_each(
        source_urls,
        client.lookup_playlist,
        kind=PlaylistMatch,
        expected_error=PlaylistLookupError,
        field_name="playlists",
        provider="playlists",
        label="playlist",
        fallback=build_playlist_fallback,
    )


async def _lookup_artists(
    client: ArtistClient,
    source_urls: list[str],
) -> list[ArtistMatch]:
    return await _lookup_each(
        source_urls,
        client.lookup_artist,
        kind=ArtistMatch,
        expected_error=ArtistLookupError,
        field_name="artists",
        provider="artists",
        label="artist",
        fallback=lambda url: ArtistMatch(
            title="Spotify artist", platform="Spotify", url=url
        ),
    )


async def _lookup_youtube_videos(
    client: YouTubeClient,
    source_urls: list[str],
) -> list[VideoMatch]:
    return await _lookup_each(
        source_urls,
        client.lookup_video,
        kind=VideoMatch,
        expected_error=YouTubeLookupError,
        field_name="videos",
        provider="youtube",
        label="YouTube",
        fallback=lambda url: VideoMatch(
            title="YouTube video", author="YouTube", url=url
        ),
    )


async def _lookup_titles(
    client: TitleClient,
    source_urls: list[str],
    *,
    provider: str = "netflix",
) -> list[TitleMatch]:
    blocked: list[TitleUnavailableError] = []

    async def fetch(url: str) -> TitleMatch:
        try:
            return await client.lookup_title(url)
        except TitleUnavailableError as exc:
            blocked.append(exc)
            raise

    # No placeholder card: a film without its title or poster says nothing.
    titles = await _lookup_each(
        source_urls,
        fetch,
        kind=TitleMatch,
        expected_error=TitleLookupError,
        field_name="titles",
        provider=provider,
        label=SERVICES[provider].name,
        fallback=lambda url: None,
    )
    if blocked and not titles:
        # Fail the provider task, so the links read "Netflix is not answering,
        # retry" instead of a false "not found".
        raise blocked[0]
    return titles


async def _lookup_nts_radios(
    client: NTSClient,
    source_urls: list[str],
) -> list[RadioMatch]:
    return await _lookup_each(
        source_urls,
        client.lookup_radio,
        kind=RadioMatch,
        expected_error=NTSLookupError,
        field_name="radios",
        provider="nts",
        label="NTS",
        fallback=build_nts_fallback,
    )


async def _send_youtube_result(
    bot: Bot,
    message: Message,
    videos: list[VideoMatch],
    *,
    user_prefix: str,
    include_channel_button: bool,
    include_hashtags: bool,
    lang: str,
    allow_share: bool = True,
    requested_count: int | None = None,
) -> None:
    await _send_youtube_result_impl(
        bot,
        message,
        videos,
        send_track_result=_send_track_result,
        user_prefix=user_prefix,
        include_channel_button=include_channel_button,
        include_hashtags=include_hashtags,
        lang=lang,
        allow_share=allow_share,
        requested_count=requested_count,
    )


async def _send_title_result(
    bot: Bot,
    message: Message,
    titles: list[TitleMatch],
    **kwargs,
) -> None:
    await _send_title_result_impl(
        bot, message, titles, send_track_result=_send_track_result, **kwargs
    )


async def _send_nts_result(
    bot: Bot,
    message: Message,
    radios: list[RadioMatch],
    *,
    user_prefix: str,
    include_channel_button: bool,
    include_hashtags: bool,
    lang: str,
    allow_share: bool = True,
    requested_count: int | None = None,
) -> None:
    await _send_nts_result_impl(
        bot,
        message,
        radios,
        send_track_result=_send_track_result,
        user_prefix=user_prefix,
        include_channel_button=include_channel_button,
        include_hashtags=include_hashtags,
        lang=lang,
        allow_share=allow_share,
        requested_count=requested_count,
    )


async def _send_playlist_result(
    bot: Bot,
    message: Message,
    playlists: list[PlaylistMatch],
    *,
    user_prefix: str,
    include_channel_button: bool,
    include_hashtags: bool,
    lang: str,
    allow_share: bool = True,
    requested_count: int | None = None,
    import_id: str | None = None,
) -> None:
    await _send_playlist_result_impl(
        bot,
        message,
        playlists,
        send_track_result=_send_track_result,
        user_prefix=user_prefix,
        include_channel_button=include_channel_button,
        include_hashtags=include_hashtags,
        lang=lang,
        allow_share=allow_share,
        requested_count=requested_count,
        import_id=import_id,
    )


async def _send_artist_result(
    bot: Bot,
    message: Message,
    artists: list[ArtistMatch],
    *,
    user_prefix: str,
    include_channel_button: bool,
    include_hashtags: bool,
    lang: str,
    allow_share: bool = True,
    requested_count: int | None = None,
) -> None:
    await _send_artist_result_impl(
        bot,
        message,
        artists,
        send_track_result=_send_track_result,
        user_prefix=user_prefix,
        include_channel_button=include_channel_button,
        include_hashtags=include_hashtags,
        lang=lang,
        allow_share=allow_share,
        requested_count=requested_count,
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
    lang: str,
    allow_share: bool = True,
    requested_count: int | None = None,
) -> None:
    await _send_mixed_result_impl(
        bot,
        message,
        tracks,
        videos,
        radios,
        playlists,
        artists,
        send_track_result=_send_track_result,
        send_track_video_pair_result=_send_track_video_pair_result,
        user_prefix=user_prefix,
        include_channel_button=include_channel_button,
        include_hashtags=include_hashtags,
        context=context,
        lang=lang,
        allow_share=allow_share,
        requested_count=requested_count,
    )
