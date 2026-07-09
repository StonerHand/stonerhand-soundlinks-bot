from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from typing import Any

from music_links_bot.models import (
    ArtistMatch,
    PlaylistMatch,
    RadioMatch,
    TrackMatch,
    VideoMatch,
)


def _default_stats_path() -> Path:
    configured_path = os.getenv("STATS_PATH", "").strip()
    if configured_path:
        return Path(configured_path)

    if os.getenv("VERCEL"):
        return Path("/tmp/stonerhand_stats.json")

    return Path("data/stats.json")


STATS_PATH = _default_stats_path()
SUPPORTED_KINDS = ("song", "album", "podcast")
STATS_LOCK = Lock()
StatsData = dict[str, Any]


def load_stats(path: Path = STATS_PATH) -> StatsData:
    if not path.exists():
        return _empty_stats()

    try:
        raw_stats = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_stats()

    if not isinstance(raw_stats, dict):
        return _empty_stats()

    stats = _empty_stats()
    for key in (
        "posts",
        "song",
        "album",
        "podcast",
        "videos",
        "radios",
        "playlists",
        "artists",
        "collections",
    ):
        value = raw_stats.get(key)
        if isinstance(value, int) and value >= 0:
            stats[key] = value

    stats["users"] = _clean_counter_map(raw_stats.get("users"))
    stats["chats"] = _clean_counter_map(raw_stats.get("chats"))
    return stats


def record_matches(
    matches: list[TrackMatch],
    path: Path = STATS_PATH,
    *,
    user: dict[str, object] | None = None,
    chat: dict[str, object] | None = None,
) -> StatsData:
    return _record_activity(
        path,
        matches=matches,
        video_count=0,
        radio_count=0,
        playlist_count=0,
        artist_count=0,
        user=user,
        chat=chat,
    )


def record_videos(
    videos: list[VideoMatch],
    path: Path = STATS_PATH,
    *,
    user: dict[str, object] | None = None,
    chat: dict[str, object] | None = None,
) -> StatsData:
    return _record_activity(
        path,
        matches=[],
        video_count=len(videos),
        radio_count=0,
        playlist_count=0,
        artist_count=0,
        user=user,
        chat=chat,
    )


def record_radios(
    radios: list[RadioMatch],
    path: Path = STATS_PATH,
    *,
    user: dict[str, object] | None = None,
    chat: dict[str, object] | None = None,
) -> StatsData:
    return _record_activity(
        path,
        matches=[],
        video_count=0,
        radio_count=len(radios),
        playlist_count=0,
        artist_count=0,
        user=user,
        chat=chat,
    )


def record_playlists(
    playlists: list[PlaylistMatch],
    path: Path = STATS_PATH,
    *,
    user: dict[str, object] | None = None,
    chat: dict[str, object] | None = None,
) -> StatsData:
    return _record_activity(
        path,
        matches=[],
        video_count=0,
        radio_count=0,
        playlist_count=len(playlists),
        artist_count=0,
        user=user,
        chat=chat,
    )


def record_artists(
    artists: list[ArtistMatch],
    path: Path = STATS_PATH,
    *,
    user: dict[str, object] | None = None,
    chat: dict[str, object] | None = None,
) -> StatsData:
    return _record_activity(
        path,
        matches=[],
        video_count=0,
        radio_count=0,
        playlist_count=0,
        artist_count=len(artists),
        user=user,
        chat=chat,
    )


def record_mixed(
    matches: list[TrackMatch],
    videos: list[VideoMatch],
    playlists: list[PlaylistMatch] | None = None,
    path: Path = STATS_PATH,
    *,
    artists: list[ArtistMatch] | None = None,
    radios: list[RadioMatch] | None = None,
    user: dict[str, object] | None = None,
    chat: dict[str, object] | None = None,
) -> StatsData:
    return _record_activity(
        path,
        matches=matches,
        video_count=len(videos),
        radio_count=len(radios or []),
        playlist_count=len(playlists or []),
        artist_count=len(artists or []),
        user=user,
        chat=chat,
    )


def _record_activity(
    path: Path,
    *,
    matches: list[TrackMatch],
    video_count: int,
    radio_count: int,
    playlist_count: int,
    artist_count: int,
    user: dict[str, object] | None,
    chat: dict[str, object] | None,
) -> StatsData:
    with STATS_LOCK:
        stats = load_stats(path)
        stats["posts"] += 1
        stats["videos"] += video_count
        stats["radios"] += radio_count
        stats["playlists"] += playlist_count
        stats["artists"] += artist_count

        item_count = (
            len(matches)
            + video_count
            + radio_count
            + playlist_count
            + artist_count
        )
        if item_count > 1:
            stats["collections"] += 1

        for match in matches:
            stats[match.kind if match.kind in SUPPORTED_KINDS else "song"] += 1

        if user:
            _record_counter(stats["users"], user)

        if chat:
            _record_counter(stats["chats"], chat)

        _write_stats(path, stats)
        return stats


