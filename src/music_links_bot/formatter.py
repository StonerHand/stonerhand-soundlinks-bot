from __future__ import annotations

from html import escape
import hashlib

from music_links_bot.models import TrackMatch
from music_links_bot.phrases import pick_phrase

TRACK_EMOJIS = ("🎵", "🎧", "🎶", "🔊", "📻")


def pick_track_emoji(track: TrackMatch) -> str:
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

    return (
        f"{emoji} · {format_track_heading(track)}\n\n"
        f"<i>{escape(pick_phrase('listen_cta', seed))}</i>\n\n"
        f"{build_auto_hashtags(track)}"
    )


def format_collection_message(tracks: list[TrackMatch]) -> str:
    seed = "|".join(f"{track.artist}:{track.title}:{track.kind}" for track in tracks)
    lines = [
        pick_phrase("collection_title", seed),
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
        return f"{escape(author_label)}: {escape(header)}\n\n"

    return f"{escape(header)}\n\n"


def build_auto_hashtags(track: TrackMatch) -> str:
    if track.kind == "album":
        return "#stonerhand #album"

    return "#stonerhand #track"


def build_collection_hashtags(tracks: list[TrackMatch]) -> str:
    hashtags = ["#stonerhand", "#collection"]
    kinds = {track.kind for track in tracks}

    if "track" in kinds or "song" in kinds:
        hashtags.append("#track")

    if "album" in kinds:
        hashtags.append("#album")

    return " ".join(hashtags)
