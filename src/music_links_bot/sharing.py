from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

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
from music_links_bot.url_utils import cache_key_for_url, is_supported_music_url

SHARE_QUERY_PREFIX = "sh|"
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
    if not urls or len(urls) > MAX_SHARE_ITEMS:
        return None

    tokens: list[str] = []
    for url in urls:
        token = _compact_share_url(url)
        if token is None:
            return None
        tokens.append(token)

    query = SHARE_QUERY_PREFIX + "|".join(tokens)
    return query if len(query) <= MAX_SHARE_QUERY_LENGTH else None


def parse_share_query(query: str) -> list[str] | None:
    if not query.startswith(SHARE_QUERY_PREFIX):
        return None

    raw_tokens = query[len(SHARE_QUERY_PREFIX) :].split("|")
    if not raw_tokens or len(raw_tokens) > MAX_SHARE_ITEMS:
        return []

    urls: list[str] = []
    for token in raw_tokens:
        url = _expand_share_token(token)
        if url is None or not is_supported_music_url(url):
            return []
        urls.append(url)
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
                    api_kwargs={"style": "primary"},
                )
            ],
        ]
    )


def render_inline_share_card(
    bundle: Any,
    *,
    context: Any,
    lang: str,
    share_query: str | None,
    share_label: str,
) -> InlineShareCard:
    preview_url = _bundle_preview_url(bundle, context)

    if bundle.content_type_count == 1 and bundle.tracks:
        text = format_collection_message(bundle.tracks, include_hashtags=True)
        keyboard = _build_collection_keyboard(bundle.tracks)
        title = _collection_title(lang, len(bundle.tracks), "release")
    elif bundle.content_type_count == 1 and bundle.videos:
        text = format_video_collection_message(bundle.videos, include_hashtags=True)
        keyboard = _build_youtube_collection_keyboard(bundle.videos)
        title = _collection_title(lang, len(bundle.videos), "video")
    elif bundle.content_type_count == 1 and bundle.radios:
        text = format_radio_collection_message(bundle.radios, include_hashtags=True)
        keyboard = _build_nts_collection_keyboard(bundle.radios)
        title = _collection_title(lang, len(bundle.radios), "radio")
    elif bundle.content_type_count == 1 and bundle.playlists:
        text = format_playlist_collection_message(
            bundle.playlists, include_hashtags=True
        )
        keyboard = _build_playlist_collection_keyboard(bundle.playlists)
        title = _collection_title(lang, len(bundle.playlists), "playlist")
    elif bundle.content_type_count == 1 and bundle.artists:
        text = format_artist_collection_message(
            bundle.artists, include_hashtags=True
        )
        keyboard = _build_artist_collection_keyboard(bundle.artists)
        title = _collection_title(lang, len(bundle.artists), "artist")
    else:
        text = format_mixed_collection_message(
            bundle.tracks,
            bundle.videos,
            bundle.playlists,
            bundle.artists,
            bundle.radios,
            include_hashtags=True,
        )
        keyboard = _build_mixed_collection_keyboard(
            bundle.tracks,
            bundle.videos,
            bundle.playlists,
            bundle.artists,
            bundle.radios,
        )
        title = _collection_title(lang, bundle.item_count, "item")

    return InlineShareCard(
        title=title,
        description=(
            "Ready-to-share post with every button"
            if lang == "en"
            else "Готовый пост со всеми кнопками"
        ),
        text=text,
        keyboard=add_share_button(
            keyboard,
            share_query=share_query,
            label=share_label,
        ),
        preview_url=preview_url,
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


def _collection_title(lang: str, count: int, item_kind: str) -> str:
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
