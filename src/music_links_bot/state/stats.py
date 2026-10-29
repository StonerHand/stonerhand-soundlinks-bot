from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from threading import Lock
from typing import Any

from music_links_bot.core.models import (
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
        return Path(tempfile.gettempdir()) / "stonerhand_stats.json"

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


def record_post(
    path: Path | None = STATS_PATH,
    *,
    tracks: Sequence[TrackMatch] = (),
    videos: Sequence[VideoMatch] = (),
    radios: Sequence[RadioMatch] = (),
    playlists: Sequence[PlaylistMatch] = (),
    artists: Sequence[ArtistMatch] = (),
    user: dict[str, object] | None = None,
    chat: dict[str, object] | None = None,
) -> StatsData:
    """Count one delivered post: releases by kind, other items by type."""
    with STATS_LOCK:
        stats = load_stats(path) if path is not None else _empty_stats()
        stats["posts"] += 1
        stats["videos"] += len(videos)
        stats["radios"] += len(radios)
        stats["playlists"] += len(playlists)
        stats["artists"] += len(artists)
        item_count = (
            len(tracks) + len(videos) + len(radios) + len(playlists) + len(artists)
        )
        if item_count > 1:
            stats["collections"] += 1

        for track in tracks:
            stats[track.kind if track.kind in SUPPORTED_KINDS else "song"] += 1

        if user:
            _record_counter(stats["users"], user)

        if chat:
            _record_counter(stats["chats"], chat)

        if path is not None:
            _write_stats(path, stats)
        return stats


def remove_identity(
    user_id: int,
    path: Path = STATS_PATH,
) -> StatsData:
    """Remove user/chat labels while retaining anonymous aggregate counters."""
    identifier = str(int(user_id))
    with STATS_LOCK:
        stats = load_stats(path)
        stats["users"].pop(identifier, None)
        stats["chats"].pop(identifier, None)
        _write_stats(path, stats)
        return stats


def format_stats_message(stats: StatsData, *, include_private: bool = False) -> str:
    lines = [
        "StonerHand stats",
        "",
        f"постов обработано: {stats.get('posts', 0)}",
        f"треков: {stats.get('song', 0)}",
        f"альбомов: {stats.get('album', 0)}",
        f"подкастов: {stats.get('podcast', 0)}",
        f"видео: {stats.get('videos', 0)}",
        f"радио: {stats.get('radios', 0)}",
        f"плейлистов: {stats.get('playlists', 0)}",
        f"артистов: {stats.get('artists', 0)}",
        f"подборок: {stats.get('collections', 0)}",
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


def _record_counter(
    counter: dict[str, dict[str, object]], entry: dict[str, object]
) -> None:
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
    count = current.get("count")
    current["count"] = (count if isinstance(count, int) else 0) + 1
    current["label"] = str(entry.get("label") or current.get("label") or entry_id)
    current["last_seen"] = str(entry.get("last_seen") or current.get("last_seen") or "")


def _write_stats(path: Path, stats: StatsData) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
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
