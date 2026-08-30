from __future__ import annotations

import asyncio
import contextvars
import hashlib
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from html import escape

from telegram import (
    Bot,
    ForceReply,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from music_links_bot import bot_lookup as _bot_lookup
from music_links_bot.bot_actions import action_spec
from music_links_bot.bot_batch import (
    send_partial_lookup_status as _send_partial_lookup_status_impl,
)
from music_links_bot.bot_builder import (
    BuilderScreen,
    builder_screen,
    fit_telegram_html,
    schedule_timestamp,
)
from music_links_bot.bot_crate import (
    add_many_to_crate,
    add_to_crate,
    crate_contains_item,
    load_crate,
)
from music_links_bot.bot_crate_handlers import (
    dispatch_crate_action as _dispatch_crate_action,
)
from music_links_bot.bot_editor_state import (
    apply_delivery_action,
    apply_editor_shortcut,
    apply_setting_action as _apply_editor_setting,
    draft_owned_by as _draft_owned_by,
    remember_draft as _remember_session_draft,
    remember_setting_state,
    restore_setting_state,
)
from music_links_bot.bot_history import record_history as _record_recent_item
from music_links_bot.bot_lookup import (
    _format_no_url_message,
    _send_artist_result,
    _send_mixed_result,
    _send_nts_result,
    _send_playlist_result,
    _send_youtube_result,
    _strip_bot_mention,
)
from music_links_bot.bot_menu import (
    MENU_HELP,
    dispatch_menu_action as _dispatch_menu_action,
    dispatch_privacy_action as _dispatch_privacy_action,
    reply_with_menu as _reply_with_menu,
    runtime_for as _runtime,
    update_lang as _update_lang,
)
from music_links_bot.bot_pending import (
    consume_pending_input as _consume_pending_input_impl,
)
from music_links_bot.bot_pipeline import LookupRequest, delivery_kind
from music_links_bot.bot_progress import (
    adopt_progress_message as _adopt_progress_message,
    cancel_progress as _cancel_progress,
    start_progress as _send_loading_placeholder,
    take_progress as _take_placeholder,
    update_progress as _update_loading_placeholder,
    update_progress_text as _update_progress_text,
)
from music_links_bot.bot_queue import dispatch_queue_action
from music_links_bot.bot_runtime import (
    BotErrorCode,
    BotFlowError,
    CallbackAction,
    decode_callback,
    detect_action,
    encode_callback,
)
from music_links_bot.bot_stats import (
    build_user_prefix as _build_user_prefix,
    message_entities as _message_entities,
    message_source_urls as _message_source_urls,
    message_text as _message_text,
    record_artist_items as _record_artists_safely,
    record_mixed_items as _record_mixed_safely,
    record_playlist_items as _record_playlists_safely,
    record_radio_items as _record_radios_safely,
    record_tracks as _record_matches_safely,
    record_video_items as _record_videos_safely,
)
from music_links_bot.bot_storage import (
    load_draft as _load_draft,
    load_retry_sources as _load_retry_sources,
    load_search_selection as _load_search_selection,
    store_draft as _store_draft,
    store_retry_sources as _store_retry_sources,
    store_search_selection as _store_search_selection,
)
from music_links_bot.bot_ui import (
    build_delete_confirmation_keyboard as _delete_confirmation_keyboard,
    build_deleted_draft_keyboard as _deleted_draft_keyboard,
    build_duplicate_post_keyboard as _duplicate_post_keyboard,
    build_error_keyboard as _build_error_keyboard_view,
    build_publish_confirmation as _build_publish_confirmation,
    build_section_keyboard as _build_section_keyboard,
    editor_delivery_rows as _editor_delivery_rows,
    editor_hashtag_rows as _editor_hashtag_rows,
    editor_intro_rows as _editor_intro_rows,
    editor_overflow_rows as _editor_overflow_rows,
    editor_platform_rows as _editor_platform_rows,
    editor_schedule_rows as _editor_schedule_rows,
    editor_style_rows as _editor_style_rows,
    editor_template_rows as _editor_template_rows,
)
from music_links_bot.branding import (
    brand_label,
    brand_logo_url,
    build_branded_cover,
    photo_branding_enabled,
)
from music_links_bot.channel_templates import (
    apply_channel_template,
    apply_template,
    save_channel_template,
)
from music_links_bot.chat_access import check_publish_access
from music_links_bot.collection_collage import collection_collage_preview_url
from music_links_bot.constants import MAX_LINKS_PER_MESSAGE
from music_links_bot.draft_model import new_track_draft
from music_links_bot.editor_view import (
    draft_intro_limit as _draft_intro_limit,
    render_track_draft as _render_track_draft,
)
from music_links_bot.ephemeral import (
    ephemeral_group_replies_enabled,
    send_ephemeral_message,
)
from music_links_bot.formatter import (
    format_collection_message,
    format_track_message,
)
from music_links_bot.i18n import get_text, resolve_lang
from music_links_bot.keyboards import (
    CHANNEL_USERNAME,
    _build_collection_keyboard,
    _build_link_keyboard,
    _build_link_preview_options,
    _channel_button,
    _get_platform_order,
    _select_preview_url,
    _should_include_channel_button,
    _should_include_hashtags,
)
from music_links_bot.lookup_transport import (
    reply_with_track as _reply_with_track,
    send_track_result as _send_track_result,
    send_track_video_pair_result as _send_track_video_pair_result,
)
from music_links_bot.models import (
    TrackMatch,
)
from music_links_bot.publication_contract import (
    RenderedPublication,
    require_valid_publication,
)
from music_links_bot.publication_preflight import validate_publication
from music_links_bot.publication_presets import (
    apply_named_preset,
    delete_named_preset,
    load_presets,
)
from music_links_bot.publication_service import PublicationService
from music_links_bot.publication_state import (
    find_posted_record as _find_posted_record,
    mark_posted as _schedule_mark_posted,
)
from music_links_bot.publish_queue import (
    QueueBusyError,
    QueueFullError,
    QueueStorageError,
    add_job,
)
from music_links_bot.rich_publications import (
    build_rich_collection_html,
    rich_api_unavailable,
    rich_messages_enabled,
    send_rich_publication,
)
from music_links_bot.search import (
    SearchClient,
    SearchLookupError,
    normalize_search_query,
)
from music_links_bot.sharing import (
    add_share_button,
    build_share_query,
    collection_result_title,
    make_channel_safe_keyboard,
    track_share_url,
)
from music_links_bot.telegram_buttons import (
    ButtonTone,
    button as InlineKeyboardButton,
    callback_button,
    current_chat_button,
    disabled_button,
)
from music_links_bot.telegram_messages import (
    delete_message_safely as _try_delete_message,
)
from music_links_bot.telegram_text import format_user_note_html
from music_links_bot.track_merge import coalesce_equivalent_tracks
from music_links_bot.url_utils import (
    cache_key_for_url,
    extract_supported_urls,
)

LOGGER = logging.getLogger(__name__)
DRAFT_UNDO_SECONDS = 15

_INPUT_OVERRIDE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "input_override", default=None
)
_SEARCH_QUERY_OVERRIDE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "search_query_override", default=None
)
_BYPASS_INTENT_GUARD: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "bypass_intent_guard", default=False
)

_SIMPLE_EDITOR_SCREENS = {
    BuilderScreen.STYLE: ("ed_style_title", _editor_style_rows),
    BuilderScreen.INTRO: ("ed_intro_title", _editor_intro_rows),
    BuilderScreen.HASHTAGS: ("ed_hashtags_title", _editor_hashtag_rows),
    BuilderScreen.DELIVERY: ("ed_delivery_title", _editor_delivery_rows),
}
_PREFLIGHT_EDITOR_ACTIONS = frozenset(
    {"p", "q1", "q3", "qe", "qd", "pc", "r", "x", "s"}
)
_SCHEDULE_EDITOR_ACTIONS = frozenset({"q1", "q3", "qe", "qd"})
_PRIMARY_EDITOR_ACTIONS = frozenset({"pc", "r", "x", "s", "c"})
_PENDING_EDITOR_INPUTS = {
    "ti": "intro",
    "hi": "hashtags",
    "qi": "schedule",
    "ci": "cover",
    "tn": "template_name",
}


@dataclass(slots=True)
class EditorActionRequest:
    query: object
    context: ContextTypes.DEFAULT_TYPE
    action: str
    draft_id: str
    draft: dict
    lang: str
    track: TrackMatch

    @property
    def user_id(self) -> int:
        user = getattr(self.query, "from_user", None)
        return int(user.id) if user is not None else 0


