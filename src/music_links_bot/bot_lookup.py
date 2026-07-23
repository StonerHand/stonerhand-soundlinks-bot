from __future__ import annotations

import asyncio
import logging
from time import monotonic
from urllib.parse import quote
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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
from music_links_bot.playlist import PlaylistClient, PlaylistLookupError
from music_links_bot.search import SearchClient
from music_links_bot.songlink import SonglinkClient, SonglinkError, SonglinkLookupError
from music_links_bot.soundcloud import (
    SoundCloudClient,
    SoundCloudLookupError,
    build_soundcloud_fallback,
)
from music_links_bot.url_utils import (
    apple_podcasts_url_type, is_nts_url, is_spotify_artist_url,
    is_spotify_playlist_url, is_youtube_video_url, spotify_url_type,
)
from music_links_bot.youtube import YouTubeClient, YouTubeLookupError

LOGGER = logging.getLogger(__name__)
NOT_FOUND_DETAIL = (
    "Проверь, что это ссылка на трек, альбом, плейлист, артиста, "
    "подкаст, YouTube-видео или NTS Radio"
)
_track_result_sender: Callable[..., Awaitable[Any]] | None = None
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def configure_track_result_sender(sender: Callable[..., Awaitable[Any]]) -> None:
    global _track_result_sender
    _track_result_sender = sender


async def _send_track_result(*args, **kwargs):
    if _track_result_sender is None:
        raise RuntimeError("track result sender is not configured")
    return await _track_result_sender(*args, **kwargs)


@dataclass(slots=True)
class LookupBundle:
    tracks: list[TrackMatch]
    unavailable_urls: list[str]
    videos: list[VideoMatch]
    radios: list[RadioMatch]
    playlists: list[PlaylistMatch]
    artists: list[ArtistMatch]

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


async def resolve_sources(bot_data: dict, source_urls: list[str]) -> LookupBundle:
    artist_urls, playlist_urls, youtube_urls, nts_urls, music_urls = (
        _split_source_urls(source_urls)
    )
    lookup_result, videos, radios, playlists, artists = await asyncio.gather(
        _measured_lookup(bot_data, "songlink", _lookup_tracks(
            bot_data["songlink_client"],
            music_urls,
            soundcloud_client=bot_data["soundcloud_client"],
            search_client=bot_data.get("search_client"),
        ))
        if music_urls
        else _empty_track_lookup(),
        _measured_lookup(bot_data, "youtube", _lookup_youtube_videos(bot_data["youtube_client"], youtube_urls))
        if youtube_urls
        else _empty_video_lookup(),
        _measured_lookup(bot_data, "nts", _lookup_nts_radios(bot_data["nts_client"], nts_urls))
        if nts_urls
        else _empty_radio_lookup(),
        _measured_lookup(bot_data, "spotify", _lookup_playlists(bot_data["playlist_client"], playlist_urls))
        if playlist_urls
        else _empty_playlist_lookup(),
        _measured_lookup(bot_data, "spotify", _lookup_artists(bot_data["artist_client"], artist_urls))
        if artist_urls
        else _empty_artist_lookup(),
    )
    tracks, unavailable_urls = lookup_result
    if unavailable_urls:
        runtime = bot_data.get("runtime")
        if runtime is not None and hasattr(runtime, "record_provider"):
            runtime.record_provider(
                "songlink", ok=False, latency_ms=0, error=SonglinkError("lookup failed")
            )
    return LookupBundle(
        tracks=[track for track in tracks if track.links],
        unavailable_urls=unavailable_urls,
        videos=videos,
        radios=radios,
        playlists=playlists,
        artists=artists,
    )


async def _measured_lookup(bot_data: dict, provider: str, awaitable):
    started = monotonic()
    try:
        result = await awaitable
    except BaseException as exc:
        runtime = bot_data.get("runtime")
        if runtime is not None and hasattr(runtime, "record_provider"):
            runtime.record_provider(
                provider,
                ok=False,
                latency_ms=int((monotonic() - started) * 1000),
                error=exc,
            )
        raise
    runtime = bot_data.get("runtime")
    if runtime is not None and hasattr(runtime, "record_provider"):
        runtime.record_provider(
            provider,
            ok=True,
            latency_ms=int((monotonic() - started) * 1000),
        )
    return result

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
        reply_markup=add_share_button(
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
                    *[
                        track_share_url(track) or ""
                        for track in tracks
                    ],
                    *[playlist.url for playlist in playlists],
                    *[artist.url for artist in artists],
                    *[radio.url for radio in radios],
                    *[video.url for video in videos],
                ]
            ),
            label=get_text(lang, "share_post"),
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
