from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from telegram import InlineKeyboardMarkup

from music_links_bot.formatter import (
    format_artist_collection_message,
    format_collection_message,
    format_mixed_collection_message,
    format_playlist_collection_message,
    format_radio_collection_message,
    format_video_collection_message,
)
from music_links_bot.keyboards import (
    DEFAULT_PLATFORM_ORDER,
    _build_artist_collection_keyboard,
    _build_collection_keyboard,
    _build_mixed_collection_keyboard,
    _build_nts_collection_keyboard,
    _build_playlist_collection_keyboard,
    _build_youtube_collection_keyboard,
    _select_preview_url,
)
from music_links_bot.models import TrackMatch
from music_links_bot.telegram_buttons import button as InlineKeyboardButton
from music_links_bot.url_utils import cache_key_for_url, is_supported_music_url

SHARE_QUERY_PREFIX = "sh4|"
LEGACY_SHARE_QUERY_PREFIXES = ("sh3|", "sh2|", "sh|")
MAX_SHARE_QUERY_LENGTH = 256
MAX_SHARE_ITEMS = 12
_SPOTIFY_KINDS = {
    "track": "t",
    "album": "a",
    "playlist": "p",
    "artist": "r",
    "episode": "e",
    "show": "s",
}
_SPOTIFY_CODES = {code: kind for kind, code in _SPOTIFY_KINDS.items()}
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@dataclass(slots=True)
class InlineShareCard:
    title: str
    description: str
    text: str
    keyboard: InlineKeyboardMarkup
    preview_url: str | None


def track_share_url(track: TrackMatch) -> str | None:
    """Choose a stable source URL which the inline lookup can resolve again."""
    for platform in DEFAULT_PLATFORM_ORDER:
        url = track.links.get(platform)
        if url and is_supported_music_url(url):
            return cache_key_for_url(url)

    for url in track.links.values():
        if url and is_supported_music_url(url):
            return cache_key_for_url(url)

    return None


def build_share_query(urls: list[str]) -> str | None:
    unique_urls = list(dict.fromkeys(cache_key_for_url(url) for url in urls if url))
    if not unique_urls or len(unique_urls) > MAX_SHARE_ITEMS:
        return None

    tokens: list[str] = []
    for url in unique_urls:
        token = _compact_share_url(url)
        if token is None:
            return None
        tokens.append(token)

    query = SHARE_QUERY_PREFIX + "|".join(tokens)
    return query if len(query) <= MAX_SHARE_QUERY_LENGTH else None


def parse_share_query(query: str) -> list[str] | None:
    prefix = next(
        (
            candidate
            for candidate in (SHARE_QUERY_PREFIX, *LEGACY_SHARE_QUERY_PREFIXES)
            if query.startswith(candidate)
        ),
        None,
    )
    if prefix is None:
        return None

    raw_tokens = query[len(prefix) :].split("|")
    if not raw_tokens or len(raw_tokens) > MAX_SHARE_ITEMS:
        return []

    urls: list[str] = []
    seen: set[str] = set()
    for token in raw_tokens:
        url = _expand_share_token(token)
        if url is None or not is_supported_music_url(url):
            return []
        key = cache_key_for_url(url)
        if key in seen:
            continue
        urls.append(url)
        seen.add(key)
    return urls


def add_share_button(
    keyboard: InlineKeyboardMarkup,
    *,
    share_query: str | None,
    label: str,
) -> InlineKeyboardMarkup:
    if not share_query:
        return keyboard

    if any(
        button.switch_inline_query == share_query
        for row in keyboard.inline_keyboard
        for button in row
    ):
        return keyboard

    return InlineKeyboardMarkup(
        [
            *keyboard.inline_keyboard,
            [
                InlineKeyboardButton(
                    label,
                    switch_inline_query=share_query,
                    style="primary",
                )
            ],
        ]
    )


