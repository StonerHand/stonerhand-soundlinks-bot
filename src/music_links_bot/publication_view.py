from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardMarkup

from music_links_bot.constants import PLATFORM_LABELS
from music_links_bot.formatter import build_auto_hashtags, format_track_message
from music_links_bot.keyboards import _build_link_keyboard, _select_preview_url
from music_links_bot.models import TrackMatch
from music_links_bot.publication_budget import IntroBudget, compose_with_intro
from music_links_bot.text_utils import normalize_hashtag


@dataclass(slots=True, frozen=True)
class PublicationPlan:
    """One immutable rendering plan shared by preview and every delivery path."""

    text: str
    keyboard: InlineKeyboardMarkup
    intro: IntroBudget
    hashtags: str | None
    preview_url: str | None
    cover: str | None
    source_audio_file_id: str | None
    as_photo: bool
    prefer_large_preview: bool
    delivery_mode: str


# Compatibility name for callers that only consume the rendered text/keyboard.
PublicationView = PublicationPlan


def resolve_draft_hashtags(draft: dict, track: TrackMatch) -> str | None:
    """Return the one hashtag string shared by preview and every delivery path."""
    if not bool(draft.get("hashtags", True)):
        return None

    custom_tags = draft.get("custom_tags")
    if isinstance(custom_tags, list):
        tags = [
            tag for tag in (normalize_hashtag(value) for value in custom_tags) if tag
        ]
        if tags:
            return " ".join(tags)
        return None
    return build_auto_hashtags(track)


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
    max_visible_platforms: int | None = None,
) -> PublicationPlan:
    hashtags = resolve_draft_hashtags(draft, track)
    prefix = str(draft.get("prefix") or "")
    body = format_track_message(
        track,
        include_hashtags=hashtags is not None,
        hashtags=hashtags,
    )
    text, intro = compose_with_intro(
        draft,
        prefix_html=prefix,
        body_html=body,
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
    source_audio_file_id = draft.get("source_audio_file_id")
    if not isinstance(source_audio_file_id, str) or not source_audio_file_id:
        source_audio_file_id = None
    custom_cover = draft.get("custom_cover_file_id")
    cover = custom_cover if isinstance(custom_cover, str) and custom_cover else None
    cover = cover or track.thumbnail_url
    return PublicationPlan(
        text=text,
        keyboard=keyboard,
        intro=intro,
        hashtags=hashtags,
        preview_url=_select_preview_url(track.links, context) or track.thumbnail_url,
        cover=cover,
        source_audio_file_id=source_audio_file_id,
        as_photo=bool(draft.get("as_photo")),
        prefer_large_preview=bool(draft.get("large_preview")),
        delivery_mode=(
            "classic" if draft.get("delivery_mode") == "classic" else "auto"
        ),
    )
