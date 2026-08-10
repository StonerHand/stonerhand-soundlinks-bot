from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Awaitable, Callable
from dataclasses import asdict
import hashlib
from html import escape
import logging
import secrets
import time

from telegram import (
    Bot,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, ContextTypes
from music_links_bot.branding import (
    brand_label,
    brand_logo_url,
    build_branded_cover,
    photo_branding_enabled,
)
from music_links_bot.bot_stats import (
    build_user_prefix as _build_user_prefix,
    message_text as _message_text,
    record_artist_items as _record_artists_safely,
    record_mixed_items as _record_mixed_safely,
    record_playlist_items as _record_playlists_safely,
    record_radio_items as _record_radios_safely,
    record_tracks as _record_matches_safely,
    record_video_items as _record_videos_safely,
)
from music_links_bot.bot_batch import (
    send_partial_lookup_status as _send_partial_lookup_status_impl,
)
from music_links_bot.bot_admin import (
    id_command,
    stats_command,
    stats_text as _stats_text,
    status_command,
)
from music_links_bot.bot_app import (
    BOT_DESCRIPTIONS,
    BOT_SHORT_DESCRIPTIONS,
    PUBLIC_BOT_COMMANDS,
    close_application_resources,
    sync_application_commands,
)
from music_links_bot.bot_inline import (
    _build_inline_collection_result,
    _build_inline_result,
    inline_query_handler,
)

from music_links_bot import bot_lookup as _bot_lookup

_split_source_urls = _bot_lookup._split_source_urls
_format_not_found_message = _bot_lookup._format_not_found_message
_strip_bot_mention = _bot_lookup._strip_bot_mention
_format_no_url_message = _bot_lookup._format_no_url_message
_format_service_unavailable_message = _bot_lookup._format_service_unavailable_message
_has_recovery_hint = _bot_lookup._has_recovery_hint
_lookup_playlists = _bot_lookup._lookup_playlists
_lookup_artists = _bot_lookup._lookup_artists
_empty_track_lookup = _bot_lookup._empty_track_lookup
_empty_video_lookup = _bot_lookup._empty_video_lookup
_empty_radio_lookup = _bot_lookup._empty_radio_lookup
_empty_playlist_lookup = _bot_lookup._empty_playlist_lookup
_empty_artist_lookup = _bot_lookup._empty_artist_lookup
_lookup_youtube_videos = _bot_lookup._lookup_youtube_videos
_lookup_nts_radios = _bot_lookup._lookup_nts_radios
_send_youtube_result = _bot_lookup._send_youtube_result
_send_nts_result = _bot_lookup._send_nts_result
_send_playlist_result = _bot_lookup._send_playlist_result
_send_artist_result = _bot_lookup._send_artist_result
_send_mixed_result = _bot_lookup._send_mixed_result
_select_mixed_preview_url = _bot_lookup._select_mixed_preview_url
_lookup_tracks = _bot_lookup._lookup_tracks
_fill_genres = _bot_lookup._fill_genres
_ensure_spotify_link = _bot_lookup._ensure_spotify_link
_build_lookup_fallback = _bot_lookup._build_lookup_fallback
_songlink_page_url = _bot_lookup._songlink_page_url
_build_podcast_fallback = _bot_lookup._build_podcast_fallback

from music_links_bot.config import Settings
from music_links_bot.chat_access import check_publish_access
from music_links_bot.channel_templates import apply_channel_template, save_channel_template
from music_links_bot.ephemeral import (
    ephemeral_group_replies_enabled,
    send_ephemeral_message,
)
from music_links_bot.i18n import get_text, resolve_lang

from music_links_bot import keyboards as _keyboards

_select_preview_url = _keyboards._select_preview_url
_build_link_preview_options = _keyboards._build_link_preview_options
_build_link_keyboard = _keyboards._build_link_keyboard
_platform_button_label = _keyboards._platform_button_label
_build_collection_keyboard = _keyboards._build_collection_keyboard
_build_youtube_keyboard = _keyboards._build_youtube_keyboard
_build_nts_keyboard = _keyboards._build_nts_keyboard
_build_playlist_keyboard = _keyboards._build_playlist_keyboard
_build_artist_keyboard = _keyboards._build_artist_keyboard
_build_youtube_collection_keyboard = _keyboards._build_youtube_collection_keyboard
_build_nts_collection_keyboard = _keyboards._build_nts_collection_keyboard
_build_playlist_collection_keyboard = _keyboards._build_playlist_collection_keyboard
_build_artist_collection_keyboard = _keyboards._build_artist_collection_keyboard
_build_mixed_collection_keyboard = _keyboards._build_mixed_collection_keyboard
_should_include_channel_button = _keyboards._should_include_channel_button
_should_include_hashtags = _keyboards._should_include_hashtags
_build_platform_order = _keyboards._build_platform_order
_normalize_platform_key = _keyboards._normalize_platform_key
_shorten_button_text = _keyboards._shorten_button_text
_track_button_icon = _keyboards._track_button_icon
_release_hub_button_label = _keyboards._release_hub_button_label
_get_ui_mode = _keyboards._get_ui_mode
_button_rows = _keyboards._button_rows
_keyboard_with_optional_channel = _keyboards._keyboard_with_optional_channel
_single_url_keyboard = _keyboards._single_url_keyboard
_channel_button = _keyboards._channel_button
_get_platform_order = _keyboards._get_platform_order

from music_links_bot.bot_crate import (
    add_many_to_crate,
    add_to_crate,
    crate_contains_item,
    load_crate,
    load_crate_title,
    move_crate_item,
    remove_crate_item,
    restore_crate_item,
    save_crate,
    save_crate_title,
)
from music_links_bot.bot_editor_state import (
    apply_setting_action as _apply_editor_setting,
    draft_owned_by as _draft_owned_by,
    draft_status as _draft_status,
    remember_draft as _remember_session_draft,
)
from music_links_bot.bot_runtime import (
    BotErrorCode,
    BotFlowError,
    BotRuntime,
    CallbackAction,
    UserSession,
    decode_callback,
    detect_action,
    encode_callback,
)
from music_links_bot.bot_storage import (
    DRAFT_TTL_SECONDS as _DRAFT_TTL_SECONDS,
    MAX_MEMORY_DRAFTS as _MAX_MEMORY_DRAFTS,
    load_draft as _load_draft,
    load_retry_sources as _load_retry_sources,
    load_search_selection as _load_search_selection,
    remember_bounded as _remember_bounded,
    store_draft as _store_draft,
    store_search_selection as _store_search_selection,
)
from music_links_bot.bot_progress import (
    adopt_progress_message as _adopt_progress_message,
    cancel_progress as _cancel_progress,
    start_progress as _send_loading_placeholder,
    take_progress as _take_placeholder,
    update_progress as _update_loading_placeholder,
    update_progress_text as _update_progress_text,
)
from music_links_bot.bot_pipeline import LookupRequest, delivery_kind
from music_links_bot.bot_recent import render_recent_view
from music_links_bot.bot_ui import (
    build_create_keyboard as _build_create_keyboard,
    build_deleted_draft_keyboard as _deleted_draft_keyboard,
    build_delete_confirmation_keyboard as _delete_confirmation_keyboard,
    build_duplicate_post_keyboard as _duplicate_post_keyboard,
    build_error_keyboard as _build_error_keyboard_view,
    build_home_text as _build_home_text,
    build_onboarding_keyboard as _build_onboarding_keyboard,
    build_publish_confirmation as _build_publish_confirmation,
    build_section_keyboard as _build_section_keyboard,
    build_start_keyboard as _build_start_keyboard,
    editor_more_rows as _editor_more_rows,
    editor_hashtag_rows as _editor_hashtag_rows,
    editor_intro_rows as _editor_intro_rows,
    editor_overflow_rows as _editor_overflow_rows,
    editor_platform_rows as _editor_platform_rows,
    editor_preview_rows as _editor_preview_rows,
    editor_rows as _editor_rows,
    editor_schedule_rows as _editor_schedule_rows,
    editor_style_rows as _editor_style_rows,
    render_crate as _render_bot_crate,
)
from music_links_bot.search import (
    SearchClient,
    SearchLookupError,
    normalize_search_query,
)
from music_links_bot.constants import MAX_LINKS_PER_MESSAGE
from music_links_bot.formatter import (
    format_collection_message,
    format_track_message,
)
from music_links_bot.models import (
    TrackMatch,
    VideoMatch,
)
from music_links_bot.draft_model import new_track_draft
from music_links_bot.bot_builder import (
    BuilderScreen,
    active_card_label,
    apply_custom_tags,
    apply_intro_text,
    builder_screen,
    fit_telegram_html,
    remove_intro,
    remove_tags,
    schedule_timestamp,
    select_all_platforms,
    select_preset,
    toggle_platform,
    use_auto_tags,
    normalize_crate_title,
    PENDING_INPUT_TTL_SECONDS,
)
from music_links_bot.mixed_post import send_track_video_album
from music_links_bot.publication_state import (
    find_posted_record as _find_posted_record,
    mark_posted as _schedule_mark_posted,
    release_fingerprint as _release_fingerprint,
)
from music_links_bot.publication_service import PublicationService
from music_links_bot.publish_queue import QueueBusyError, QueueStorageError, add_job
from music_links_bot.publication_view import (
    build_publication_view,
    draft_message_overrides,
    draft_platform_selection,
)

_draft_message_overrides = draft_message_overrides
_draft_platform_selection = draft_platform_selection
from music_links_bot.sharing import (
    add_share_button,
    build_share_query,
    collection_result_title,
    make_channel_safe_keyboard,
    track_share_url,
)
from music_links_bot.bot_history import record_history as _record_recent_item
from music_links_bot.text_utils import normalize_hashtag
from music_links_bot.telegram_buttons import (
    ButtonTone,
    callback_button,
    current_chat_button,
)
from music_links_bot.url_utils import (
    cache_key_for_url,
    extract_supported_urls,
)

LOGGER = logging.getLogger(__name__)
__all__ = [
    "BOT_DESCRIPTIONS",
    "BOT_SHORT_DESCRIPTIONS",
    "PUBLIC_BOT_COMMANDS",
    "_build_inline_collection_result",
    "_build_inline_result",
    "_release_fingerprint",
    "close_application_resources",
    "id_command",
    "inline_query_handler",
    "normalize_hashtag",
    "stats_command",
    "status_command",
    "sync_application_commands",
]
CHANNEL_USERNAME = "stonerhand"
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME}"
CHANNEL_BUTTON_TEXT = "🪨 Открыть канал"
MENU_START = "menu:start"
MENU_HELP = "menu:help"
MENU_GUIDE = "menu:guide"
MENU_PLATFORMS = "menu:platforms"
MENU_DEMO = "menu:demo"
MENU_MORE = "menu:more"
MENU_RECENT = "menu:recent"
MENU_KEYS = frozenset(
    (
        MENU_START,
        MENU_HELP,
        MENU_GUIDE,
        MENU_PLATFORMS,
        MENU_DEMO,
        MENU_MORE,
        MENU_RECENT,
    )
)
CRATE_UNDO_SECONDS = 15
MAX_CRATE_UNDO_RECORDS = 300
DRAFT_UNDO_SECONDS = 15
DEFAULT_UI_MODE = "stonerhand"
MAX_BUTTON_TEXT_LENGTH = 64
STATS_KV_KEY = "stats:v1"
# Public compatibility constants used by tests and queue storage.
DRAFT_TTL_SECONDS = _DRAFT_TTL_SECONDS
MAX_MEMORY_DRAFTS = _MAX_MEMORY_DRAFTS

