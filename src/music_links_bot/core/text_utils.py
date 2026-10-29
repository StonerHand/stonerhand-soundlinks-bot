from __future__ import annotations

import re


def normalize_hashtag(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    slug = re.sub(r"[^0-9a-zа-яё_]", "", value.casefold())
    return f"#{slug[:32]}" if slug else None
