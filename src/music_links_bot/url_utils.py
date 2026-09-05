from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import (
    ParseResult,
    parse_qs,
    parse_qsl,
    unquote,
    urlencode,
    urlparse,
    urlunparse,
)

from music_links_bot.constants import SUPPORTED_INPUT_HOSTS

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,!?;:)]}>\"'\u00bb\u2019\u201d\u2026"
YOUTUBE_MUSIC_HOST = "music.youtube.com"
YOUTUBE_VIDEO_HOSTS = {"youtube.com", "m.youtube.com", "youtu.be"}
SOUNDCLOUD_HOSTS = {"soundcloud.com", "m.soundcloud.com", "on.soundcloud.com"}
NTS_HOSTS = {"nts.live", "www.nts.live"}
PLATFORM_DESTINATION_HOSTS = {
    "spotify": frozenset({"open.spotify.com", "spotify.com"}),
    "appleMusic": frozenset(
        {"music.apple.com", "geo.music.apple.com", "itunes.apple.com"}
    ),
    "applePodcasts": frozenset({"podcasts.apple.com"}),
    "youtubeMusic": frozenset(
        {"music.youtube.com", "youtube.com", "m.youtube.com", "youtu.be"}
    ),
    "soundcloud": frozenset(
        {"soundcloud.com", "m.soundcloud.com", "on.soundcloud.com"}
    ),
    "deezer": frozenset({"deezer.com"}),
    "tidal": frozenset({"tidal.com", "listen.tidal.com"}),
    "yandexMusic": frozenset({"music.yandex.ru", "music.yandex.com"}),
}
TRACKING_QUERY_KEYS = {
    "fbclid",
    "feature",
    "gclid",
    "igsh",
    "igshid",
    "si",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


def clean_url_token(token: str) -> str:
    return token.rstrip(TRAILING_PUNCTUATION)


def normalize_host(host: str | None) -> str:
    return (host or "").lower().removeprefix("www.")


def _parse_url(value: object) -> ParseResult | None:
    if not isinstance(value, str):
        return None
    try:
        return urlparse(value)
    except ValueError:
        return None


def is_supported_music_url(url: str) -> bool:
    if not is_direct_platform_url(url):
        return False
    parsed = _parse_url(url)
    if parsed is None:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    normalized = normalize_host(parsed.hostname)

    if normalized == YOUTUBE_MUSIC_HOST:
        return True

    if normalized in YOUTUBE_VIDEO_HOSTS:
        return is_youtube_video_url(url)

    if normalized.endswith(".youtube.com"):
        return False

    if normalized in SUPPORTED_INPUT_HOSTS:
        return True

    return any(normalized.endswith(f".{host}") for host in SUPPORTED_INPUT_HOSTS)


def is_direct_platform_url(value: object) -> bool:
    """Accept a real provider destination, never a synthetic search page."""
    if not isinstance(value, str) or not value.strip():
        return False

    value = value.strip()
    if any(char.isspace() or ord(char) < 32 for char in value) or "\\" in value:
        return False
    try:
        parsed = _parse_url(value)
        if (
            parsed is None
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or (
                parsed.port is not None
                and not (
                    (parsed.scheme == "https" and parsed.port == 443)
                    or (parsed.scheme == "http" and parsed.port == 80)
                )
            )
        ):
            return False
    except ValueError:
        return False

    path_parts = [part.casefold() for part in unquote(parsed.path).split("/") if part]
    return "search" not in path_parts


def canonical_platform_key(value: object) -> str | None:
    key = (
        str(value or "")
        .strip()
        .casefold()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
    )
    aliases = {
        "apple": "appleMusic",
        "applemusic": "appleMusic",
        "itunes": "appleMusic",
        "applepodcasts": "applePodcasts",
        "itunespodcast": "applePodcasts",
        "podcastapple": "applePodcasts",
        "podcasts": "applePodcasts",
        "youtube": "youtubeMusic",
        "youtubemusic": "youtubeMusic",
        "yandex": "yandexMusic",
        "yandexmusic": "yandexMusic",
    }
    return aliases.get(key) or next(
        (
            name
            for name in PLATFORM_DESTINATION_HOSTS
            if name.casefold().replace("_", "").replace("-", "") == key
        ),
        None,
    )


def is_platform_destination_url(platform_key: object, value: object) -> bool:
    """Validate that a trusted platform label points to its own HTTPS host."""
    if not isinstance(platform_key, str) or not is_direct_platform_url(value):
        return False
    if not isinstance(value, str):
        return False

    allowed_hosts = PLATFORM_DESTINATION_HOSTS.get(
        canonical_platform_key(platform_key) or ""
    )
    if not allowed_hosts:
        return False
    parsed = _parse_url(value.strip())
    if parsed is None:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and port in {None, 443}
        and normalize_host(parsed.hostname) in allowed_hosts
    )


