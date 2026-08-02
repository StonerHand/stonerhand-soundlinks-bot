from __future__ import annotations

from html import escape
import re

from music_links_bot.models import (
    ArtistMatch,
    PlaylistMatch,
    RadioMatch,
    TrackMatch,
    VideoMatch,
)
from music_links_bot.release_presentation import release_emoji

MAX_METADATA_TEXT_LENGTH = 180
MAX_COLLECTION_TEXT_LENGTH = 96


def pick_track_emoji(track: TrackMatch) -> str:
    """Backward-compatible alias for the shared presentation model."""
    return release_emoji(track)


def format_track_label(track: TrackMatch) -> str:
    return f"{_display_text(track.artist)} - {_display_text(track.title)}"


def format_track_heading(track: TrackMatch) -> str:
    artist = _display_text(track.artist, MAX_COLLECTION_TEXT_LENGTH)
    title = _display_text(track.title, MAX_COLLECTION_TEXT_LENGTH)
    if artist and title:
        return f"<b>{artist}</b> — {title}"
    return f"<b>{artist or title}</b>"


def format_release_heading(track: TrackMatch) -> str:
    return (
        f"{pick_track_emoji(track)} · <b>{_display_text(track.artist)}</b>\n"
        f"{_display_text(track.title)}"
    )


def format_track_message(
    track: TrackMatch,
    *,
    include_hashtags: bool = True,
    hashtags: str | None = None,
) -> str:
    return _with_hashtags(
        [format_release_heading(track)],
        hashtags if hashtags is not None else build_auto_hashtags(track),
        include_hashtags=include_hashtags,
    )


def format_video_message(video: VideoMatch, *, include_hashtags: bool = True) -> str:
    lines = [
        f"📺 · <b>{_display_text(video.title)}</b>",
        f"канал: {_display_text(video.author)}",
    ]
    return _with_hashtags(lines, "#stonerhand #video", include_hashtags=include_hashtags)


def format_radio_message(radio: RadioMatch, *, include_hashtags: bool = True) -> str:
    lines = [
        f"📡 · <b>{_display_text(radio.title)}</b>",
        f"станция: {_display_text(radio.station)}",
    ]
    return _with_hashtags(lines, "#stonerhand #radio", include_hashtags=include_hashtags)


def format_playlist_message(
    playlist: PlaylistMatch,
    *,
    include_hashtags: bool = True,
) -> str:
    lines = [
        f"🎛 · <b>{_display_text(playlist.title)}</b>",
        f"платформа: {_display_text(playlist.platform)}",
    ]
    return _with_hashtags(lines, "#stonerhand #playlist", include_hashtags=include_hashtags)


def format_artist_message(
    artist: ArtistMatch,
    *,
    include_hashtags: bool = True,
) -> str:
    lines = [
        f"🧬 · <b>{_display_text(artist.title)}</b>",
        f"профиль: {_display_text(artist.platform)}",
    ]
    return _with_hashtags(lines, "#stonerhand #artist", include_hashtags=include_hashtags)


def format_artist_collection_message(
    artists: list[ArtistMatch],
    *,
    include_hashtags: bool = True,
) -> str:
    lines = ["<b>Артисты</b>", ""]
    for index, artist in enumerate(artists, start=1):
        heading = f"<b>{_display_text(artist.title, MAX_COLLECTION_TEXT_LENGTH)}</b>"
        lines.append(f"{index}. 🧬 · {heading}")

    return _with_hashtags(lines, "#stonerhand #collection #artist", include_hashtags=include_hashtags)


def format_playlist_collection_message(
    playlists: list[PlaylistMatch],
    *,
    include_hashtags: bool = True,
) -> str:
    lines = ["<b>Плейлисты</b>", ""]
    for index, playlist in enumerate(playlists, start=1):
        heading = f"<b>{_display_text(playlist.title, MAX_COLLECTION_TEXT_LENGTH)}</b>"
        lines.append(f"{index}. 🎛 · {heading}")

    return _with_hashtags(lines, "#stonerhand #collection #playlist", include_hashtags=include_hashtags)


def format_video_collection_message(
    videos: list[VideoMatch],
    *,
    include_hashtags: bool = True,
) -> str:
    lines = ["<b>Видео</b>", ""]
    for index, video in enumerate(videos, start=1):
        heading = f"<b>{_display_text(video.title, MAX_COLLECTION_TEXT_LENGTH)}</b>"
        lines.append(f"{index}. 📺 · {heading}")

    return _with_hashtags(lines, "#stonerhand #collection #video", include_hashtags=include_hashtags)


