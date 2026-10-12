"""Human dates for the interface: "сегодня 20:00", "завтра 12:00", "пт 21:00".

Also parses the same kind of phrases back, so scheduling accepts what people
naturally type instead of one rigid format.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_WEEKDAYS = {
    "ru": ("пн", "вт", "ср", "чт", "пт", "сб", "вс"),
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
}
_DAY_WORDS = {
    "ru": ("сегодня", "завтра", "вчера"),
    "en": ("today", "tomorrow", "yesterday"),
}
# Weekday names people type, in Russian and English, mapped to Monday=0.
_WEEKDAY_INPUT = {
    **{
        name: index
        for index, names in enumerate(
            (
                ("пн", "пон", "понедельник", "mon", "monday"),
                ("вт", "вто", "вторник", "tue", "tuesday"),
                ("ср", "сре", "среда", "среду", "wed", "wednesday"),
                ("чт", "чет", "четверг", "thu", "thursday"),
                ("пт", "пят", "пятница", "пятницу", "fri", "friday"),
                ("сб", "суб", "суббота", "субботу", "sat", "saturday"),
                ("вс", "вос", "воскресенье", "sun", "sunday"),
            )
        )
        for name in names
    }
}


def zone(name: str | None) -> tzinfo:
    try:
        return ZoneInfo(name or "Europe/Moscow")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Europe/Moscow")


def human_datetime(
    timestamp: float,
    *,
    timezone_name: str | None = None,
    lang: str = "ru",
    now: float | None = None,
) -> str:
    """ "сегодня 20:00", "завтра 12:00", "пт 21:00" (this week) or "08.09 15:00"."""
    lang = "en" if lang == "en" else "ru"
    tz = zone(timezone_name)
    moment = datetime.fromtimestamp(timestamp, tz)
    today = datetime.fromtimestamp(time.time() if now is None else now, tz).date()
    clock = moment.strftime("%H:%M")
    delta = (moment.date() - today).days
    if delta in (0, 1, -1):
        word = _DAY_WORDS[lang][{0: 0, 1: 1, -1: 2}[delta]]
        return f"{word} {clock}"
    if 1 < delta < 7:
        return f"{_WEEKDAYS[lang][moment.weekday()]} {clock}"
    if moment.year == today.year:
        return f"{moment:%d.%m} {clock}"
    return f"{moment:%d.%m.%Y} {clock}"


def human_date(
    timestamp: float,
    *,
    timezone_name: str | None = None,
    lang: str = "ru",
    now: float | None = None,
) -> str:
    """Like ``human_datetime`` but without the clock for anything older than today."""
    text = human_datetime(timestamp, timezone_name=timezone_name, lang=lang, now=now)
    word = text.split(" ", 1)[0]
    if word in _DAY_WORDS["ru"][:1] + _DAY_WORDS["en"][:1]:
        return text
    return word


def parse_human_datetime(
    value: str,
    *,
    timezone_name: str | None = None,
    now: float | None = None,
) -> float | None:
    """Parse "21:00", "15.08 19:30", "завтра 18:30", "пт 21:00", "через 2 часа".

    Returns a UNIX timestamp in the future, or ``None`` when the text is not a
    time we understand. A bare clock time that already passed today means
    tomorrow, which is what people mean when they type it.
    """
    text = " ".join(str(value or "").casefold().replace("ё", "е").split())
    if not text:
        return None
    tz = zone(timezone_name)
    current = datetime.fromtimestamp(time.time() if now is None else now, tz)

    relative = re.fullmatch(
        r"(?:через|in)\s+(?:(\d{1,3})\s*)?"
        r"(час|часа|часов|ч|hour|hours|h|минут[уы]?|мин|m|min|minutes?|"
        r"день|дня|дней|day|days)",
        text,
    )
    if relative:
        amount = int(relative.group(1) or 1)
        unit = relative.group(2)
        if unit.startswith(("мин", "min")) or unit == "m":
            step = timedelta(minutes=amount)
        elif unit.startswith(("д", "day")):
            step = timedelta(days=amount)
        else:
            step = timedelta(hours=amount)
        if step > timedelta(days=60) or step <= timedelta(0):
            return None
        return (current + step).timestamp()

    clock = re.search(r"(?<!\d)(\d{1,2})[:.](\d{2})(?!\d)$", text)
    if clock is None:
        return None
    hour, minute = int(clock.group(1)), int(clock.group(2))
    if hour > 23 or minute > 59:
        return None
    day_part = text[: clock.start()].strip()
    if day_part in {"в", "at", ""}:
        day_part = ""
    day_part = re.sub(r"\s+(в|at)$", "", day_part)

    def at(day: datetime) -> datetime:
        return day.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if not day_part:
        candidate = at(current)
        if candidate <= current:
            candidate += timedelta(days=1)
        return candidate.timestamp()
    if day_part in {"сегодня", "today"}:
        candidate = at(current)
        return candidate.timestamp() if candidate > current else None
    if day_part in {"завтра", "tomorrow"}:
        return at(current + timedelta(days=1)).timestamp()
    if day_part in {"послезавтра"}:
        return at(current + timedelta(days=2)).timestamp()
    weekday = _WEEKDAY_INPUT.get(re.sub(r"^(в|во|on)\s+", "", day_part))
    if weekday is not None:
        days_ahead = (weekday - current.weekday()) % 7
        candidate = at(current + timedelta(days=days_ahead))
        if candidate <= current:
            candidate += timedelta(days=7)
        return candidate.timestamp()
    date = re.fullmatch(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2}|\d{4}))?", day_part)
    if date is None:
        return None
    day, month = int(date.group(1)), int(date.group(2))
    year = date.group(3)
    full_year = (
        current.year
        if year is None
        else int(year) + 2000
        if len(year) == 2
        else int(year)
    )
    try:
        candidate = at(current.replace(year=full_year, month=month, day=day))
    except ValueError:
        return None
    if year is None and candidate <= current:
        try:
            candidate = candidate.replace(year=full_year + 1)
        except ValueError:
            return None
    return candidate.timestamp() if candidate > current else None
