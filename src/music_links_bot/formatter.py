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
from music_links_bot.release_metadata import duration_label, duration_ms, metadata_url
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


def _list_number(index: int) -> str:
    """Aligned monospace numbers: 01, 02 … 10."""
    return f"<code>{index:02}</code>"


def format_track_heading(track: TrackMatch) -> str:
    artist = _display_text(track.artist, MAX_COLLECTION_TEXT_LENGTH)
    title = _display_text(track.title, MAX_COLLECTION_TEXT_LENGTH)
    if artist and title:
        return f"<b>{artist}</b> — {title}"
    return f"<b>{artist or title}</b>"


def format_release_heading(track: TrackMatch) -> str:
    """ "Artist — Title" in bold, a blank line, then the release details."""
    artist, title = _display_text(track.artist), _display_text(track.title)
    various_artists = track.artist.strip().casefold() in {
        "various artists",
        "разные исполнители",
    }
    if artist and not (track.kind == "album" and various_artists):
        heading = (
            f"<b>{_metadata_link(artist, track.artist_url, 'artist')} — {title}</b>"
        )
    else:
        heading = f"<b>{title}</b>"
    lines = []
    details = release_details(track)
    if details:
        lines.append(f"{release_emoji(track)} {escape(details)}")
    # Album membership is provider metadata, never inferred from the song title.
    if track.kind == "song" and track.album_title:
        album = _display_text(track.album_title)
        if album:
            label = "From the album" if resolve_lang(None) == "en" else "Из альбома"
            lines.append(
                f"💿 {label} «{_metadata_link(album, track.album_url, 'album')}»"
            )
    # A blank line keeps the title apart from the details under it.
    return "\n\n".join(filter(None, (heading, "\n".join(lines))))


def _metadata_link(label: str, url: str | None, kind: str) -> str:
    safe = metadata_url(url, kind)
    return f'<a href="{escape(safe, quote=True)}">{label}</a>' if safe else label


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
    from music_links_bot.video_kinds import video_kind, video_kind_label

    kind = video_kind(video)
    label = (
        ("Video" if resolve_lang(None) == "en" else "Видео")
        if kind == "video"
        else video_kind_label(kind).split(" ", 1)[1]
    )
    details = [label, "YouTube"]
    if video.author.strip():
        details.append(_display_text(video.author))
    lines = [
        f"<b>{_display_text(video.title)}</b>",
        "",
        f"{video_kind_emoji(video)} " + " · ".join(details),
    ]
    return _with_hashtags(
        lines, "#stonerhand #video", include_hashtags=include_hashtags
    )


def format_radio_message(radio: RadioMatch, *, include_hashtags: bool = True) -> str:
    lines = [
        f"<b>{_display_text(radio.title)}</b>",
        "",
        "📻 "
        + (
            f"{'Radio show' if resolve_lang(None) == 'en' else 'Радиошоу'} · {_display_text(radio.station)}"
            if radio.station == "Apple Music"
            else f"{'Radio' if resolve_lang(None) == 'en' else 'Радио'} · {_display_text(radio.station)}"
        ),
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
        f"<b>{_display_text(playlist.title)}</b>",
        "",
        f"🎛 {'Playlist' if resolve_lang(None) == 'en' else 'Плейлист'} · {_display_text(playlist.platform)}",
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
        f"<b>{_display_text(artist.title)}</b>",
        "",
        f"🧬 {'Artist' if resolve_lang(None) == 'en' else 'Исполнитель'} · {_display_text(artist.platform)}",
    ]
    return _with_hashtags(
        lines, "#stonerhand #artist", include_hashtags=include_hashtags
    )


def _collection_header(icon: str, title: str | None, counts: list[str]) -> list[str]:
    """Every collection opens the same way as a single release:

        🎶 Название
        Подборка · 2 трека · 1 видео

    A custom title takes the bold line; otherwise "Подборка" does and the
    details line carries only the counts.
    """
    label = "Collection" if resolve_lang(None) == "en" else "Подборка"
    details = " · ".join(counts)
    name = _display_text(title) if title else ""
    lines = [f"{icon} <b>{name or label}</b>"]
    if details:
        lines.append(f"{label} · {details}" if name else details)
    return [*lines, ""]


def _collection_item(index: int, icon: str, title: str) -> str:
    """ "01 · 🎛 Women of Punk": number, kind icon, plain title."""
    return (
        f"{_list_number(index)} · {icon} "
        f"{_display_text(title, MAX_COLLECTION_TEXT_LENGTH)}"
    )


