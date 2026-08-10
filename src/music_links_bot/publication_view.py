from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardMarkup

from music_links_bot.constants import PLATFORM_LABELS
from music_links_bot.formatter import format_track_message
from music_links_bot.keyboards import _build_link_keyboard
from music_links_bot.models import TrackMatch
from music_links_bot.text_utils import normalize_hashtag


@dataclass(slots=True, frozen=True)
class PublicationView:
    text: str
    keyboard: InlineKeyboardMarkup


def draft_message_overrides(
    draft: dict,
    *,
    include_hashtags: bool,
) -> tuple[bool, dict]:
    """Custom draft tags replace generated house tags."""
    overrides: dict = {}
    custom_tags = draft.get("custom_tags")
    if isinstance(custom_tags, list):
        tags = [
            tag for tag in (normalize_hashtag(value) for value in custom_tags) if tag
        ]
        if tags:
            overrides["hashtags"] = " ".join(tags)
        else:
            include_hashtags = False
    return include_hashtags, overrides


def draft_platform_selection(draft: dict) -> list[str] | None:
    platforms = draft.get("platforms")
    if not isinstance(platforms, list):
        return None
    selection = [
        key for key in platforms if isinstance(key, str) and key in PLATFORM_LABELS
    ]
    if selection:
        return selection
    return [] if not platforms else None


def build_publication_view(
    draft: dict,
    track: TrackMatch,
    *,
    context,
    include_channel_button: bool,
    channel_style: bool = False,
    max_visible_platforms: int | None = None,
) -> PublicationView:
    include_hashtags, overrides = draft_message_overrides(
        draft,
        include_hashtags=(True if channel_style else bool(draft.get("hashtags", True))),
    )
    prefix = str(draft.get("prefix") or "")
    text = (prefix if draft.get("quote") and prefix else "") + format_track_message(
        track,
        include_hashtags=include_hashtags,
        **overrides,
    )
    keyboard = _build_link_keyboard(
        track.links,
        context=context,
        include_channel_button=include_channel_button,
        release_page_url=track.page_url,
        release_kind=track.kind,
        release_format=track.release_format,
        platform_selection=draft_platform_selection(draft),
        max_visible_platforms=max_visible_platforms,
    )
    return PublicationView(text=text, keyboard=keyboard)
