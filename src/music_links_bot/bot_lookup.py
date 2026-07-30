from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from telegram import Bot, Message
from telegram.ext import ContextTypes

from music_links_bot.artist import ArtistClient, ArtistLookupError
from music_links_bot.formatter import (
    format_artist_collection_message, format_artist_message,
    format_mixed_collection_message,
    format_playlist_collection_message, format_playlist_message,
    format_radio_collection_message, format_radio_message,
    format_video_collection_message, format_video_message,
)
from music_links_bot.i18n import get_text
from music_links_bot.keyboards import (
    _build_artist_collection_keyboard, _build_artist_keyboard,
    _build_mixed_collection_keyboard,
    _build_nts_collection_keyboard, _build_nts_keyboard,
    _build_playlist_collection_keyboard, _build_playlist_keyboard,
    _build_youtube_collection_keyboard, _build_youtube_keyboard,
    _select_preview_url,
)
from music_links_bot.models import ArtistMatch, PlaylistMatch, RadioMatch, TrackMatch, VideoMatch
from music_links_bot.sharing import add_share_button, build_share_query, track_share_url
from music_links_bot.nts import NTSClient, NTSLookupError, build_nts_fallback
from music_links_bot.phrases import pick_phrase
from music_links_bot.playlist import (
    PlaylistClient,
    PlaylistLookupError,
    build_playlist_fallback,
)
from music_links_bot.search import SearchClient
from music_links_bot.songlink import SonglinkClient, SonglinkError, SonglinkLookupError
from music_links_bot.soundcloud import (
    SoundCloudClient,
    SoundCloudLookupError,
    build_soundcloud_fallback,
)
from music_links_bot.url_utils import apple_podcasts_url_type, spotify_url_type
from music_links_bot.youtube import YouTubeClient, YouTubeLookupError
from music_links_bot.provider_runtime import (
    ProviderTask,
    get_cached_lookup,
    run_provider_tasks_detailed,
    set_cached_lookup,
)
from music_links_bot.provider_registry import DEFAULT_PROVIDER_REGISTRY

LOGGER = logging.getLogger(__name__)
NOT_FOUND_DETAIL = (
    "Проверь, что это ссылка на трек, альбом, плейлист, артиста, "
    "подкаст, YouTube-видео или NTS Radio"
)
_track_result_sender: Callable[..., Awaitable[Any]] | None = None
_track_video_pair_sender: Callable[..., Awaitable[bool]] | None = None
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()
_BATCH_LOOKUP_CONCURRENCY = 2
_BATCH_RETRY_DELAY_SECONDS = 0.2


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


@dataclass(slots=True)
class LookupBundle:
    tracks: list[TrackMatch]
    unavailable_urls: list[str]
    videos: list[VideoMatch]
    radios: list[RadioMatch]
    playlists: list[PlaylistMatch]
    artists: list[ArtistMatch]
    statuses: list["SourceStatus"] = field(default_factory=list)

    @property
    def item_count(self) -> int:
        return sum(
            len(items)
            for items in (
                self.tracks,
                self.videos,
                self.radios,
                self.playlists,
                self.artists,
            )
        )

    @property
    def content_type_count(self) -> int:
        return sum(
            bool(items)
            for items in (
                self.tracks,
                self.videos,
                self.radios,
                self.playlists,
                self.artists,
            )
        )


@dataclass(slots=True)
class SourceStatus:
    source_url: str
    provider: str
    state: str
    label: str = ""
    retryable: bool = False


async def resolve_sources(bot_data: dict, source_urls: list[str]) -> LookupBundle:
    cached = await get_cached_lookup(bot_data, source_urls)
    if cached is not None:
        restored = _bundle_from_cache(cached)
        if restored is not None:
            return restored

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
    outcomes = await run_provider_tasks_detailed(bot_data, tasks)
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
                "songlink", ok=False, latency_ms=0, error=SonglinkError("lookup failed")
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
    if bundle.item_count and not bundle.unavailable_urls:
        await set_cached_lookup(bot_data, source_urls, _bundle_to_cache(bundle))
    return bundle


