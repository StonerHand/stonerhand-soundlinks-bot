from __future__ import annotations

from html import escape
import hashlib

from music_links_bot.models import (
    ArtistMatch,
    PlaylistMatch,
    RadioMatch,
    TrackMatch,
    VideoMatch,
)
from music_links_bot.phrases import pick_phrase

TRACK_EMOJIS = ("🎵", "🎧", "🎶", "🔊", "📻")
VIDEO_SIGNATURES = (
    "видео на месте, можно смотреть",
    "экран готов, жми смотреть",
    "включай, пока не остыло",
    "картинка поймана, звук рядом",
    "смотреть можно отсюда",
)
PLAYLIST_SIGNATURES = (
    "плейлист на месте, можно нырять",
    "пачка собрана, вход открыт",
    "выбирай трек и проваливайся",
    "готово, можно запускать по кругу",
    "сохранил маршрут, осталось открыть",
)
PLAYLIST_COLLECTION_SIGNATURES = (
    "выбирай, с какой пачки начать",
    "несколько маршрутов, один пост",
    "плейлисты рядом, дальше твой ход",
)
VIDEO_COLLECTION_SIGNATURES = (
    "выбирай, что включить первым",
    "экранная пачка готова",
    "можно смотреть по порядку, можно наугад",
)
RADIO_SIGNATURES = (
    "эфир на месте, можно включать",
    "радио поймано, дальше NTS",
    "здесь уже можно нырять",
    "передача готова к запуску",
    "включай, если хочется провалиться",
)
RADIO_COLLECTION_SIGNATURES = (
    "эфиры рядом, выбирай первый",
    "радио-пачка готова",
    "можно включать по порядку, можно наугад",
)
ARTIST_SIGNATURES = (
    "точка входа в артиста",
    "дальше уже дискография",
    "если зацепило - ныряй в каталог",
    "профиль открыт, можно копать глубже",
    "сначала артист, потом все остальное",
)
ARTIST_COLLECTION_SIGNATURES = (
    "артисты рядом, выбирай с кого начать",
    "несколько входов в разные каталоги",
    "витрина артистов готова",
)


def pick_track_emoji(track: TrackMatch) -> str:
    if track.kind == "podcast":
        return "🎙️"

    if track.kind == "album":
        return "💿"

    key = f"{track.artist}:{track.title}".encode("utf-8")
    index = int(hashlib.sha256(key).hexdigest(), 16) % len(TRACK_EMOJIS)
    return TRACK_EMOJIS[index]


def format_track_label(track: TrackMatch) -> str:
    return f"{escape(track.artist)} - {escape(track.title)}"


def format_track_heading(track: TrackMatch) -> str:
    return f"<b>{escape(track.artist)}</b> - {escape(track.title)}"


def format_release_heading(track: TrackMatch) -> str:
    if track.kind == "album":
        return f"💿 · <b>{escape(track.artist)}</b>\n{escape(track.title)}"

    if track.kind == "podcast":
        label = "шоу" if track.release_format == "show" else "выпуск"
        return f"🎙️ · <b>{escape(track.artist)}</b>\n{label}: {escape(track.title)}"

    return f"{pick_track_emoji(track)} · <b>{escape(track.artist)}</b>\n{escape(track.title)}"


def format_track_message(
    track: TrackMatch,
    *,
    include_hashtags: bool = True,
) -> str:
    seed = f"{track.artist}:{track.title}:{track.kind}"
    cta_key = {
        "album": "album_cta",
        "podcast": "podcast_cta",
    }.get(track.kind, "track_cta")

    lines = [
        format_release_heading(track),
        "",
        f"<i>{escape(pick_phrase(cta_key, seed))}</i>",
    ]
    return _with_hashtags(lines, build_auto_hashtags(track), include_hashtags=include_hashtags)


def format_video_message(video: VideoMatch, *, include_hashtags: bool = True) -> str:
    signature = _pick_signature(
        VIDEO_SIGNATURES,
        f"{video.author}:{video.title}:{video.url}",
    )
    lines = [
        f"📺 · <b>{escape(video.title)}</b>",
        f"канал: {escape(video.author)}",
        "",
        f"<i>{escape(signature)}</i>",
    ]
    return _with_hashtags(lines, "#stonerhand #video", include_hashtags=include_hashtags)


def format_radio_message(radio: RadioMatch, *, include_hashtags: bool = True) -> str:
    signature = _pick_signature(
        RADIO_SIGNATURES,
        f"{radio.station}:{radio.title}:{radio.url}",
    )
    lines = [
        f"📡 · <b>{escape(radio.title)}</b>",
        f"станция: {escape(radio.station)}",
        "",
        f"<i>{escape(signature)}</i>",
    ]
    return _with_hashtags(lines, "#stonerhand #radio", include_hashtags=include_hashtags)


