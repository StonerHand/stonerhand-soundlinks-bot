from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from telegram import Bot, Message
from telegram.ext import ContextTypes

from music_links_bot.artist import ArtistClient, ArtistLookupError
from music_links_bot.i18n import get_text
from music_links_bot.lookup_delivery import (
    select_mixed_preview_url as _select_mixed_preview_url_impl,
    send_artist_result as _send_artist_result_impl,
    send_mixed_result as _send_mixed_result_impl,
    send_nts_result as _send_nts_result_impl,
    send_playlist_result as _send_playlist_result_impl,
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
from music_links_bot.release_hubs import canonical_release_hub_url
from music_links_bot.search import SearchClient
from music_links_bot.songlink import SonglinkClient, SonglinkError, SonglinkLookupError
from music_links_bot.soundcloud import (
    SoundCloudClient,
    SoundCloudLookupError,
    build_soundcloud_fallback,
)
from music_links_bot.url_utils import (
    apple_podcasts_url_type,
    cache_key_for_url,
    direct_platform_links,
    spotify_url_type,
)
from music_links_bot.youtube import YouTubeClient, YouTubeLookupError

LOGGER = logging.getLogger(__name__)
NOT_FOUND_DETAIL = (
    "Проверь, что это ссылка на трек, альбом, плейлист, артиста, "
    "подкаст, YouTube-видео или NTS Radio"
)
_track_result_sender: Callable[..., Awaitable[Any]] | None = None
_track_video_pair_sender: Callable[..., Awaitable[bool]] | None = None
_BATCH_LOOKUP_CONCURRENCY = 5
_BATCH_LOOKUP_START_INTERVAL_SECONDS = 0.08
_BATCH_RETRY_DELAY_SECONDS = 0.2
_BATCH_ITEM_TIMEOUT_SECONDS = 8.5
_BATCH_PROVIDER_WORK_SECONDS = 18.0
_LOOKUP_REQUEST_BUDGET_SECONDS = 20.0
_GENRE_ENRICHMENT_TIMEOUT_SECONDS = 0.75


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
    source_urls = _unique_source_urls(source_urls)
    cached = await get_cached_lookup(bot_data, source_urls)
    if cached is not None:
        restored = _bundle_from_cache(cached)
        if restored is not None:
            restored = _ensure_source_accounting(restored, source_urls)
            if restored.is_complete_for(source_urls) or restored.is_negative_for(
                source_urls
            ):
                return restored

    key = lookup_cache_key(source_urls)
    inflight: dict[str, asyncio.Task[LookupBundle]] = bot_data.setdefault(
        "lookup_inflight", {}
    )
    pending = inflight.get(key)
    if pending is not None:
        return await asyncio.shield(pending)

    task = asyncio.create_task(_resolve_sources_uncached(bot_data, source_urls))
    inflight[key] = task

    def finish(completed: asyncio.Task[LookupBundle]) -> None:
        if inflight.get(key) is completed:
            inflight.pop(key, None)
        if completed.done() and not completed.cancelled():
            completed.exception()

    task.add_done_callback(finish)
    try:
        return await asyncio.shield(task)
    finally:
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
    music_urls = grouped["songlink"]
    tasks: list[ProviderTask] = []
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
    radios = _outcome_value(outcomes, "nts", [])
    playlists = _outcome_value(outcomes, "playlists", [])
    artists = _outcome_value(outcomes, "artists", [])
    tracks, unavailable_urls, track_statuses = lookup_result
    statuses = [
        *track_statuses,
        *_provider_statuses("youtube", youtube_urls, videos, outcomes),
        *_provider_statuses("nts", nts_urls, radios, outcomes),
        *_provider_statuses("playlists", playlist_urls, playlists, outcomes),
        *_provider_statuses("artists", artist_urls, artists, outcomes),
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


def _split_source_urls(
    source_urls: list[str],
) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    grouped = DEFAULT_PROVIDER_REGISTRY.group(source_urls)
    return (
        grouped["artists"],
        grouped["playlists"],
        grouped["youtube"],
        grouped["nts"],
        grouped["songlink"],
    )


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
    for source_url, result in zip(source_urls, results, strict=True):
        if isinstance(result, PlaylistMatch):
            playlists.append(result)
            continue

        if isinstance(result, PlaylistLookupError):
            LOGGER.info(
                "Could not fetch playlist metadata source=%s",
                _source_log_id(source_url),
            )
        elif isinstance(result, Exception):
            LOGGER.error(
                "Unexpected error while fetching playlist metadata source=%s",
                _source_log_id(source_url),
                exc_info=(type(result), result, result.__traceback__),
            )

        playlists.append(build_playlist_fallback(source_url))

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
    for source_url, result in zip(source_urls, results, strict=True):
        if isinstance(result, ArtistMatch):
            artists.append(result)
            continue

        if isinstance(result, ArtistLookupError):
            LOGGER.info(
                "Could not fetch artist metadata source=%s", _source_log_id(source_url)
            )
        elif isinstance(result, Exception):
            LOGGER.error(
                "Unexpected error while fetching artist metadata source=%s",
                _source_log_id(source_url),
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
    for source_url, result in zip(source_urls, results, strict=True):
        if isinstance(result, VideoMatch):
            videos.append(result)
            continue

        if isinstance(result, YouTubeLookupError):
            LOGGER.info(
                "Could not fetch YouTube metadata source=%s", _source_log_id(source_url)
            )
        elif isinstance(result, Exception):
            LOGGER.error(
                "Unexpected error while fetching YouTube metadata source=%s",
                _source_log_id(source_url),
                exc_info=(type(result), result, result.__traceback__),
            )

        videos.append(
            VideoMatch(title="YouTube video", author="YouTube", url=source_url)
        )

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
    for source_url, result in zip(source_urls, results, strict=True):
        if isinstance(result, RadioMatch):
            radios.append(result)
            continue

        if isinstance(result, NTSLookupError):
            LOGGER.info(
                "Could not fetch NTS metadata source=%s", _source_log_id(source_url)
            )
        elif isinstance(result, Exception):
            LOGGER.error(
                "Unexpected error while fetching NTS metadata source=%s",
                _source_log_id(source_url),
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


def _select_mixed_preview_url(
    tracks: list[TrackMatch],
    playlists: list[PlaylistMatch],
    artists: list[ArtistMatch],
    radios: list[RadioMatch],
    videos: list[VideoMatch],
    context: ContextTypes.DEFAULT_TYPE,
) -> str | None:
    return _select_mixed_preview_url_impl(
        tracks,
        playlists,
        artists,
        radios,
        videos,
        context,
    )


async def _lookup_tracks(
    client: SonglinkClient,
    source_urls: list[str],
    *,
    soundcloud_client: SoundCloudClient | None = None,
    search_client: SearchClient | None = None,
) -> tuple[list[TrackMatch], list[str]]:
    tracks, unavailable_urls, _statuses = await _lookup_tracks_detailed(
        client,
        source_urls,
        soundcloud_client=soundcloud_client,
        search_client=search_client,
    )
    return tracks, unavailable_urls


async def _lookup_tracks_detailed(
    client: SonglinkClient,
    source_urls: list[str],
    *,
    soundcloud_client: SoundCloudClient | None = None,
    search_client: SearchClient | None = None,
) -> tuple[list[TrackMatch], list[str], list[SourceStatus]]:
    # Song.link can throttle a burst of otherwise valid URLs. Keep batch
    # lookups bounded and retry transient provider failures once so a
    # three-link collection cannot silently collapse into a one-track post.
    semaphore = asyncio.Semaphore(_BATCH_LOOKUP_CONCURRENCY)
    loop = asyncio.get_running_loop()
    start_lock = asyncio.Lock()
    next_start_at = loop.time()

    async def pace_provider_start() -> None:
        """Spread a batch burst without reducing the ten-link capacity."""
        nonlocal next_start_at
        async with start_lock:
            now = loop.time()
            delay = max(0.0, next_start_at - now)
            next_start_at = (
                max(now, next_start_at) + _BATCH_LOOKUP_START_INTERVAL_SECONDS
            )
        if delay:
            await asyncio.sleep(delay)

    async def lookup_one(
        index: int,
        source_url: str,
    ) -> TrackMatch | Exception:
        item_deadline: float | None = None
        provider_attempt = 0
        while True:
            async with semaphore:
                await pace_provider_start()
                if item_deadline is None:
                    # Queue wait must not consume a source's own timeout. This
                    # guarantees that slow URLs at the start of a ten-link
                    # batch cannot starve otherwise fast followers. Five
                    # paced slots also let all ten accepted sources receive
                    # their full deadline within the webhook budget.
                    item_deadline = loop.time() + _BATCH_ITEM_TIMEOUT_SECONDS
                remaining = item_deadline - loop.time()
                if remaining <= 0:
                    return TimeoutError("source lookup deadline exhausted")
                try:
                    return await asyncio.wait_for(
                        client.lookup_track(source_url),
                        timeout=remaining,
                    )
                except TimeoutError as exc:
                    return exc
                except SonglinkLookupError as exc:
                    can_retry = spotify_url_type(source_url) in {"track", "album"}
                    if provider_attempt > 0 or not can_retry:
                        return exc
                except SonglinkError as exc:
                    if provider_attempt > 0:
                        return exc
                except Exception as exc:  # noqa: BLE001 — provider SDKs vary.
                    return exc

            provider_attempt += 1
            delay = _BATCH_RETRY_DELAY_SECONDS + (index % 3) * 0.05
            remaining = item_deadline - loop.time()
            if remaining <= delay:
                return TimeoutError("source lookup deadline exhausted")
            await asyncio.sleep(delay)

    lookup_tasks = [
        asyncio.create_task(lookup_one(index, source_url))
        for index, source_url in enumerate(source_urls)
    ]
    done, pending = await asyncio.wait(
        lookup_tasks,
        timeout=_BATCH_PROVIDER_WORK_SECONDS,
    )
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    results: list[TrackMatch | Exception] = [
        task.result()
        if task in done and not task.cancelled()
        else TimeoutError("batch provider deadline exhausted")
        for task in lookup_tasks
    ]

    tracks: list[TrackMatch] = []
    unavailable_urls: list[str] = []
    statuses: list[SourceStatus] = []

    for source_url, result in zip(source_urls, results, strict=True):
        if isinstance(result, TrackMatch):
            tracks.append(result)
            statuses.append(
                SourceStatus(
                    source_url=source_url,
                    provider="songlink",
                    state="success",
                    label=_item_label(result),
                )
            )
            continue

        if isinstance(result, SonglinkError):
            fallback_track = await _build_lookup_fallback(
                source_url,
                soundcloud_client=soundcloud_client,
            )
            if fallback_track:
                tracks.append(fallback_track)
                statuses.append(
                    SourceStatus(
                        source_url=source_url,
                        provider="songlink",
                        state="success",
                        label=_item_label(fallback_track),
                    )
                )
                continue

            if isinstance(result, SonglinkLookupError):
                retryable = spotify_url_type(source_url) in {"track", "album"}
                LOGGER.info(
                    "Song.link could not resolve source=%s retryable=%s",
                    _source_log_id(source_url),
                    retryable,
                )
                statuses.append(
                    SourceStatus(
                        source_url=source_url,
                        provider="songlink",
                        state="not_found",
                        retryable=retryable,
                        reason="release_not_found",
                    )
                )
                continue

            LOGGER.error(
                "Song.link request failed source=%s",
                _source_log_id(source_url),
                exc_info=(type(result), result, result.__traceback__),
            )
            unavailable_urls.append(source_url)
            statuses.append(
                SourceStatus(
                    source_url=source_url,
                    provider="songlink",
                    state="unavailable",
                    retryable=True,
                    reason=_failure_reason(result),
                )
            )
            continue

        if isinstance(result, Exception):
            log = LOGGER.warning if isinstance(result, TimeoutError) else LOGGER.error
            log(
                "Resolver failed source=%s error=%s",
                _source_log_id(source_url),
                type(result).__name__,
                exc_info=(
                    (type(result), result, result.__traceback__)
                    if not isinstance(result, TimeoutError)
                    else None
                ),
            )
            unavailable_urls.append(source_url)
            statuses.append(
                SourceStatus(
                    source_url=source_url,
                    provider="songlink",
                    state="unavailable",
                    retryable=True,
                    reason=_failure_reason(result),
                )
            )

    # Provider search pages are suggestions, not verified release matches.
    # Strip any legacy synthetic links before the result reaches cache or UI.
    for track in tracks:
        track.links = direct_platform_links(track.links)
    if search_client is not None and tracks:
        try:
            # Only enrichment completed before rendering can affect this card.
            # wait_for cancels a slow request so it cannot outlive the update
            # and mutate data after the result has already been cached/sent.
            await asyncio.wait_for(
                _fill_genres(search_client, tracks),
                timeout=_GENRE_ENRICHMENT_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            LOGGER.debug("Genre enrichment timed out and was cancelled")

    return tracks, unavailable_urls, statuses


def _source_log_id(source_url: str) -> str:
    """Return a diagnostic token without writing a user's raw URL to logs."""
    canonical = cache_key_for_url(source_url)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def _failure_reason(error: BaseException) -> str:
    name = type(error).__name__.casefold()
    detail = str(error).casefold()
    if "rate" in name or "429" in detail:
        return "rate_limited"
    if isinstance(error, TimeoutError) or "timeout" in name:
        return "timeout"
    return "provider_unavailable"


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
    for track, genre in zip(pending, genres, strict=True):
        if isinstance(genre, str):
            track.genre = genre


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
        LOGGER.info(
            "Could not fetch SoundCloud metadata source=%s", _source_log_id(source_url)
        )
    except Exception:
        LOGGER.exception(
            "Unexpected error while fetching SoundCloud metadata source=%s",
            _source_log_id(source_url),
        )

    return generic_soundcloud_fallback


def _songlink_page_url(source_url: str) -> str | None:
    return canonical_release_hub_url(source_url)


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
