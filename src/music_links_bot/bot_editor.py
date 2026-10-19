"""Editor callbacks: every button on a draft card and its screens."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from html import escape

from telegram import (
    ForceReply,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from music_links_bot.bot_actions import action_spec
from music_links_bot.bot_builder import (
    MAX_SCHEDULE_DAYS,
    BuilderScreen,
    active_card_label,
    builder_screen,
    fit_telegram_html,
    schedule_timestamp,
)
from music_links_bot.bot_crate import (
    add_to_crate,
    crate_contains_item,
    load_crate,
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
from music_links_bot.bot_lookup_flow import (
    _BYPASS_INTENT_GUARD,
    _INPUT_OVERRIDE,
    track_lookup_message,
)
from music_links_bot.bot_menu import (
    runtime_for as _runtime,
)
from music_links_bot.bot_progress import (
    adopt_progress_message as _adopt_progress_message,
)
from music_links_bot.bot_release_settings import apply_release_setting
from music_links_bot.bot_runtime import (
    CallbackAction,
    decode_callback,
    encode_callback,
)
from music_links_bot.bot_storage import (
    load_draft as _load_draft,
    store_draft as _store_draft,
)
from music_links_bot.bot_ui import (
    build_delete_confirmation_keyboard as _delete_confirmation_keyboard,
    build_deleted_draft_keyboard as _deleted_draft_keyboard,
    build_delivery_success_keyboard as _build_delivery_success_keyboard,
    build_duplicate_post_keyboard as _duplicate_post_keyboard,
    build_publish_confirmation as _build_publish_confirmation,
    editor_appearance_rows,
    editor_hashtag_rows as _editor_hashtag_rows,
    editor_intro_rows as _editor_intro_rows,
    editor_overflow_rows as _editor_overflow_rows,
    editor_platform_rows as _editor_platform_rows,
    editor_schedule_rows as _editor_schedule_rows,
    editor_template_rows as _editor_template_rows,
    editor_text_rows,
    editor_tools_rows,
)
from music_links_bot.branding import (
    brand_label,
    brand_logo_url,
    build_branded_cover,
    photo_branding_enabled,
)
from music_links_bot.channel_templates import (
    apply_template,
)
from music_links_bot.constants import CHANNEL_USERNAME, channel_target
from music_links_bot.editor_view import (
    draft_intro_limit as _draft_intro_limit,
    render_track_draft as _render_track_draft,
)
from music_links_bot.i18n import get_text, resolve_lang
from music_links_bot.keyboards import (
    _build_link_preview_options,
    _get_platform_order,
)
from music_links_bot.models import (
    TrackMatch,
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
from music_links_bot.publication_view import editor_preview_url
from music_links_bot.publish_queue import (
    QueueBusyError,
    QueueFullError,
    QueueStorageError,
    add_job,
)
from music_links_bot.telegram_buttons import (
    ButtonTone,
    button as InlineKeyboardButton,
    callback_button,
    disabled_button,
)
from music_links_bot.telegram_messages import (
    delete_message_safely as _try_delete_message,
)

LOGGER = logging.getLogger(__name__)


DRAFT_UNDO_SECONDS = 15


_SIMPLE_EDITOR_SCREENS = {
    BuilderScreen.APPEARANCE: ("ed_appearance_title", editor_appearance_rows),
    BuilderScreen.TEXT: ("ed_text_title", editor_text_rows),
    BuilderScreen.TOOLS: ("ed_tools_title", editor_tools_rows),
    BuilderScreen.INTRO: ("ed_intro_title", _editor_intro_rows),
    BuilderScreen.HASHTAGS: ("ed_hashtags_title", _editor_hashtag_rows),
}


_PREFLIGHT_EDITOR_ACTIONS = frozenset(
    {"p", "qt", "q1", "q3", "qe", "qd", "pc", "r", "x", "s"}
)


_SCHEDULE_EDITOR_ACTIONS = frozenset({"qt", "q1", "q3", "qe", "qd"})


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
    schedule_at: int | None = None

    @property
    def user_id(self) -> int:
        user = getattr(self.query, "from_user", None)
        return int(user.id) if user is not None else 0


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
        text, _ = _render_track_draft(
            draft, context, draft_id=draft_id, show_status=True
        )
        text = f"{get_text(lang, 'ed_actions_title')}\n\n{text}"
        overflow_rows = _editor_overflow_rows(draft_id, draft)
        keyboard = InlineKeyboardMarkup(overflow_rows)
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
        timezone_name = str(
            context.application.bot_data.get("timezone_name") or "Europe/Moscow"
        )
        from music_links_bot.human_time import human_zone

        text += "\n\n" + get_text(lang, "schedule_timezone").format(
            zone=escape(human_zone(timezone_name, lang=lang))
        )
        keyboard = InlineKeyboardMarkup(
            _editor_schedule_rows(draft_id, draft, timezone_name=timezone_name)
        )
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


async def _handle_release_setting(request: EditorActionRequest) -> bool:
    screen = await apply_release_setting(request)
    if screen is None:
        return False
    if screen == "answered":
        return True
    await _store_draft(request.context, request.draft_id, request.draft)
    await _handle_editor_navigation(
        request.query,
        request.context,
        action=screen,
        draft_id=request.draft_id,
        draft=request.draft,
        lang=request.lang,
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
        answer_text=get_text(request.lang, "settings_saved"),
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
    target = str(channel_target(request.context.application.bot_data))
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
    elif request.action in {"pc", "r", "x"}:
        # Publish, repeat and replace all affect the same channel post.
        lock_action = "publish"
    elif request.action in _PRIMARY_EDITOR_ACTIONS:
        lock_action = request.action
    else:
        return False
    from music_links_bot.delivery_receipts import DeliveryBlockedError

    runtime = _runtime(request.context)
    lock_key = f"{request.user_id}:{lock_action}:{request.draft_id}"
    token = await runtime.acquire_action(lock_key)
    if token is None:
        await request.query.answer(
            get_text(request.lang, "action_busy"),
            show_alert=True,
        )
        return True
    try:
        if request.action in _PRIMARY_EDITOR_ACTIONS:
            await _show_action_busy(request.query, request.lang)
        if request.action in _SCHEDULE_EDITOR_ACTIONS:
            await _schedule_editor_draft(
                request.query,
                request.context,
                request.action,
                request.draft,
                lang=request.lang,
                publish_at=request.schedule_at,
                draft_id=request.draft_id,
            )
        else:
            await _run_primary_editor_action(request)
    except DeliveryBlockedError as exc:
        await _show_delivery_recovery(request, exc.receipt)
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
        action="ap" if request.action == "cr" else "rs",
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
    await _save_editor_settings(request)
    await request.query.answer(
        get_text(request.lang, "settings_saved") if request.action != "f" else None
    )
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
    revision = None
    if "~" in draft_id:
        draft_id, raw_revision = draft_id.rsplit("~", 1)
        if not raw_revision.isdigit() or len(raw_revision) > 10:
            await query.answer(get_text(user_lang, "ed_expired"), show_alert=True)
            return
        revision = int(raw_revision)
    schedule_at = None
    if action == "qt":
        draft_id, separator, raw_timestamp = draft_id.partition(":")
        if (
            not separator
            or not raw_timestamp.isascii()
            or not raw_timestamp.isdigit()
            or len(raw_timestamp) > 11
        ):
            await query.answer(get_text(user_lang, "schedule_stale"), show_alert=True)
            return
        schedule_at = int(raw_timestamp)
    draft = await _load_draft(context, draft_id)
    if draft is None:
        await query.answer(get_text(user_lang, "ed_expired"), show_alert=True)
        return

    lang = resolve_lang(draft.get("lang") or user_lang)
    if query.from_user is None or not _draft_owned_by(draft, query.from_user.id):
        await query.answer(get_text(lang, "ed_owner_only"), show_alert=True)
        return
    if draft.get("deleted_at") and action != "du":
        await query.answer(get_text(lang, "ed_deleted_recovery"), show_alert=True)
        return
    if (
        revision is not None
        and revision != int(draft.get("revision") or 0)
        and action not in {"b", "m", "pv", "ap", "hs", "ls", "why_tags"}
    ):
        await query.answer(get_text(lang, "state_conflict"), show_alert=True)
        text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
        await _edit_editor_message(query, context, draft, text, keyboard)
        return
    crate_items = await load_crate(context.application.bot_data, query.from_user.id)
    draft["in_crate"] = crate_contains_item(crate_items, draft["item"])
    draft["crate_count"] = len(crate_items)
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
        schedule_at=schedule_at,
    )
    from music_links_bot.bot_publish_undo import handle_unpublish
    from music_links_bot.bot_workspace import handle_workspace_action

    for handler in (
        handle_workspace_action,
        handle_unpublish,
        _apply_last_editor_template,
        _reject_failed_editor_preflight,
        _handle_release_setting,
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
    if draft is not None:
        prompt_text = (
            get_text(lang, "pending_for_post").format(
                release=escape(active_card_label(draft, ""))
            )
            + "\n\n"
            + prompt_text
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
        "draft_revision": int((draft or {}).get("revision") or 0),
    }
    await _runtime(context).save_session(session)
    await query.answer()


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
    from music_links_bot.human_time import human_datetime, local_time_html

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
        from music_links_bot.bot_publish_undo import remember_publication

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
    from music_links_bot.bot_ui import build_publish_success_keyboard
    from music_links_bot.human_time import local_time_html

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
    await _edit_editor_message(
        request.query,
        request.context,
        request.draft,
        success_text,
        keyboard,
    )


async def _show_editor_delivery_success(request: EditorActionRequest) -> None:
    """Replace the busy editor with a small, terminal success state."""
    from music_links_bot.bot_ui import draft_share_query

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


def _editor_success_text(request: EditorActionRequest, title_key: str) -> str:
    return (
        f"{get_text(request.lang, title_key)}\n\n"
        f"<blockquote><b>{escape(request.track.artist)}</b> — "
        f"{escape(request.track.title)}</blockquote>"
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
    from music_links_bot.bot_ui import version_editor_keyboard

    keyboard = version_editor_keyboard(keyboard, draft)
    track = TrackMatch(**draft["item"])
    text = fit_telegram_html(text)
    try:
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            link_preview_options=_build_link_preview_options(
                editor_preview_url(draft, track, context),
                prefer_large_media=bool(draft.get("large_preview")),
            ),
            reply_markup=keyboard,
        )
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


async def _publish_draft(context, draft):
    target = channel_target(context.application.bot_data)
    return await _deliver_draft(context, draft, target=target, channel_style=True)


async def _deliver_draft(context, draft, *, target, channel_style):
    from music_links_bot.delivery_receipts import begin_delivery, finish_delivery

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
        from music_links_bot.delivery_receipts import DeliveryBlockedError

        raise DeliveryBlockedError({**intent[1], "status": "uncertain"})
    return sent


async def _show_delivery_recovery(request, receipt):
    from music_links_bot.publication_state import _message_url

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
