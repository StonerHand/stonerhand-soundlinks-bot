from __future__ import annotations

import re
from urllib.parse import urlparse

from music_links_bot.constants import SUPPORTED_INPUT_HOSTS

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,!?)]}>\"'"


def clean_url_token(token: str) -> str:
    return token.rstrip(TRAILING_PUNCTUATION)


def normalize_host(host: str) -> str:
    return host.lower().removeprefix("www.")


def is_supported_music_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    normalized = normalize_host(parsed.netloc)

    if normalized in SUPPORTED_INPUT_HOSTS:
        return True

    return any(normalized.endswith(f".{host}") for host in SUPPORTED_INPUT_HOSTS)


def extract_supported_urls(text: str | None) -> list[str]:
    if not text:
        return []

    urls: list[str] = []
    seen: set[str] = set()
    for match in URL_RE.finditer(text):
        candidate = clean_url_token(match.group(0))
        if candidate in seen or not is_supported_music_url(candidate):
            continue

        urls.append(candidate)
        seen.add(candidate)

    return urls