def format_radio_collection_message(
    radios: list[RadioMatch],
    *,
    include_hashtags: bool = True,
) -> str:
    lines = ["<b>Радио</b>", ""]
    for index, radio in enumerate(radios, start=1):
        heading = f"<b>{_display_text(radio.title, MAX_COLLECTION_TEXT_LENGTH)}</b>"
        lines.append(f"{index}. 📡 · {heading}")

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
    if (
        len(tracks) == 1
        and len(videos) == 1
        and not playlists
        and not artists
        and not radios
    ):
        return format_track_video_pair_message(
            tracks[0],
            videos[0],
            include_hashtags=include_hashtags,
        )

    lines = ["<b>Подборка</b>", ""]

    index = 1
    for track in tracks:
        emoji = pick_track_emoji(track)
        lines.append(
            f"{index}. {emoji} · {format_track_heading(track)}"
        )
        index += 1

    for playlist in playlists:
        heading = f"<b>{_display_text(playlist.title, MAX_COLLECTION_TEXT_LENGTH)}</b>"
        lines.append(f"{index}. 🎛 · {heading}")
        index += 1

    for artist in artists:
        heading = f"<b>{_display_text(artist.title, MAX_COLLECTION_TEXT_LENGTH)}</b>"
        lines.append(f"{index}. 🧬 · {heading}")
        index += 1

    for radio in radios:
        heading = f"<b>{_display_text(radio.title, MAX_COLLECTION_TEXT_LENGTH)}</b>"
        lines.append(f"{index}. 📡 · {heading}")
        index += 1

    for video in videos:
        heading = f"<b>{_display_text(video.title, MAX_COLLECTION_TEXT_LENGTH)}</b>"
        lines.append(f"{index}. 📺 · {heading}")
        index += 1

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


def format_track_video_pair_message(
    track: TrackMatch,
    video: VideoMatch,
    *,
    include_hashtags: bool = True,
) -> str:
    """A compact editorial layout for the most common mixed post."""
    track_heading = format_track_heading(track)
    video_heading = f"<b>{_display_text(video.title, MAX_COLLECTION_TEXT_LENGTH)}</b>"
    lines = [
        "<b>Песня + клип</b>",
        "",
        f"🎧 · {track_heading}",
        f"📺 · {video_heading}",
    ]
    if video.author:
        lines.append(f"   <i>{_display_text(video.author, MAX_COLLECTION_TEXT_LENGTH)}</i>")
    return _with_hashtags(
        lines,
        build_mixed_collection_hashtags([track], has_videos=True),
        include_hashtags=include_hashtags,
    )


def format_collection_message(
    tracks: list[TrackMatch],
    *,
    include_hashtags: bool = True,
    title: str | None = None,
    intro: str | None = None,
    outro: str | None = None,
    hashtags: str | None = None,
    item_notes: list[str] | None = None,
    item_sections: list[str] | None = None,
) -> str:
    if (
        len(tracks) == 2
        and not any((title, intro, outro, item_notes, item_sections))
        and {track.kind for track in tracks} == {"song", "video"}
    ):
        song = next(track for track in tracks if track.kind == "song")
        video_track = next(track for track in tracks if track.kind == "video")
        return format_track_video_pair_message(
            song,
            VideoMatch(
                title=video_track.title,
                author=video_track.artist,
                url=video_track.page_url or "",
                thumbnail_url=video_track.thumbnail_url,
            ),
            include_hashtags=include_hashtags,
        )

    lines: list[str] = []
    if title:
        lines.extend([f"<b>{escape(title)}</b>", ""])
    elif not intro:
        lines.extend(["<b>Подборка</b>", ""])
    if intro:
        lines.extend([escape(intro), ""])

    active_section = ""
    for index, track in enumerate(tracks, start=1):
        section = (
            item_sections[index - 1].strip()
            if item_sections and index <= len(item_sections)
            else ""
        )
        if section and section != active_section:
            if lines and lines[-1]:
                lines.append("")
            lines.append(f"<b>{escape(section)}</b>")
            active_section = section
        emoji = pick_track_emoji(track)
        lines.append(
            f"{index}. {emoji} · {format_track_heading(track)}"
        )
        note = (
            item_notes[index - 1].strip()
            if item_notes and index <= len(item_notes)
            else ""
        )
        if note:
            lines.append(f"   <i>↳ {escape(note)}</i>")

    if outro:
        lines.extend(["", f"<i>{escape(outro)}</i>"])

    return _with_hashtags(
        lines,
        hashtags if hashtags is not None else build_collection_hashtags(tracks),
        include_hashtags=include_hashtags,
    )


