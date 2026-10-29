from __future__ import annotations

import re


def normalize_hashtag(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    slug = re.sub(r"[^0-9a-zа-яё_]", "", value.casefold())
    return f"#{slug[:32]}" if slug else None


_GENRE_ALIASES = {"hiphoprap": "hiphop", "rhythmandblues": "rnb", "rnb": "rnb"}


def genre_hashtags(genre: str | None, *, limit: int = 2) -> list[str]:
    if not isinstance(genre, str):
        return []
    genre = re.sub(r"hip[ -]?hop\s*/\s*rap", "hiphop", genre, flags=re.IGNORECASE)
    result = []
    for part in re.split(r"[/,;]", genre.replace("&", "n")):
        tag = normalize_hashtag(part)
        if not tag or tag in {"#music", "#музыка", "#unknown", "#other"}:
            continue
        tag = "#" + _GENRE_ALIASES.get(tag[1:], tag[1:])
        if tag not in result:
            result.append(tag)
    return result[:limit]
