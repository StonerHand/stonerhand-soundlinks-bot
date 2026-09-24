"""Shared rendering and validation for collection preview and publication."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any

from telegram import InlineKeyboardMarkup

from music_links_bot.collection_collage import (
    branded_artwork_preview_url,
    collection_collage_preview_url,
)
from music_links_bot.formatter import format_collection_message
from music_links_bot.i18n import get_text
from music_links_bot.keyboards import _build_collection_keyboard, _select_preview_url
from music_links_bot.models import TrackMatch
from music_links_bot.publication_budget import compose_with_intro
from music_links_bot.url_utils import cache_key_for_url, is_platform_destination_url


@dataclass(frozen=True, slots=True)
class CollectionIssue:
    index: int
    code: str
    blocking: bool = False


@dataclass(frozen=True, slots=True)
class CollectionPlan:
    text: str
    keyboard: InlineKeyboardMarkup
    preview_url: str | None
    source_urls: tuple[str, ...]


def collection_issues(items: list[dict]) -> tuple[CollectionIssue, ...]:
    issues = []
    seen_urls: set[str] = set()
    seen_titles: set[tuple[str, str, str]] = set()
    for index, entry in enumerate(items, 1):
        item = entry.get("item") or {}
        if not isinstance(item, dict):
            issues.append(CollectionIssue(index, "metadata", True))
            continue
        artist = str(item.get("artist") or "").strip()
        title = str(item.get("title") or "").strip()
        links = item.get("links") or {}
        urls = (
            {
                cache_key_for_url(url)
                for platform, url in links.items()
                if isinstance(url, str) and is_platform_destination_url(platform, url)
            }
            if isinstance(links, dict)
            else set()
        )
        if not artist or not title or not urls:
            issues.append(CollectionIssue(index, "metadata", True))
        if not item.get("thumbnail_url"):
            issues.append(CollectionIssue(index, "cover"))
        identity = (
            artist.casefold(),
            title.casefold(),
            str(item.get("kind") or "song"),
        )
        if urls & seen_urls or (artist and title and identity in seen_titles):
            issues.append(CollectionIssue(index, "duplicate"))
        seen_urls.update(urls)
        if artist and title:
            seen_titles.add(identity)
    return tuple(issues)


def collection_check_text(items: list[dict], lang: str) -> str:
    issues = collection_issues(items)
    if not issues:
        return get_text(lang, "collection_check_ok")
    lines = [get_text(lang, "collection_check_title")]
    lines.extend(
        get_text(lang, "collection_check_" + issue.code).format(index=issue.index)
        for issue in issues
    )
    return escape("\n".join(lines))


def build_collection_plan(
    tracks: list[TrackMatch],
    *,
    context: Any = None,
    title: str,
    include_hashtags: bool = True,
    include_channel_button: bool = True,
    intro_html: str = "",
    complete: bool = True,
) -> CollectionPlan:
    body = format_collection_message(
        tracks, include_hashtags=include_hashtags, title=title
    )
    text, _ = compose_with_intro(
        {"quote": bool(intro_html)}, prefix_html=intro_html, body_html=body
    )
    preview = collection_collage_preview_url(tracks) if complete else None
    if tracks:
        preview = preview or branded_artwork_preview_url(tracks[0].thumbnail_url)
        preview = (
            preview
            or _select_preview_url(tracks[0].links, context)
            or tracks[0].thumbnail_url
        )
    return CollectionPlan(
        text=text,
        keyboard=_build_collection_keyboard(
            tracks, include_channel_button=include_channel_button
        ),
        preview_url=preview,
        source_urls=tuple(url for track in tracks for url in track.links.values()),
    )
