from __future__ import annotations

import re
from html import escape, unescape

from music_links_bot.bot_builder import fit_telegram_html
from music_links_bot.i18n import resolve_lang
from music_links_bot.models import (
    ArtistMatch,
    PlaylistMatch,
    RadioMatch,
    TrackMatch,
    VideoMatch,
)
from music_links_bot.release_preferences import (
    current_presentation,
    release_preference_key,
)
from music_links_bot.release_presentation import (
    compact_release_title,
    release_emoji,
    shared_collection_artist,
)
from music_links_bot.release_tags import (
    build_auto_hashtags as build_auto_hashtags,
    build_collection_hashtags as build_collection_hashtags,
    build_mixed_collection_hashtags as build_mixed_collection_hashtags,
    genre_hashtags as _genre_hashtags,
    release_type,
)
from music_links_bot.telegram_text import telegram_text_length

MAX_METADATA_TEXT_LENGTH = 180
MAX_COLLECTION_TEXT_LENGTH = 96


def genre_hashtags(genre: str | None, *, limit: int = 2) -> list[str]:
    """Compatibility entry point for callers of the original formatter."""
    return _genre_hashtags(genre, limit=limit)


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
    artist, title = _display_text(track.artist), _display_text(track.title)
    lines = [f"{release_emoji(track)} · <b>{title}</b>"]
    if artist:
        lines.append(artist)
    details = release_details(track)
    if details:
        lines.extend(["", escape(details)])
    # Album membership is provider metadata, never inferred from the song title.
    if track.kind == "song" and track.album_title:
        album = _display_text(track.album_title)
        if album:
            label = "From the album" if resolve_lang(None) == "en" else "Из альбома"
            lines.append(f"💿 {label} «{album}»")
    return "\n".join(lines)


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
        f"<b>{_display_text(video.title)}</b>",
        f"<i>{'Source' if resolve_lang(None) == 'en' else 'Источник'}: {_display_text(video.author)}</i>",
    ]
    return _with_hashtags(
        lines, "#stonerhand #video", include_hashtags=include_hashtags
    )


def format_radio_message(radio: RadioMatch, *, include_hashtags: bool = True) -> str:
    lines = [
        f"📻 · <b>{_display_text(radio.title)}</b>",
        f"станция: {_display_text(radio.station)}",
    ]
    return _with_hashtags(
        lines, "#stonerhand #radio", include_hashtags=include_hashtags
    )


def format_playlist_message(
    playlist: PlaylistMatch,
    *,
    include_hashtags: bool = True,
) -> str:
    lines = [
        f"🎛 · <b>{_display_text(playlist.title)}</b>",
        f"платформа: {_display_text(playlist.platform)}",
    ]
    return _with_hashtags(
        lines, "#stonerhand #playlist", include_hashtags=include_hashtags
    )


def format_artist_message(
    artist: ArtistMatch,
    *,
    include_hashtags: bool = True,
) -> str:
    lines = [
        f"🧬 · <b>{_display_text(artist.title)}</b>",
        f"профиль: {_display_text(artist.platform)}",
    ]
    return _with_hashtags(
        lines, "#stonerhand #artist", include_hashtags=include_hashtags
    )


def format_artist_collection_message(
    artists: list[ArtistMatch],
    *,
    include_hashtags: bool = True,
    title: str | None = None,
) -> str:
    lines = [f"<b>{escape(title or 'Артисты')}</b>", ""]
    for index, artist in enumerate(artists, start=1):
        heading = f"<b>{_display_text(artist.title, MAX_COLLECTION_TEXT_LENGTH)}</b>"
        lines.append(f"{index}. 🧬 · {heading}")

    return _with_hashtags(
        lines, "#stonerhand #collection #artist", include_hashtags=include_hashtags
    )


def format_playlist_collection_message(
    playlists: list[PlaylistMatch],
    *,
    include_hashtags: bool = True,
    title: str | None = None,
) -> str:
    lines = [f"<b>{escape(title or 'Плейлисты')}</b>", ""]
    for index, playlist in enumerate(playlists, start=1):
        heading = f"<b>{_display_text(playlist.title, MAX_COLLECTION_TEXT_LENGTH)}</b>"
        lines.append(f"{index}. 🎛 · {heading}")

    return _with_hashtags(
        lines, "#stonerhand #collection #playlist", include_hashtags=include_hashtags
    )


def format_video_collection_message(
    videos: list[VideoMatch],
    *,
    include_hashtags: bool = True,
    title: str | None = None,
) -> str:
    lines = [f"<b>{escape(title or 'Видео')}</b>", ""]
    for index, video in enumerate(videos, start=1):
        heading = f"<b>{_display_text(video.title, MAX_COLLECTION_TEXT_LENGTH)}</b>"
        lines.append(f"{index}. 📺 · {heading}")

    return _with_hashtags(
        lines, "#stonerhand #collection #video", include_hashtags=include_hashtags
    )