_INPUT_OVERRIDE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "input_override", default=None
)
_SEARCH_QUERY_OVERRIDE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "search_query_override", default=None
)
_BYPASS_INTENT_GUARD: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "bypass_intent_guard", default=False
)
DEFAULT_PLATFORM_ORDER = (
    "spotify",
    "appleMusic",
    "applePodcasts",
    "youtubeMusic",
    "soundcloud",
    "deezer",
    "tidal",
    "yandexMusic",
)
PRIMARY_PLATFORM_ALIASES = {
    "spotify": "spotify",
    "apple": "appleMusic",
    "applemusic": "appleMusic",
    "itunes": "appleMusic",
    "applepodcasts": "applePodcasts",
    "podcasts": "applePodcasts",
    "youtube": "youtubeMusic",
    "youtubemusic": "youtubeMusic",
    "ytmusic": "youtubeMusic",
    "soundcloud": "soundcloud",
    "sc": "soundcloud",
    "deezer": "deezer",
    "tidal": "tidal",
    "yandex": "yandexMusic",
    "yandexmusic": "yandexMusic",
    "yamusic": "yandexMusic",
}
NOT_FOUND_DETAIL = (
    "Проверь, что это ссылка на трек, альбом, плейлист, артиста, "
    "подкаст, YouTube-видео или NTS Radio"
)


def build_application(settings: Settings) -> Application:
    from music_links_bot.bot_app import build_application as assemble

    return assemble(settings)


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


def _update_lang(update: Update) -> str:
    user = update.effective_user
    return resolve_lang(user.language_code if user else None)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    lang = _update_lang(update)
    user_id = update.effective_user.id if update.effective_user else update.message.chat_id
    runtime = _runtime(context)
    if not await runtime.claim_intent(user_id, kind="command", value="start"):
        return
    session = await runtime.get_session(user_id, lang=lang)
    active_draft_id, active_draft_label = await _active_home_card(
        context, runtime, session, lang=lang
    )
    crate_count, is_admin = await _home_state(context, user_id)
    text = _build_home_text(
        lang=lang,
        first_name=update.effective_user.first_name if update.effective_user else "",
        crate_count=crate_count,
        is_admin=is_admin,
        first_visit=not session.onboarding_seen,
    )
    keyboard = _build_start_keyboard(
        context.bot.username,
        lang=lang,
        crate_count=crate_count,
        is_admin=is_admin,
        show_tour=not session.onboarding_seen,
        active_draft_id=active_draft_id,
        active_draft_label=active_draft_label,
    )
    sent = await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    if update.message.chat.type == "private":
        await _remember_fresh_home_message(
            context,
            runtime,
            session,
            chat_id=update.message.chat_id,
            sent=sent,
        )


