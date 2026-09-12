"""Focused workspace actions: save, restore and explain a post."""

from __future__ import annotations

import time
from html import escape

from telegram import InlineKeyboardMarkup

from music_links_bot.bot_editor_state import reset_original
from music_links_bot.bot_runtime import encode_callback
from music_links_bot.bot_storage import load_drafts, store_draft, valid_state_id
from music_links_bot.i18n import get_text
from music_links_bot.publication_view import resolve_draft_hashtags
from music_links_bot.release_preferences import (
    current_presentation,
    release_preference_key,
)
from music_links_bot.release_tags import genre_hashtags, release_type
from music_links_bot.telegram_buttons import button


def tag_explanation(draft, track, lang):
    manual = (
        "custom_tags" in draft
        or release_preference_key(track) in current_presentation.get().tags
    )
    selected = resolve_draft_hashtags(draft, track) or get_text(
        lang, "ed_status_tags_none"
    )
    return get_text(lang, "tag_explanation").format(
        selected=escape(selected),
        mode=get_text(lang, "tags_manual" if manual else "tags_auto"),
        kind=escape("#" + release_type(track)),
        genre=escape(track.genre or get_text(lang, "tags_genre_missing")),
        genre_tags=escape(" ".join(genre_hashtags(track.genre)) or "—"),
    )


async def handle_workspace_action(request):
    from music_links_bot.bot import (
        _edit_editor_message,
        _handle_editor_navigation,
        _runtime,
    )

    action, draft, lang = request.action, request.draft, request.lang
    if action in {"retry_review", "retry_self", "retry_channel"}:
        from music_links_bot.bot import _run_locked_editor_action
        from music_links_bot.constants import CHANNEL_USERNAME
        from music_links_bot.delivery_receipts import load_delivery

        target = (
            request.user_id
            if action == "retry_self"
            else request.context.application.bot_data.get("publish_chat_id")
            or f"@{CHANNEL_USERNAME}"
        )
        if action == "retry_review":
            rows = []
            for destination, retry_action in (
                (request.user_id, "retry_self"),
                (target, "retry_channel"),
            ):
                if (
                    retry_action == "retry_channel"
                    and request.context.application.bot_data.get("admin_chat_id")
                    != request.user_id
                ):
                    continue
                receipt = await load_delivery(
                    request.context, request.draft_id, destination
                )
                if receipt and receipt.get("status") in {"sending", "uncertain"}:
                    rows.append(
                        [
                            button(
                                get_text(lang, "delivery_retry_confirm"),
                                callback_data=encode_callback(
                                    "editor", retry_action, request.draft_id
                                ),
                                style="danger",
                            )
                        ]
                    )
            rows.append(
                [
                    button(
                        get_text(lang, "ed_back_card"),
                        callback_data=encode_callback("editor", "b", request.draft_id),
                    )
                ]
            )
            await request.query.answer()
            await _edit_editor_message(
                request.query,
                request.context,
                draft,
                get_text(lang, "delivery_retry_question"),
                InlineKeyboardMarkup(rows),
            )
            return True
        if (
            action == "retry_channel"
            and request.context.application.bot_data.get("admin_chat_id")
            != request.user_id
        ):
            await request.query.answer(get_text(lang, "ed_admin_only"), show_alert=True)
            return True
        receipt = await load_delivery(request.context, request.draft_id, target)
        if not receipt or receipt.get("status") not in {"sending", "uncertain"}:
            await request.query.answer(
                get_text(lang, "delivery_already_sent"), show_alert=True
            )
            return True
        draft["repeat_delivery"] = "reviewed"
        request.action = "s" if action == "retry_self" else "pc"
        await _run_locked_editor_action(request)
        return True
    if action not in {"sv", "reset", "reset_yes", "why_tags"}:
        return False

    def cb(key, action, **kwargs):
        return button(
            get_text(lang, key),
            callback_data=encode_callback("editor", action, request.draft_id),
            **kwargs,
        )

    if action in {"reset", "why_tags"}:
        text = (
            get_text(lang, "ed_reset_question")
            if action == "reset"
            else tag_explanation(draft, request.track, lang)
        )
        rows = (
            [[cb("ed_reset_confirm", "reset_yes", style="danger")]]
            if action == "reset"
            else []
        )
        rows.append([cb("ed_back_card", "m" if action == "reset" else "hs")])
        await request.query.answer()
        await _edit_editor_message(
            request.query, request.context, draft, text, InlineKeyboardMarkup(rows)
        )
        return True
    if action == "reset_yes":
        if not reset_original(draft):
            await request.query.answer(
                get_text(lang, "ed_original_missing"), show_alert=True
            )
            return True
        await store_draft(request.context, request.draft_id, draft)
        notice = get_text(lang, "settings_restored")
    else:
        runtime = _runtime(request.context)
        session = await runtime.get_session(request.user_id, lang=lang)
        saved_ids = list(
            dict.fromkeys(v for v in session.saved_draft_ids if valid_state_id(v))
        )
        values = await load_drafts(request.context, saved_ids)
        saved = [
            key
            for key, value in zip(saved_ids, values, strict=True)
            if value
            and value.get("saved_at")
            and not value.get("deleted_at")
            and value.get("chat_id") == request.user_id
        ]
        if (
            not draft.get("saved_at")
            and request.draft_id not in saved
            and len(saved) >= 30
        ):
            await request.query.answer(get_text(lang, "ed_save_limit"), show_alert=True)
            return True
        if draft.get("saved_at"):
            draft.pop("saved_at", None)
            session.saved_draft_ids = [v for v in saved if v != request.draft_id]
            notice = get_text(lang, "ed_unsaved_notice")
        else:
            draft["saved_at"] = int(time.time())
            session.saved_draft_ids = [
                request.draft_id,
                *(v for v in saved if v != request.draft_id),
            ][:30]
            notice = get_text(lang, "ed_saved_notice")
        await store_draft(request.context, request.draft_id, draft)
        await runtime.save_session(session)
    await _handle_editor_navigation(
        request.query,
        request.context,
        action="m" if action == "reset_yes" else "b",
        draft_id=request.draft_id,
        draft=draft,
        lang=lang,
        answer_text=notice,
    )
    return True
