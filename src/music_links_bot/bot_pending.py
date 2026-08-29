from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from html import escape

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from music_links_bot.bot_builder import (
    PENDING_INPUT_TTL_SECONDS,
    apply_custom_tags,
    apply_intro_html,
    format_schedule_datetime,
    normalize_crate_title,
    parse_schedule_datetime,
)
from music_links_bot.bot_crate import load_crate, load_crate_title, save_crate_title
from music_links_bot.bot_editor_state import draft_owned_by, remember_setting_state
from music_links_bot.bot_menu import runtime_for, update_lang
from music_links_bot.bot_stats import message_entities, message_text
from music_links_bot.bot_storage import (
    load_draft,
    load_retry_sources,
    store_draft,
)
from music_links_bot.bot_ui import render_crate
from music_links_bot.channel_templates import save_channel_template
from music_links_bot.editor_view import draft_intro_limit, render_track_draft
from music_links_bot.i18n import get_text
from music_links_bot.keyboards import (
    _build_link_preview_options as build_link_preview_options,
    _select_preview_url as select_preview_url,
)
from music_links_bot.models import TrackMatch
from music_links_bot.publication_presets import save_named_preset
from music_links_bot.publish_queue import (
    QueueBusyError,
    QueueFullError,
    QueueStorageError,
    add_job,
)
from music_links_bot.telegram_text import format_user_note_html, telegram_text_length
from music_links_bot.url_utils import extract_supported_urls, strip_supported_urls

LOGGER = logging.getLogger(__name__)

RetryLookup = Callable[[object, ContextTypes.DEFAULT_TYPE, list[str]], Awaitable[None]]
_DRAFT_INPUT_KINDS = frozenset(
    {"intro", "hashtags", "schedule", "cover", "template_name"}
)


@dataclass(slots=True, frozen=True)
class DraftInputResult:
    saved_key: str | None = None
    schedule_label: str | None = None
    clear_pending: bool = False


async def consume_pending_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    retry_lookup: RetryLookup,
) -> bool:
    """Consume one native Force Reply value and restore its original editor."""
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or message.chat.type != "private":
        return False

    lang = update_lang(update)
    runtime = runtime_for(context)
    session = await runtime.get_session(user.id, lang=lang)
    pending = session.pending_input
    if not pending:
        return False
    if _pending_expired(pending):
        await _clear_pending(runtime, session)
        return False

    kind = str(pending.get("kind") or "")
    value = (message_text(message) or "").strip()
    if not value and kind != "cover":
        return True
    if kind == "replace_source":
        return await _replace_failed_source(
            message,
            context,
            user_id=user.id,
            lang=lang,
            pending=pending,
            value=value,
            runtime=runtime,
            session=session,
            retry_lookup=retry_lookup,
        )

    draft_id = str(pending.get("draft_id") or "")
    draft = await load_draft(context, draft_id) if draft_id else None
    schedule_label: str | None = None
    if kind in _DRAFT_INPUT_KINDS:
        if draft is None:
            await _clear_pending(runtime, session)
            await message.reply_text(get_text(lang, "ed_expired"))
            return True
        if not draft_owned_by(draft, user.id):
            await _clear_pending(runtime, session)
            await message.reply_text(get_text(lang, "ed_owner_only"))
            return True
        result = await _apply_draft_input(
            message,
            context,
            user_id=user.id,
            kind=kind,
            value=value,
            draft=draft,
            lang=lang,
        )
        if result.saved_key is None:
            if result.clear_pending:
                await _clear_pending(runtime, session)
            return True
        saved_key = result.saved_key
        schedule_label = result.schedule_label
        await store_draft(context, draft_id, draft)
        if kind not in {"schedule", "cover", "template_name"}:
            await save_channel_template(context, f"user:{user.id}", draft)
    elif kind == "crate_title":
        await save_crate_title(
            context.application.bot_data,
            user.id,
            normalize_crate_title(value),
        )
        saved_key = "crate_name_saved"
    else:
        await _clear_pending(runtime, session)
        return False

    await _clear_pending(runtime, session)
    await _delete_prompt(context, message, pending)
    if kind == "crate_title":
        await _restore_crate_screen(
            message,
            context,
            user_id=user.id,
            lang=lang,
            pending=pending,
            saved_key=saved_key,
        )
    elif draft is not None:
        await _restore_draft_screen(
            message,
            context,
            draft_id=draft_id,
            draft=draft,
            lang=lang,
            pending=pending,
            saved_key=saved_key,
            schedule_label=schedule_label,
        )
    return True