def format_radio_collection_message(
    radios: list[RadioMatch],
    *,
    include_hashtags: bool = True,
    title: str | None = None,
) -> str:
    lines = [f"<b>{escape(title or 'Радио')}</b>", ""]
    for index, radio in enumerate(radios, start=1):
        heading = f"<b>{_display_text(radio.title, MAX_COLLECTION_TEXT_LENGTH)}</b>"
        lines.append(f"{index}. 📻 · {heading}")

    return _with_hashtags(
        lines, "#stonerhand #collection #radio", include_hashtags=include_hashtags
    )


def format_mixed_collection_message(
    tracks: list[TrackMatch],
    videos: list[VideoMatch],
    playlists: list[PlaylistMatch] | None = None,
    artists: list[ArtistMatch] | None = None,
    radios: list[RadioMatch] | None = None,
    *,
    include_hashtags: bool = True,
    title: str | None = None,
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
        and not title
    ):
        return format_track_video_pair_message(
            tracks[0],
            videos[0],
            include_hashtags=include_hashtags,
        )

    lines = [f"<b>{escape(title or 'Подборка')}</b>", ""]

    index = 1
    for track in tracks:
        emoji = pick_track_emoji(track)
        lines.append(f"{index}. {emoji} · {format_track_heading(track)}")
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
        lines.append(f"{index}. 📻 · {heading}")
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
        lines.append(
            f"   <i>{_display_text(video.author, MAX_COLLECTION_TEXT_LENGTH)}</i>"
        )
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
        lines.extend([f"<b>{_display_text(title)}</b>", ""])
    elif not intro:
        lines.extend(["<b>Подборка</b>", ""])
    if intro:
        lines.extend([_display_text(intro), ""])

    presentation = current_presentation.get()
    annotations = [
        presentation.annotations.get(release_preference_key(track), {})
        for track in tracks
    ]
    if item_notes is None:
        item_notes = [item.get("note", "") for item in annotations]
    if item_sections is None:
        item_sections = [
            item.get("section")
            or (
                track.artist
                if presentation.grouping == "artist"
                else (
                    track.album_title or (track.title if track.kind == "album" else "")
                )
                if presentation.grouping == "album"
                else ""
            )
            for track, item in zip(tracks, annotations, strict=True)
        ]
    if len(tracks) > 1:
        lines.extend([f"<i>{escape(collection_composition(tracks))}</i>", ""])
    active_section = ""
    shared_artist = (
        shared_collection_artist(tracks)
        if not any(section.strip() for section in (item_sections or []))
        else None
    )
    if shared_artist:
        lines.append(f"<b>{_display_text(shared_artist)}</b>")
    for index, track in enumerate(tracks, start=1):
        section = (
            item_sections[index - 1].strip()
            if item_sections and index <= len(item_sections)
            else ""
        )
        if section and section != active_section:
            if lines and lines[-1]:
                lines.append("")
            lines.append(f"<b>{_display_text(section, 64)}</b>")
            active_section = section
        title_text = _display_text(
            compact_release_title(track.title),
            MAX_COLLECTION_TEXT_LENGTH,
        )
        if shared_artist:
            lines.append(f"{index}. {title_text}")
        else:
            artist = _display_text(track.artist, MAX_COLLECTION_TEXT_LENGTH)
            lines.append(f"{index}. <b>{artist}</b> — {title_text}")
        note = (
            item_notes[index - 1].strip()
            if item_notes and index <= len(item_notes)
            else ""
        )
        if note:
            lines.append(f"   <i>↳ {escape(note)}</i>")

    if outro:
        lines.extend(["", f"<i>{_display_text(outro)}</i>"])

    return _fit_collection_message(
        _with_hashtags(
            lines,
            hashtags if hashtags is not None else build_collection_hashtags(tracks),
            include_hashtags=include_hashtags,
        )
    )


