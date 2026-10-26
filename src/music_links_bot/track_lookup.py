"""Music links to release cards: Songlink first, then every fallback."""

from __future__ import annotations

import asyncio
import hashlib
import logging

from music_links_bot.lookup_control import (
    observe_source,
)
from music_links_bot.lookup_models import (
    SourceStatus,
    item_label as _item_label,
)
from music_links_bot.models import (
    TrackMatch,
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
    is_soundcloud_url,
    spotify_url_type,
)

LOGGER = logging.getLogger(__name__)
_BATCH_LOOKUP_CONCURRENCY = 5
_BATCH_LOOKUP_START_INTERVAL_SECONDS = 0.08
_BATCH_RETRY_DELAY_SECONDS = 0.2
_BATCH_ITEM_TIMEOUT_SECONDS = 8.5
_BATCH_PROVIDER_WORK_SECONDS = 18.0
_RELEASE_ENRICHMENT_TIMEOUT_SECONDS = 1.5


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


async def _attempt_source(
    client: SonglinkClient,
    soundcloud_client: SoundCloudClient | None,
    source_url: str,
    *,
    remaining: float,
    retried: bool,
) -> TrackMatch | Exception | None:
    """One provider attempt for one source; None means "worth one more try"."""
    if soundcloud_client is not None and is_soundcloud_url(source_url):
        # SoundCloud is authoritative for a direct SoundCloud URL. Asking an
        # aggregator to infer another service can attach a same-named but
        # unrelated Spotify release.
        try:
            return await asyncio.wait_for(
                soundcloud_client.lookup_track(source_url), timeout=remaining
            )
        except SoundCloudLookupError as exc:
            return build_soundcloud_fallback(source_url) or exc
        except Exception as exc:  # noqa: BLE001 — includes the timeout.
            return exc
    try:
        return await asyncio.wait_for(
            client.lookup_track(source_url), timeout=remaining
        )
    except TimeoutError as exc:
        return exc
    except SonglinkLookupError as exc:
        # Song.link throttles bursts: a Spotify release gets one more try.
        if retried or spotify_url_type(source_url) not in {"track", "album"}:
            return exc
    except SonglinkError as exc:
        if retried:
            return exc
    except Exception as exc:  # noqa: BLE001 — provider SDKs vary.
        return exc
    return None


def _source_outcome(
    source_url: str,
    result: TrackMatch | Exception,
    fallback: object = None,
) -> tuple[TrackMatch | None, SourceStatus, bool]:
    """One source's card (if any), its status, and whether it was unavailable."""
    provider = _track_provider(source_url)
    if isinstance(result, SonglinkError) and isinstance(fallback, TrackMatch):
        result = fallback
    if isinstance(result, TrackMatch):
        return (
            result,
            SourceStatus(
                source_url=source_url,
                provider=provider,
                state="success",
                label=_item_label(result),
            ),
            False,
        )

    if isinstance(fallback, BaseException):
        LOGGER.error(
            "Fallback resolver failed source=%s error=%s",
            _source_log_id(source_url),
            type(fallback).__name__,
            exc_info=(type(fallback), fallback, fallback.__traceback__),
        )
    if isinstance(result, SonglinkLookupError):
        reason = _failure_reason(result)
        known_failure = reason != "provider_unavailable" or result.__cause__ is not None
        retryable = (
            reason not in {"region_unavailable", "release_not_found"}
            if known_failure
            else spotify_url_type(source_url) in {"track", "album"}
        )
        LOGGER.info(
            "Song.link could not resolve source=%s retryable=%s",
            _source_log_id(source_url),
            retryable,
        )
        return (
            None,
            SourceStatus(
                source_url=source_url,
                provider=provider,
                state="unavailable"
                if known_failure and reason != "release_not_found"
                else "not_found",
                retryable=retryable,
                reason=reason if known_failure else "release_not_found",
            ),
            False,
        )

    if isinstance(result, SonglinkError):
        LOGGER.error(
            "Song.link request failed source=%s",
            _source_log_id(source_url),
            exc_info=(type(result), result, result.__traceback__),
        )
    else:
        timeout = isinstance(result, TimeoutError)
        (LOGGER.warning if timeout else LOGGER.error)(
            "Resolver failed source=%s error=%s",
            _source_log_id(source_url),
            type(result).__name__,
            exc_info=None if timeout else (type(result), result, result.__traceback__),
        )
    return (
        None,
        SourceStatus(
            source_url=source_url,
            provider=provider,
            state="unavailable",
            retryable=True,
            reason=_failure_reason(result),
        ),
        True,
    )


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
        retried = False
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
                result = await _attempt_source(
                    client,
                    soundcloud_client,
                    source_url,
                    remaining=remaining,
                    retried=retried,
                )
            if result is not None:
                return result

            retried = True
            delay = _BATCH_RETRY_DELAY_SECONDS + (index % 3) * 0.05
            if item_deadline - loop.time() <= delay:
                return TimeoutError("source lookup deadline exhausted")
            await asyncio.sleep(delay)

    lookup_tasks = [
        asyncio.create_task(
            observe_source(
                lookup_one(index, source_url),
                source_url,
                field_name="tracks",
                provider=_track_provider(source_url),
            )
        )
        for index, source_url in enumerate(source_urls)
    ]
    try:
        done, _pending = await asyncio.wait(
            lookup_tasks,
            timeout=_BATCH_PROVIDER_WORK_SECONDS,
        )
    finally:
        for task in lookup_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*lookup_tasks, return_exceptions=True)
    results: list[TrackMatch | Exception] = [
        task.result()
        if task in done and not task.cancelled()
        else TimeoutError("batch provider deadline exhausted")
        for task in lookup_tasks
    ]

    # Resolve independent provider fallbacks concurrently. In particular,
    # exact MusicBrainz enrichment is rate-limited internally; starting all
    # fallbacks together lets later items hit their own short deadline instead
    # of making a ten-link collection wait for ten sequential timeouts.
    fallback_indexes = [
        index
        for index, result in enumerate(results)
        if isinstance(result, SonglinkError)
    ]
    fallback_values = await asyncio.gather(
        *(
            observe_source(
                _build_lookup_fallback(
                    source_urls[index],
                    soundcloud_client=soundcloud_client,
                    search_client=search_client,
                ),
                source_urls[index],
                field_name="tracks",
                provider=_track_provider(source_urls[index]),
            )
            for index in fallback_indexes
        ),
        return_exceptions=True,
    )
    fallback_by_index = dict(zip(fallback_indexes, fallback_values, strict=True))

    tracks: list[TrackMatch] = []
    unavailable_urls: list[str] = []
    statuses: list[SourceStatus] = []

    for index, (source_url, result) in enumerate(
        zip(source_urls, results, strict=True)
    ):
        track, status, unavailable = _source_outcome(
            source_url, result, fallback_by_index.get(index)
        )
        if track is not None:
            tracks.append(track)
        if unavailable:
            unavailable_urls.append(source_url)
        statuses.append(status)

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
                asyncio.gather(
                    _fill_genres(search_client, tracks),
                    _fill_release_metadata(client, search_client, tracks),
                ),
                timeout=_RELEASE_ENRICHMENT_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            LOGGER.debug("Release metadata enrichment timed out and was cancelled")

    return tracks, unavailable_urls, statuses