async def _application_error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    del update
    error = context.error
    if isinstance(error, BaseException):
        context.application.bot_data["last_error"] = {
            "type": type(error).__name__,
        }
        LOGGER.error(
            "Unhandled Telegram update error",
            exc_info=(type(error), error, error.__traceback__),
        )
        return

    LOGGER.error("Unhandled Telegram update error: %r", error)


async def bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Versioned callback dispatcher for all new interactive bot surfaces."""
    query = update.callback_query
    parsed = decode_callback(query.data if query else None)
    if query is None or parsed is None:
        return
    if action_spec(parsed.scope, parsed.action) is None and parsed.version == "v2":
        await query.answer()
        LOGGER.info(
            "Ignored unknown callback action %s:%s", parsed.scope, parsed.action
        )
        return

    runtime = _runtime(context)
    callback_id = str(
        getattr(query, "id", "") or hashlib.sha256(query.data.encode()).hexdigest()
    )
    if not await runtime.claim_callback(callback_id):
        lang = resolve_lang(query.from_user.language_code if query.from_user else None)
        await query.answer(get_text(lang, "action_duplicate"))
        return

    handlers: dict[
        str,
        Callable[[object, ContextTypes.DEFAULT_TYPE, CallbackAction], Awaitable[None]],
    ] = {
        "menu": _dispatch_menu_action,
        "select": _dispatch_selection_action,
        "editor": _dispatch_editor_action,
        "crate": _dispatch_crate_action,
        "retry": _dispatch_retry_action,
        "noop": _dispatch_noop_action,
        "progress": _dispatch_progress_action,
        "privacy": _dispatch_privacy_action,
        "queue": dispatch_queue_action,
        "playlist": _dispatch_playlist_action,
    }
    handler = handlers.get(parsed.scope)
    if handler is None:
        await query.answer()
        return
    await handler(query, context, parsed)


async def _dispatch_noop_action(query, context, action: CallbackAction) -> None:
    del context, action
    await query.answer()


async def _dispatch_progress_action(query, context, action: CallbackAction) -> None:
    del action
    if query.from_user is None:
        await query.answer()
        return
    lang = resolve_lang(query.from_user.language_code)
    runtime = _runtime(context)
    cancelled = await runtime.cancel_request_durable(query.from_user.id)
    await query.answer(
        get_text(lang, "request_cancelled" if cancelled else "request_not_running")
    )


async def _send_track_draft(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    track: TrackMatch,
    *,
    user_prefix: str,
    lang: str,
    user_id: int,
    search_query: str | None = None,
) -> None:
    admin_chat_id = context.application.bot_data.get("admin_chat_id")
    draft_id = secrets.token_hex(8)
    draft = new_track_draft(
        track,
        chat_id=message.chat_id,
        lang=lang,
        prefix=user_prefix,
        search_query=search_query or "",
        can_publish=(admin_chat_id is not None and user_id == admin_chat_id),
    )
    await apply_channel_template(context, f"user:{user_id}", draft)
    if draft["can_publish"]:
        target = (
            context.application.bot_data.get("publish_chat_id")
            or f"@{CHANNEL_USERNAME}"
        )
        await apply_channel_template(context, target, draft)

    crate_items = await load_crate(context.application.bot_data, user_id)
    draft["in_crate"] = crate_contains_item(crate_items, draft["item"])
    draft["crate_count"] = len(crate_items)

    text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
    await _reply_with_track(
        message,
        text,
        preview_url=_select_preview_url(track.links, context) or track.thumbnail_url,
        reply_markup=keyboard,
        prefer_large_preview=bool(draft.get("large_preview")),
        source_urls=tuple(track.links.values()),
        content_kind=track.kind,
    )
    await _store_draft(context, draft_id, draft)
    session = await _runtime(context).get_session(user_id, lang=lang)
    _remember_session_draft(session, draft_id)
    await _runtime(context).save_session(session)
    source_url = track_share_url(track) or track.page_url or ""
    if source_url:
        await _record_recent_item(context, user_id, track, source_url)


async def _send_uploaded_audio_draft(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    lang: str,
) -> None:
    audio = message.audio
    if audio is None:
        return
    filename = str(getattr(audio, "file_name", "") or "").rsplit("/", 1)[-1]
    fallback_title = (
        filename.rsplit(".", 1)[0]
        if filename
        else get_text(lang, "uploaded_audio_title")
    )
    track = TrackMatch(
        title=str(getattr(audio, "title", "") or fallback_title)[:160],
        artist=str(
            getattr(audio, "performer", "") or get_text(lang, "uploaded_audio_artist")
        )[:160],
        links={},
        kind="audio",
    )
    intro = ""
    if message.caption:
        intro = format_user_note_html(
            message.caption,
            _message_entities(message),
            max_length=900,
        )
        if intro:
            intro = f"<blockquote>{intro}</blockquote>\n\n"
    draft_id = secrets.token_hex(8)
    admin_chat_id = context.application.bot_data.get("admin_chat_id")
    draft = new_track_draft(
        track,
        chat_id=message.chat_id,
        lang=lang,
        prefix=intro,
        can_publish=admin_chat_id is not None and user_id == admin_chat_id,
    )
    draft["source_audio_file_id"] = str(audio.file_id)
    draft["source_audio_unique_id"] = str(audio.file_unique_id)
    draft["source_audio_duration"] = int(audio.duration or 0)
    draft["delivery_mode"] = "classic"
    draft["as_photo"] = False
    text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    await _store_draft(context, draft_id, draft)
    session = await _runtime(context).get_session(user_id, lang=lang)
    _remember_session_draft(session, draft_id)
    await _runtime(context).save_session(session)


async def _dispatch_selection_action(query, context, action: CallbackAction) -> None:
    lang = resolve_lang(query.from_user.language_code if query.from_user else None)
    if action.action != "pick" or ":" not in action.payload:
        await query.answer()
        return
    selection_id, raw_index = action.payload.rsplit(":", 1)
    payload = await _load_search_selection(context, selection_id)
    try:
        index = int(raw_index)
        urls = payload["urls"] if payload else []
        source_url = urls[index]
    except (IndexError, KeyError, TypeError, ValueError):
        await query.answer(get_text(lang, "ed_expired"), show_alert=True)
        return
    if query.from_user and int(payload.get("user_id") or 0) != query.from_user.id:
        await query.answer(get_text(lang, "ed_admin_only"), show_alert=True)
        return

    await query.answer(get_text(lang, "progress_links"))
    if query.message is None:
        return
    _adopt_progress_message(query.message)
    token = _INPUT_OVERRIDE.set(source_url)
    search_token = _SEARCH_QUERY_OVERRIDE.set(str(payload.get("query") or ""))
    guard_token = _BYPASS_INTENT_GUARD.set(True)
    try:
        synthetic = Update(update_id=0, callback_query=query)
        await track_lookup_message(synthetic, context)
    finally:
        _BYPASS_INTENT_GUARD.reset(guard_token)
        _SEARCH_QUERY_OVERRIDE.reset(search_token)
        _INPUT_OVERRIDE.reset(token)


async def _dispatch_retry_action(query, context, action: CallbackAction) -> None:
    if query.from_user is None or query.message is None:
        await query.answer()
        return
    lang = resolve_lang(query.from_user.language_code)
    if action.action == "replace" and action.payload:
        try:
            retry_id, raw_index = action.payload.rsplit(":", 1)
            source_index = int(raw_index)
        except (TypeError, ValueError):
            await query.answer(get_text(lang, "ed_expired"), show_alert=True)
            return
        payload = await _load_retry_sources(context, retry_id)
        urls = payload.get("urls", []) if isinstance(payload, dict) else []
        if (
            not isinstance(payload, dict)
            or int(payload.get("user_id") or 0) != query.from_user.id
            or not 1 <= source_index <= len(urls)
        ):
            await query.answer(get_text(lang, "ed_expired"), show_alert=True)
            return
        prompt = await query.message.reply_text(
            get_text(lang, "replace_source_prompt").format(index=source_index),
            parse_mode=ParseMode.HTML,
            reply_markup=ForceReply(selective=True),
        )
        session = await _runtime(context).get_session(query.from_user.id, lang=lang)
        session.pending_input = {
            "kind": "replace_source",
            "retry_id": retry_id,
            "source_index": source_index,
            "prompt_message_id": prompt.message_id,
            "created_at": int(time.time()),
        }
        await _runtime(context).save_session(session)
        await query.answer()
        return

    value = ""
    if action.action == "failed" and action.payload:
        payload = await _load_retry_sources(context, action.payload)
        if (
            isinstance(payload, dict)
            and int(payload.get("user_id") or 0) == query.from_user.id
        ):
            value = "\n".join(
                str(url) for url in payload.get("urls", []) if isinstance(url, str)
            )
    else:
        session = await _runtime(context).get_session(query.from_user.id, lang=lang)
        value = str(session.last_action.get("value") or "")
    if not value:
        await query.answer(get_text(lang, "ed_expired"), show_alert=True)
        return
    await query.answer(get_text(lang, "progress_search"))
    _adopt_progress_message(query.message)
    token = _INPUT_OVERRIDE.set(value)
    guard_token = _BYPASS_INTENT_GUARD.set(True)
    try:
        await track_lookup_message(Update(update_id=0, callback_query=query), context)
    finally:
        _BYPASS_INTENT_GUARD.reset(guard_token)
        _INPUT_OVERRIDE.reset(token)


async def _dispatch_playlist_action(query, context, action: CallbackAction) -> None:
    if (
        action.action != "import"
        or not action.payload
        or query.from_user is None
        or query.message is None
    ):
        await query.answer()
        return
    lang = resolve_lang(query.from_user.language_code)
    payload = await _load_retry_sources(context, action.payload)
    if (
        not isinstance(payload, dict)
        or int(payload.get("user_id") or 0) != query.from_user.id
    ):
        await query.answer(get_text(lang, "ed_expired"), show_alert=True)
        return
    urls = [str(url) for url in payload.get("urls", []) if isinstance(url, str)][
        :MAX_LINKS_PER_MESSAGE
    ]
    if not urls:
        await query.answer(get_text(lang, "ed_expired"), show_alert=True)
        return
    await query.answer(get_text(lang, "playlist_import_started"))
    _adopt_progress_message(query.message)
    token = _INPUT_OVERRIDE.set("\n".join(urls))
    guard_token = _BYPASS_INTENT_GUARD.set(True)
    try:
        await track_lookup_message(Update(update_id=0, callback_query=query), context)
    finally:
        _BYPASS_INTENT_GUARD.reset(guard_token)
        _INPUT_OVERRIDE.reset(token)


async def editor_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    parsed = decode_callback(query.data if query else None)
    if query is None or parsed is None or parsed.scope != "editor":
        return
    callback_id = str(
        getattr(query, "id", "")
        or hashlib.sha256((query.data or "").encode()).hexdigest()
    )
    if not await _runtime(context).claim_callback(callback_id):
        lang = resolve_lang(query.from_user.language_code if query.from_user else None)
        await query.answer(get_text(lang, "action_duplicate"))
        return
    await _handle_editor_action(query, context, parsed.action, parsed.payload)


async def _dispatch_editor_action(query, context, action: CallbackAction) -> None:
    await _handle_editor_action(query, context, action.action, action.payload)


async def _handle_editor_navigation(
    query,
    context,
    *,
    action: str,
    draft_id: str,
    draft: dict,
    lang: str,
    answer_text: str | None = None,
) -> bool:
    if action == "a":
        search_query = str(draft.get("search_query") or "").strip()
        if not search_query or query.message is None:
            await query.answer(get_text(lang, "ed_expired"), show_alert=True)
            return True
        await query.answer(get_text(lang, "progress_search"))
        _adopt_progress_message(query.message)
        token = _INPUT_OVERRIDE.set(search_query)
        guard_token = _BYPASS_INTENT_GUARD.set(True)
        try:
            await track_lookup_message(
                Update(update_id=0, callback_query=query), context
            )
        finally:
            _BYPASS_INTENT_GUARD.reset(guard_token)
            _INPUT_OVERRIDE.reset(token)
        return True

    screen = builder_screen(action)
    track = TrackMatch(**draft["item"])
    if screen == BuilderScreen.MAIN:
        text, keyboard = _render_track_draft(
            draft, context, draft_id=draft_id, settings=True, show_status=True
        )
    elif screen == BuilderScreen.ACTIONS:
        text, base_keyboard = _render_track_draft(
            draft, context, draft_id=draft_id, show_status=True
        )
        text = f"{get_text(lang, 'ed_actions_title')}\n\n{text}"
        overflow_rows = _editor_overflow_rows(draft_id, draft)
        share_query = build_share_query(
            [url] if (url := track_share_url(track)) else []
        )
        if share_query:
            overflow_rows.insert(
                max(1, len(overflow_rows) - 2),
                [
                    InlineKeyboardButton(
                        get_text(lang, "share_post"), switch_inline_query=share_query
                    )
                ],
            )
        keyboard = InlineKeyboardMarkup(
            [*base_keyboard.inline_keyboard[:1], *overflow_rows]
        )
    elif screen in _SIMPLE_EDITOR_SCREENS:
        title_key, row_builder = _SIMPLE_EDITOR_SCREENS[screen]
        text, _ = _render_track_draft(draft, context, draft_id=None)
        text = f"{get_text(lang, title_key)}\n\n{text}"
        keyboard = InlineKeyboardMarkup(row_builder(draft_id, draft))
    elif screen == BuilderScreen.PLATFORMS:
        text, _ = _render_track_draft(draft, context, draft_id=None)
        text = f"{get_text(lang, 'ed_platforms_title')}\n\n{text}"
        keyboard = InlineKeyboardMarkup(
            _editor_platform_rows(
                draft_id,
                draft,
                track,
                list(_get_platform_order(context)),
            )
        )
    elif screen == BuilderScreen.PREVIEW:
        sent = (
            await _deliver_preview_draft(
                context,
                draft,
                target=query.message.chat_id,
            )
            if query.message is not None
            else None
        )
        await query.answer(
            get_text(lang, "ed_preview_sent" if sent else "ed_publish_failed"),
            show_alert=not bool(sent),
        )
        return True
    elif screen == BuilderScreen.SCHEDULE:
        text = (
            f"{get_text(lang, 'schedule_title')}\n\n"
            f"<blockquote><b>{escape(track.artist)}</b> — {escape(track.title)}</blockquote>"
        )
        keyboard = InlineKeyboardMarkup(_editor_schedule_rows(draft_id, draft))
    elif screen == BuilderScreen.TEMPLATES:
        presets = await load_presets(
            context, query.from_user.id if query.from_user else 0
        )
        text, _ = _render_track_draft(draft, context, draft_id=None)
        text = f"{get_text(lang, 'ed_templates_title')}\n\n{text}"
        keyboard = InlineKeyboardMarkup(_editor_template_rows(draft_id, draft, presets))
    elif action == "b":
        text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
    else:
        return False
    await query.answer(answer_text)
    await _edit_editor_message(query, context, draft, text, keyboard)
    return True


async def _handle_editor_lifecycle(
    query,
    context,
    *,
    action: str,
    draft_id: str,
    draft: dict,
    lang: str,
) -> bool:
    if action == "d":
        await query.answer()
        await _edit_editor_message(
            query,
            context,
            draft,
            get_text(lang, "ed_delete_confirm"),
            _delete_confirmation_keyboard(draft_id, lang=lang),
        )
        return True
    if action == "dc":
        await query.answer()
        draft["deleted_at"] = int(time.time())
        await _store_draft(context, draft_id, draft)
        if query.from_user is not None:
            session = await _runtime(context).get_session(query.from_user.id, lang=lang)
            if session.active_draft_id == draft_id:
                session.active_draft_id = ""
                await _runtime(context).save_session(session)
        await _edit_editor_message(
            query,
            context,
            draft,
            get_text(lang, "ed_deleted"),
            _deleted_draft_keyboard(draft_id, lang=lang),
        )
        return True
    if action != "du":
        return False
    deleted_at = int(draft.get("deleted_at") or 0)
    if not deleted_at or time.time() - deleted_at > DRAFT_UNDO_SECONDS:
        await query.answer(get_text(lang, "ed_undo_expired"), show_alert=True)
        if query.message is not None:
            await _try_delete_message(query.message)
        return True
    draft.pop("deleted_at", None)
    await _store_draft(context, draft_id, draft)
    if query.from_user is not None:
        session = await _runtime(context).get_session(query.from_user.id, lang=lang)
        _remember_session_draft(session, draft_id)
        await _runtime(context).save_session(session)
    await query.answer()
    text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
    await _edit_editor_message(query, context, draft, text, keyboard)
    return True


async def _save_editor_settings(request: EditorActionRequest) -> None:
    await _store_draft(request.context, request.draft_id, request.draft)
    if request.user_id:
        await save_channel_template(
            request.context,
            f"user:{request.user_id}",
            request.draft,
        )


async def _apply_last_editor_template(request: EditorActionRequest) -> bool:
    if request.action != "lp":
        return False
    template = request.draft.get("last_template")
    if not isinstance(template, dict) or not apply_template(request.draft, template):
        await request.query.answer(
            get_text(request.lang, "ed_expired"),
            show_alert=True,
        )
        return True
    request.draft["last_template_applied"] = True
    await _store_draft(request.context, request.draft_id, request.draft)
    await request.query.answer(get_text(request.lang, "ed_last_template_applied"))
    text, keyboard = _render_track_draft(
        request.draft,
        request.context,
        draft_id=request.draft_id,
        settings=True,
        show_status=True,
    )
    await _edit_editor_message(
        request.query,
        request.context,
        request.draft,
        text,
        keyboard,
    )
    return True


async def _reject_failed_editor_preflight(request: EditorActionRequest) -> bool:
    if request.action not in _PREFLIGHT_EDITOR_ACTIONS:
        return False
    preflight = validate_publication(request.draft, request.track)
    if preflight.ready:
        return False
    await request.query.answer(
        get_text(request.lang, f"ed_preflight_{preflight.blocking_code}"),
        show_alert=True,
    )
    return True


async def _handle_editor_shortcut(request: EditorActionRequest) -> bool:
    if request.action == "u":
        if not restore_setting_state(request.draft):
            await request.query.answer(
                get_text(request.lang, "ed_undo_expired"),
                show_alert=True,
            )
            return True
        await _save_editor_settings(request)
        await request.query.answer(get_text(request.lang, "settings_restored"))
        text, keyboard = _render_track_draft(
            request.draft,
            request.context,
            draft_id=request.draft_id,
            settings=True,
            show_status=True,
        )
        await _edit_editor_message(
            request.query,
            request.context,
            request.draft,
            text,
            keyboard,
        )
        return True
    return_screen = apply_editor_shortcut(
        request.draft,
        request.action,
        track=request.track,
        platform_order=_get_platform_order(request.context),
    )
    if return_screen is None:
        return False
    await _save_editor_settings(request)
    await _handle_editor_navigation(
        request.query,
        request.context,
        action=return_screen,
        draft_id=request.draft_id,
        draft=request.draft,
        lang=request.lang,
    )
    return True


async def _handle_named_editor_template(request: EditorActionRequest) -> bool:
    action = request.action
    if not (action.startswith(("ta", "td")) and action[2:].isdigit()):
        return False
    index = int(action[2:])
    if action.startswith("ta"):
        remember_setting_state(request.draft)
        changed = await apply_named_preset(
            request.context,
            request.user_id,
            index,
            request.draft,
        )
        answer_key = "ed_template_applied"
    else:
        changed = await delete_named_preset(
            request.context,
            request.user_id,
            index,
        )
        answer_key = "ed_template_deleted"
    if not changed:
        await request.query.answer(
            get_text(request.lang, "ed_expired"),
            show_alert=True,
        )
        return True
    await _store_draft(request.context, request.draft_id, request.draft)
    await _handle_editor_navigation(
        request.query,
        request.context,
        action="tp",
        draft_id=request.draft_id,
        draft=request.draft,
        lang=request.lang,
        answer_text=get_text(request.lang, answer_key),
    )
    return True


async def _handle_pending_editor_action(request: EditorActionRequest) -> bool:
    kind = _PENDING_EDITOR_INPUTS.get(request.action)
    if kind is None:
        return False
    await _start_pending_editor_input(
        request.query,
        request.context,
        draft_id=request.draft_id,
        kind=kind,
        lang=request.lang,
        draft=request.draft,
    )
    return True


async def _open_editor_publish_confirmation(request: EditorActionRequest) -> bool:
    if request.action != "p":
        return False
    admin_chat_id = request.context.application.bot_data.get("admin_chat_id")
    if (
        not request.draft.get("can_publish")
        or not request.user_id
        or admin_chat_id is None
        or request.user_id != admin_chat_id
    ):
        await request.query.answer(
            get_text(request.lang, "ed_admin_only"),
            show_alert=True,
        )
        return True
    target = str(
        request.context.application.bot_data.get("publish_chat_id")
        or f"@{CHANNEL_USERNAME}"
    )
    text, keyboard = _build_publish_confirmation(
        request.draft_id,
        request.draft,
        request.track,
        target=target,
        lang=request.lang,
    )
    await request.query.answer()
    await _edit_editor_message(
        request.query,
        request.context,
        request.draft,
        text,
        keyboard,
    )
    return True


async def _run_locked_editor_action(request: EditorActionRequest) -> bool:
    if request.action in _SCHEDULE_EDITOR_ACTIONS:
        lock_action = "schedule"
    elif request.action in _PRIMARY_EDITOR_ACTIONS:
        lock_action = request.action
    else:
        return False
    runtime = _runtime(request.context)
    lock_key = f"{request.user_id}:{lock_action}:{request.draft_id}"
    token = await runtime.acquire_action(lock_key)
    if token is None:
        await request.query.answer(
            get_text(request.lang, "action_busy"),
            show_alert=True,
        )
        return True
    if request.action in _PRIMARY_EDITOR_ACTIONS:
        await _show_action_busy(request.query, request.lang)
    try:
        if request.action in _SCHEDULE_EDITOR_ACTIONS:
            await _schedule_editor_draft(
                request.query,
                request.context,
                request.action,
                request.draft,
                lang=request.lang,
            )
        else:
            await _run_primary_editor_action(request)
    finally:
        await runtime.release_action(lock_key, token)
    return True


async def _handle_editor_delivery_setting(request: EditorActionRequest) -> bool:
    if not apply_delivery_action(request.draft, request.action):
        return False
    await _store_draft(request.context, request.draft_id, request.draft)
    await _handle_editor_navigation(
        request.query,
        request.context,
        action="rs",
        draft_id=request.draft_id,
        draft=request.draft,
        lang=request.lang,
        answer_text=get_text(request.lang, "settings_saved"),
    )
    return True


async def _finish_editor_setting(request: EditorActionRequest) -> None:
    if request.action != "f" and not _apply_editor_setting(
        request.draft,
        request.action,
        track=request.track,
        platform_order=_get_platform_order(request.context),
    ):
        await request.query.answer()
        return
    await request.query.answer(
        get_text(request.lang, "settings_saved") if request.action != "f" else None
    )
    await _save_editor_settings(request)
    text, keyboard = _render_track_draft(
        request.draft,
        request.context,
        draft_id=request.draft_id,
        settings=request.action != "f",
        show_status=request.action != "f",
    )
    await _edit_editor_message(
        request.query,
        request.context,
        request.draft,
        text,
        keyboard,
    )


async def _handle_editor_action(query, context, action: str, draft_id: str) -> None:
    user_lang = resolve_lang(query.from_user.language_code if query.from_user else None)
    draft = await _load_draft(context, draft_id)
    if draft is None:
        await query.answer(get_text(user_lang, "ed_expired"), show_alert=True)
        return

    lang = draft.get("lang") or user_lang
    if query.from_user is not None and not _draft_owned_by(draft, query.from_user.id):
        await query.answer(get_text(lang, "ed_owner_only"), show_alert=True)
        return
    spec = action_spec("editor", action)
    if spec is not None and spec.mutating:
        _runtime(context).record_funnel("edited")

    if await _handle_editor_navigation(
        query,
        context,
        action=action,
        draft_id=draft_id,
        draft=draft,
        lang=lang,
    ):
        return
    if await _handle_editor_lifecycle(
        query,
        context,
        action=action,
        draft_id=draft_id,
        draft=draft,
        lang=lang,
    ):
        return

    request = EditorActionRequest(
        query=query,
        context=context,
        action=action,
        draft_id=draft_id,
        draft=draft,
        lang=lang,
        track=TrackMatch(**draft["item"]),
    )
    for handler in (
        _apply_last_editor_template,
        _reject_failed_editor_preflight,
        _handle_editor_shortcut,
        _handle_named_editor_template,
        _handle_pending_editor_action,
        _open_editor_publish_confirmation,
        _run_locked_editor_action,
        _handle_editor_delivery_setting,
    ):
        if await handler(request):
            return
    await _finish_editor_setting(request)
    return


async def _start_pending_editor_input(
    query,
    context,
    *,
    draft_id: str,
    kind: str,
    lang: str,
    draft: dict | None = None,
) -> None:
    if query.from_user is None or query.message is None:
        await query.answer()
        return
    prompt_key = {
        "intro": "ed_intro_prompt",
        "hashtags": "ed_tags_prompt",
        "schedule": "schedule_prompt",
        "cover": "ed_cover_prompt",
        "template_name": "ed_template_prompt",
    }[kind]
    prompt_text = get_text(lang, prompt_key)
    if kind == "intro" and draft is not None:
        prompt_text = prompt_text.format(
            limit=_draft_intro_limit(draft, context),
        )
    prompt = await query.message.reply_text(
        prompt_text,
        parse_mode=ParseMode.HTML,
        reply_markup=ForceReply(selective=True),
    )
    session = await _runtime(context).get_session(query.from_user.id, lang=lang)
    session.pending_input = {
        "kind": kind,
        "draft_id": draft_id,
        "editor_chat_id": query.message.chat_id,
        "editor_message_id": query.message.message_id,
        "prompt_message_id": prompt.message_id,
        "created_at": int(time.time()),
    }
    await _runtime(context).save_session(session)
    await query.answer()


async def _schedule_editor_draft(
    query, context, action: str, draft: dict, *, lang: str
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
    publish_at = schedule_timestamp(action, timezone_name=timezone_name)
    try:
        await add_job(context, dict(draft), publish_at)
    except QueueFullError:
        await query.answer(get_text(lang, "ed_queue_full"), show_alert=True)
        return
    except (QueueBusyError, QueueStorageError):
        await query.answer(get_text(lang, "ed_queue_unavailable"), show_alert=True)
        return
    date = get_text(
        lang,
        {
            "q1": "schedule_1h",
            "q3": "schedule_3h",
            "qe": "schedule_evening",
            "qd": "schedule_1d",
        }[action],
    )
    await query.answer(
        get_text(lang, "schedule_done").format(date=date), show_alert=True
    )
    text, _ = _render_track_draft(draft, context, draft_id=None)
    text = (
        f"<b>{escape(get_text(lang, 'schedule_done').format(date=date))}</b>\n\n{text}"
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
                        get_text(lang, "home_back"),
                        callback_data=encode_callback("menu", "start"),
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

    record = await _find_posted_record(request.context, request.track)
    if request.action == "pc" and record:
        await _show_duplicate_editor_post(request, record)
        return
    if (
        request.action == "x"
        and record
        and not await _delete_duplicate_editor_post(
            request,
            record,
        )
    ):
        return
    published = await _publish_draft(request.context, request.draft)
    await _finish_editor_publish(request, published)


async def _restore_editor_card(request: EditorActionRequest) -> None:
    text, keyboard = _render_track_draft(
        request.draft,
        request.context,
        draft_id=request.draft_id,
    )
    await _edit_editor_message(
        request.query,
        request.context,
        request.draft,
        text,
        keyboard,
    )


async def _add_editor_item_to_crate(request: EditorActionRequest) -> None:
    items, added = await add_to_crate(
        request.context.application.bot_data,
        request.user_id,
        draft_id=request.draft_id,
        item=request.draft["item"],
    )
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
    await _restore_editor_card(request)


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
    target = (
        request.context.application.bot_data.get("publish_chat_id")
        or f"@{CHANNEL_USERNAME}"
    )
    try:
        await request.context.bot.delete_message(
            chat_id=target,
            message_id=message_id,
        )
        return True
    except TelegramError:
        await request.query.answer(
            get_text(request.lang, "ed_publish_failed"),
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
        return False


async def _finish_editor_publish(request: EditorActionRequest, published) -> None:
    if published:
        target = (
            request.context.application.bot_data.get("publish_chat_id")
            or f"@{CHANNEL_USERNAME}"
        )
        await _schedule_mark_posted(
            request.context,
            request.track,
            message=published,
            target=target,
        )
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
            "ed_published" if published else "ed_publish_failed",
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
    if isinstance(published_link, str) and published_link.startswith("http"):
        first_row = [
            InlineKeyboardButton(
                get_text(request.lang, "ed_open_publication"),
                url=published_link,
            )
        ]
    else:
        first_row = [_channel_button()]
    keyboard = InlineKeyboardMarkup(
        [
            first_row,
            [
                InlineKeyboardButton(
                    get_text(request.lang, "ed_create_more"),
                    callback_data=encode_callback("menu", "create"),
                    style="primary",
                )
            ],
        ]
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
        f"<b>{escape(get_text(request.lang, 'ed_published'))}</b>\n\n{text}",
        keyboard,
    )


async def _show_action_busy(query, lang: str) -> None:
    try:
        await query.edit_message_reply_markup(
            InlineKeyboardMarkup(
                [
                    [
                        disabled_button(
                            get_text(lang, "progress_busy"),
                            tone=ButtonTone.PRIMARY,
                        )
                    ]
                ]
            )
        )
    except (AttributeError, TelegramError, TypeError):
        try:
            await query.edit_message_reply_markup(
                InlineKeyboardMarkup(
                    [
                        [
                            callback_button(
                                get_text(lang, "progress_busy"),
                                encode_callback("noop", "busy"),
                                tone=ButtonTone.PRIMARY,
                            )
                        ]
                    ]
                )
            )
        except (AttributeError, TelegramError, TypeError):
            LOGGER.debug("Could not mark editor action busy", exc_info=True)


async def _edit_editor_message(
    query, context, draft: dict, text: str, keyboard
) -> None:
    track = TrackMatch(**draft["item"])
    text = fit_telegram_html(text)
    try:
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            link_preview_options=_build_link_preview_options(
                _select_preview_url(track.links, context) or track.thumbnail_url,
                prefer_large_media=bool(draft.get("large_preview")),
            ),
            reply_markup=keyboard,
        )
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


async def _publish_draft(
    context: ContextTypes.DEFAULT_TYPE,
    draft: dict,
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
    ).publish(draft)


async def _deliver_draft(
    context: ContextTypes.DEFAULT_TYPE,
    draft: dict,
    *,
    target: int | str,
    channel_style: bool,
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
    ).deliver(
        draft,
        target=target,
        channel_style=channel_style,
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


async def _reply_with_error(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    lang: str = "ru",
) -> None:
    reply_markup = _build_error_keyboard(context.bot.username, lang=lang)
    if await _try_ephemeral_error(
        message,
        context,
        text,
        reply_markup,
    ):
        return
    placeholder = _take_placeholder(message.chat_id)
    if placeholder is not None:
        try:
            await placeholder.edit_text(text, reply_markup=reply_markup)
            return
        except TelegramError:
            LOGGER.debug("Could not edit loading placeholder", exc_info=True)
            await _try_delete_message(placeholder)

    await message.reply_text(text, reply_markup=reply_markup)


async def _reply_with_flow_error(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    error: BotFlowError,
    *,
    lang: str,
    search_query: str | None = None,
    source_url: str | None = None,
) -> None:
    detail_key = {
        BotErrorCode.INVALID_INPUT: "no_url_hint",
        BotErrorCode.SEARCH_NOT_FOUND: "error_search",
        BotErrorCode.RELEASE_NOT_FOUND: "error_search",
        BotErrorCode.PROVIDER_UNAVAILABLE: "error_provider",
        BotErrorCode.RATE_LIMITED: "error_rate_limit",
    }.get(error.code, "no_url_hint")
    detail = get_text(lang, detail_key)
    if error.code == BotErrorCode.RATE_LIMITED:
        detail = detail.format(seconds=escape(error.detail or "60"))
    if error.code == BotErrorCode.PROVIDER_UNAVAILABLE and error.provider:
        provider_labels = {
            "songlink": "Song.link",
            "youtube": "YouTube",
            "nts": "NTS Radio",
            "apple": "Apple Music",
            "spotify": "Spotify",
        }
        provider = provider_labels.get(error.provider.casefold(), error.provider)
        detail = get_text(lang, "error_provider_named").format(
            provider=escape(provider)
        )
    title_key = {
        BotErrorCode.INVALID_INPUT: "error_title_invalid_input",
        BotErrorCode.SEARCH_NOT_FOUND: "error_title_not_found",
        BotErrorCode.RELEASE_NOT_FOUND: "error_title_not_found",
        BotErrorCode.PROVIDER_UNAVAILABLE: "error_title_provider",
        BotErrorCode.RATE_LIMITED: "error_title_rate_limit",
    }.get(error.code, "error_title")
    text = f"⚠️ <b>{get_text(lang, title_key)}</b>\n{detail}"
    keyboard = _build_error_keyboard(
        context.bot.username,
        lang=lang,
        retryable=error.retryable,
        search_query=search_query,
        source_url=source_url,
    )
    if await _try_ephemeral_error(
        message,
        context,
        text,
        keyboard,
        parse_mode=ParseMode.HTML,
    ):
        return
    placeholder = _take_placeholder(message.chat_id)
    if placeholder is not None:
        try:
            await placeholder.edit_text(
                text, parse_mode=ParseMode.HTML, reply_markup=keyboard
            )
            return
        except TelegramError:
            LOGGER.debug("Could not edit flow-error placeholder", exc_info=True)
            await _try_delete_message(placeholder)
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def _try_ephemeral_error(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    keyboard: InlineKeyboardMarkup,
    *,
    parse_mode: object | None = None,
) -> bool:
    """Keep recovery private in groups and preserve the public fallback."""
    user = getattr(message, "from_user", None)
    if (
        getattr(message.chat, "type", None) not in {"group", "supergroup"}
        or user is None
        or not ephemeral_group_replies_enabled()
    ):
        return False
    delivered = await send_ephemeral_message(
        getattr(context.bot, "token", None),
        message.chat_id,
        user.id,
        text,
        parse_mode=parse_mode,
        reply_markup=keyboard,
        reply_to_message_id=getattr(message, "message_id", None),
    )
    if not delivered:
        return False
    placeholder = _take_placeholder(message.chat_id)
    if placeholder is not None:
        await _try_delete_message(placeholder)
    return True


async def _send_typing_action(bot: Bot, message: Message) -> None:
    if message.chat.type == "channel":
        return

    try:
        await bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
    except TelegramError:
        LOGGER.debug("Could not send typing action", exc_info=True)


async def _resolve_search_sources(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    message_text: str | None,
    *,
    user_id: int,
    lang: str,
) -> tuple[list[str], bool, str] | None:
    """Resolve a private text query or finish the flow with a picker/error."""
    search_query = normalize_search_query(
        _strip_bot_mention(message_text or "", context.bot.username)
    )
    if search_query is None:
        await _reply_with_error(
            message,
            context,
            _format_no_url_message(message_text, message.chat_id, lang=lang),
            lang=lang,
        )
        return None

    await _send_loading_placeholder(message, lang)
    search_client: SearchClient = context.application.bot_data["search_client"]
    try:
        if hasattr(search_client, "search_release_candidates"):
            candidates = await search_client.search_release_candidates(search_query)
        else:
            source_url = await search_client.search_release_url(search_query)
            candidates = [
                type(
                    "SearchChoice",
                    (),
                    {"url": source_url, "artist": "", "title": search_query},
                )()
            ]
        if len(candidates) > 1:
            selection_id = await _store_search_selection(
                context,
                user_id=user_id,
                query=search_query,
                urls=[candidate.url for candidate in candidates[:3]],
            )
            placeholder = _take_placeholder(message.chat_id)
            lines = [
                get_text(lang, "search_choose").replace(
                    "{query}", escape(search_query)
                ),
                "",
            ]
            for index, candidate in enumerate(candidates[:3], start=1):
                artist = escape(str(getattr(candidate, "artist", "") or "—"))
                title = escape(str(getattr(candidate, "title", "") or "—"))
                meta = [
                    escape(str(value))
                    for value in (
                        getattr(candidate, "album", None),
                        getattr(candidate, "year", None),
                    )
                    if value
                ]
                suffix = f" <i>· {' · '.join(meta)}</i>" if meta else ""
                lines.append(f"<b>{index}.</b> {artist} — {title}{suffix}")
            text = "\n".join(lines)
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        callback_button(
                            (
                                f"{index + 1} · "
                                f"{getattr(candidate, 'artist', '')} — {candidate.title}"
                            )[:64],
                            encode_callback(
                                "select", "pick", f"{selection_id}:{index}"
                            ),
                            tone=ButtonTone.PRIMARY if index == 0 else None,
                        )
                    ]
                    for index, candidate in enumerate(candidates[:3])
                ]
                + [
                    [
                        current_chat_button(
                            get_text(lang, "search_change"),
                            search_query,
                        )
                    ],
                    [
                        callback_button(
                            get_text(lang, "home_back"),
                            encode_callback("menu", "start"),
                        )
                    ],
                ]
            )
            if placeholder is not None:
                try:
                    await placeholder.edit_text(
                        text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                    )
                    return None
                except TelegramError:
                    LOGGER.debug("Could not edit search progress", exc_info=True)
                    await _try_delete_message(placeholder)
            await message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            return None
        return [candidates[0].url], True, search_query
    except (SearchLookupError, IndexError):
        await _reply_with_flow_error(
            message,
            context,
            BotFlowError(BotErrorCode.SEARCH_NOT_FOUND, retryable=True),
            lang=lang,
            search_query=search_query,
        )
        return None


async def track_lookup_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    started = asyncio.get_running_loop().time()
    completed = False
    message = update.effective_message
    private_user_id: int | None = None
    if message is not None and message.chat.type == "private":
        private_user_id = (
            update.effective_user.id
            if update.effective_user is not None
            else message.chat_id
        )
    try:
        await _track_lookup_message_impl(update, context)
        completed = True
    except asyncio.CancelledError:
        # A newer private-chat request superseded this one. Treat cancellation
        # as an expected UX event, not a failed Telegram webhook delivery.
        LOGGER.debug("Stale lookup cancelled in favor of a newer request")
        completed = True
        if message is not None:
            await _cancel_progress(message.chat_id, _update_lang(update))
    except TelegramError as exc:
        if message is not None and message.chat.type == "private":
            await _cancel_progress(message.chat_id, _update_lang(update))
        if message is not None and message.chat.type == "channel":
            await _notify_admin(
                context,
                "Автозамена поста в канале завершилась ошибкой: "
                f"{type(exc).__name__}: {str(exc)[:180]}",
                only_for_channel_message=message,
            )
        raise
    except Exception:
        if message is not None and message.chat.type == "private":
            await _cancel_progress(message.chat_id, _update_lang(update))
        raise
    finally:
        runtime = _runtime(context)
        runtime.record_request(
            latency_ms=int((asyncio.get_running_loop().time() - started) * 1000),
            ok=completed,
        )
        await runtime.persist_metrics()
        if private_user_id is not None:
            await runtime.finish_request_durable(private_user_id)


async def _handle_empty_lookup(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    bundle: _bot_lookup.LookupBundle,
    source_urls: list[str],
    *,
    lang: str,
) -> bool:
    """Report an empty provider result and return whether delivery is finished."""
    if bundle.unavailable_urls:
        await _notify_admin(
            context,
            "Внешний resolver недоступен для "
            f"{len(bundle.unavailable_urls)} из {len(source_urls)} источников.",
            only_for_channel_message=message,
        )

    if bundle.item_count:
        return False

    if not bundle.unavailable_urls:
        await _notify_admin(
            context,
            f"Не найдено ни одного релиза для {len(source_urls)} источников "
            f"в чате {message.chat_id}.",
            only_for_channel_message=message,
        )

    if message.chat.type == "channel":
        return True

    if bundle.unavailable_urls:
        await _reply_with_flow_error(
            message,
            context,
            BotFlowError(
                BotErrorCode.PROVIDER_UNAVAILABLE,
                retryable=True,
                provider="songlink",
            ),
            lang=lang,
            source_url=source_urls[0] if source_urls else None,
        )
    else:
        await _reply_with_flow_error(
            message,
            context,
            BotFlowError(BotErrorCode.RELEASE_NOT_FOUND),
            lang=lang,
            source_url=source_urls[0] if source_urls else None,
        )
    return True


async def _send_partial_lookup_status(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    bundle: _bot_lookup.LookupBundle,
    *,
    user_id: int,
    lang: str,
) -> None:
    await _send_partial_lookup_status_impl(
        message,
        context,
        bundle,
        user_id=user_id,
        lang=lang,
        notify_admin=_notify_admin,
    )


async def _add_track_drafts_to_crate(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    tracks: list[TrackMatch],
    *,
    user_id: int,
    lang: str,
) -> tuple[list[dict], int]:
    crate_entries: list[tuple[str, dict]] = []
    draft_writes: list[Awaitable[None]] = []
    for track in tracks:
        draft_id = secrets.token_hex(8)
        item = asdict(track)
        draft = new_track_draft(
            track,
            chat_id=message.chat_id,
            lang=lang,
        )
        crate_entries.append((draft_id, item))
        draft_writes.append(_store_draft(context, draft_id, draft))

    await asyncio.gather(*draft_writes)
    crate_items, added_count = await add_many_to_crate(
        context.application.bot_data,
        user_id,
        entries=crate_entries,
    )
    return crate_items, added_count


async def _send_track_matches(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    tracks: list[TrackMatch],
    *,
    is_private: bool,
    user_id: int,
    user_prefix: str,
    lang: str,
    include_channel_button: bool,
    include_hashtags: bool,
    search_query: str | None = None,
    requested_count: int | None = None,
    allow_share: bool = True,
) -> None:
    """Deliver one release or a collection without mixing lookup concerns."""
    total = max(len(tracks), int(requested_count or len(tracks)))
    if total > 1:
        title = collection_result_title(
            lang,
            found=len(tracks),
            total=total,
        )
        if is_private:
            await _add_track_drafts_to_crate(
                message,
                context,
                tracks,
                user_id=user_id,
                lang=lang,
            )
            rows = [
                [
                    InlineKeyboardButton(
                        get_text(lang, "crate_view"),
                        callback_data=encode_callback("crate", "open"),
                        style="primary",
                    )
                ],
                [
                    InlineKeyboardButton(
                        get_text(lang, "crate_reorder"),
                        callback_data=encode_callback("crate", "open"),
                    )
                ],
            ]
            collection_keyboard = InlineKeyboardMarkup(rows)
        else:
            collection_keyboard = _build_collection_keyboard(
                tracks,
                include_channel_button=include_channel_button,
            )
            if allow_share:
                collection_keyboard = add_share_button(
                    collection_keyboard,
                    share_query=build_share_query(
                        [track_share_url(track) or "" for track in tracks]
                    ),
                    label=get_text(lang, "share_post"),
                )
            if message.chat.type == "channel":
                collection_keyboard = make_channel_safe_keyboard(collection_keyboard)
        collection_text = user_prefix + format_collection_message(
            tracks,
            include_hashtags=include_hashtags,
            title=title,
        )
        collection_preview = (
            (collection_collage_preview_url(tracks) if len(tracks) == total else None)
            or _select_preview_url(tracks[0].links, context)
            or tracks[0].thumbnail_url
        )
        collection_sources = tuple(
            url for track in tracks for url in track.links.values()
        )
        if not is_private and rich_messages_enabled():
            require_valid_publication(
                RenderedPublication(
                    text=collection_text,
                    keyboard=collection_keyboard,
                    preview_url=collection_preview,
                    source_urls=collection_sources,
                    found_count=len(tracks),
                    requested_count=total,
                    mode="rich",
                    content_kind="collection",
                    cover_expected=any(track.thumbnail_url for track in tracks),
                )
            )
            rich_html = build_rich_collection_html(
                tracks,
                title=title,
                hashtags=(
                    "#stonerhand #track #collection" if include_hashtags else None
                ),
                reply_markup=collection_keyboard,
            )
            placeholder = _take_placeholder(message.chat_id)
            if placeholder is not None:
                await _try_delete_message(placeholder)
            try:
                await send_rich_publication(
                    context.bot,
                    chat_id=message.chat_id,
                    rich_html=rich_html,
                )
                await _try_delete_message(message)
                _record_matches_safely(tracks, message, context=context)
                runtime = context.application.bot_data.get("runtime")
                if runtime is not None and hasattr(runtime, "record_rich_message"):
                    runtime.record_rich_message(ok=True)
                return
            except TelegramError as exc:
                runtime = context.application.bot_data.get("runtime")
                if runtime is not None and hasattr(runtime, "record_rich_message"):
                    runtime.record_rich_message(
                        ok=False,
                        fallback=rich_api_unavailable(exc),
                    )
                LOGGER.info(
                    "Rich collection unavailable; using classic collection",
                    exc_info=not rich_api_unavailable(exc),
                )
        await _send_track_result(
            context.bot,
            message,
            collection_text,
            preview_url=collection_preview,
            reply_markup=collection_keyboard,
            found_count=len(tracks),
            requested_count=total,
            source_urls=collection_sources,
            content_kind="collection",
        )
        _record_matches_safely(tracks, message, context=context)
        return

    track = tracks[0]
    if is_private:
        await _send_track_draft(
            message,
            context,
            track,
            user_prefix=user_prefix,
            lang=lang,
            user_id=user_id,
            search_query=search_query,
        )
    else:
        keyboard = _build_link_keyboard(
            track.links,
            context=context,
            include_channel_button=include_channel_button,
            release_page_url=track.page_url,
            release_kind=track.kind,
            release_format=track.release_format,
        )
        if allow_share:
            keyboard = add_share_button(
                keyboard,
                share_query=build_share_query(
                    [url] if (url := track_share_url(track)) else []
                ),
                label=get_text(lang, "share_post"),
            )
        await _send_track_result(
            context.bot,
            message,
            user_prefix
            + format_track_message(
                track,
                include_hashtags=include_hashtags,
            ),
            preview_url=_select_preview_url(track.links, context)
            or track.thumbnail_url,
            reply_markup=keyboard,
            source_urls=tuple(track.links.values()),
            content_kind=track.kind,
        )
    _record_matches_safely([track], message, context=context)


async def _consume_pending_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    return await _consume_pending_input_impl(
        update,
        context,
        retry_lookup=_retry_pending_lookup,
    )


async def _retry_pending_lookup(message, context, urls: list[str]) -> None:
    token = _INPUT_OVERRIDE.set("\n".join(urls))
    guard_token = _BYPASS_INTENT_GUARD.set(True)
    try:
        await track_lookup_message(Update(update_id=0, message=message), context)
    finally:
        _BYPASS_INTENT_GUARD.reset(guard_token)
        _INPUT_OVERRIDE.reset(token)


async def _handle_lookup_input_mode(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    message: Message,
) -> bool:
    if await _consume_pending_input(update, context):
        return True
    if message.chat.type == "private" and getattr(message, "audio", None) is not None:
        user_id = update.effective_user.id if update.effective_user else message.chat_id
        await _send_uploaded_audio_draft(
            message,
            context,
            user_id=user_id,
            lang=_update_lang(update),
        )
        return True
    if (
        message.chat.type == "private"
        and getattr(message, "photo", None)
        and not (_message_text(message) or "").strip()
    ):
        return True
    via_bot = getattr(message, "via_bot", None)
    return via_bot is not None and via_bot.id == getattr(context.bot, "id", None)


def _build_lookup_request(update: Update, context, message: Message) -> LookupRequest:
    override = _INPUT_OVERRIDE.get()
    message_text = override or _message_text(message) or ""
    is_private = message.chat.type == "private"
    source_urls = (
        extract_supported_urls(message_text)
        if override is not None
        else _message_source_urls(message, text=message_text)
    )[:MAX_LINKS_PER_MESSAGE]
    return LookupRequest(
        message_text=message_text,
        source_urls=source_urls,
        is_private=is_private,
        lang=_update_lang(update) if is_private else "ru",
        user_id=(
            update.effective_user.id if update.effective_user else message.chat_id
        ),
        include_channel_button=_should_include_channel_button(message),
        include_hashtags=_should_include_hashtags(message),
        search_query=(_SEARCH_QUERY_OVERRIDE.get() or "").strip() or None,
    )


async def _admit_private_lookup(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    request: LookupRequest,
):
    if not request.is_private:
        return True, None
    runtime = _runtime(context)
    action_kind = detect_action(
        request.message_text,
        request.source_urls,
        is_private=True,
    )
    allowed, retry_after = await runtime.allow_user_request(request.user_id)
    if not allowed:
        await _reply_with_flow_error(
            message,
            context,
            BotFlowError(BotErrorCode.RATE_LIMITED, detail=str(retry_after)),
            lang=request.lang,
        )
        return False, None
    intent_value = (
        "\n".join(sorted(cache_key_for_url(url) for url in request.source_urls))
        if request.source_urls
        else request.message_text
    )
    if not _BYPASS_INTENT_GUARD.get() and not await runtime.claim_intent(
        request.user_id,
        kind=action_kind,
        value=intent_value,
    ):
        return False, None
    if action_kind == "help":
        await _reply_with_menu(message, context, MENU_HELP, lang=request.lang)
        return False, None
    request_token = await runtime.begin_request(request.user_id)
    runtime.record_funnel("started")
    remembered_value = request.search_query or request.message_text
    if not request.search_query and len(request.source_urls) == 1:
        remembered_value = request.source_urls[0]
    await runtime.remember_action(
        request.user_id,
        kind="search" if request.search_query or not request.source_urls else "resolve",
        value=remembered_value,
        lang=request.lang,
    )
    return True, request_token


async def _resolve_request_sources(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    request: LookupRequest,
) -> bool:
    if request.source_urls:
        request.found_via_search = request.search_query is not None
        return True
    if not request.is_private:
        return False
    search_result = await _resolve_search_sources(
        message,
        context,
        request.message_text,
        user_id=request.user_id,
        lang=request.lang,
    )
    if search_result is None:
        return False
    source_urls, found_via_search, search_query = search_result
    request.source_urls = source_urls
    request.found_via_search = found_via_search
    request.search_query = search_query
    return True


async def _ensure_current_lookup(context, request: LookupRequest, token) -> None:
    if request.is_private and not await _runtime(context).request_is_current(
        request.user_id,
        token,
    ):
        raise asyncio.CancelledError


async def _ensure_channel_publish_access(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    if message.chat.type != "channel":
        return True
    access = await check_publish_access(context, message.chat_id)
    if access.allowed and access.can_delete:
        return True
    missing = "публиковать" if not access.allowed else "удалять исходные сообщения"
    await _notify_admin(
        context,
        f"Автозамена в канале {message.chat_id} остановлена: "
        f"бот не может {missing}. {access.detail}",
        only_for_channel_message=message,
    )
    return False


async def _start_lookup_progress(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    request: LookupRequest,
) -> None:
    if not request.is_private:
        await _send_typing_action(context.bot, message)
        return
    await _send_loading_placeholder(
        message,
        request.lang,
        total=max(1, len(request.source_urls)),
    )
    if len(request.source_urls) > 1:
        await _update_progress_text(
            get_text(request.lang, "progress_batch_links").format(
                total=len(request.source_urls)
            ),
            stage=2,
            lang=request.lang,
        )
    else:
        await _update_loading_placeholder(request.lang, "progress_links")


async def _update_resolved_progress(request: LookupRequest, bundle) -> None:
    if not request.is_private:
        return
    if len(request.source_urls) == 1:
        await _update_loading_placeholder(request.lang, "progress_card")
        return
    await _update_progress_text(
        get_text(
            request.lang,
            "progress_batch"
            if bundle.is_complete_for(request.source_urls)
            else "progress_batch_partial",
        ).format(done=bundle.item_count, total=len(request.source_urls)),
        lang=request.lang,
    )


async def _track_lookup_message_impl(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    if message is None:
        return

    if await _handle_lookup_input_mode(update, context, message):
        return
    request = _build_lookup_request(update, context, message)
    accepted, request_token = await _admit_private_lookup(message, context, request)
    if not accepted or not await _resolve_request_sources(message, context, request):
        return
    await _ensure_current_lookup(context, request, request_token)
    if not await _ensure_channel_publish_access(message, context):
        return
    user_prefix = (
        ""
        if request.prefix_is_noise
        else _build_user_prefix(message, bot_username=context.bot.username)
    )
    await _start_lookup_progress(message, context, request)
    bundle = await _bot_lookup.resolve_sources(
        context.application.bot_data,
        request.source_urls,
    )
    await _ensure_current_lookup(context, request, request_token)
    if request.is_private and bundle.item_count:
        _runtime(context).record_funnel("resolved")
    await _update_resolved_progress(request, bundle)
    if await _handle_empty_lookup(
        message,
        context,
        bundle,
        request.source_urls,
        lang=request.lang,
    ):
        return
    await _deliver_lookup_bundle(
        message,
        context,
        bundle,
        request=request,
        user_prefix=user_prefix,
    )


async def _deliver_lookup_bundle(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    bundle: _bot_lookup.LookupBundle,
    *,
    request: LookupRequest,
    user_prefix: str,
) -> None:
    """Render an already resolved bundle; lookup orchestration stays separate."""
    partial = not bundle.is_complete_for(request.source_urls)
    # Different platform URLs often point to the exact same release. Keep the
    # per-source statuses for retries and diagnostics, but show one merged card
    # with all discovered service buttons instead of duplicate releases.
    if bundle.tracks:
        bundle.tracks = coalesce_equivalent_tracks(bundle.tracks)
    kind = delivery_kind(bundle)
    # Multi-source input is an instruction, not editorial copy. Even when
    # cross-service merging leaves one card, never quote the submitted URLs.
    prefix = (
        "" if len(request.source_urls) > 1 or bundle.item_count > 1 else user_prefix
    )
    common = {
        "user_prefix": prefix,
        "include_channel_button": request.include_channel_button,
        "include_hashtags": request.include_hashtags,
        "lang": request.lang,
    }
    if kind == "tracks":
        await _send_track_matches(
            message,
            context,
            bundle.tracks,
            is_private=request.is_private,
            user_id=request.user_id,
            search_query=request.search_query,
            requested_count=(
                len(bundle.tracks) if not partial else len(request.source_urls)
            ),
            allow_share=not partial,
            **common,
        )
    elif kind == "videos":
        await _send_youtube_result(
            context.bot,
            message,
            bundle.videos,
            requested_count=len(request.source_urls),
            allow_share=not partial,
            **common,
        )
        _record_videos_safely(bundle.videos, message, context=context)
    elif kind == "radios":
        await _send_nts_result(
            context.bot,
            message,
            bundle.radios,
            requested_count=len(request.source_urls),
            allow_share=not partial,
            **common,
        )
        _record_radios_safely(bundle.radios, message, context=context)
    elif kind == "playlists":
        import_id = None
        if (
            request.is_private
            and len(bundle.playlists) == 1
            and bundle.playlists[0].track_urls
        ):
            import_id = await _store_retry_sources(
                context,
                request.user_id,
                bundle.playlists[0].track_urls[:MAX_LINKS_PER_MESSAGE],
            )
        await _send_playlist_result(
            context.bot,
            message,
            bundle.playlists,
            requested_count=len(request.source_urls),
            allow_share=not partial,
            import_id=import_id,
            **common,
        )
        _record_playlists_safely(bundle.playlists, message, context=context)
    elif kind == "artists":
        await _send_artist_result(
            context.bot,
            message,
            bundle.artists,
            requested_count=len(request.source_urls),
            allow_share=not partial,
            **common,
        )
        _record_artists_safely(bundle.artists, message, context=context)
    elif kind == "mixed":
        await _send_mixed_result(
            context.bot,
            message,
            bundle.tracks,
            bundle.videos,
            bundle.radios,
            bundle.playlists,
            bundle.artists,
            context=context,
            requested_count=len(request.source_urls),
            allow_share=not partial,
            **common,
        )
        _record_mixed_safely(
            bundle.tracks,
            bundle.videos,
            bundle.radios,
            bundle.playlists,
            bundle.artists,
            message,
            context=context,
        )
    await _send_partial_lookup_status(
        message,
        context,
        bundle,
        user_id=request.user_id,
        lang=request.lang,
    )


_bot_lookup.configure_track_result_sender(_send_track_result)
_bot_lookup.configure_track_video_pair_sender(_send_track_video_pair_result)


def _build_intro_keyboard(
    bot_username: str | None,
    *,
    active: str | None = None,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    del active
    return _build_section_keyboard(bot_username, lang=lang)


def _build_error_keyboard(
    bot_username: str | None,
    *,
    lang: str = "ru",
    retryable: bool = False,
    search_query: str | None = None,
    source_url: str | None = None,
) -> InlineKeyboardMarkup:
    return _build_error_keyboard_view(
        bot_username,
        lang=lang,
        retryable=retryable,
        search_query=search_query,
        source_url=source_url,
    )


async def _notify_admin(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    only_for_channel_message: Message | None = None,
) -> None:
    if only_for_channel_message and only_for_channel_message.chat.type != "channel":
        return

    admin_chat_id: int | None = context.application.bot_data.get("admin_chat_id")
    if admin_chat_id is None:
        return

    try:
        await context.bot.send_message(chat_id=admin_chat_id, text=text)
    except TelegramError:
        LOGGER.info("Could not notify admin chat %s", admin_chat_id)
