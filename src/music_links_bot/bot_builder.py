from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from html import escape, unescape
import re

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


def schedule_timestamp(option: str, *, now: datetime | None = None) -> int:
    current = now or datetime.now(timezone.utc)
    delta = {
        "q1": timedelta(hours=1),
        "q3": timedelta(hours=3),
        "qd": timedelta(days=1),
    }.get(option)
    if delta is None:
        raise ValueError("Unsupported schedule option")
    return int((current + delta).timestamp())


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
