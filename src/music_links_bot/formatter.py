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


def format_track_message(track: TrackMatch) -> str:
    emoji = pick_track_emoji(track)
    seed = f"{track.artist}:{track.title}:{track.kind}"
    cta_key = {
        "album": "album_cta",
        "podcast": "podcast_cta",
    }.get(track.kind, "track_cta")

    return (
        f"{emoji} · {format_track_heading(track)}\n\n"
        f"<i>{escape(pick_phrase(cta_key, seed))}</i>\n\n"
        f"{build_auto_hashtags(track)}"
    )


def format_video_message(video: VideoMatch) -> str:
    return (
        f"📺 · <b>{escape(video.title)}</b>\n"
        f"канал: {escape(video.author)}\n\n"
        "<i>видео на месте, можно смотреть</i>\n\n"
        "#stonerhand #video"
    )


def format_playlist_message(playlist: PlaylistMatch) -> str:
    return (
        f"🎛 · <b>{escape(playlist.title)}</b>\n"
        f"платформа: {escape(playlist.platform)}\n\n"
        "<i>плейлист на месте, можно нырять</i>\n\n"
        "#stonerhand #playlist"
    )


def format_playlist_collection_message(playlists: list[PlaylistMatch]) -> str:
    lines = ["сегодня в плейлистах:", ""]
    for index, playlist in enumerate(playlists, start=1):
        lines.append(f"{index}. 🎛 · <b>{escape(playlist.title)}</b>")

    lines.extend(
        [
            "",
            "<i>выбирай, с какой пачки начать</i>",
            "",
            "#stonerhand #collection #playlist",
        ]
    )
    return "\n".join(lines)


def format_video_collection_message(videos: list[VideoMatch]) -> str:
    lines = ["сегодня на экране:", ""]
    for index, video in enumerate(videos, start=1):
        lines.append(f"{index}. 📺 · <b>{escape(video.title)}</b>")

    lines.extend(
        [
            "",
            "<i>выбирай, что включить первым</i>",
            "",
            "#stonerhand #collection #video",
        ]
    )
    return "\n".join(lines)


def format_mixed_collection_message(
    tracks: list[TrackMatch],
    videos: list[VideoMatch],
    playlists: list[PlaylistMatch] | None = None,
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
            f"<i>{escape(pick_phrase('collection_cta', seed))}</i>",
            "",
            build_mixed_collection_hashtags(
                tracks,
                has_playlists=bool(playlists),
                has_videos=bool(videos),
            ),
        ]
    )

    return "\n".join(lines)


def format_collection_message(tracks: list[TrackMatch]) -> str:
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
            "",
            build_collection_hashtags(tracks),
        ]
    )

    return "\n".join(lines)


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
