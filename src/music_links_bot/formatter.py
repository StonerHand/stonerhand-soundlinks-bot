from __future__ import annotations

from html import escape
import hashlib

from music_links_bot.models import PlaylistMatch, TrackMatch, VideoMatch
from music_links_bot.phrases import pick_phrase

TRACK_EMOJIS = ("🎵", "🎧", "🎶", "🔊", "📻")


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


def format_release_badge(track: TrackMatch) -> str:
    if track.kind == "album":
        return "<b>альбом найден</b>"

    if track.kind == "podcast":
        return "<b>подкаст найден</b>"

    return "<b>трек найден</b>"


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
    platform_count: int | None = None,
    include_hashtags: bool = True,
) -> str:
    seed = f"{track.artist}:{track.title}:{track.kind}"
    cta_key = {
        "album": "album_cta",
        "podcast": "podcast_cta",
    }.get(track.kind, "track_cta")

    lines = [
        format_release_badge(track),
        format_release_heading(track),
        "",
    ]
    if platform_count is not None:
        lines.extend([format_found_platforms(platform_count), ""])

    lines.extend(
        [
            "слушать:",
            f"<i>{escape(pick_phrase(cta_key, seed))}</i>",
        ]
    )
    return _with_hashtags(lines, build_auto_hashtags(track), include_hashtags=include_hashtags)


def format_video_message(video: VideoMatch, *, include_hashtags: bool = True) -> str:
    lines = [
        "<b>видео найдено</b>",
        f"📺 · <b>{escape(video.title)}</b>",
        f"канал: {escape(video.author)}",
        "",
        "смотреть:",
        "<i>видео на месте, можно смотреть</i>",
    ]
    return _with_hashtags(lines, "#stonerhand #video", include_hashtags=include_hashtags)


def format_playlist_message(
    playlist: PlaylistMatch,
    *,
    include_hashtags: bool = True,
) -> str:
    lines = [
        "<b>плейлист найден</b>",
        f"🎛 · <b>{escape(playlist.title)}</b>",
        f"платформа: {escape(playlist.platform)}",
        "",
        "открывать:",
        "<i>плейлист на месте, можно нырять</i>",
    ]
    return _with_hashtags(lines, "#stonerhand #playlist", include_hashtags=include_hashtags)


def format_playlist_collection_message(
    playlists: list[PlaylistMatch],
    *,
    include_hashtags: bool = True,
) -> str:
    lines = ["<b>подборка плейлистов</b>", f"пунктов: {len(playlists)}", "", "сегодня в плейлистах:", ""]
    for index, playlist in enumerate(playlists, start=1):
        lines.append(f"{index}. 🎛 · <b>{escape(playlist.title)}</b>")

    lines.extend(
        [
            "",
            "выбирать:",
            "<i>выбирай, с какой пачки начать</i>",
        ]
    )
    return _with_hashtags(lines, "#stonerhand #collection #playlist", include_hashtags=include_hashtags)


def format_video_collection_message(
    videos: list[VideoMatch],
    *,
    include_hashtags: bool = True,
) -> str:
    lines = ["<b>видео-подборка</b>", f"пунктов: {len(videos)}", "", "сегодня на экране:", ""]
    for index, video in enumerate(videos, start=1):
        lines.append(f"{index}. 📺 · <b>{escape(video.title)}</b>")

    lines.extend(
        [
            "",
            "смотреть:",
            "<i>выбирай, что включить первым</i>",
        ]
    )
    return _with_hashtags(lines, "#stonerhand #collection #video", include_hashtags=include_hashtags)


def format_mixed_collection_message(
    tracks: list[TrackMatch],
    videos: list[VideoMatch],
    playlists: list[PlaylistMatch] | None = None,
    *,
    include_hashtags: bool = True,
) -> str:
    playlists = playlists or []
    seed = "|".join(
        [
            *(f"{track.artist}:{track.title}:{track.kind}" for track in tracks),
            *(f"{playlist.platform}:{playlist.title}:playlist" for playlist in playlists),
            *(f"{video.author}:{video.title}:video" for video in videos),
        ]
    )
    lines = [
        "<b>подборка найдена</b>",
        f"пунктов: {len(tracks) + len(playlists) + len(videos)}",
        "",
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

    for video in videos:
        lines.append(f"{index}. 📺 · <b>{escape(video.title)}</b>")
        index += 1

    lines.extend(
        [
            "",
            "выбирать:",
            f"<i>{escape(pick_phrase('collection_cta', seed))}</i>",
        ]
    )

    return _with_hashtags(
        lines,
        build_mixed_collection_hashtags(
            tracks,
            has_playlists=bool(playlists),
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
        "<b>подборка найдена</b>",
        f"пунктов: {len(tracks)}",
        "",
        pick_phrase("collection_intro", seed),
        "",
    ]

    for index, track in enumerate(tracks, start=1):
        emoji = pick_track_emoji(track)
        lines.append(f"{index}. {emoji} · {format_track_heading(track)}")

    lines.extend(
        [
            "",
            "выбирать:",
            f"<i>{escape(pick_phrase('collection_cta', seed))}</i>",
        ]
    )

    return _with_hashtags(lines, build_collection_hashtags(tracks), include_hashtags=include_hashtags)


def prepend_user_text(message_text: str, *, author_label: str | None = None) -> str:
    header = message_text.strip()
    if not header:
        return ""

    if author_label:
        return f"<blockquote>{escape(author_label)}: {escape(header)}</blockquote>\n\n"

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


def format_found_platforms(count: int) -> str:
    return f"найдено: {count} {_plural_ru(count, 'площадка', 'площадки', 'площадок')}"


def _plural_ru(count: int, one: str, few: str, many: str) -> str:
    last_two_digits = count % 100
    if 11 <= last_two_digits <= 14:
        return many

    last_digit = count % 10
    if last_digit == 1:
        return one
    if 2 <= last_digit <= 4:
        return few
    return many


def _with_hashtags(lines: list[str], hashtags: str, *, include_hashtags: bool) -> str:
    if include_hashtags:
        lines.extend(["", hashtags])

    return "\n".join(lines)


def build_mixed_collection_hashtags(
    tracks: list[TrackMatch],
    *,
    has_playlists: bool = False,
    has_videos: bool = True,
) -> str:
    hashtags = build_collection_hashtags(tracks).split()
    if has_playlists and "#playlist" not in hashtags:
        hashtags.append("#playlist")

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