def format_playlist_message(
    playlist: PlaylistMatch,
    *,
    include_hashtags: bool = True,
) -> str:
    signature = _pick_signature(
        PLAYLIST_SIGNATURES,
        f"{playlist.platform}:{playlist.title}:{playlist.url}",
    )
    lines = [
        f"🎛 · <b>{escape(playlist.title)}</b>",
        f"платформа: {escape(playlist.platform)}",
        "",
        f"<i>{escape(signature)}</i>",
    ]
    return _with_hashtags(lines, "#stonerhand #playlist", include_hashtags=include_hashtags)


def format_artist_message(
    artist: ArtistMatch,
    *,
    include_hashtags: bool = True,
) -> str:
    signature = _pick_signature(
        ARTIST_SIGNATURES,
        f"{artist.platform}:{artist.title}:{artist.url}",
    )
    lines = [
        f"🧬 · <b>{escape(artist.title)}</b>",
        f"профиль: {escape(artist.platform)}",
        "",
        f"<i>{escape(signature)}</i>",
    ]
    return _with_hashtags(lines, "#stonerhand #artist", include_hashtags=include_hashtags)


def format_artist_collection_message(
    artists: list[ArtistMatch],
    *,
    include_hashtags: bool = True,
) -> str:
    signature = _pick_signature(
        ARTIST_COLLECTION_SIGNATURES,
        "|".join(artist.url for artist in artists),
    )
    lines = ["сегодня по артистам:", ""]
    for index, artist in enumerate(artists, start=1):
        lines.append(f"{index}. 🧬 · <b>{escape(artist.title)}</b>")

    lines.extend(["", f"<i>{escape(signature)}</i>"])
    return _with_hashtags(lines, "#stonerhand #collection #artist", include_hashtags=include_hashtags)


def format_playlist_collection_message(
    playlists: list[PlaylistMatch],
    *,
    include_hashtags: bool = True,
) -> str:
    signature = _pick_signature(
        PLAYLIST_COLLECTION_SIGNATURES,
        "|".join(playlist.url for playlist in playlists),
    )
    lines = ["сегодня в плейлистах:", ""]
    for index, playlist in enumerate(playlists, start=1):
        lines.append(f"{index}. 🎛 · <b>{escape(playlist.title)}</b>")

    lines.extend(
        [
            "",
            f"<i>{escape(signature)}</i>",
        ]
    )
    return _with_hashtags(lines, "#stonerhand #collection #playlist", include_hashtags=include_hashtags)


def format_video_collection_message(
    videos: list[VideoMatch],
    *,
    include_hashtags: bool = True,
) -> str:
    signature = _pick_signature(
        VIDEO_COLLECTION_SIGNATURES,
        "|".join(video.url for video in videos),
    )
    lines = ["сегодня на экране:", ""]
    for index, video in enumerate(videos, start=1):
        lines.append(f"{index}. 📺 · <b>{escape(video.title)}</b>")

    lines.extend(
        [
            "",
            f"<i>{escape(signature)}</i>",
        ]
    )
    return _with_hashtags(lines, "#stonerhand #collection #video", include_hashtags=include_hashtags)


def format_radio_collection_message(
    radios: list[RadioMatch],
    *,
    include_hashtags: bool = True,
) -> str:
    signature = _pick_signature(
        RADIO_COLLECTION_SIGNATURES,
        "|".join(radio.url for radio in radios),
    )
    lines = ["сегодня на NTS:", ""]
    for index, radio in enumerate(radios, start=1):
        lines.append(f"{index}. 📡 · <b>{escape(radio.title)}</b>")

    lines.extend(
        [
            "",
            f"<i>{escape(signature)}</i>",
        ]
    )
    return _with_hashtags(lines, "#stonerhand #collection #radio", include_hashtags=include_hashtags)


