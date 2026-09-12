from __future__ import annotations

from html import escape
from typing import Any

from telegram import InlineKeyboardMarkup

from music_links_bot.bot_builder import MESSAGE_TEXT_LIMIT, fit_telegram_html
from music_links_bot.bot_editor_state import draft_status
from music_links_bot.bot_ui import editor_rows, version_editor_keyboard
from music_links_bot.i18n import get_text, resolve_lang
from music_links_bot.models import TrackMatch
from music_links_bot.publication_budget import visible_length
from music_links_bot.publication_preflight import validate_publication
from music_links_bot.publication_view import build_publication_view
from music_links_bot.sharing import add_share_button, build_share_query, track_share_url


def render_track_draft(
    draft: dict,
    context: Any,
    *,
    draft_id: str | None = None,
    settings: bool = False,
    show_status: bool = False,
) -> tuple[str, InlineKeyboardMarkup]:
    """Render the canonical editor card and its context-aware actions."""
    track = TrackMatch(**draft["item"])
    view = build_publication_view(
        draft,
        track,
        context=context,
        include_channel_button=False,
        max_visible_platforms=1 if draft_id is not None else None,
    )
    text = view.text
    draft["intro_length"] = view.intro.used
    draft["intro_limit"] = view.intro.limit
    draft["intro_truncated"] = view.intro.truncated

    lang = resolve_lang(draft.get("lang") or "ru")
    # Legacy settings/back callbacks share the same editor card.
    if draft_id is not None:
        text = (
            get_text(
                lang,
                "workspace_editing"
                if settings
                else "workspace_published"
                if draft.get("published_at")
                else "workspace_sent"
                if draft.get("sent_at")
                else "workspace_ready",
            )
            + "\n\n"
            + text
        )
        notices = []
        preflight = validate_publication(draft, track)
        if not preflight.ready:
            notices.append(get_text(lang, f"ed_preflight_{preflight.blocking_code}"))
        if view.intro.truncated:
            notices.append(get_text(lang, "ed_intro_will_trim"))
        if settings or show_status:
            notices.append(draft_status(draft, track, lang=lang))
        if notices:
            text += "\n\n<i>" + escape("\n".join(notices)) + "</i>"
        if visible_length(text) > MESSAGE_TEXT_LIMIT:
            hint = get_text(lang, "editor_short_view")
            text = (
                fit_telegram_html(text, MESSAGE_TEXT_LIMIT - visible_length(hint) - 2)
                + "\n\n"
                + hint
            )

    keyboard = view.keyboard
    if draft_id is None:
        source_url = track_share_url(track)
        return text, add_share_button(
            keyboard,
            share_query=build_share_query([source_url] if source_url else []),
            label=get_text(lang, "share_post"),
        )

    return text, version_editor_keyboard(
        InlineKeyboardMarkup(editor_rows(draft_id, draft, settings=settings)), draft
    )


def draft_intro_limit(draft: dict, context: Any) -> int:
    """Calculate the intro budget without changing the current draft."""
    preview = dict(draft)
    preview["prefix"] = ""
    preview["quote"] = False
    track = TrackMatch(**preview["item"])
    return build_publication_view(
        preview,
        track,
        context=context,
        include_channel_button=False,
    ).intro.limit