def format_artist_collection_message(
    artists: list[ArtistMatch],
    *,
    include_hashtags: bool = True,
    title: str | None = None,
) -> str:
    lines = _collection_header("🧬", title, [count_label(len(artists), "artist")])
    for index, artist in enumerate(artists, start=1):
        lines.append(_collection_item(index, "🧬", artist.title))

    return _with_hashtags(
        lines, "#stonerhand #collection #artist", include_hashtags=include_hashtags
    )


def format_playlist_collection_message(
    playlists: list[PlaylistMatch],
    *,
    include_hashtags: bool = True,
    title: str | None = None,
) -> str:
    lines = _collection_header("🎛", title, [count_label(len(playlists), "playlist")])
    for index, playlist in enumerate(playlists, start=1):
        lines.append(_collection_item(index, "🎛", playlist.title))

    return _with_hashtags(
        lines, "#stonerhand #collection #playlist", include_hashtags=include_hashtags
    )


def format_video_collection_message(
    videos: list[VideoMatch],
    *,
    include_hashtags: bool = True,
    title: str | None = None,
) -> str:
    lines = _collection_header("📺", title, [count_label(len(videos), "video")])
    for index, video in enumerate(videos, start=1):
        lines.append(_collection_item(index, video_kind_emoji(video), video.title))

    return _with_hashtags(
        lines, "#stonerhand #collection #video", include_hashtags=include_hashtags
    )


def format_radio_collection_message(
    radios: list[RadioMatch],
    *,
    include_hashtags: bool = True,
    title: str | None = None,
) -> str:
    lines = _collection_header("📻", title, [count_label(len(radios), "radio")])
    for index, radio in enumerate(radios, start=1):
        lines.append(_collection_item(index, "📻", radio.title))

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
        and videos
        and not playlists
        and not artists
        and not radios
        and not title
    ):
        return format_track_videos_message(
            tracks[0],
            videos,
            include_hashtags=include_hashtags,
        )

    counts = [
        *([collection_composition(tracks)] if tracks else []),
        *[
            count_label(len(items), kind)
            for items, kind in (
                (playlists, "playlist"),
                (artists, "artist"),
                (radios, "radio"),
                (videos, "video"),
            )
            if items
        ],
    ]
    lines = _collection_header("🎶", title, counts)

    index = 1
    for track in tracks:
        emoji = pick_track_emoji(track)
        lines.append(f"{_list_number(index)} · {emoji} {format_track_heading(track)}")
        index += 1
    for items, icon in ((playlists, "🎛"), (artists, "🧬"), (radios, "📻")):
        for item in items:
            lines.append(_collection_item(index, icon, item.title))
            index += 1
    for video in videos:
        lines.append(_collection_item(index, video_kind_emoji(video), video.title))
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


def video_kind_emoji(video: VideoMatch) -> str:
    from music_links_bot.video_kinds import video_kind_emoji as emoji

    return emoji(video)


def format_track_video_pair_message(
    track: TrackMatch,
    video: VideoMatch,
    *,
    include_hashtags: bool = True,
) -> str:
    """A compact editorial layout for the most common mixed post."""
    return format_track_videos_message(
        track, [video], include_hashtags=include_hashtags
    )


_KIND_HEADINGS = {
    "clip": "клип",
    "live": "live",
    "lyric": "lyric video",
    "acoustic": "акустика",
    "visualizer": "визуализация",
    "audio": "аудио",
}
_KIND_HEADINGS_EN = {
    "clip": "music video",
    "live": "live",
    "lyric": "lyric video",
    "acoustic": "acoustic",
    "visualizer": "visualizer",
    "audio": "audio",
}


