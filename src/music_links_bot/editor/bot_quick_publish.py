"""Owner's quick publish: a link becomes a channel post without the editor."""

from __future__ import annotations

import logging

from telegram.constants import ParseMode

from music_links_bot.core.constants import channel_target
from music_links_bot.core.i18n import get_text

LOGGER = logging.getLogger(__name__)


async def try_quick_publish(message, context, *, draft_id, draft, track, user_id):
    """Publish now when the owner enabled it; return True if the post went out.

    A release that was already posted is never re-published silently: the
    normal card appears instead, with the usual duplicate warning on publish.
    """
    if not draft.get("can_publish"):
        return False
    from music_links_bot.chat.bot_menu import runtime_for as _runtime
    from music_links_bot.editor.editor_delivery import _publish_draft
    from music_links_bot.publishing.publication_state import (
        find_posted_record as _find_posted_record,
        mark_posted as _schedule_mark_posted,
    )
    from music_links_bot.state.bot_storage import store_draft as _store_draft

    session = await _runtime(context).get_session(user_id, lang=draft.get("lang"))
    if not session.quick_publish:
        return False
    if await _find_posted_record(context, track):
        return False
    from music_links_bot.chat.bot_ui import build_publish_success_keyboard
    from music_links_bot.editor.bot_publish_undo import remember_publication
    from music_links_bot.publishing.publication_state import _message_url

    target = channel_target(context.application.bot_data)
    published = await _publish_draft(context, draft)
    if not published:
        return False
    await _schedule_mark_posted(context, track, message=published, target=target)
    remember_publication(draft, published, target)
    await _store_draft(context, draft_id, draft)
    lang = draft.get("lang") or "ru"
    link = getattr(published, "link", None) or _message_url(
        target, getattr(published, "message_id", None)
    )
    from music_links_bot.tg.message_effects import send_with_effect

    await send_with_effect(
        message.reply_text,
        text=get_text(lang, "quick_published").format(
            artist=_escape(track.artist), title=_escape(track.title)
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=build_publish_success_keyboard(
            draft_id,
            lang=lang,
            link=link if isinstance(link, str) and link.startswith("http") else None,
        ),
    )
    return True


def _escape(value: str) -> str:
    from html import escape

    return escape(value or "")