def merge_stats(base: StatsData, other: object) -> StatsData:
    """Merges two stats snapshots (e.g. the local file and the Redis blob).

    Counters diverge across serverless instances, so the merged view takes the
    maximum of each counter and unions the user/chat maps entry by entry.
    """
    if not isinstance(other, dict):
        return base

    merged = _empty_stats()
    for key in (
        "posts",
        "song",
        "album",
        "podcast",
        "videos",
        "radios",
        "playlists",
        "artists",
        "collections",
    ):
        base_value = base.get(key, 0)
        other_value = other.get(key, 0)
        merged[key] = max(
            base_value if isinstance(base_value, int) else 0,
            other_value if isinstance(other_value, int) else 0,
        )

    for map_key in ("users", "chats"):
        merged_map = dict(_clean_counter_map(other.get(map_key)))
        for entry_id, entry in _clean_counter_map(base.get(map_key)).items():
            existing = merged_map.get(entry_id)
            if existing is None or int(entry.get("count") or 0) >= int(
                existing.get("count") or 0
            ):
                merged_map[entry_id] = entry

        merged[map_key] = merged_map

    return merged


def format_stats_message(stats: StatsData, *, include_private: bool = False) -> str:
    lines = [
        "StonerHand stats\n\n"
        f"постов обработано: {stats.get('posts', 0)}\n"
        f"треков: {stats.get('song', 0)}\n"
        f"альбомов: {stats.get('album', 0)}\n"
        f"подкастов: {stats.get('podcast', 0)}\n"
        f"видео: {stats.get('videos', 0)}\n"
        f"радио: {stats.get('radios', 0)}\n"
        f"плейлистов: {stats.get('playlists', 0)}\n"
        f"артистов: {stats.get('artists', 0)}\n"
        f"подборок: {stats.get('collections', 0)}"
    ]

    if include_private:
        lines.extend(
            [
                "",
                _format_top_entries("топ пользователей", stats.get("users")),
                "",
                _format_top_entries("топ чатов", stats.get("chats")),
            ]
        )

    return "\n".join(lines)


def _empty_stats() -> StatsData:
    return {
        "posts": 0,
        "song": 0,
        "album": 0,
        "podcast": 0,
        "videos": 0,
        "radios": 0,
        "playlists": 0,
        "artists": 0,
        "collections": 0,
        "users": {},
        "chats": {},
    }


def _clean_counter_map(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, dict):
        return {}

    cleaned: dict[str, dict[str, object]] = {}
    for key, entry in value.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue

        count = entry.get("count")
        if not isinstance(count, int) or count < 0:
            continue

        cleaned[key] = {
            "count": count,
            "label": str(entry.get("label") or key),
            "last_seen": str(entry.get("last_seen") or ""),
        }

    return cleaned


def _record_counter(counter: dict[str, dict[str, object]], entry: dict[str, object]) -> None:
    entry_id = str(entry.get("id") or "").strip()
    if not entry_id:
        return

    current = counter.setdefault(
        entry_id,
        {
            "count": 0,
            "label": entry_id,
            "last_seen": "",
        },
    )
    current["count"] = int(current.get("count") or 0) + 1
    current["label"] = str(entry.get("label") or current.get("label") or entry_id)
    current["last_seen"] = str(entry.get("last_seen") or current.get("last_seen") or "")


def _write_stats(path: Path, stats: StatsData) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _format_top_entries(title: str, value: object, *, limit: int = 10) -> str:
    if not isinstance(value, dict) or not value:
        return f"{title}: пока пусто"

    entries = sorted(
        value.values(),
        key=lambda item: item.get("count", 0) if isinstance(item, dict) else 0,
        reverse=True,
    )
    lines = [f"{title}:"]

    for index, entry in enumerate(entries[:limit], start=1):
        if not isinstance(entry, dict):
            continue

        label = entry.get("label") or "unknown"
        count = entry.get("count") or 0
        last_seen = entry.get("last_seen")
        suffix = f", последний раз: {last_seen}" if last_seen else ""
        lines.append(f"{index}. {label} - {count}{suffix}")

    return "\n".join(lines)