def direct_platform_links(value: object) -> dict[str, str]:
    """Return only direct HTTP(S) release links from provider metadata."""
    if not isinstance(value, Mapping):
        return {}
    links: dict[str, str] = {}
    for key, url in value.items():
        canonical_key = canonical_platform_key(key)
        if (
            canonical_key
            and isinstance(url, str)
            and is_platform_destination_url(canonical_key, url)
        ):
            links[canonical_key] = url.strip()
    return links


def extract_supported_urls(text: str | None) -> list[str]:
    if not text:
        return []

    urls: list[str] = []
    seen: set[str] = set()
    for match in URL_RE.finditer(text):
        candidate = clean_url_token(match.group(0))
        dedupe_key = cache_key_for_url(candidate)
        if dedupe_key in seen or not is_supported_music_url(candidate):
            continue

        urls.append(candidate)
        seen.add(dedupe_key)

    return urls


def cache_key_for_url(url: str) -> str:
    parsed = _parse_url(url)
    if parsed is None:
        return url
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return url

    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS
    ]
    return urlunparse(
        parsed._replace(
            query=urlencode(query_items),
            fragment="",
        )
    )


def strip_supported_urls(text: str | None) -> str:
    stripped, _ = strip_supported_urls_with_mapping(text)
    return stripped


def strip_supported_urls_with_mapping(
    text: str | None,
) -> tuple[str, tuple[int, ...]]:
    """Remove supported URLs and map every output character to its source index."""
    if not text:
        return "", ()

    spans: list[tuple[int, int]] = []
    for match in URL_RE.finditer(text):
        candidate = clean_url_token(match.group(0))
        if is_supported_music_url(candidate):
            spans.append(match.span())

    removal_spans: list[tuple[int, int]] = []
    for start, end in spans:
        before = text[start - 1] if start > 0 else ""
        after = text[end] if end < len(text) else ""
        before_is_inline_space = bool(before) and before in " \t"
        after_is_inline_space = bool(after) and after in " \t"
        before_is_line_boundary = not before or before in "\r\n"
        after_is_line_boundary = not after or after in "\r\n"
        after_is_punctuation = bool(after) and after in TRAILING_PUNCTUATION

        # Remove one separator together with an inline URL, while preserving
        # every other user-authored space, line break, and empty paragraph.
        if before_is_inline_space and after_is_inline_space:
            end += 1
        elif before_is_inline_space and (
            after_is_line_boundary or after_is_punctuation
        ):
            start -= 1
        elif before_is_line_boundary and after_is_inline_space:
            end += 1

        removal_spans.append((start, end))

    kept = [True] * len(text)
    for start, end in removal_spans:
        kept[start:end] = [False] * (end - start)

    source_pairs: list[tuple[str, int]] = []
    for index, character in enumerate(text):
        if not kept[index]:
            continue

        if character == "\r":
            if index + 1 < len(text) and kept[index + 1] and text[index + 1] == "\n":
                continue
            character = "\n"

        source_pairs.append((character, index))

    segments: list[tuple[list[tuple[str, int]], tuple[str, int] | None]] = []
    current_line: list[tuple[str, int]] = []
    for pair in source_pairs:
        if pair[0] == "\n":
            segments.append((current_line, pair))
            current_line = []
        else:
            current_line.append(pair)
    segments.append((current_line, None))

    normalized_segments: list[tuple[list[tuple[str, int]], tuple[str, int] | None]] = []
    for line, separator in segments:
        while line and line[-1][0] in " \t":
            line.pop()
        normalized_segments.append((line, separator))

    while normalized_segments and not _line_has_content(normalized_segments[0][0]):
        normalized_segments.pop(0)
    while normalized_segments and not _line_has_content(normalized_segments[-1][0]):
        normalized_segments.pop()

    output_pairs: list[tuple[str, int]] = []
    for index, (line, separator) in enumerate(normalized_segments):
        output_pairs.extend(line)
        if index < len(normalized_segments) - 1 and separator is not None:
            output_pairs.append(separator)

    return (
        "".join(character for character, _ in output_pairs),
        tuple(source_index for _, source_index in output_pairs),
    )