def format_track_videos_message(
    track: TrackMatch,
    videos: list[VideoMatch],
    *,
    include_hashtags: bool = True,
) -> str:
    """One release with its clips: what to listen to, then what to watch."""
    from music_links_bot.video_kinds import video_kind

    if resolve_lang(None) == "en":
        heading = (
            "Song + " + _KIND_HEADINGS_EN.get(video_kind(videos[0]), "video")
            if len(videos) == 1
            else f"Song + {len(videos)} videos"
        )
    elif len(videos) == 1:
        heading = "Песня + " + _KIND_HEADINGS.get(video_kind(videos[0]), "клип")
    else:
        heading = f"Песня + {len(videos)} видео"
    lines = [f"<b>{escape(heading)}</b>", "", f"🎧 · {format_track_heading(track)}"]
    for video in videos:
        video_heading = (
            f"<b>{_display_text(video.title, MAX_COLLECTION_TEXT_LENGTH)}</b>"
        )
        lines.append(f"{video_kind_emoji(video)} · {video_heading}")
    if len(videos) == 1 and videos[0].author:
        lines.append(
            f"   <i>{_display_text(videos[0].author, MAX_COLLECTION_TEXT_LENGTH)}</i>"
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
    lines: list[str] = []
    title_named_artist = False
    composition = escape(collection_composition(tracks)) if len(tracks) > 1 else ""
    shared_artist = (
        shared_collection_artist(tracks)
        if not any(section.strip() for section in (item_sections or []))
        else None
    )
    if title or not intro:
        # Like a single release: the name in bold, then what it is and how big.
        #   🎶 The Growlers
        #   Подборка · 8 треков
        # Generated titles ("Подборка · 2 релиза") already carry a count.
        label = "Collection" if resolve_lang(None) == "en" else "Подборка"
        counted = bool(title) and any(char.isdigit() for char in title)
        generated = counted and str(title).startswith(("Подборка", "Collection"))
        if shared_artist and (not title or generated):
            lines.append(f"🎶 <b>{_display_text(shared_artist)}</b>")
            details = _display_text(title) if title else f"{label} · {composition}"
        else:
            # A generated title ("Подборка · 3 релиза") splits into the label
            # and a details line, like every other post.
            name = _display_text(title) if title and not generated else ""
            counted = counted and not generated
            # "⚠️ Подборка · 3 из 4" already starts with its own icon.
            icon = "" if title and not title.lstrip()[:1].isalnum() else "🎶 "
            lines.append(f"{icon}<b>{name or label}</b>")
            details = (
                "" if counted else (f"{label} · {composition}" if name else composition)
            )
        if composition and details:
            lines.append(details)
        lines.append("")
        composition = ""
        title_named_artist = bool(shared_artist) and (not title or generated)
    if intro:
        lines.extend([_display_text(intro), ""])

    if composition:
        lines.extend([f"<i>{composition}</i>", ""])
    active_section = ""
    if shared_artist and not title_named_artist:
        # The heading names something else: keep the artist above the list.
        lines.append(f"<b>{_display_text(shared_artist)}</b>")
    groups = (
        _artist_runs(tracks)
        if not shared_artist
        and not any(section.strip() for section in (item_sections or []))
        else [""] * len(tracks)
    )
    # Group only when every item sits in a run; a half-grouped list reads as
    # two different styles ("NONCONS / 01 · Dance" next to "03 · The Growlers — …").
    if not all(groups):
        groups = [""] * len(tracks)
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
        group = groups[index - 1]
        previous = groups[index - 2] if index > 1 else ""
        if group and group != previous:
            # Several releases in a row by one artist: name them once.
            if lines and lines[-1]:
                lines.append("")
            lines.append(f"<b>{_display_text(group, MAX_COLLECTION_TEXT_LENGTH)}</b>")
        elif previous and not group:
            lines.append("")
        title_text = _display_text(
            compact_release_title(track.title),
            MAX_COLLECTION_TEXT_LENGTH,
        )
        number = _list_number(index)
        if shared_artist or group:
            lines.append(f"{number} · {title_text}")
        else:
            artist = _display_text(track.artist, MAX_COLLECTION_TEXT_LENGTH)
            lines.append(f"{number} · <b>{artist}</b> — {title_text}")
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


def _artist_runs(tracks: list[TrackMatch]) -> list[str]:
    """The artist of each item that sits in a run of 2+ by that artist, else ""."""
    keys = [" ".join(track.artist.split()).casefold() for track in tracks]
    runs = [""] * len(tracks)
    start = 0
    while start < len(tracks):
        end = start
        while end + 1 < len(tracks) and keys[start] and keys[end + 1] == keys[start]:
            end += 1
        if end > start:
            runs[start : end + 1] = [tracks[start].artist] * (end - start + 1)
        start = end + 1
    return runs


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
            "playlist": "playlist",
            "artist": "artist",
            "radio": "radio show",
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
        "playlist": ("плейлист", "плейлиста", "плейлистов"),
        "artist": ("артист", "артиста", "артистов"),
        "radio": ("радиошоу", "радиошоу", "радиошоу"),
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
    if track.kind == "album" and (total := duration_ms(track.duration_ms)):
        # Albums read better in minutes: "63 мин", not "1:03:00".
        minutes = max(1, round(total / 60000))
        details.append(
            f"{minutes} min" if resolve_lang(None) == "en" else f"{minutes} мин"
        )
    elif duration := duration_label(track.duration_ms):
        details.append(duration)
    return " · ".join(details)