def _bundle_to_cache(bundle: LookupBundle) -> dict[str, Any]:
    return {
        "tracks": [asdict(item) for item in bundle.tracks],
        "unavailable_urls": list(bundle.unavailable_urls),
        "videos": [asdict(item) for item in bundle.videos],
        "radios": [asdict(item) for item in bundle.radios],
        "playlists": [asdict(item) for item in bundle.playlists],
        "artists": [asdict(item) for item in bundle.artists],
        "statuses": [asdict(item) for item in bundle.statuses],
    }


def _bundle_from_cache(payload: dict) -> LookupBundle | None:
    try:
        return LookupBundle(
            tracks=[TrackMatch(**item) for item in payload.get("tracks", [])],
            unavailable_urls=[
                str(url) for url in payload.get("unavailable_urls", [])
            ],
            videos=[VideoMatch(**item) for item in payload.get("videos", [])],
            radios=[RadioMatch(**item) for item in payload.get("radios", [])],
            playlists=[
                PlaylistMatch(**item) for item in payload.get("playlists", [])
            ],
            artists=[ArtistMatch(**item) for item in payload.get("artists", [])],
            statuses=[
                SourceStatus(**item) for item in payload.get("statuses", [])
            ],
        )
    except (TypeError, ValueError):
        return None


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
        return [
            SourceStatus(
                source_url=url,
                provider=provider,
                state="unavailable",
                retryable=True,
            )
            for url in source_urls
        ]

    statuses: list[SourceStatus] = []
    for index, source_url in enumerate(source_urls):
        item = items[index] if index < len(items) else None
        statuses.append(
            SourceStatus(
                source_url=source_url,
                provider=provider,
                state="success" if item is not None else "not_found",
                label=_item_label(item),
            )
        )
    return statuses


def _item_label(item: object) -> str:
    if item is None:
        return ""
    title = str(getattr(item, "title", "") or "")
    artist = str(
        getattr(item, "artist", "")
        or getattr(item, "author", "")
        or getattr(item, "station", "")
        or ""
    )
    return " — ".join(part for part in (artist, title) if part)[:120]