def _track_provider(source_url: str) -> str:
    return "soundcloud" if is_soundcloud_url(source_url) else "songlink"


def _source_log_id(source_url: str) -> str:
    """Return a diagnostic token without writing a user's raw URL to logs."""
    canonical = cache_key_for_url(source_url)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def _failure_reason(error: BaseException) -> str:
    from music_links_bot.provider_errors import provider_failure_reason

    return provider_failure_reason(error)


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


async def _fill_release_metadata(client, search_client, tracks):
    from music_links_bot.release_metadata import duration_ms, metadata_url
    from music_links_bot.search import SearchCandidate

    async def fill(track):
        if track.kind not in {"song", "album"}:
            return
        if (
            track.duration_ms
            and track.artist_url
            and (track.kind == "album" or (track.album_url and track.album_title))
        ):
            return
        provider = search_client if track.links.get("appleMusic") else client
        lookup = getattr(provider, "lookup_release_metadata", None)
        source = track.links.get("appleMusic") or track.links.get("spotify")
        if not source or not callable(lookup):
            return
        try:
            details = await lookup(source)
        except Exception:  # noqa: BLE001 — enrichment must not lose a resolved release.
            return
        if not isinstance(details, (TrackMatch, SearchCandidate)):
            return
        kind = "album" if details.kind == "album" else "song"
        if kind != track.kind:
            return
        album = (
            details.album
            if isinstance(details, SearchCandidate)
            else details.album_title
        )
        # Keep an existing title/link pair intact if stores describe different editions.
        if not track.album_title or (
            album and track.album_title.casefold() == album.casefold()
        ):
            track.album_title = track.album_title or album
            track.album_url = track.album_url or metadata_url(
                details.album_url, "album"
            )
        if " ".join(track.artist.casefold().split()) == " ".join(
            details.artist.casefold().split()
        ):
            track.artist_url = track.artist_url or metadata_url(
                details.artist_url, "artist"
            )
        track.duration_ms = track.duration_ms or duration_ms(details.duration_ms)
        if track.kind == "album":
            track.track_count = track.track_count or details.track_count

    await asyncio.gather(*(fill(track) for track in tracks))


async def _build_lookup_fallback(
    source_url: str,
    *,
    soundcloud_client: SoundCloudClient | None,
    search_client: SearchClient | None = None,
) -> TrackMatch | None:
    podcast_fallback = _build_podcast_fallback(source_url)
    if podcast_fallback:
        return podcast_fallback

    if search_client is not None and hasattr(search_client, "lookup_release_fallback"):
        try:
            search_fallback = await search_client.lookup_release_fallback(source_url)
        except Exception:
            LOGGER.exception(
                "Unexpected Apple Music fallback error source=%s",
                _source_log_id(source_url),
            )
        else:
            if search_fallback is not None:
                return search_fallback

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
