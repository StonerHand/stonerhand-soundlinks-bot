from __future__ import annotations

import json
from pathlib import Path

from music_links_bot.models import TrackMatch

STATS_PATH = Path("data/stats.json")
SUPPORTED_KINDS = ("song", "album")


def load_stats(path: Path = STATS_PATH) -> dict[str, int]:
    if not path.exists():
        return _empty_stats()

    try:
        raw_stats = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_stats()

    stats = _empty_stats()
    for key in stats:
        value = raw_stats.get(key)
        if isinstance(value, int) and value >= 0:
            stats[key] = value

    return stats


def record_matches(matches: list[TrackMatch], path: Path = STATS_PATH) -> dict[str, int]:
    stats = load_stats(path)
    stats["posts"] += 1

    if len(matches) > 1:
        stats["collections"] += 1

    for match in matches:
        stats[match.kind if match.kind in SUPPORTED_KINDS else "song"] += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def format_stats_message(stats: dict[str, int]) -> str:
    return (
        "StonerHand stats\n\n"
        f"постов обработано: {stats.get('posts', 0)}\n"
        f"треков: {stats.get('song', 0)}\n"
        f"альбомов: {stats.get('album', 0)}\n"
        f"подборок: {stats.get('collections', 0)}"
    )


def _empty_stats() -> dict[str, int]:
    return {
        "posts": 0,
        "song": 0,
        "album": 0,
        "collections": 0,
    }