def _sort_statuses(
    statuses: list[SourceStatus],
    source_urls: list[str],
) -> list[SourceStatus]:
    positions = {url: index for index, url in enumerate(source_urls)}
    return sorted(statuses, key=lambda item: positions.get(item.source_url, 10_000))


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
    lang: str,
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
            reply_markup=add_share_button(
                _build_youtube_keyboard(
                    video.url,
                    include_channel_button=include_channel_button,
                ),
                share_query=build_share_query([video.url]),
                label=get_text(lang, "share_post"),
            ),
        )
        return

    await _send_track_result(
        bot,
        message,
        user_prefix
        + format_video_collection_message(videos, include_hashtags=include_hashtags),
        preview_url=videos[0].url,
        reply_markup=add_share_button(
            _build_youtube_collection_keyboard(
                videos,
                include_channel_button=include_channel_button,
            ),
            share_query=build_share_query([video.url for video in videos]),
            label=get_text(lang, "share_post"),
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
    lang: str,
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
            reply_markup=add_share_button(
                _build_nts_keyboard(
                    radio.url,
                    include_channel_button=include_channel_button,
                ),
                share_query=build_share_query([radio.url]),
                label=get_text(lang, "share_post"),
            ),
        )
        return

    await _send_track_result(
        bot,
        message,
        user_prefix
        + format_radio_collection_message(radios, include_hashtags=include_hashtags),
        preview_url=radios[0].url,
        reply_markup=add_share_button(
            _build_nts_collection_keyboard(
                radios,
                include_channel_button=include_channel_button,
            ),
            share_query=build_share_query([radio.url for radio in radios]),
            label=get_text(lang, "share_post"),
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
    lang: str,
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
            reply_markup=add_share_button(
                _build_playlist_keyboard(
                    playlist.url,
                    include_channel_button=include_channel_button,
                ),
                share_query=build_share_query([playlist.url]),
                label=get_text(lang, "share_post"),
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
        reply_markup=add_share_button(
            _build_playlist_collection_keyboard(
                playlists,
                include_channel_button=include_channel_button,
            ),
            share_query=build_share_query([playlist.url for playlist in playlists]),
            label=get_text(lang, "share_post"),
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
    lang: str,
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
            reply_markup=add_share_button(
                _build_artist_keyboard(
                    artist.url,
                    include_channel_button=include_channel_button,
                ),
                share_query=build_share_query([artist.url]),
                label=get_text(lang, "share_post"),
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
        reply_markup=add_share_button(
            _build_artist_collection_keyboard(
                artists,
                include_channel_button=include_channel_button,
            ),
            share_query=build_share_query([artist.url for artist in artists]),
            label=get_text(lang, "share_post"),
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
    lang: str,
) -> None:
    preview_url = _select_mixed_preview_url(
        tracks,
        playlists,
        artists,
        radios,
        videos,
        context,
    )
    text = user_prefix + format_mixed_collection_message(
        tracks,
        videos,
        playlists,
        artists,
        radios,
        include_hashtags=include_hashtags,
    )
    keyboard = add_share_button(
        _build_mixed_collection_keyboard(
            tracks,
            videos,
            playlists,
            artists,
            radios,
            include_channel_button=include_channel_button,
        ),
        share_query=build_share_query(
            [
                *[track_share_url(track) or "" for track in tracks],
                *[playlist.url for playlist in playlists],
                *[artist.url for artist in artists],
                *[radio.url for radio in radios],
                *[video.url for video in videos],
            ]
        ),
        label=get_text(lang, "share_post"),
    )
    if (
        len(tracks) == 1
        and len(videos) == 1
        and not playlists
        and not artists
        and not radios
        and await _send_track_video_pair_result(
            bot,
            message,
            text,
            track=tracks[0],
            video=videos[0],
            reply_markup=keyboard,
        )
    ):
        return

    await _send_track_result(
        bot,
        message,
        text,
        preview_url=preview_url,
        reply_markup=keyboard,
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

    async def lookup_one(index: int, source_url: str) -> TrackMatch | Exception:
        for attempt in range(2):
            try:
                async with semaphore:
                    return await client.lookup_track(source_url)
            except SonglinkLookupError as exc:
                return exc
            except SonglinkError as exc:
                if attempt == 1:
                    return exc
                await asyncio.sleep(
                    _BATCH_RETRY_DELAY_SECONDS + (index % 3) * 0.05
                )
            except Exception as exc:
                return exc
        return SonglinkError("Song.link is unavailable right now.")

    results = await asyncio.gather(
        *(
            lookup_one(index, source_url)
            for index, source_url in enumerate(source_urls)
        ),
    )

    tracks: list[TrackMatch] = []
    unavailable_urls: list[str] = []
    statuses: list[SourceStatus] = []

    for source_url, result in zip(source_urls, results, strict=False):
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
                LOGGER.info("Song.link could not resolve %s", source_url)
                statuses.append(
                    SourceStatus(
                        source_url=source_url,
                        provider="songlink",
                        state="not_found",
                    )
                )
                continue

            LOGGER.error(
                "Song.link request failed for %s",
                source_url,
                exc_info=(type(result), result, result.__traceback__),
            )
            unavailable_urls.append(source_url)
            statuses.append(
                SourceStatus(
                    source_url=source_url,
                    provider="songlink",
                    state="unavailable",
                    retryable=True,
                )
            )
            continue

        if isinstance(result, Exception):
            LOGGER.error(
                "Unexpected error while resolving %s",
                source_url,
                exc_info=(type(result), result, result.__traceback__),
            )
            unavailable_urls.append(source_url)
            statuses.append(
                SourceStatus(
                    source_url=source_url,
                    provider="songlink",
                    state="unavailable",
                    retryable=True,
                )
            )

    tracks = [_ensure_spotify_link(track) for track in tracks]
    if search_client is not None and tracks:
        enrichment = asyncio.create_task(_fill_genres(search_client, tracks))
        _BACKGROUND_TASKS.add(enrichment)
        enrichment.add_done_callback(_BACKGROUND_TASKS.discard)
        try:
            # Fast metadata enriches the initial card; a slow provider never
            # blocks the core link result and can finish in the background.
            await asyncio.wait_for(asyncio.shield(enrichment), timeout=0.75)
        except TimeoutError:
            LOGGER.debug("Genre enrichment continues in background")

    return tracks, unavailable_urls, statuses


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
