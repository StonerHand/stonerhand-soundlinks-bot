"""Short "undo" window right after a channel publication."""

from __future__ import annotations

import logging
import time

from telegram.error import TelegramError

from music_links_bot.core.i18n import get_text

LOGGER = logging.getLogger(__name__)
UNDO_PUBLISH_SECONDS = 120


def can_undo_publish(draft: dict, *, now: float | None = None) -> bool:
    published_at = draft.get("published_at")
    return (
        isinstance(published_at, (int, float))
        and isinstance(draft.get("published_message_id"), int)
        and draft.get("published_target") is not None
        and (time.time() if now is None else now) - published_at <= UNDO_PUBLISH_SECONDS
    )


def remember_publication(draft: dict, message, target) -> None:
    message_id = getattr(message, "message_id", None)
    draft["published_at"] = int(time.time())
    if isinstance(message_id, int):
        draft["published_message_id"] = message_id
        draft["published_target"] = target


async def handle_unpublish(request) -> bool:
    """Delete the post from the channel and turn the card back into a draft."""
    if request.action != "un":
        return False
    from music_links_bot.editor.editor_view import render_track_draft
    from music_links_bot.publishing.delivery_receipts import forget_delivery
    from music_links_bot.state.publication_state import forget_posted

    draft = request.draft
    if not can_undo_publish(draft):
        await request.query.answer(
            get_text(request.lang, "unpublish_expired"), show_alert=True
        )
        return True
    target = draft["published_target"]
    try:
        await request.context.bot.delete_message(
            chat_id=target, message_id=draft["published_message_id"]
        )
    except TelegramError:
        LOGGER.info("Could not delete a just-published post", exc_info=True)
        await request.query.answer(
            get_text(request.lang, "unpublish_failed"), show_alert=True
        )
        return True
    for key in ("published_at", "published_message_id", "published_target"):
        draft.pop(key, None)
    await forget_posted(request.context, request.track, target)
    await forget_delivery(request.context, request.draft_id, target)
    from music_links_bot.state.bot_storage import store_draft

    await store_draft(request.context, request.draft_id, draft)
    await request.query.answer(get_text(request.lang, "unpublished"))
    text, keyboard = render_track_draft(
        draft, request.context, draft_id=request.draft_id
    )
    from music_links_bot.editor.editor_screen import _edit_editor_message

    await _edit_editor_message(request.query, request.context, draft, text, keyboard)
    return True