def _fit_collection_message(value: str) -> str:
    """Shorten overlong lines proportionally; never drop numbered entries."""
    lines = value.split("\n")
    lengths = [
        telegram_text_length(unescape(re.sub(r"<[^>]*>", "", line))) for line in lines
    ]
    budget = 4096 - len(lines) + 1
    if sum(lengths) <= budget:
        return value
    note_indices = [
        index for index, line in enumerate(lines) if line.startswith("   <i>↳ ")
    ]
    notes_size = sum(lengths[index] for index in note_indices)
    fixed_size = sum(lengths) - notes_size
    if notes_size and fixed_size < budget:
        ratio = (budget - fixed_size) / notes_size
        for index in note_indices:
            lines[index] = (
                "<i>"
                + fit_telegram_html(lines[index], int(lengths[index] * ratio))
                + "</i>"
            )
        return "\n".join(lines)
    # Keep the complete type/tag footer, even on a maximal ten-item collection.
    fixed = sum(
        size for line, size in zip(lines, lengths, strict=True) if line.startswith("#")
    )
    ratio = max(0, (budget - fixed) / max(1, sum(lengths) - fixed))
    return "\n".join(
        line if line.startswith("#") else fit_telegram_html(line, int(size * ratio))
        for line, size in zip(lines, lengths, strict=True)
    )


def prepend_user_text(message_text: str, *, author_label: str | None = None) -> str:
    header = message_text.strip()
    if not header:
        return ""

    if author_label:
        return f"<blockquote>{escape(author_label)}:\n{escape(header)}</blockquote>\n\n"

    return f"<blockquote>{escape(header)}</blockquote>\n\n"


def prepend_user_html(message_html: str, *, author_label: str | None = None) -> str:
    header = message_html.strip()
    if not header:
        return ""

    if author_label:
        return f"<blockquote>{escape(author_label)}:\n{header}</blockquote>\n\n"

    return f"<blockquote>{header}</blockquote>\n\n"


def _display_text(value: str, max_length: int = MAX_METADATA_TEXT_LENGTH) -> str:
    normalized = " ".join(value.split())
    if telegram_text_length(normalized) > max_length:
        normalized = (
            normalized.encode("utf-16-le")[: (max_length - 1) * 2]
            .decode("utf-16-le", errors="ignore")
            .rstrip()
            + "…"
        )

    return escape(normalized)


def _with_hashtags(lines: list[str], hashtags: str, *, include_hashtags: bool) -> str:
    if include_hashtags and hashtags:
        lines.extend(["", hashtags])

    return "\n".join(lines)


def count_label(count: int, kind: str) -> str:
    if resolve_lang(None) == "en":
        singular = {
            "track": "track",
            "album": "album",
            "ep": "EP",
            "single": "single",
            "compilation": "compilation",
            "soundtrack": "soundtrack",
            "video": "video",
            "podcast": "podcast",
        }.get(kind, "release")
        return f"{count} {singular}{'' if count == 1 else 's'}"
    forms = {
        "track": ("трек", "трека", "треков"),
        "album": ("альбом", "альбома", "альбомов"),
        "ep": ("EP", "EP", "EP"),
        "single": ("сингл", "сингла", "синглов"),
        "compilation": ("сборник", "сборника", "сборников"),
        "soundtrack": ("саундтрек", "саундтрека", "саундтреков"),
        "video": ("видео", "видео", "видео"),
        "podcast": ("подкаст", "подкаста", "подкастов"),
    }.get(kind, ("релиз", "релиза", "релизов"))
    form = (
        0
        if count % 10 == 1 and count % 100 != 11
        else 1
        if count % 10 in {2, 3, 4} and count % 100 not in {12, 13, 14}
        else 2
    )
    return f"{count} {forms[form]}"


def collection_composition(tracks: list[TrackMatch]) -> str:
    counts: dict[str, int] = {}
    for track in tracks:
        kind = release_type(track)
        counts[kind] = counts.get(kind, 0) + 1
    return " · ".join(count_label(count, kind) for kind, count in counts.items())


def release_details(track: TrackMatch) -> str:
    details = []
    if track.kind == "album":
        kind = release_type(track)
        ru = {
            "album": "Альбом",
            "ep": "EP",
            "single": "Сингл",
            "compilation": "Сборник",
            "soundtrack": "Саундтрек",
        }
        details.append(
            kind.upper()
            if kind == "ep"
            else kind.capitalize()
            if resolve_lang(None) == "en"
            else ru.get(kind, "Альбом")
        )
    else:
        en, ru = {
            "song": ("Track", "Трек"),
            "audio": ("Audio", "Аудио"),
            "video": ("Video", "Видео"),
            "podcast": ("Podcast", "Подкаст"),
        }.get(track.kind, ("Release", "Релиз"))
        details.append(en if resolve_lang(None) == "en" else ru)
    if track.release_year and re.fullmatch(r"(?:19|20)\d{2}", str(track.release_year)):
        details.append(str(track.release_year))
    if (
        track.kind == "album"
        and isinstance(track.track_count, int)
        and 0 < track.track_count <= 9999
    ):
        details.append(count_label(track.track_count, "track"))
    return " · ".join(details)
