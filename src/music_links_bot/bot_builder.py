from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from html import escape, unescape
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from music_links_bot.constants import PLATFORM_LABELS
from music_links_bot.models import TrackMatch
from music_links_bot.release_presentation import PRESET_ORDER, apply_preset
from music_links_bot.text_utils import normalize_hashtag

MESSAGE_TEXT_LIMIT = 4096
PHOTO_CAPTION_LIMIT = 1024
MAX_INTRO_LENGTH = 900
MAX_CRATE_TITLE_LENGTH = 72
MAX_CUSTOM_TAGS = 5
MAX_SELECTED_PLATFORMS = 6
PENDING_INPUT_TTL_SECONDS = 15 * 60


class BuilderScreen(str, Enum):
    MAIN = "main"
    STYLE = "style"
    PLATFORMS = "platforms"
    INTRO = "intro"
    HASHTAGS = "hashtags"
    PREVIEW = "preview"
    ACTIONS = "actions"
    SCHEDULE = "schedule"


SCREEN_ACTIONS = {
    "m": BuilderScreen.MAIN,
    "zs": BuilderScreen.STYLE,
    "ls": BuilderScreen.PLATFORMS,
    "ts": BuilderScreen.INTRO,
    "hs": BuilderScreen.HASHTAGS,
    "pv": BuilderScreen.PREVIEW,
    "o": BuilderScreen.ACTIONS,
    "qs": BuilderScreen.SCHEDULE,
}


def builder_screen(action: str) -> BuilderScreen | None:
    return SCREEN_ACTIONS.get(action)


def active_card_label(draft: dict, fallback: str, *, max_length: int = 42) -> str:
    item = draft.get("item") if isinstance(draft, dict) else None
    if not isinstance(item, dict):
        return fallback
    artist = str(item.get("artist") or "").strip()
    title = str(item.get("title") or "").strip()
    value = " — ".join(part for part in (artist, title) if part) or fallback
    if len(value) <= max_length:
        return value
    return value[: max(1, max_length - 1)].rstrip() + "…"


def available_platforms(track: TrackMatch, platform_order: list[str]) -> list[str]:
    return [
        key
        for key in platform_order
        if key in PLATFORM_LABELS and isinstance(track.links.get(key), str)
    ][:MAX_SELECTED_PLATFORMS]


def selected_platforms(
    draft: dict, track: TrackMatch, platform_order: list[str]
) -> list[str]:
    available = available_platforms(track, platform_order)
    stored = draft.get("platforms")
    if not isinstance(stored, list):
        return available
    return [key for key in stored if key in available]


def toggle_platform(
    draft: dict, track: TrackMatch, platform_order: list[str], index: int
) -> list[str]:
    available = available_platforms(track, platform_order)
    if not 0 <= index < len(available):
        return selected_platforms(draft, track, platform_order)
    current = selected_platforms(draft, track, platform_order)
    key = available[index]
    if key in current:
        current.remove(key)
    else:
        current.append(key)
        current.sort(key=available.index)
    draft["platforms"] = current
    return current


def select_all_platforms(
    draft: dict, track: TrackMatch, platform_order: list[str]
) -> list[str]:
    selection = available_platforms(track, platform_order)
    draft["platforms"] = selection
    return selection


def select_preset(draft: dict, index: int) -> str:
    if not 0 <= index < len(PRESET_ORDER):
        index = 1
    return apply_preset(draft, PRESET_ORDER[index])


def apply_intro_text(draft: dict, value: str) -> str:
    lines = [" ".join(line.split()) for line in str(value or "").splitlines()]
    clean = "\n".join(lines).strip()[:MAX_INTRO_LENGTH].strip()
    draft["prefix"] = f"<blockquote>{escape(clean)}</blockquote>\n\n" if clean else ""
    draft["quote"] = bool(clean)
    return clean


def remove_intro(draft: dict) -> None:
    draft["prefix"] = ""
    draft["quote"] = False


def parse_custom_tags(value: str) -> list[str]:
    tags: list[str] = []
    for token in re.split(r"[\s,;]+", str(value or "")):
        tag = normalize_hashtag(token)
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= MAX_CUSTOM_TAGS:
            break
    return tags


def apply_custom_tags(draft: dict, value: str) -> list[str]:
    tags = parse_custom_tags(value)
    draft["custom_tags"] = tags
    draft["hashtags"] = bool(tags)
    return tags


def use_auto_tags(draft: dict) -> None:
    draft.pop("custom_tags", None)
    draft["hashtags"] = True


def remove_tags(draft: dict) -> None:
    draft["custom_tags"] = []
    draft["hashtags"] = False


def normalize_crate_title(value: str) -> str:
    return " ".join(str(value or "").split())[:MAX_CRATE_TITLE_LENGTH].strip()


def schedule_timestamp(
    option: str,
    *,
    now: datetime | None = None,
    timezone_name: str = "Europe/Moscow",
) -> int:
    current = now or datetime.now(_timezone(timezone_name))
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if option == "q1":
        result = current + timedelta(hours=1)
    elif option == "q3":  # compatibility with already-sent keyboards
        result = current + timedelta(hours=3)
    elif option == "qe":
        result = current.replace(hour=20, minute=0, second=0, microsecond=0)
        if result <= current:
            result += timedelta(days=1)
    elif option == "qd":
        result = (current + timedelta(days=1)).replace(
            hour=12,
            minute=0,
            second=0,
            microsecond=0,
        )
    else:
        raise ValueError("Unsupported schedule option")
    return int(result.timestamp())


def parse_schedule_datetime(
    value: str,
    *,
    now: datetime | None = None,
    timezone_name: str = "Europe/Moscow",
) -> int | None:
    """Parse a compact local date/time without guessing ambiguous formats."""
    current = now or datetime.now(_timezone(timezone_name))
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    match = re.fullmatch(
        r"\s*(?:(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\s+)?"
        r"([01]?\d|2[0-3]):([0-5]\d)\s*",
        str(value or ""),
    )
    if match is None:
        return None
    day, month, year, hour, minute = match.groups()
    try:
        if day is None:
            result = current.replace(
                hour=int(hour), minute=int(minute), second=0, microsecond=0
            )
            if result <= current:
                result += timedelta(days=1)
        else:
            parsed_year = current.year if year is None else int(year)
            if parsed_year < 100:
                parsed_year += 2000
            result = datetime(
                parsed_year,
                int(month),
                int(day),
                int(hour),
                int(minute),
                tzinfo=current.tzinfo,
            )
    except ValueError:
        return None
    if result <= current or result > current + timedelta(days=366):
        return None
    return int(result.timestamp())


def format_schedule_datetime(
    timestamp: int,
    *,
    timezone_name: str = "Europe/Moscow",
) -> str:
    return datetime.fromtimestamp(timestamp, _timezone(timezone_name)).strftime(
        "%d.%m · %H:%M"
    )


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Europe/Moscow")


def fit_telegram_html(text: str, limit: int = MESSAGE_TEXT_LIMIT) -> str:
    """Keep valid HTML; use a safe plain-text fallback only at Telegram's edge."""
    value = str(text or "")
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    plain = unescape(re.sub(r"<[^>]*>", "", value))
    suffix = "…"
    if limit == 1:
        return suffix
    low, high = 0, len(plain)
    while low < high:
        middle = (low + high + 1) // 2
        if len(escape(plain[:middle])) + len(suffix) <= limit:
            low = middle
        else:
            high = middle - 1
    return escape(plain[:low].rstrip()) + suffix