def prepend_user_text(message_text: str, *, author_label: str | None = None) -> str:
    header = message_text.strip()
    if not header:
        return ""

    if author_label:
        return (
            f"<blockquote>{escape(author_label)}:\n"
            f"{escape(header)}</blockquote>\n\n"
        )

    return f"<blockquote>{escape(header)}</blockquote>\n\n"


def prepend_user_html(message_html: str, *, author_label: str | None = None) -> str:
    header = message_html.strip()
    if not header:
        return ""

    if author_label:
        return (
            f"<blockquote>{escape(author_label)}:\n"
            f"{header}</blockquote>\n\n"
        )

    return f"<blockquote>{header}</blockquote>\n\n"


def _display_text(value: str, max_length: int = MAX_METADATA_TEXT_LENGTH) -> str:
    normalized = " ".join(value.split())
    if len(normalized) > max_length:
        normalized = normalized[: max_length - 1].rstrip() + "…"

    return escape(normalized)


def build_auto_hashtags(track: TrackMatch) -> str:
    hashtags = ["#stonerhand"]

    if track.kind == "video":
        hashtags.append("#video")
        return " ".join(hashtags[:3])

    if track.kind == "podcast":
        hashtags.append("#podcast")
        if track.release_format == "show":
            hashtags.append("#show")
        return " ".join(hashtags[:3])

    if track.kind == "album":
        hashtags.append("#album")
        if track.release_format == "ep":
            hashtags.append("#ep")
        elif track.release_format == "single":
            hashtags.append("#single")
        hashtags.extend(genre_hashtags(track.genre))
        return " ".join(hashtags[:3])

    hashtags.append("#track")
    if track.release_format == "single":
        hashtags.append("#single")
    hashtags.extend(genre_hashtags(track.genre))

    return " ".join(hashtags[:3])


def genre_hashtags(genre: str | None, *, limit: int = 2) -> list[str]:
    """Turns an iTunes genre like "Hip-Hop/Rap" into ["#hiphop", "#rap"]."""
    if not genre:
        return []

    tags: list[str] = []
    for part in re.split(r"[/,]", genre.replace("&", "n")):
        slug = re.sub(r"[^a-z0-9а-яё]", "", part.casefold())
        if slug and slug not in {"music", "музыка"} and f"#{slug}" not in tags:
            tags.append(f"#{slug}")

        if len(tags) >= limit:
            break

    return tags


def _with_hashtags(lines: list[str], hashtags: str, *, include_hashtags: bool) -> str:
    if include_hashtags:
        lines.extend(["", hashtags])

    return "\n".join(lines)


def build_mixed_collection_hashtags(
    tracks: list[TrackMatch],
    *,
    has_playlists: bool = False,
    has_artists: bool = False,
    has_radios: bool = False,
    has_videos: bool = True,
) -> str:
    hashtags = ["#stonerhand"]
    for tag in build_collection_hashtags(tracks).split():
        if tag not in {"#stonerhand", "#collection"} and tag not in hashtags:
            hashtags.append(tag)
    if has_playlists and "#playlist" not in hashtags:
        hashtags.append("#playlist")

    if has_artists and "#artist" not in hashtags:
        hashtags.append("#artist")

    if has_radios and "#radio" not in hashtags:
        hashtags.append("#radio")

    if has_videos and "#video" not in hashtags:
        hashtags.append("#video")

    hashtags.append("#collection")
    return " ".join(hashtags[:3])


def build_collection_hashtags(tracks: list[TrackMatch]) -> str:
    hashtags = ["#stonerhand"]
    kinds = {track.kind for track in tracks}
    formats = {track.release_format for track in tracks if track.release_format}

    if "track" in kinds or "song" in kinds:
        hashtags.append("#track")

    if "album" in kinds:
        hashtags.append("#album")

    if "podcast" in kinds:
        hashtags.append("#podcast")

    if "video" in kinds:
        hashtags.append("#video")

    if "show" in formats:
        hashtags.append("#show")

    if "single" in formats:
        hashtags.append("#single")

    if "ep" in formats:
        hashtags.append("#ep")

    hashtags.append("#collection")
    return " ".join(hashtags[:3])