def format_mixed_collection_message(
    tracks: list[TrackMatch],
    videos: list[VideoMatch],
    playlists: list[PlaylistMatch] | None = None,
    artists: list[ArtistMatch] | None = None,
    radios: list[RadioMatch] | None = None,
    *,
    include_hashtags: bool = True,
) -> str:
    playlists = playlists or []
    artists = artists or []
    radios = radios or []
    seed = "|".join(
        [
            *(f"{track.artist}:{track.title}:{track.kind}" for track in tracks),
            *(f"{playlist.platform}:{playlist.title}:playlist" for playlist in playlists),
            *(f"{artist.platform}:{artist.title}:artist" for artist in artists),
            *(f"{radio.station}:{radio.title}:radio" for radio in radios),
            *(f"{video.author}:{video.title}:video" for video in videos),
        ]
    )
    lines = [
        pick_phrase("collection_intro", seed),
        "",
    ]

    index = 1
    for track in tracks:
        emoji = pick_track_emoji(track)
        lines.append(f"{index}. {emoji} · {format_track_heading(track)}")
        index += 1

    for playlist in playlists:
        lines.append(f"{index}. 🎛 · <b>{escape(playlist.title)}</b>")
        index += 1

    for artist in artists:
        lines.append(f"{index}. 🧬 · <b>{escape(artist.title)}</b>")
        index += 1

    for radio in radios:
        lines.append(f"{index}. 📡 · <b>{escape(radio.title)}</b>")
        index += 1

    for video in videos:
        lines.append(f"{index}. 📺 · <b>{escape(video.title)}</b>")
        index += 1

    lines.extend(
        [
            "",
            f"<i>{escape(pick_phrase('collection_cta', seed))}</i>",
        ]
    )

    return _with_hashtags(
        lines,
        build_mixed_collection_hashtags(
            tracks,
            has_playlists=bool(playlists),
            has_artists=bool(artists),
            has_radios=bool(radios),
            has_videos=bool(videos),
        ),
        include_hashtags=include_hashtags,
    )


def format_collection_message(
    tracks: list[TrackMatch],
    *,
    include_hashtags: bool = True,
) -> str:
    seed = "|".join(f"{track.artist}:{track.title}:{track.kind}" for track in tracks)
    lines = [
        pick_phrase("collection_intro", seed),
        "",
    ]

    for index, track in enumerate(tracks, start=1):
        emoji = pick_track_emoji(track)
        lines.append(f"{index}. {emoji} · {format_track_heading(track)}")

    lines.extend(
        [
            "",
            f"<i>{escape(pick_phrase('collection_cta', seed))}</i>",
        ]
    )

    return _with_hashtags(lines, build_collection_hashtags(tracks), include_hashtags=include_hashtags)


def prepend_user_text(message_text: str, *, author_label: str | None = None) -> str:
    header = message_text.strip()
    if not header:
        return ""

    if author_label:
        return f"<blockquote>{escape(author_label)}:\n{escape(header)}</blockquote>\n\n"

    return f"<blockquote>{escape(header)}</blockquote>\n\n"


def build_auto_hashtags(track: TrackMatch) -> str:
    hashtags = ["#stonerhand"]

    if track.kind == "podcast":
        hashtags.append("#podcast")
        if track.release_format == "show":
            hashtags.append("#show")
        return " ".join(hashtags)

    if track.kind == "album":
        hashtags.append("#album")
        if track.release_format == "ep":
            hashtags.append("#ep")
        elif track.release_format == "single":
            hashtags.append("#single")
        return " ".join(hashtags)

    hashtags.append("#track")
    if track.release_format == "single":
        hashtags.append("#single")

    return " ".join(hashtags)


def _with_hashtags(lines: list[str], hashtags: str, *, include_hashtags: bool) -> str:
    if include_hashtags:
        lines.extend(["", hashtags])

    return "\n".join(lines)


def _pick_signature(options: tuple[str, ...], seed: str) -> str:
    index = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % len(options)
    return options[index]


def build_mixed_collection_hashtags(
    tracks: list[TrackMatch],
    *,
    has_playlists: bool = False,
    has_artists: bool = False,
    has_radios: bool = False,
    has_videos: bool = True,
) -> str:
    hashtags = build_collection_hashtags(tracks).split()
    if has_playlists and "#playlist" not in hashtags:
        hashtags.append("#playlist")

    if has_artists and "#artist" not in hashtags:
        hashtags.append("#artist")

    if has_radios and "#radio" not in hashtags:
        hashtags.append("#radio")

    if has_videos and "#video" not in hashtags:
        hashtags.append("#video")

    return " ".join(hashtags)


def build_collection_hashtags(tracks: list[TrackMatch]) -> str:
    hashtags = ["#stonerhand", "#collection"]
    kinds = {track.kind for track in tracks}
    formats = {track.release_format for track in tracks if track.release_format}

    if "track" in kinds or "song" in kinds:
        hashtags.append("#track")

    if "album" in kinds:
        hashtags.append("#album")

    if "podcast" in kinds:
        hashtags.append("#podcast")

    if "show" in formats:
        hashtags.append("#show")

    if "single" in formats:
        hashtags.append("#single")

    if "ep" in formats:
        hashtags.append("#ep")

    return " ".join(hashtags)