def _pending_expired(pending: dict) -> bool:
    created_at = int(pending.get("created_at") or 0)
    return not created_at or time.time() - created_at > PENDING_INPUT_TTL_SECONDS


async def _clear_pending(runtime, session) -> None:
    session.pending_input = {}
    await runtime.save_session(session)


async def _replace_failed_source(
    message,
    context,
    *,
    user_id: int,
    lang: str,
    pending: dict,
    value: str,
    runtime,
    session,
    retry_lookup: RetryLookup,
) -> bool:
    replacement_urls = extract_supported_urls(value)
    payload = await load_retry_sources(context, str(pending.get("retry_id") or ""))
    source_index = int(pending.get("source_index") or 0) - 1
    original_urls = (
        [str(url) for url in payload.get("urls", []) if isinstance(url, str)]
        if isinstance(payload, dict) and int(payload.get("user_id") or 0) == user_id
        else []
    )
    if len(replacement_urls) != 1 or not 0 <= source_index < len(original_urls):
        await message.reply_text(get_text(lang, "replace_source_invalid"))
        return True
    original_urls[source_index] = replacement_urls[0]
    await _clear_pending(runtime, session)
    await _delete_prompt(context, message, pending)
    await retry_lookup(message, context, original_urls)
    return True


async def _apply_draft_input(
    message,
    context,
    *,
    user_id: int,
    kind: str,
    value: str,
    draft: dict,
    lang: str,
) -> DraftInputResult:
    if kind == "cover":
        photos = list(getattr(message, "photo", ()) or ())
        if not photos:
            await message.reply_text(get_text(lang, "ed_cover_invalid"))
            return DraftInputResult()
        remember_setting_state(draft)
        cover = photos[-1]
        draft["custom_cover_file_id"] = str(cover.file_id)
        if unique_id := getattr(cover, "file_unique_id", None):
            draft["custom_cover_unique_id"] = str(unique_id)
        draft["as_photo"] = True
        return DraftInputResult("ed_cover_saved")
    if kind == "template_name":
        await save_named_preset(context, user_id, value, draft)
        return DraftInputResult("ed_template_saved")
    if kind == "intro":
        remember_setting_state(draft)
        limit = draft_intro_limit(draft, context)
        visible_source = strip_supported_urls(value).strip()
        visible_length = telegram_text_length(visible_source)
        apply_intro_html(
            draft,
            format_user_note_html(value, message_entities(message), max_length=limit),
            visible_length=min(visible_length, limit),
            max_length=limit,
            truncated=visible_length > limit,
        )
        return DraftInputResult("ed_intro_saved")
    if kind == "hashtags":
        remember_setting_state(draft)
        apply_custom_tags(draft, value)
        return DraftInputResult("ed_tags_saved")
    return await _schedule_custom_time(
        message,
        context,
        user_id=user_id,
        value=value,
        draft=draft,
        lang=lang,
    )


