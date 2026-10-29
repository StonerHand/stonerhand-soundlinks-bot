"""Sending a draft somewhere: publish, schedule, send to yourself, duplicates."""

from __future__ import annotations

import logging
import time
from html import escape

from telegram import (
    InlineKeyboardMarkup,
    Message,
)
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from music_links_bot.artwork.branding import (
    brand_label,
    brand_logo_url,
    build_branded_cover,
    photo_branding_enabled,
)
from music_links_bot.chat.bot_crate import (
    add_to_crate,
    crate_contains_item,
)
from music_links_bot.chat.bot_menu import (
    runtime_for as _runtime,
)
from music_links_bot.chat.bot_ui import (
    build_delivery_success_keyboard as _build_delivery_success_keyboard,
    build_duplicate_post_keyboard as _duplicate_post_keyboard,
)
from music_links_bot.core.constants import CHANNEL_USERNAME, channel_target
from music_links_bot.core.i18n import get_text
from music_links_bot.editor.bot_builder import (
    MAX_SCHEDULE_DAYS,
    schedule_timestamp,
)
from music_links_bot.editor.editor_screen import (
    EditorActionRequest,
    _edit_editor_message,
    _editor_success_text,
    _restore_editor_card,
)
from music_links_bot.editor.editor_view import (
    render_track_draft as _render_track_draft,
)
from music_links_bot.publishing.publication_service import PublicationService
from music_links_bot.publishing.publication_state import (
    find_posted_record as _find_posted_record,
    mark_posted as _schedule_mark_posted,
)
from music_links_bot.publishing.publish_queue import (
    QueueBusyError,
    QueueFullError,
    QueueStorageError,
    add_job,
)
from music_links_bot.state.bot_runtime import (
    encode_callback,
)
from music_links_bot.state.bot_storage import (
    store_draft as _store_draft,
)
from music_links_bot.tg.telegram_buttons import (
    button as InlineKeyboardButton,
)

LOGGER = logging.getLogger(__name__)


async def _schedule_editor_draft(
    query,
    context,
    action: str,
    draft: dict,
    *,
    lang: str,
    publish_at: int | None = None,
    draft_id: str | None = None,
) -> None:
    if query.from_user is None:
        await query.answer()
        return
    admin_chat_id = context.application.bot_data.get("admin_chat_id")
    if not draft.get("can_publish") or admin_chat_id != query.from_user.id:
        await query.answer(get_text(lang, "ed_admin_only"), show_alert=True)
        return
    timezone_name = str(
        context.application.bot_data.get("timezone_name") or "Europe/Moscow"
    )
    if publish_at is None:
        publish_at = schedule_timestamp(action, timezone_name=timezone_name)
    if not time.time() < publish_at <= time.time() + MAX_SCHEDULE_DAYS * 86400:
        await query.answer(get_text(lang, "schedule_stale"), show_alert=True)
        return
    try:
        await add_job(context, dict(draft), publish_at)
    except QueueFullError:
        await query.answer(get_text(lang, "ed_queue_full"), show_alert=True)
        return
    except (QueueBusyError, QueueStorageError):
        await query.answer(get_text(lang, "ed_queue_unavailable"), show_alert=True)
        return
    draft["scheduled_at"] = publish_at
    if draft_id:
        await _store_draft(context, draft_id, draft)
    from music_links_bot.core.human_time import human_datetime, local_time_html

    date = human_datetime(publish_at, timezone_name=timezone_name, lang=lang)
    await query.answer(
        get_text(lang, "schedule_done").format(date=date), show_alert=True
    )
    text, _ = _render_track_draft(draft, context, draft_id=None)
    local = local_time_html(publish_at, timezone_name=timezone_name, lang=lang)
    text = (
        f"<b>{escape(get_text(lang, 'schedule_done')).format(date=local)}</b>\n\n{text}"
    )
    await _edit_editor_message(
        query,
        context,
        draft,
        text,
        InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        get_text(lang, "home_queue"),
                        callback_data=encode_callback("queue", "open"),
                    )
                ]
            ]
        ),
    )