async def _remember_fresh_home_message(
    context: ContextTypes.DEFAULT_TYPE,
    runtime: BotRuntime,
    session: UserSession,
    *,
    chat_id: int,
    sent: Message,
) -> None:
    """Point navigation at a visible reply, then retire the previous menu.

    A slash command is an explicit request for feedback at the bottom of the
    chat. Editing an old home message can succeed off-screen — or return
    ``Message is not modified`` — while looking like the command was ignored.
    """
    message_id = getattr(sent, "message_id", None)
    if not isinstance(message_id, int) or message_id <= 0:
        return

    previous_chat_id = session.home_chat_id
    previous_message_id = session.home_message_id
    session.home_chat_id = chat_id
    session.home_message_id = message_id
    await runtime.save_session(session)

    if (
        previous_chat_id != chat_id
        or not previous_message_id
        or previous_message_id == message_id
    ):
        return
    try:
        await context.bot.delete_message(
            chat_id=previous_chat_id,
            message_id=previous_message_id,
        )
    except TelegramError:
        # The new menu is already live and saved, so stale-message cleanup must
        # never make a successfully handled command look failed.
        LOGGER.debug("Could not retire previous home message", exc_info=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await _reply_with_menu(update.message, context, MENU_HELP, lang=_update_lang(update))


async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return

    lang = _update_lang(update)
    if message.chat.type == "private":
        await _reply_with_menu(message, context, MENU_GUIDE, lang=lang)
        return

    user_id = update.effective_user.id if update.effective_user else message.chat_id
    crate_count, _is_admin = await _home_state(context, user_id)
    sent_message = await message.reply_text(
        _menu_text(MENU_GUIDE, lang=lang),
        parse_mode=ParseMode.HTML,
        reply_markup=_build_section_keyboard(
            context.bot.username,
            lang=lang,
            crate_count=crate_count,
            active="guide",
        ),
    )

    if message.chat.type in {"group", "supergroup", "channel"}:
        try:
            await sent_message.pin(disable_notification=True)
        except (BadRequest, Forbidden):
            LOGGER.info("Could not pin guide in chat %s", message.chat_id)


async def platforms_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await _reply_with_menu(
        update.message,
        context,
        MENU_PLATFORMS,
        lang=_update_lang(update),
    )


async def channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if not update.message:
        return

    await update.message.reply_text(
        "StonerHand рядом",
        reply_markup=InlineKeyboardMarkup([[_channel_button()]]),
    )


def _runtime(context: ContextTypes.DEFAULT_TYPE) -> BotRuntime:
    runtime = context.application.bot_data.get("runtime")
    if not isinstance(runtime, BotRuntime):
        runtime = BotRuntime(context.application.bot_data.get("kv_store"))
        context.application.bot_data["runtime"] = runtime
    return runtime


async def _home_state(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> tuple[int, bool]:
    items = await load_crate(context.application.bot_data, user_id)
    admin_chat_id = context.application.bot_data.get("admin_chat_id")
    return len(items), admin_chat_id is not None and user_id == admin_chat_id


async def _active_home_draft_id(
    context: ContextTypes.DEFAULT_TYPE,
    runtime: BotRuntime,
    session: UserSession,
) -> str | None:
    """Return only a live, restorable card and forget stale home pointers."""
    draft_id = session.active_draft_id
    if not draft_id:
        return None
    draft = await _load_draft(context, draft_id)
    if draft is not None and not draft.get("deleted_at"):
        return draft_id
    session.active_draft_id = ""
    await runtime.save_session(session)
    return None


async def _active_home_card(
    context: ContextTypes.DEFAULT_TYPE,
    runtime: BotRuntime,
    session: UserSession,
    *,
    lang: str,
) -> tuple[str | None, str | None]:
    draft_id = await _active_home_draft_id(context, runtime, session)
    if not draft_id:
        return None, None
    draft = await _load_draft(context, draft_id)
    if draft is None:
        return None, None
    return draft_id, active_card_label(draft, get_text(lang, "home_continue"))


async def _home_view(query, context, *, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    user = query.from_user
    user_id = user.id if user else 0
    crate_count, is_admin = await _home_state(context, user_id)
    runtime = _runtime(context)
    session = await runtime.get_session(user_id, lang=lang)
    active_draft_id, active_draft_label = await _active_home_card(
        context, runtime, session, lang=lang
    )
    text = _build_home_text(
        lang=lang,
        first_name=user.first_name if user else "",
        crate_count=crate_count,
        is_admin=is_admin,
    )
    keyboard = _build_start_keyboard(
        context.bot.username,
        lang=lang,
        crate_count=crate_count,
        is_admin=is_admin,
        active_draft_id=active_draft_id,
        active_draft_label=active_draft_label,
    )
    return text, keyboard


async def bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Versioned callback dispatcher for all new interactive bot surfaces."""
    query = update.callback_query
    parsed = decode_callback(query.data if query else None)
    if query is None or parsed is None:
        return

    runtime = _runtime(context)
    callback_id = str(getattr(query, "id", "") or hashlib.sha256(query.data.encode()).hexdigest())
    if not await runtime.claim_callback(callback_id):
        lang = resolve_lang(query.from_user.language_code if query.from_user else None)
        await query.answer(get_text(lang, "action_duplicate"))
        return

    handlers: dict[str, Callable[[object, ContextTypes.DEFAULT_TYPE, CallbackAction], Awaitable[None]]] = {
        "menu": _dispatch_menu_action,
        "select": _dispatch_selection_action,
        "editor": _dispatch_editor_action,
        "crate": _dispatch_crate_action,
        "retry": _dispatch_retry_action,
        "noop": _dispatch_noop_action,
    }
    handler = handlers.get(parsed.scope)
    if handler is None:
        await query.answer()
        return
    await handler(query, context, parsed)


async def _dispatch_noop_action(query, context, action: CallbackAction) -> None:
    del context, action
    await query.answer()


async def _dispatch_menu_action(query, context, action: CallbackAction) -> None:
    lang = resolve_lang(query.from_user.language_code if query.from_user else None)
    if action.action.startswith("onboard"):
        step = action.action.removeprefix("onboard") or "1"
        if step == "done":
            session = await _runtime(context).get_session(query.from_user.id, lang=lang)
            session.onboarding_seen = True
            await _runtime(context).save_session(session)
            text, keyboard = await _home_view(query, context, lang=lang)
        else:
            step_number = max(1, min(3, int(step)))
            text = get_text(lang, f"onboarding_{step_number}")
            keyboard = _build_onboarding_keyboard(step_number, lang)
        await query.answer()
        await _safe_edit(query, text, keyboard)
        return

    if action.action == "stats":
        user_id = query.from_user.id if query.from_user else 0
        crate_count, is_admin = await _home_state(context, user_id)
        if not is_admin:
            await query.answer(get_text(lang, "ed_admin_only"), show_alert=True)
            return
        text = escape(await _stats_text(context, include_private=True))
        await query.answer()
        await _safe_edit(
            query,
            text,
            _build_section_keyboard(
                context.bot.username,
                lang=lang,
                crate_count=crate_count,
                active=None,
            ),
        )
        return

    if action.action == "start":
        text, keyboard = await _home_view(query, context, lang=lang)
        await query.answer()
        await _safe_edit(query, text, keyboard)
        return

    if action.action == "recent":
        await query.answer()
        text, keyboard = await _recent_view(query, context, lang=lang)
        await _safe_edit(query, text, keyboard)
        return

    if action.action == "create":
        await query.answer()
        await _safe_edit(
            query,
            get_text(lang, "create_prompt"),
            _build_create_keyboard(lang=lang),
        )
        return

    menu_key = {
        "start": MENU_START,
        "help": MENU_HELP,
        "guide": MENU_GUIDE,
        "platforms": MENU_PLATFORMS,
        "demo": MENU_DEMO,
        "more": MENU_MORE,
    }.get(action.action, MENU_START)
    await query.answer()
    user_id = query.from_user.id if query.from_user else 0
    crate_count, _is_admin = await _home_state(context, user_id)
    await _safe_edit(
        query,
        _menu_text(menu_key, lang=lang),
        _build_section_keyboard(
            context.bot.username,
            lang=lang,
            crate_count=crate_count,
            active=action.action,
        ),
    )


async def _recent_view(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    lang: str,
) -> tuple[str, InlineKeyboardMarkup]:
    user_id = query.from_user.id if query.from_user else 0
    session = await _runtime(context).get_session(user_id, lang=lang)
    return await render_recent_view(
        context,
        user_id=user_id,
        lang=lang,
        draft_ids=session.recent_draft_ids,
        load_draft=_load_draft,
    )


async def _safe_edit(query, text: str, keyboard: InlineKeyboardMarkup | None) -> None:
    try:
        await query.edit_message_text(
            text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    await query.answer()
    lang = resolve_lang(query.from_user.language_code if query.from_user else None)
    menu_key = query.data if query.data in MENU_KEYS else MENU_START
    if menu_key == MENU_START:
        text, keyboard = await _home_view(query, context, lang=lang)
    else:
        user_id = query.from_user.id if query.from_user else 0
        crate_count, _is_admin = await _home_state(context, user_id)
        text = _menu_text(menu_key, lang=lang)
        keyboard = _build_section_keyboard(
            context.bot.username,
            lang=lang,
            crate_count=crate_count,
            active=menu_key.removeprefix("menu:"),
        )
    try:
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            return
        raise


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
        can_publish=(
            admin_chat_id is not None and user_id == admin_chat_id
        ),
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
    )
    await _store_draft(context, draft_id, draft)
    session = await _runtime(context).get_session(user_id, lang=lang)
    _remember_session_draft(session, draft_id)
    await _runtime(context).save_session(session)
    source_url = track_share_url(track) or track.page_url or ""
    if source_url:
        await _record_recent_item(context, user_id, track, source_url)


def _render_track_draft(
    draft: dict,
    context: ContextTypes.DEFAULT_TYPE | None,
    *,
    draft_id: str | None = None,
    settings: bool = False,
    show_status: bool = False,
) -> tuple[str, InlineKeyboardMarkup]:
    track = TrackMatch(**draft["item"])
    view = build_publication_view(
        draft,
        track,
        context=context,
        include_channel_button=False,
        max_visible_platforms=1 if draft_id is not None else None,
    )
    text = view.text
    if settings:
        lang = draft.get("lang") or "ru"
        status = _draft_status(draft, track, lang=lang)
        text = (
            f"🎛 <b>{escape(get_text(lang, 'ed_constructor_title'))}</b>\n"
            f"<i>{escape(get_text(lang, 'ed_constructor_hint'))}</i>\n"
            f"<i>{escape(status)}</i>\n\n{text}"
        )
    elif show_status:
        lang = draft.get("lang") or "ru"
        status = _draft_status(draft, track, lang=lang)
        text = f"{text}\n\n<i>{escape(status)}</i>"
    keyboard = view.keyboard
    if draft_id is None:
        return text, add_share_button(
            keyboard,
            share_query=build_share_query(
                [url] if (url := track_share_url(track)) else []
            ),
            label=get_text(draft.get("lang") or "ru", "share_post"),
        )

    base_rows = [list(row) for row in keyboard.inline_keyboard]
    url_buttons = [button for row in base_rows for button in row]
    rows = [url_buttons[:2]] if url_buttons else []
    rows.extend(
        _editor_more_rows(draft_id, draft)
        if settings
        else _editor_rows(draft_id, draft)
    )
    return text, InlineKeyboardMarkup(rows)


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
            await track_lookup_message(Update(update_id=0, callback_query=query), context)
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
    elif screen == BuilderScreen.STYLE:
        text, _ = _render_track_draft(draft, context, draft_id=None)
        text = f"{get_text(lang, 'ed_style_title')}\n\n{text}"
        keyboard = InlineKeyboardMarkup(_editor_style_rows(draft_id, draft))
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
    elif screen == BuilderScreen.INTRO:
        text, _ = _render_track_draft(draft, context, draft_id=None)
        text = f"{get_text(lang, 'ed_intro_title')}\n\n{text}"
        keyboard = InlineKeyboardMarkup(_editor_intro_rows(draft_id, draft))
    elif screen == BuilderScreen.HASHTAGS:
        text, _ = _render_track_draft(draft, context, draft_id=None)
        text = f"{get_text(lang, 'ed_hashtags_title')}\n\n{text}"
        keyboard = InlineKeyboardMarkup(_editor_hashtag_rows(draft_id, draft))
    elif screen == BuilderScreen.PREVIEW:
        view = build_publication_view(
            draft,
            track,
            context=context,
            include_channel_button=False,
        )
        text = view.text
        keyboard = InlineKeyboardMarkup(
            [
                *[list(row) for row in view.keyboard.inline_keyboard],
                *_editor_preview_rows(draft_id, draft),
            ]
        )
    elif screen == BuilderScreen.SCHEDULE:
        text = (
            f"{get_text(lang, 'schedule_title')}\n\n"
            f"<blockquote><b>{escape(track.artist)}</b> — {escape(track.title)}</blockquote>"
        )
        keyboard = InlineKeyboardMarkup(_editor_schedule_rows(draft_id, draft))
    elif action == "b":
        text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
    else:
        return False
    await query.answer()
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


async def _handle_editor_action(query, context, action: str, draft_id: str) -> None:
    user_lang = resolve_lang(query.from_user.language_code if query.from_user else None)
    draft = await _load_draft(context, draft_id)
    if draft is None:
        await query.answer(get_text(user_lang, "ed_expired"), show_alert=True)
        return

    lang = draft.get("lang") or user_lang
    if (
        query.from_user is not None
        and not _draft_owned_by(draft, query.from_user.id)
    ):
        await query.answer(get_text(lang, "ed_owner_only"), show_alert=True)
        return

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

    track = TrackMatch(**draft["item"])
    return_screen: str | None = None
    if action in {"z0", "z1", "z2"}:
        select_preset(draft, int(action[1]))
        return_screen = "zs"
    elif len(action) >= 2 and action.startswith("l") and action[1:].isdigit():
        toggle_platform(
            draft,
            track,
            list(_get_platform_order(context)),
            int(action[1:]),
        )
        return_screen = "ls"
    elif action == "la":
        select_all_platforms(
            draft,
            track,
            list(_get_platform_order(context)),
        )
        return_screen = "ls"
    elif action == "ha":
        use_auto_tags(draft)
        return_screen = "hs"
    elif action == "hn":
        remove_tags(draft)
        return_screen = "hs"
    elif action == "t0":
        remove_intro(draft)
        return_screen = "ts"

    if return_screen is not None:
        await _store_draft(context, draft_id, draft)
        if query.from_user is not None:
            await save_channel_template(context, f"user:{query.from_user.id}", draft)
        await _handle_editor_navigation(
            query,
            context,
            action=return_screen,
            draft_id=draft_id,
            draft=draft,
            lang=lang,
        )
        return

    if action in {"ti", "hi"}:
        await _start_pending_editor_input(
            query,
            context,
            draft_id=draft_id,
            kind="intro" if action == "ti" else "hashtags",
            lang=lang,
        )
        return

    if action == "p":
        user_id = query.from_user.id if query.from_user else 0
        admin_chat_id = context.application.bot_data.get("admin_chat_id")
        if (
            not draft.get("can_publish")
            or not user_id
            or admin_chat_id is None
            or user_id != admin_chat_id
        ):
            await query.answer(get_text(lang, "ed_admin_only"), show_alert=True)
            return
        target = str(
            context.application.bot_data.get("publish_chat_id")
            or f"@{CHANNEL_USERNAME}"
        )
        text, keyboard = _build_publish_confirmation(
            draft_id,
            draft,
            track,
            target=target,
            lang=lang,
        )
        await query.answer()
        await _edit_editor_message(query, context, draft, text, keyboard)
        return

    if action in {"q1", "q3", "qd"}:
        user_id = query.from_user.id if query.from_user else 0
        runtime = _runtime(context)
        lock_key = f"{user_id}:schedule:{draft_id}"
        token = await runtime.acquire_action(lock_key)
        if token is None:
            await query.answer(get_text(lang, "action_busy"), show_alert=True)
            return
        try:
            await _schedule_editor_draft(query, context, action, draft, lang=lang)
        finally:
            await runtime.release_action(lock_key, token)
        return

    if action in {"pc", "r", "x", "s", "c"}:
        user_id = query.from_user.id if query.from_user else 0
        runtime = _runtime(context)
        lock_key = f"{user_id}:{action}:{draft_id}"
        token = await runtime.acquire_action(lock_key)
        if token is None:
            await query.answer(get_text(lang, "action_busy"), show_alert=True)
            return
        await _show_action_busy(query, lang)
        try:
            await _run_primary_editor_action(
                query, context, action, draft_id, draft, lang
            )
        finally:
            await runtime.release_action(lock_key, token)
        return

    if action != "f" and not _apply_editor_setting(
        draft,
        action,
        track=TrackMatch(**draft["item"]),
        platform_order=_get_platform_order(context),
    ):
        await query.answer()
        return

    await query.answer(
        get_text(lang, "settings_saved") if action != "f" else None
    )
    await _store_draft(context, draft_id, draft)
    if query.from_user is not None:
        await save_channel_template(context, f"user:{query.from_user.id}", draft)
    text, keyboard = _render_track_draft(
        draft,
        context,
        draft_id=draft_id,
        settings=action != "f",
        show_status=action != "f",
    )
    await _edit_editor_message(query, context, draft, text, keyboard)


async def _start_pending_editor_input(
    query,
    context,
    *,
    draft_id: str,
    kind: str,
    lang: str,
) -> None:
    if query.from_user is None or query.message is None:
        await query.answer()
        return
    prompt_key = "ed_intro_prompt" if kind == "intro" else "ed_tags_prompt"
    prompt = await query.message.reply_text(
        get_text(lang, prompt_key),
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


async def _schedule_editor_draft(query, context, action: str, draft: dict, *, lang: str) -> None:
    if query.from_user is None:
        await query.answer()
        return
    admin_chat_id = context.application.bot_data.get("admin_chat_id")
    if not draft.get("can_publish") or admin_chat_id != query.from_user.id:
        await query.answer(get_text(lang, "ed_admin_only"), show_alert=True)
        return
    publish_at = schedule_timestamp(action)
    try:
        await add_job(context, dict(draft), publish_at)
    except (QueueBusyError, QueueStorageError):
        await query.answer(get_text(lang, "ed_publish_failed"), show_alert=True)
        return
    date = get_text(
        lang,
        {"q1": "schedule_1h", "q3": "schedule_3h", "qd": "schedule_1d"}[action],
    )
    await query.answer(
        get_text(lang, "schedule_done").format(date=date), show_alert=True
    )
    text, keyboard = _render_track_draft(draft, context, draft_id=None)
    text = f"<b>{escape(get_text(lang, 'schedule_done').format(date=date))}</b>\n\n{text}"
    await _edit_editor_message(
        query,
        context,
        draft,
        text,
        InlineKeyboardMarkup(
            [[InlineKeyboardButton(get_text(lang, "home_back"), callback_data=encode_callback("menu", "start"))]]
        ),
    )


async def _run_primary_editor_action(
    query, context, action: str, draft_id: str, draft: dict, lang: str
) -> None:
    user_id = query.from_user.id if query.from_user else 0
    if action == "c":
        items, added = await add_to_crate(
            context.application.bot_data,
            user_id,
            draft_id=draft_id,
            item=draft["item"],
        )
        draft["in_crate"] = True
        draft["crate_count"] = len(items)
        await _store_draft(context, draft_id, draft)
        await query.answer(
            get_text(lang, "ed_crate_added").format(count=len(items))
            if added
            else get_text(lang, "ed_crate_exists").format(count=len(items)),
            show_alert=False,
        )
        text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
        await _edit_editor_message(query, context, draft, text, keyboard)
        return

    if action == "s":
        sent = await _deliver_draft(
            context, draft, target=user_id, channel_style=False
        )
        await query.answer(
            get_text(lang, "ed_sent" if sent else "ed_publish_failed"),
            show_alert=not bool(sent),
        )
        text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
        await _edit_editor_message(query, context, draft, text, keyboard)
        return

    admin_chat_id = context.application.bot_data.get("admin_chat_id")
    if not user_id or admin_chat_id is None or user_id != admin_chat_id:
        await query.answer(get_text(lang, "ed_admin_only"), show_alert=True)
        text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
        await _edit_editor_message(query, context, draft, text, keyboard)
        return

    track = TrackMatch(**draft["item"])
    record = await _find_posted_record(context, track)
    if action == "pc" and record:
        draft["duplicate_record"] = record
        await _store_draft(context, draft_id, draft)
        await query.answer(
            get_text(lang, "ed_duplicate").replace(
                "{date}", str(record.get("date") or "")
            ),
            show_alert=True,
        )
        text, _keyboard = _render_track_draft(draft, context, draft_id=None)
        await _edit_editor_message(
            query,
            context,
            draft,
            text,
            _duplicate_post_keyboard(draft_id, record, lang=lang),
        )
        return

    if action == "x" and record:
        message_id = record.get("message_id")
        target = (
            context.application.bot_data.get("publish_chat_id")
            or f"@{CHANNEL_USERNAME}"
        )
        if isinstance(message_id, int) and message_id > 0:
            try:
                await context.bot.delete_message(
                    chat_id=target,
                    message_id=message_id,
                )
            except TelegramError:
                await query.answer(
                    get_text(lang, "ed_publish_failed"),
                    show_alert=True,
                )
                text, _keyboard = _render_track_draft(
                    draft, context, draft_id=None
                )
                await _edit_editor_message(
                    query,
                    context,
                    draft,
                    text,
                    _duplicate_post_keyboard(draft_id, record, lang=lang),
                )
                return
        else:
            await query.answer(
                get_text(lang, "ed_publish_failed"),
                show_alert=True,
            )
            return

    published = await _publish_draft(context, draft)
    if published:
        target = (
            context.application.bot_data.get("publish_chat_id")
            or f"@{CHANNEL_USERNAME}"
        )
        await _schedule_mark_posted(
            context,
            track,
            message=published,
            target=target,
        )
        published_link = (
            getattr(published, "link", None)
            if not isinstance(published, bool)
            else None
        )
        success_rows: list[list[InlineKeyboardButton]] = []
        if isinstance(published_link, str) and published_link.startswith("http"):
            success_rows.append(
                [
                    InlineKeyboardButton(
                        get_text(lang, "ed_open_publication"),
                        url=published_link,
                    )
                ]
            )
        else:
            success_rows.append([_channel_button()])
        success_rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "ed_create_more"),
                    callback_data=encode_callback("menu", "create"),
                    api_kwargs={"style": "primary"},
                )
            ]
        )
        success_keyboard = InlineKeyboardMarkup(success_rows)
        text, _ = _render_track_draft(draft, context, draft_id=None)
        text = f"<b>{escape(get_text(lang, 'ed_published'))}</b>\n\n{text}"
        await _edit_editor_message(query, context, draft, text, success_keyboard)
        if query.from_user is not None:
            session = await _runtime(context).get_session(
                query.from_user.id,
                lang=lang,
            )
            if session.active_draft_id == draft_id:
                session.active_draft_id = ""
                await _runtime(context).save_session(session)
    await query.answer(
        get_text(lang, "ed_published" if published else "ed_publish_failed"),
        show_alert=not bool(published),
    )
    if not published:
        text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
        await _edit_editor_message(query, context, draft, text, keyboard)


async def _show_action_busy(query, lang: str) -> None:
    try:
        await query.edit_message_reply_markup(
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("⏳ " + get_text(lang, "progress_card"), callback_data=encode_callback("noop", "busy"))]]
            )
        )
    except (AttributeError, TelegramError):
        LOGGER.debug("Could not mark editor action busy", exc_info=True)


async def _edit_editor_message(query, context, draft: dict, text: str, keyboard) -> None:
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


async def crate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    user_id = update.effective_user.id if update.effective_user else message.chat_id
    lang = _update_lang(update)
    items = await load_crate(context.application.bot_data, user_id)
    title = await load_crate_title(context.application.bot_data, user_id)
    text, keyboard = _render_bot_crate(items, lang=lang, title=title)
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def _dispatch_crate_action(query, context, action: CallbackAction) -> None:
    if query.from_user is None:
        await query.answer()
        return
    lang = resolve_lang(query.from_user.language_code)
    user_id = query.from_user.id
    bot_data = context.application.bot_data
    title = await load_crate_title(bot_data, user_id)
    undo_map = bot_data.setdefault("crate_undo", {})
    now = time.time()
    for key, value in list(undo_map.items()):
        try:
            active = (
                isinstance(value, dict)
                and float(value.get("expires_at") or 0) > now
            )
        except (TypeError, ValueError):
            active = False
        if not active:
            undo_map.pop(key, None)
    undo_record = undo_map.get(user_id)
    try:
        index = int(action.payload)
    except (TypeError, ValueError):
        index = -1
    selected_index: int | None = None
    notice: str | None = None
    if action.action == "rename":
        if query.message is None:
            await query.answer()
            return
        prompt = await query.message.reply_text(
            get_text(lang, "crate_name_prompt"),
            reply_markup=ForceReply(selective=True),
        )
        session = await _runtime(context).get_session(user_id, lang=lang)
        session.pending_input = {
            "kind": "crate_title",
            "editor_chat_id": query.message.chat_id,
            "editor_message_id": query.message.message_id,
            "prompt_message_id": prompt.message_id,
            "created_at": int(time.time()),
        }
        await _runtime(context).save_session(session)
        await query.answer()
        return
    if action.action == "preview":
        items = await load_crate(bot_data, user_id)
        tracks = [
            TrackMatch(**entry["item"])
            for entry in items
            if isinstance(entry.get("item"), dict)
        ]
        if not tracks:
            await query.answer()
            text, keyboard = _render_bot_crate([], lang=lang, title=title)
            await _safe_edit(query, text, keyboard)
            return
        preview_keyboard = _build_collection_keyboard(
            tracks,
            include_channel_button=False,
        )
        keyboard = InlineKeyboardMarkup(
            [
                *[list(row) for row in preview_keyboard.inline_keyboard],
                [
                    InlineKeyboardButton(
                        get_text(lang, "back"),
                        callback_data=encode_callback("crate", "open"),
                    )
                ],
            ]
        )
        await query.answer()
        await _safe_edit(
            query,
            format_collection_message(
                tracks,
                title=title or get_text(lang, "crate_preview_title"),
                include_hashtags=True,
            ),
            keyboard,
        )
        return
    if action.action == "up":
        items = await move_crate_item(bot_data, user_id, index, -1)
        selected_index = max(0, index - 1)
    elif action.action == "down":
        items = await move_crate_item(bot_data, user_id, index, 1)
        selected_index = min(len(items) - 1, index + 1) if items else None
    elif action.action == "select":
        items = await load_crate(bot_data, user_id)
        selected_index = index
    elif action.action == "remove":
        before = await load_crate(bot_data, user_id)
        removed = before[index] if 0 <= index < len(before) else None
        items = await remove_crate_item(bot_data, user_id, index)
        if removed is not None:
            undo_record = {
                "entry": removed,
                "index": index,
                "expires_at": time.time() + CRATE_UNDO_SECONDS,
            }
            _remember_bounded(
                undo_map,
                user_id,
                undo_record,
                max_size=MAX_CRATE_UNDO_RECORDS,
            )
            notice = get_text(lang, "crate_removed")
        selected_index = min(index, len(items) - 1) if items else None
    elif action.action == "undo":
        if undo_record:
            if undo_record.get("kind") == "clear":
                items = list(undo_record.get("items") or [])
                await save_crate(bot_data, user_id, items)
                restored = bool(items)
            else:
                items, restored = await restore_crate_item(
                    bot_data,
                    user_id,
                    index=int(undo_record.get("index") or 0),
                    entry=undo_record.get("entry") or {},
                )
            if restored:
                selected_index = min(
                    int(undo_record.get("index") or 0), len(items) - 1
                )
                notice = get_text(lang, "crate_restored")
                undo_map.pop(user_id, None)
                undo_record = None
        else:
            items = await load_crate(bot_data, user_id)
    elif action.action == "clear":
        items = await load_crate(bot_data, user_id)
        await query.answer()
        text, keyboard = _render_bot_crate(
            items, lang=lang, confirm_clear=True, title=title
        )
        await _safe_edit(query, text, keyboard)
        return
    elif action.action == "clear_confirm":
        previous_items = await load_crate(bot_data, user_id)
        await save_crate(bot_data, user_id, [])
        undo_record = {
            "kind": "clear",
            "items": previous_items,
            "index": 0,
            "expires_at": time.time() + CRATE_UNDO_SECONDS,
        }
        _remember_bounded(
            undo_map,
            user_id,
            undo_record,
            max_size=MAX_CRATE_UNDO_RECORDS,
        )
        items = []
    elif action.action in {"clear_cancel", "open"}:
        items = await load_crate(bot_data, user_id)
    else:
        await query.answer()
        return
    await query.answer(notice)
    text, keyboard = _render_bot_crate(
        items,
        lang=lang,
        selected_index=selected_index,
        can_undo=undo_record is not None,
        title=title,
    )
    await _safe_edit(query, text, keyboard)


async def _reply_with_menu(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    menu_key: str,
    *,
    lang: str = "ru",
) -> None:
    runtime = _runtime(context)
    subject_id = message.from_user.id if message.from_user else message.chat_id
    crate_count, _is_admin = await _home_state(context, subject_id)
    text = _menu_text(menu_key, lang=lang)
    keyboard = _build_section_keyboard(
        context.bot.username,
        lang=lang,
        crate_count=crate_count,
        active=menu_key.removeprefix("menu:"),
    )
    session = (
        await runtime.get_session(subject_id, lang=lang)
        if message.chat.type == "private"
        else None
    )
    sent = await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    if session is not None:
        await _remember_fresh_home_message(
            context,
            runtime,
            session,
            chat_id=message.chat_id,
            sent=sent,
        )


async def _reply_with_error(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    lang: str = "ru",
) -> None:
    reply_markup = _build_error_keyboard(context.bot.username, lang=lang)
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
    }.get(error.code, "no_url_hint")
    detail = get_text(lang, detail_key)
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
    text = f"<b>{get_text(lang, 'error_title')}</b>\n\n{detail}"
    keyboard = _build_error_keyboard(
        context.bot.username,
        lang=lang,
        retryable=error.retryable,
        search_query=search_query,
        source_url=source_url,
    )
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
                    ]
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


async def track_lookup_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            runtime.finish_request(private_user_id)


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
            "Song.link недоступен при обработке: "
            + ", ".join(bundle.unavailable_urls),
            only_for_channel_message=message,
        )

    if bundle.item_count:
        return False

    if not bundle.unavailable_urls:
        await _notify_admin(
            context,
            f"Не нашел платформы для ссылок в чате {message.chat_id}: "
            + ", ".join(source_urls),
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
) -> None:
    """Deliver one release or a collection without mixing lookup concerns."""
    if len(tracks) > 1:
        total = max(len(tracks), int(requested_count or len(tracks)))
        title = collection_result_title(
            lang,
            found=len(tracks),
            total=total,
        )
        duplicate_count = 0
        if is_private:
            _crate_items, added_count = await _add_track_drafts_to_crate(
                message,
                context,
                tracks,
                user_id=user_id,
                lang=lang,
            )
            duplicate_count = max(0, len(tracks) - added_count)
            rows = [
                [
                    InlineKeyboardButton(
                        get_text(lang, "crate_view"),
                        callback_data=encode_callback("crate", "open"),
                        api_kwargs={"style": "primary"},
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
            collection_keyboard = add_share_button(
                _build_collection_keyboard(
                    tracks,
                    include_channel_button=include_channel_button,
                ),
                share_query=build_share_query(
                    [track_share_url(track) or "" for track in tracks]
                ),
                label=get_text(lang, "share_post"),
            )
        collection_text = user_prefix + format_collection_message(
            tracks,
            include_hashtags=include_hashtags,
            title=title,
        )
        if duplicate_count:
            collection_text += "\n\n" + get_text(lang, "collection_duplicates").format(
                count=duplicate_count
            )
        await _send_track_result(
            context.bot,
            message,
            collection_text,
            preview_url=_select_preview_url(tracks[0].links, context)
            or tracks[0].thumbnail_url,
            reply_markup=collection_keyboard,
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
            reply_markup=add_share_button(
                _build_link_keyboard(
                    track.links,
                    context=context,
                    include_channel_button=include_channel_button,
                    release_page_url=track.page_url,
                    release_kind=track.kind,
                    release_format=track.release_format,
                ),
                share_query=build_share_query(
                    [url] if (url := track_share_url(track)) else []
                ),
                label=get_text(lang, "share_post"),
            ),
        )
    _record_matches_safely([track], message, context=context)


async def _consume_pending_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or message.chat.type != "private":
        return False
    lang = _update_lang(update)
    runtime = _runtime(context)
    session = await runtime.get_session(user.id, lang=lang)
    pending = session.pending_input
    if not pending:
        return False
    created_at = int(pending.get("created_at") or 0)
    if not created_at or time.time() - created_at > PENDING_INPUT_TTL_SECONDS:
        session.pending_input = {}
        await runtime.save_session(session)
        return False
    value = (_message_text(message) or "").strip()
    if not value:
        return True

    kind = str(pending.get("kind") or "")
    saved_key = "settings_saved"
    draft_id = str(pending.get("draft_id") or "")
    draft = await _load_draft(context, draft_id) if draft_id else None
    if kind in {"intro", "hashtags"} and draft is None:
        session.pending_input = {}
        await runtime.save_session(session)
        await message.reply_text(get_text(lang, "ed_expired"))
        return True
    if kind in {"intro", "hashtags"} and draft is not None:
        if not _draft_owned_by(draft, user.id):
            session.pending_input = {}
            await runtime.save_session(session)
            await message.reply_text(get_text(lang, "ed_owner_only"))
            return True
        if kind == "intro":
            apply_intro_text(draft, value)
            saved_key = "ed_intro_saved"
        else:
            apply_custom_tags(draft, value)
            saved_key = "ed_tags_saved"
        await _store_draft(context, draft_id, draft)
        await save_channel_template(context, f"user:{user.id}", draft)
    elif kind == "crate_title":
        title = normalize_crate_title(value)
        await save_crate_title(context.application.bot_data, user.id, title)
        saved_key = "crate_name_saved"
    else:
        session.pending_input = {}
        await runtime.save_session(session)
        return False

    session.pending_input = {}
    await runtime.save_session(session)
    for key in ("prompt_message_id", "editor_message_id"):
        message_id = pending.get(key)
        if isinstance(message_id, int) and message_id > 0:
            try:
                await context.bot.delete_message(
                    chat_id=int(pending.get("editor_chat_id") or message.chat_id),
                    message_id=message_id,
                )
            except TelegramError:
                LOGGER.debug("Could not clean up native editor input", exc_info=True)

    if kind == "crate_title":
        items = await load_crate(context.application.bot_data, user.id)
        title = await load_crate_title(context.application.bot_data, user.id)
        text, keyboard = _render_bot_crate(items, lang=lang, title=title)
        await message.reply_text(
            f"<b>{escape(get_text(lang, saved_key))}</b>\n\n{text}",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        return True

    if draft is not None:
        text, keyboard = _render_track_draft(
            draft,
            context,
            draft_id=draft_id,
            settings=True,
            show_status=True,
        )
        track = TrackMatch(**draft["item"])
        await message.reply_text(
            f"<b>{escape(get_text(lang, saved_key))}</b>\n\n{text}",
            parse_mode=ParseMode.HTML,
            link_preview_options=_build_link_preview_options(
                _select_preview_url(track.links, context) or track.thumbnail_url,
                prefer_large_media=bool(draft.get("large_preview")),
            ),
            reply_markup=keyboard,
        )
    return True


async def _track_lookup_message_impl(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    if message is None:
        return

    if await _consume_pending_input(update, context):
        return

    # Posts inserted through this bot's own inline mode arrive as regular
    # messages; re-processing them would send their text into search.
    via_bot = getattr(message, "via_bot", None)
    if via_bot is not None and via_bot.id == getattr(context.bot, "id", None):
        return

    message_text = _INPUT_OVERRIDE.get() or _message_text(message) or ""
    is_private = message.chat.type == "private"
    request = LookupRequest(
        message_text=message_text,
        source_urls=extract_supported_urls(message_text)[:MAX_LINKS_PER_MESSAGE],
        is_private=is_private,
        lang=_update_lang(update) if is_private else "ru",
        user_id=(
            update.effective_user.id if update.effective_user else message.chat_id
        ),
        include_channel_button=_should_include_channel_button(message),
        include_hashtags=_should_include_hashtags(message),
        search_query=(_SEARCH_QUERY_OVERRIDE.get() or "").strip() or None,
    )
    source_urls = request.source_urls
    lang = request.lang
    user_id = request.user_id
    runtime = _runtime(context)
    search_query = request.search_query
    if is_private:
        action_kind = detect_action(message_text or "", source_urls, is_private=True)
        intent_value = (
            "\n".join(sorted(cache_key_for_url(url) for url in source_urls))
            if source_urls
            else message_text or ""
        )
        if (
            not _BYPASS_INTENT_GUARD.get()
            and not await runtime.claim_intent(
                user_id,
                kind=action_kind,
                value=intent_value,
            )
        ):
            return
        if action_kind == "help":
            await _reply_with_menu(message, context, MENU_HELP, lang=lang)
            return
        runtime.register_request(user_id)
        remembered_value = search_query or message_text or ""
        if not search_query and len(source_urls) == 1:
            remembered_value = source_urls[0]
        await runtime.remember_action(
            user_id,
            kind="search" if search_query or not source_urls else "resolve",
            value=remembered_value,
            lang=lang,
        )
    found_via_search = search_query is not None
    if not source_urls:
        if not is_private:
            return

        search_result = await _resolve_search_sources(
            message,
            context,
            message_text,
            user_id=user_id,
            lang=lang,
        )
        if search_result is None:
            return
        source_urls, found_via_search, search_query = search_result
        request.source_urls = source_urls
        request.found_via_search = found_via_search
        request.search_query = search_query

    if message.chat.type == "channel":
        access = await check_publish_access(context, message.chat_id)
        if not access.allowed or not access.can_delete:
            missing = (
                "публиковать"
                if not access.allowed
                else "удалять исходные сообщения"
            )
            await _notify_admin(
                context,
                f"Автозамена в канале {message.chat_id} остановлена: "
                f"бот не может {missing}. {access.detail}",
                only_for_channel_message=message,
            )
            return

    # The whole message was the search query, so quoting it back is noise.
    user_prefix = (
        ""
        if found_via_search
        else _build_user_prefix(message, bot_username=context.bot.username)
    )
    if is_private:
        await _send_loading_placeholder(message, lang)
        await _update_loading_placeholder(lang, "progress_links")
    else:
        await _send_typing_action(context.bot, message)

    bundle = await _bot_lookup.resolve_sources(
        context.application.bot_data, source_urls
    )
    if is_private:
        if len(source_urls) > 1:
            await _update_progress_text(
                get_text(lang, "progress_batch").format(
                    done=bundle.item_count,
                    total=len(source_urls),
                )
            )
        else:
            await _update_loading_placeholder(lang, "progress_card")
    if await _handle_empty_lookup(
        message,
        context,
        bundle,
        source_urls,
        lang=lang,
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
    kind = delivery_kind(bundle)
    prefix = "" if bundle.item_count > 1 else user_prefix
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
            requested_count=len(request.source_urls),
            **common,
        )
    elif kind == "videos":
        await _send_youtube_result(context.bot, message, bundle.videos, **common)
        _record_videos_safely(bundle.videos, message, context=context)
    elif kind == "radios":
        await _send_nts_result(context.bot, message, bundle.radios, **common)
        _record_radios_safely(bundle.radios, message, context=context)
    elif kind == "playlists":
        await _send_playlist_result(context.bot, message, bundle.playlists, **common)
        _record_playlists_safely(bundle.playlists, message, context=context)
    elif kind == "artists":
        await _send_artist_result(context.bot, message, bundle.artists, **common)
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


async def _send_track_result(
    bot: Bot,
    message: Message,
    text: str,
    *,
    preview_url: str | None,
    reply_markup: InlineKeyboardMarkup | None,
    prefer_large_preview: bool = True,
) -> None:
    text = fit_telegram_html(text)
    if message.chat.type in {"group", "supergroup", "channel"}:
        if message.chat.type == "channel":
            reply_markup = make_channel_safe_keyboard(reply_markup)
        preview_options = _build_link_preview_options(
            preview_url,
            prefer_large_media=prefer_large_preview,
        )
        # Invisible reply: in a group the card can be shown only to the person
        # who dropped the link, leaving the chat clean and their message intact.
        # Opt-in and best-effort — falls through to the public post if Telegram
        # does not deliver it.
        if (
            message.chat.type in {"group", "supergroup"}
            and ephemeral_group_replies_enabled()
            and getattr(message, "from_user", None) is not None
        ):
            delivered = await send_ephemeral_message(
                getattr(bot, "token", None),
                message.chat_id,
                message.from_user.id,
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                link_preview_options=preview_options,
                reply_to_message_id=getattr(message, "message_id", None),
            )
            if delivered:
                return

        await bot.send_message(
            chat_id=message.chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            link_preview_options=preview_options,
            reply_markup=reply_markup,
        )
        await _try_delete_message(message)
        return

    await _reply_with_track(
        message,
        text,
        preview_url=preview_url,
        reply_markup=reply_markup,
        prefer_large_preview=prefer_large_preview,
    )


async def _send_track_video_pair_result(
    bot: Bot,
    message: Message,
    text: str,
    *,
    track: TrackMatch,
    video: VideoMatch,
    reply_markup: InlineKeyboardMarkup | None,
) -> bool:
    if (
        message.chat.type in {"group", "supergroup"}
        and ephemeral_group_replies_enabled()
        and getattr(message, "from_user", None) is not None
    ):
        await _send_track_result(
            bot,
            message,
            text,
            preview_url=_select_preview_url(track.links) or track.thumbnail_url,
            reply_markup=reply_markup,
        )
        return True

    placeholder = _take_placeholder(message.chat_id)
    if placeholder is not None:
        try:
            await placeholder.delete()
        except TelegramError:
            LOGGER.debug("Could not remove mixed-post placeholder", exc_info=True)

    sent = await send_track_video_album(
        bot,
        chat_id=message.chat_id,
        track=track,
        video_title=video.title,
        video_url=video.url,
        video_thumbnail_url=video.thumbnail_url,
        caption=text,
        reply_markup=(
            make_channel_safe_keyboard(reply_markup)
            if message.chat.type == "channel"
            else reply_markup
        ),
    )
    if sent is None:
        await _send_track_result(
            bot,
            message,
            text,
            preview_url=_select_preview_url(track.links) or track.thumbnail_url,
            reply_markup=reply_markup,
        )
        return True

    if message.chat.type in {"group", "supergroup", "channel"}:
        await _try_delete_message(message)
    return True


async def _reply_with_track(
    message: Message,
    text: str,
    *,
    preview_url: str | None,
    reply_markup: InlineKeyboardMarkup | None,
    prefer_large_preview: bool = True,
) -> Message:
    text = fit_telegram_html(text)
    link_preview_options = _build_link_preview_options(
        preview_url,
        prefer_large_media=prefer_large_preview,
    )
    placeholder = _take_placeholder(message.chat_id)
    if placeholder is not None:
        try:
            return await placeholder.edit_text(
                text=text,
                parse_mode=ParseMode.HTML,
                link_preview_options=link_preview_options,
                reply_markup=reply_markup,
            )
        except TelegramError:
            LOGGER.debug("Could not edit loading placeholder", exc_info=True)
            await _try_delete_message(placeholder)

    return await message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
        link_preview_options=link_preview_options,
        reply_markup=reply_markup,
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


def _menu_text(menu_key: str, *, lang: str = "ru") -> str:
    key_map = {
        MENU_HELP: "menu_help",
        MENU_DEMO: "menu_demo",
        MENU_GUIDE: "menu_guide",
        MENU_PLATFORMS: "menu_platforms",
        MENU_MORE: "menu_more",
    }
    return get_text(lang, key_map.get(menu_key, "menu_start"))


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


async def _try_delete_message(message: Message) -> bool:
    try:
        await message.delete()
    except TelegramError:
        return False

    return True