def make_channel_safe_keyboard(
    keyboard: InlineKeyboardMarkup | None,
) -> InlineKeyboardMarkup | None:
    """Remove inline-mode buttons that Telegram rejects in channel posts."""
    if keyboard is None:
        return None

    safe_rows = [
        [
            button
            for button in row
            if not any(
                (
                    button.switch_inline_query is not None,
                    button.switch_inline_query_current_chat is not None,
                    button.switch_inline_query_chosen_chat is not None,
                )
            )
        ]
        for row in keyboard.inline_keyboard
    ]
    safe_rows = [row for row in safe_rows if row]
    if not safe_rows:
        return None

    if safe_rows == [list(row) for row in keyboard.inline_keyboard]:
        return keyboard

    return InlineKeyboardMarkup(safe_rows)


def render_inline_share_card(
    bundle: Any,
    *,
    context: Any,
    lang: str,
    share_query: str | None,
    share_label: str,
    requested_count: int | None = None,
) -> InlineShareCard:
    preview_url = _bundle_preview_url(bundle, context)
    found_count = bundle.item_count
    total_count = max(found_count, int(requested_count or found_count))

    if bundle.content_type_count == 1 and bundle.tracks:
        title = collection_result_title(
            lang,
            found=len(bundle.tracks),
            total=total_count,
        )
        text = format_collection_message(
            bundle.tracks,
            include_hashtags=True,
            title=title,
        )
        keyboard = _build_collection_keyboard(bundle.tracks)
    elif bundle.content_type_count == 1 and bundle.videos:
        title = collection_result_title(
            lang,
            found=len(bundle.videos),
            total=total_count,
            item_kind="video",
        )
        text = format_video_collection_message(
            bundle.videos,
            include_hashtags=True,
            title=title,
        )
        keyboard = _build_youtube_collection_keyboard(bundle.videos)
    elif bundle.content_type_count == 1 and bundle.radios:
        title = collection_result_title(
            lang,
            found=len(bundle.radios),
            total=total_count,
            item_kind="radio",
        )
        text = format_radio_collection_message(
            bundle.radios,
            include_hashtags=True,
            title=title,
        )
        keyboard = _build_nts_collection_keyboard(bundle.radios)
    elif bundle.content_type_count == 1 and bundle.playlists:
        title = collection_result_title(
            lang,
            found=len(bundle.playlists),
            total=total_count,
            item_kind="playlist",
        )
        text = format_playlist_collection_message(
            bundle.playlists,
            include_hashtags=True,
            title=title,
        )
        keyboard = _build_playlist_collection_keyboard(bundle.playlists)
    elif bundle.content_type_count == 1 and bundle.artists:
        title = collection_result_title(
            lang,
            found=len(bundle.artists),
            total=total_count,
            item_kind="artist",
        )
        text = format_artist_collection_message(
            bundle.artists,
            include_hashtags=True,
            title=title,
        )
        keyboard = _build_artist_collection_keyboard(bundle.artists)
    else:
        title = collection_result_title(
            lang,
            found=bundle.item_count,
            total=total_count,
            item_kind="item",
        )
        text = format_mixed_collection_message(
            bundle.tracks,
            bundle.videos,
            bundle.playlists,
            bundle.artists,
            bundle.radios,
            include_hashtags=True,
            title=title if found_count < total_count else None,
        )
        keyboard = _build_mixed_collection_keyboard(
            bundle.tracks,
            bundle.videos,
            bundle.playlists,
            bundle.artists,
            bundle.radios,
        )

    return InlineShareCard(
        title=title,
        description=(
            "Ready-to-share post with every button"
            if lang == "en"
            else "Готовый пост со всеми кнопками"
        ),
        text=text,
        keyboard=(
            _add_inline_retry_button(keyboard, share_query=share_query, lang=lang)
            if found_count < total_count
            else add_share_button(
                keyboard,
                share_query=share_query,
                label=share_label,
            )
        ),
        preview_url=preview_url,
    )