async def _schedule_custom_time(
    message,
    context,
    *,
    user_id: int,
    value: str,
    draft: dict,
    lang: str,
) -> DraftInputResult:
    timezone_name = str(
        context.application.bot_data.get("timezone_name") or "Europe/Moscow"
    )
    publish_at = parse_schedule_datetime(value, timezone_name=timezone_name)
    if publish_at is None:
        await message.reply_text(
            get_text(lang, "schedule_invalid"),
            parse_mode=ParseMode.HTML,
        )
        return DraftInputResult()
    admin_chat_id = context.application.bot_data.get("admin_chat_id")
    if not draft.get("can_publish") or admin_chat_id != user_id:
        await message.reply_text(get_text(lang, "ed_admin_only"))
        return DraftInputResult(clear_pending=True)
    try:
        await add_job(context, dict(draft), publish_at)
    except QueueFullError:
        await message.reply_text(get_text(lang, "ed_queue_full"))
        return DraftInputResult()
    except (QueueBusyError, QueueStorageError):
        await message.reply_text(get_text(lang, "ed_queue_unavailable"))
        return DraftInputResult()
    return DraftInputResult(
        "schedule_done",
        format_schedule_datetime(publish_at, timezone_name=timezone_name),
    )


async def _delete_prompt(context, message, pending: dict) -> None:
    message_id = pending.get("prompt_message_id")
    if not isinstance(message_id, int) or message_id <= 0:
        return
    try:
        await context.bot.delete_message(
            chat_id=int(pending.get("editor_chat_id") or message.chat_id),
            message_id=message_id,
        )
    except TelegramError:
        LOGGER.debug("Could not clean up native editor input", exc_info=True)


async def _restore_crate_screen(
    message,
    context,
    *,
    user_id: int,
    lang: str,
    pending: dict,
    saved_key: str,
) -> None:
    items = await load_crate(context.application.bot_data, user_id)
    title = await load_crate_title(context.application.bot_data, user_id)
    text, keyboard = render_crate(items, lang=lang, title=title)
    text = f"<b>{escape(get_text(lang, saved_key))}</b>\n\n{text}"
    restored = await edit_pending_screen(
        context,
        chat_id=int(pending.get("editor_chat_id") or message.chat_id),
        message_id=pending.get("editor_message_id"),
        text=text,
        keyboard=keyboard,
    )
    if not restored:
        await message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )


async def _restore_draft_screen(
    message,
    context,
    *,
    draft_id: str,
    draft: dict,
    lang: str,
    pending: dict,
    saved_key: str,
    schedule_label: str | None,
) -> None:
    text, keyboard = render_track_draft(
        draft,
        context,
        draft_id=draft_id,
        settings=True,
        show_status=True,
    )
    saved_label = (
        get_text(lang, saved_key).format(date=schedule_label)
        if saved_key == "schedule_done"
        else get_text(lang, saved_key)
    )
    text = f"<b>{escape(saved_label)}</b>\n\n{text}"
    track = TrackMatch(**draft["item"])
    preview_url = select_preview_url(track.links, context) or track.thumbnail_url
    restored = await edit_pending_screen(
        context,
        chat_id=int(pending.get("editor_chat_id") or message.chat_id),
        message_id=pending.get("editor_message_id"),
        text=text,
        keyboard=keyboard,
        preview_url=preview_url,
        prefer_large_preview=bool(draft.get("large_preview")),
    )
    if not restored:
        await message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            link_preview_options=build_link_preview_options(
                preview_url,
                prefer_large_media=bool(draft.get("large_preview")),
            ),
            reply_markup=keyboard,
        )


async def edit_pending_screen(
    context,
    *,
    chat_id: int,
    message_id: object,
    text: str,
    keyboard,
    preview_url: str | None = None,
    prefer_large_preview: bool = False,
) -> bool:
    if not isinstance(message_id, int) or message_id <= 0:
        return False
    edit = getattr(context.bot, "edit_message_text", None)
    if not callable(edit):
        return False
    try:
        kwargs = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": ParseMode.HTML,
            "reply_markup": keyboard,
        }
        options = build_link_preview_options(
            preview_url,
            prefer_large_media=prefer_large_preview,
        )
        if options is not None:
            kwargs["link_preview_options"] = options
        await edit(**kwargs)
        return True
    except TelegramError:
        LOGGER.debug("Could not restore native editor screen", exc_info=True)
        return False