def _line_has_content(line: list[tuple[str, int]]) -> bool:
    return any(not character.isspace() for character, _ in line)


def is_youtube_video_url(url: str) -> bool:
    parsed = _parse_url(url)
    if parsed is None:
        return False
    normalized_host = normalize_host(parsed.hostname)
    if normalized_host == YOUTUBE_MUSIC_HOST:
        return False

    if normalized_host == "youtu.be":
        return bool([part for part in parsed.path.split("/") if part])

    if normalized_host not in {"youtube.com", "m.youtube.com"}:
        return False

    parts = [part.lower() for part in parsed.path.split("/") if part]
    if not parts:
        return False

    if parts[0] == "watch":
        return bool(parse_qs(parsed.query).get("v"))

    return parts[0] in {"shorts", "live", "embed"} and len(parts) >= 2


def is_soundcloud_url(url: str) -> bool:
    parsed = _parse_url(url)
    if parsed is None:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    normalized_host = normalize_host(parsed.hostname)
    return normalized_host in SOUNDCLOUD_HOSTS or normalized_host.endswith(
        ".soundcloud.com"
    )


def is_nts_url(url: str) -> bool:
    parsed = _parse_url(url)
    if parsed is None:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    normalized_host = normalize_host(parsed.hostname)
    return normalized_host in NTS_HOSTS or normalized_host.endswith(".nts.live")


def spotify_url_type(url: str) -> str | None:
    if not is_direct_platform_url(url):
        return None
    parsed = _parse_url(url)
    if parsed is None:
        return None
    if normalize_host(parsed.hostname) not in {"open.spotify.com", "spotify.com"}:
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if parts and parts[0].lower().startswith("intl-"):
        parts = parts[1:]
    if len(parts) < 2:
        return None

    return parts[0].lower()


def is_spotify_playlist_url(url: str) -> bool:
    return spotify_url_type(url) == "playlist"


def apple_music_url_type(url: str) -> str | None:
    if not is_direct_platform_url(url):
        return None
    parsed = _parse_url(url)
    if parsed is None:
        return None
    if normalize_host(parsed.hostname) != "music.apple.com":
        return None

    parts = [part.lower() for part in parsed.path.split("/") if part]
    for part in parts:
        if part in {"album", "artist", "music-video", "playlist", "song"}:
            return part
    return None


def is_apple_music_playlist_url(url: str) -> bool:
    return apple_music_url_type(url) == "playlist"


def is_playlist_url(url: str) -> bool:
    return is_spotify_playlist_url(url) or is_apple_music_playlist_url(url)


def is_spotify_artist_url(url: str) -> bool:
    return spotify_url_type(url) == "artist"


def apple_podcasts_url_type(url: str) -> str | None:
    if not is_direct_platform_url(url):
        return None
    parsed = _parse_url(url)
    if parsed is None:
        return None
    if normalize_host(parsed.hostname) != "podcasts.apple.com":
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if "podcast" not in parts:
        return None

    if parse_qs(parsed.query).get("i"):
        return "episode"

    return "show"
