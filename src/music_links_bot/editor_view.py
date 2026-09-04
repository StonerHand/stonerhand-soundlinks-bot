from __future__ import annotations

from html import escape
from typing import Any

from telegram import InlineKeyboardMarkup

from music_links_bot.bot_editor_state import draft_status
from music_links_bot.bot_ui import editor_more_rows, editor_rows
from music_links_bot.i18n import get_text
from music_links_bot.models import TrackMatch
from music_links_bot.publication_preflight import validate_publication
from music_links_bot.publication_view import build_publication_view
from music_links_bot.sharing import add_share_button, build_share_query, track_share_url
from music_links_bot.telegram_buttons import url_button


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

    lang = draft.get("lang") or "ru"
    if settings:
        status = draft_status(draft, track, lang=lang)
        preflight = validate_publication(draft, track)
        if not preflight.ready:
            preflight_status = get_text(
                lang,
                f"ed_preflight_{preflight.blocking_code}",
            )
        elif preflight.warning_count:
            preflight_status = get_text(lang, "ed_preflight_warnings").format(
                count=preflight.warning_count
            )
        else:
            preflight_status = ""
        intro_status = ""
        if view.intro.used:
            intro_status = "\n" + get_text(lang, "ed_intro_counter").format(
                used=view.intro.used,
                limit=view.intro.limit,
            )
            if view.intro.truncated:
                intro_status += "\n" + get_text(lang, "ed_intro_will_trim")
        preflight_line = (
            f"\n<b>{escape(preflight_status)}</b>" if preflight_status else ""
        )
        text = (
            f"🎛 <b>{escape(get_text(lang, 'ed_constructor_title'))}</b>\n"
            f"<i>{escape(get_text(lang, 'ed_constructor_hint'))}</i>\n"
            f"<i>{escape(status + intro_status)}</i>"
            f"{preflight_line}\n\n{text}"
        )
    elif show_status:
        text = f"{text}\n\n<i>{escape(draft_status(draft, track, lang=lang))}</i>"

    keyboard = view.keyboard
    if draft_id is None:
        source_url = track_share_url(track)
        return text, add_share_button(
            keyboard,
            share_query=build_share_query([source_url] if source_url else []),
            label=get_text(lang, "share_post"),
        )

    # The editor uses one accent action per screen. Platform links remain
    # neutral here; their brand styling is kept in the finished publication.
    # Preserve the finished card's row hierarchy: the universal hub stays on
    # its own line and a provider shortcut never competes for the same tap area.
    link_rows = [
        [
            url_button(button.text, button.url) if button.url else button
            for button in row
        ]
        for row in keyboard.inline_keyboard[:2]
    ]
    rows = [row for row in link_rows if row]
    rows.extend(
        editor_more_rows(draft_id, draft) if settings else editor_rows(draft_id, draft)
    )
    return text, InlineKeyboardMarkup(rows)


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