async def _run_primary_editor_action(request: EditorActionRequest) -> None:
    if request.action == "c":
        await _add_editor_item_to_crate(request)
        return
    if request.action == "s":
        await _send_editor_post_to_user(request)
        return
    admin_chat_id = request.context.application.bot_data.get("admin_chat_id")
    if not request.user_id or admin_chat_id != request.user_id:
        await request.query.answer(
            get_text(request.lang, "ed_admin_only"),
            show_alert=True,
        )
        await _restore_editor_card(request)
        return

    if request.action in {"r", "x"}:
        request.draft["repeat_delivery"] = True
    record = await _find_posted_record(request.context, request.track)
    if request.action == "pc" and record:
        await _show_duplicate_editor_post(request, record)
        return
    published = await _publish_draft(request.context, request.draft)
    await _finish_editor_publish(request, published)
    if request.action == "x" and record and published:
        await _delete_duplicate_editor_post(request, record)


async def _add_editor_item_to_crate(request: EditorActionRequest) -> None:
    items, added = await add_to_crate(
        request.context.application.bot_data,
        request.user_id,
        draft_id=request.draft_id,
        item=request.draft["item"],
    )
    if not added and not crate_contains_item(items, request.draft["item"]):
        await request.query.answer(
            get_text(request.lang, "ed_crate_full"), show_alert=True
        )
        await _restore_editor_card(request)
        return
    request.draft["in_crate"] = True
    request.draft["crate_count"] = len(items)
    await _store_draft(request.context, request.draft_id, request.draft)
    answer_key = "ed_crate_added" if added else "ed_crate_exists"
    await request.query.answer(
        get_text(request.lang, answer_key).format(count=len(items)),
        show_alert=False,
    )
    await _restore_editor_card(request)


async def _send_editor_post_to_user(request: EditorActionRequest) -> None:
    sent = await _deliver_draft(
        request.context,
        request.draft,
        target=request.user_id,
        channel_style=False,
    )
    await request.query.answer(
        get_text(
            request.lang,
            "ed_sent_short" if sent else "ed_publish_failed",
        ),
        show_alert=not bool(sent),
    )
    if not sent:
        await _restore_editor_card(request)
        return
    request.draft["sent_at"] = int(time.time())
    await _store_draft(request.context, request.draft_id, request.draft)
    await _show_editor_delivery_success(request)
    if request.user_id:
        session = await _runtime(request.context).get_session(
            request.user_id,
            lang=request.lang,
        )
        if session.active_draft_id == request.draft_id:
            session.active_draft_id = ""
            await _runtime(request.context).save_session(session)


async def _show_duplicate_editor_post(
    request: EditorActionRequest,
    record: dict,
) -> None:
    request.draft["duplicate_record"] = record
    await _store_draft(request.context, request.draft_id, request.draft)
    await request.query.answer(
        get_text(request.lang, "ed_duplicate").replace(
            "{date}", str(record.get("date") or "")
        ),
        show_alert=True,
    )
    text, _ = _render_track_draft(
        request.draft,
        request.context,
        draft_id=None,
    )
    await _edit_editor_message(
        request.query,
        request.context,
        request.draft,
        text,
        _duplicate_post_keyboard(
            request.draft_id,
            record,
            lang=request.lang,
        ),
    )


async def _delete_duplicate_editor_post(
    request: EditorActionRequest,
    record: dict,
) -> bool:
    message_id = record.get("message_id")
    if not isinstance(message_id, int) or message_id <= 0:
        await request.query.answer(
            get_text(request.lang, "ed_publish_failed"),
            show_alert=True,
        )
        return False
    target = channel_target(request.context.application.bot_data)
    try:
        await request.context.bot.delete_message(
            chat_id=target,
            message_id=message_id,
        )
        return True
    except TelegramError:
        await request.query.message.reply_text(
            get_text(request.lang, "old_post_not_removed")
        )
        return False


async def _finish_editor_publish(request: EditorActionRequest, published) -> None:
    if published:
        target = channel_target(request.context.application.bot_data)
        await _schedule_mark_posted(
            request.context,
            request.track,
            message=published,
            target=target,
        )
        from music_links_bot.editor.bot_publish_undo import remember_publication

        remember_publication(request.draft, published, target)
        await _store_draft(request.context, request.draft_id, request.draft)
        await _show_editor_publish_success(request, published)
        if request.user_id:
            session = await _runtime(request.context).get_session(
                request.user_id,
                lang=request.lang,
            )
            if session.active_draft_id == request.draft_id:
                session.active_draft_id = ""
                await _runtime(request.context).save_session(session)
    await request.query.answer(
        get_text(
            request.lang,
            "ed_published_toast" if published else "ed_publish_failed",
        ),
        show_alert=not bool(published),
    )
    if not published:
        await _restore_editor_card(request)


