from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from music_links_bot.models import TrackMatch

STATS_PATH = Path("data/stats.json")
SUPPORTED_KINDS = ("song", "album")
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
    for key in ("posts", "song", "album", "collections"):
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
    stats = load_stats(path)
    stats["posts"] += 1

    if len(matches) > 1:
        stats["collections"] += 1

    for match in matches:
        stats[match.kind if match.kind in SUPPORTED_KINDS else "song"] += 1

    if user:
        _record_counter(stats["users"], user)

    if chat:
        _record_counter(stats["chats"], chat)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def format_stats_message(stats: StatsData, *, include_private: bool = False) -> str:
    lines = [
        "StonerHand stats\n\n"
        f"постов обработано: {stats.get('posts', 0)}\n"
        f"треков: {stats.get('song', 0)}\n"
        f"альбомов: {stats.get('album', 0)}\n"
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