def _add_inline_retry_button(
    keyboard: InlineKeyboardMarkup,
    *,
    share_query: str | None,
    lang: str,
) -> InlineKeyboardMarkup:
    if not share_query:
        return keyboard
    label = "🔁 Check all links again" if lang == "en" else "🔁 Проверить все ссылки"
    return InlineKeyboardMarkup(
        [
            *keyboard.inline_keyboard,
            [
                InlineKeyboardButton(
                    label,
                    switch_inline_query_current_chat=share_query,
                    style="primary",
                )
            ],
        ]
    )


def _bundle_preview_url(bundle: Any, context: Any) -> str | None:
    if bundle.tracks:
        track = bundle.tracks[0]
        return _select_preview_url(track.links, context) or track.thumbnail_url
    if bundle.playlists:
        return bundle.playlists[0].url
    if bundle.artists:
        return bundle.artists[0].url
    if bundle.radios:
        return bundle.radios[0].url
    if bundle.videos:
        return bundle.videos[0].url
    return None


def collection_title(lang: str, count: int, item_kind: str = "release") -> str:
    if lang == "en":
        nouns = {
            "release": ("release", "releases"),
            "video": ("video", "videos"),
            "radio": ("show", "shows"),
            "playlist": ("playlist", "playlists"),
            "artist": ("artist", "artists"),
            "item": ("item", "items"),
        }
        singular, plural = nouns[item_kind]
        return f"Collection · {count} {singular if count == 1 else plural}"

    forms = {
        "release": ("релиз", "релиза", "релизов"),
        "video": ("видео", "видео", "видео"),
        "radio": ("эфир", "эфира", "эфиров"),
        "playlist": ("плейлист", "плейлиста", "плейлистов"),
        "artist": ("артист", "артиста", "артистов"),
        "item": ("материал", "материала", "материалов"),
    }
    one, few, many = forms[item_kind]
    if count % 10 == 1 and count % 100 != 11:
        noun = one
    elif count % 10 in {2, 3, 4} and count % 100 not in {12, 13, 14}:
        noun = few
    else:
        noun = many
    return f"Подборка · {count} {noun}"


def collection_result_title(
    lang: str,
    *,
    found: int,
    total: int,
    item_kind: str = "release",
) -> str:
    """Describe a complete collection compactly and flag partial results."""
    if found < total:
        if lang == "en":
            return f"⚠️ Collection · {found} of {total}"
        return f"⚠️ Подборка · {found} из {total}"
    return collection_title(lang, found, item_kind)


def _compact_share_url(url: str) -> str | None:
    clean_url = cache_key_for_url(url)
    parsed = urlparse(clean_url)
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    parts = [part for part in parsed.path.split("/") if part]

    if host == "open.spotify.com":
        for index, part in enumerate(parts[:-1]):
            kind_code = _SPOTIFY_KINDS.get(part.casefold())
            item_id = parts[index + 1]
            if kind_code and _SAFE_ID_RE.fullmatch(item_id):
                return f"{kind_code}{item_id}"

    if host == "youtu.be" and parts and _SAFE_ID_RE.fullmatch(parts[0]):
        return f"y{parts[0]}"

    if host in {"youtube.com", "m.youtube.com"}:
        video_id = (parse_qs(parsed.query).get("v") or [""])[0]
        if not video_id and len(parts) >= 2 and parts[0] in {"shorts", "live", "embed"}:
            video_id = parts[1]
        if _SAFE_ID_RE.fullmatch(video_id):
            return f"y{video_id}"

    if is_supported_music_url(clean_url) and "|" not in clean_url:
        return f"u:{clean_url}"

    return None


def _expand_share_token(token: str) -> str | None:
    if len(token) > 1:
        kind = _SPOTIFY_CODES.get(token[0])
        item_id = token[1:]
        if kind and _SAFE_ID_RE.fullmatch(item_id):
            return f"https://open.spotify.com/{kind}/{item_id}"

    if token.startswith("y"):
        video_id = token[1:]
        if _SAFE_ID_RE.fullmatch(video_id):
            return f"https://youtu.be/{video_id}"

    if token.startswith("u:"):
        return cache_key_for_url(token[2:])

    return None