async def _show_editor_publish_success(
    request: EditorActionRequest,
    published,
) -> None:
    published_link = (
        getattr(published, "link", None) if not isinstance(published, bool) else None
    )
    from music_links_bot.chat.bot_ui import build_publish_success_keyboard
    from music_links_bot.core.human_time import local_time_html

    keyboard = build_publish_success_keyboard(
        request.draft_id,
        lang=request.lang,
        link=published_link
        if isinstance(published_link, str) and published_link.startswith("http")
        else None,
    )
    target = str(channel_target(request.context.application.bot_data))
    moment = local_time_html(
        time.time(),
        timezone_name=request.context.application.bot_data.get("timezone_name"),
        lang=request.lang,
    )
    success_text = (
        _editor_success_text(request, "ed_published")
        + "\n\n"
        + get_text(request.lang, "published_details").format(
            target=escape(target), date=moment
        )
    )
    from music_links_bot.tg.message_effects import celebrate

    await celebrate(
        request.context.bot,
        request.query,
        edit=lambda: _edit_editor_message(
            request.query, request.context, request.draft, success_text, keyboard
        ),
    )


async def _show_editor_delivery_success(request: EditorActionRequest) -> None:
    """Replace the busy editor with a small, terminal success state."""
    from music_links_bot.chat.bot_ui import draft_share_query

    await _edit_editor_message(
        request.query,
        request.context,
        request.draft,
        _editor_success_text(request, "ed_post_ready"),
        _build_delivery_success_keyboard(
            lang=request.lang,
            share_query=draft_share_query(request.draft_id),
        ),
    )


async def _publish_draft(context, draft):
    target = channel_target(context.application.bot_data)
    return await _deliver_draft(context, draft, target=target, channel_style=True)


async def _deliver_draft(context, draft, *, target, channel_style):
    from music_links_bot.publishing.delivery_receipts import (
        begin_delivery,
        finish_delivery,
    )

    intent = await begin_delivery(context, draft, target)
    service = PublicationService(
        context,
        channel_username=CHANNEL_USERNAME,
        branding_hooks=(
            photo_branding_enabled,
            build_branded_cover,
            brand_label,
            brand_logo_url,
        ),
    )
    sent = await service.deliver(draft, target=target, channel_style=channel_style)
    await finish_delivery(
        context, intent, sent=sent, confirmed_not_sent=service.confirmed_not_sent
    )
    if not sent and not service.confirmed_not_sent and intent is not None:
        from music_links_bot.publishing.delivery_receipts import DeliveryBlockedError

        raise DeliveryBlockedError({**intent[1], "status": "uncertain"})
    return sent


async def _show_delivery_recovery(request, receipt):
    from music_links_bot.publishing.publication_state import _message_url

    uncertain = receipt.get("status") != "sent"
    rows = []
    url = _message_url(receipt.get("target"), receipt.get("message_id"))
    if url:
        rows.append(
            [InlineKeyboardButton(get_text(request.lang, "duplicate_open"), url=url)]
        )
    if uncertain:
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(request.lang, "delivery_review_retry"),
                    callback_data=encode_callback(
                        "editor", "retry_review", request.draft_id
                    ),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                get_text(request.lang, "ed_back_card"),
                callback_data=encode_callback("editor", "b", request.draft_id),
            )
        ]
    )
    await request.query.answer(
        get_text(
            request.lang, "delivery_uncertain" if uncertain else "delivery_already_sent"
        ),
        show_alert=True,
    )
    await _edit_editor_message(
        request.query,
        request.context,
        request.draft,
        get_text(
            request.lang,
            "delivery_uncertain_detail" if uncertain else "delivery_already_sent",
        ),
        InlineKeyboardMarkup(rows),
    )


async def _deliver_preview_draft(
    context: ContextTypes.DEFAULT_TYPE,
    draft: dict,
    *,
    target: int | str,
) -> Message | bool | None:
    return await PublicationService(
        context,
        channel_username=CHANNEL_USERNAME,
        branding_hooks=(
            photo_branding_enabled,
            build_branded_cover,
            brand_label,
            brand_logo_url,
        ),
    ).preview(draft, target=target)
