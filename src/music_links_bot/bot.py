from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Awaitable, Callable

from telegram import (
    InlineQueryResultsButton,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from music_links_bot.bot_actions import action_spec
from music_links_bot.bot_crate_handlers import (
    dispatch_crate_action as _dispatch_crate_action,
)
from music_links_bot.bot_editor import _dispatch_editor_action
from music_links_bot.bot_lookup_flow import (
    _BYPASS_INTENT_GUARD,
    _INPUT_OVERRIDE,
    _SEARCH_QUERY_OVERRIDE,
    track_lookup_message,
)
from music_links_bot.bot_menu import (
    dispatch_menu_action as _dispatch_menu_action,
    dispatch_privacy_action as _dispatch_privacy_action,
    runtime_for as _runtime,
)
from music_links_bot.bot_preferences import dispatch_preferences
from music_links_bot.bot_progress import (
    adopt_progress_message as _adopt_progress_message,
)
from music_links_bot.bot_queue import dispatch_queue_action
from music_links_bot.bot_runtime import (
    CallbackAction,
    decode_callback,
)
from music_links_bot.bot_storage import (
    load_retry_sources as _load_retry_sources,
    load_search_selection as _load_search_selection,
)
from music_links_bot.constants import MAX_LINKS_PER_MESSAGE
from music_links_bot.i18n import get_text, resolve_lang
from music_links_bot.input_routing import input_prompt_markup

LOGGER = logging.getLogger(__name__)


async def _application_error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    error = context.error
    from music_links_bot.kvstore import KVUnavailableError
    from music_links_bot.state_mutations import StateConflictError

    if isinstance(error, KVUnavailableError) and isinstance(update, Update):
        user = update.effective_user
        lang = resolve_lang(user.language_code if user else None)
        text = get_text(
            lang,
            "state_conflict"
            if isinstance(error, StateConflictError)
            else "storage_temporarily_unavailable",
        )
        try:
            if update.callback_query is not None:
                await update.callback_query.answer(text, show_alert=True)
            elif update.inline_query is not None:
                await update.inline_query.answer(
                    [],
                    cache_time=0,
                    is_personal=True,
                    button=InlineQueryResultsButton(
                        text=get_text(lang, "storage_unavailable_inline"),
                        start_parameter="start",
                    ),
                )
            elif update.effective_message is not None:
                await update.effective_message.reply_text(text)
        except TelegramError:
            LOGGER.warning("Could not display storage failure notice")
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

    from music_links_bot.input_routing import dispatch_input_action

    handlers: dict[
        str,
        Callable[[object, ContextTypes.DEFAULT_TYPE, CallbackAction], Awaitable[None]],
    ] = {
        "menu": _dispatch_menu_action,
        "input": dispatch_input_action,
        "prefs": dispatch_preferences,
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


async def _rerun_lookup(
    query,
    context,
    value: str,
    *,
    search_query: str | None = None,
    completed: dict | None = None,
) -> None:
    """Run the normal lookup from a button, as if ``value`` had been sent."""
    from music_links_bot.lookup_recovery import completed_sources

    _adopt_progress_message(query.message)
    tokens = [
        (_INPUT_OVERRIDE, _INPUT_OVERRIDE.set(value)),
        (_SEARCH_QUERY_OVERRIDE, _SEARCH_QUERY_OVERRIDE.set(search_query)),
        (_BYPASS_INTENT_GUARD, _BYPASS_INTENT_GUARD.set(True)),
        (completed_sources, completed_sources.set(completed)),
    ]
    try:
        await track_lookup_message(Update(update_id=0, callback_query=query), context)
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


async def _dispatch_noop_action(query, context, action: CallbackAction) -> None:
    del context, action
    await query.answer()


async def _dispatch_progress_action(query, context, action: CallbackAction) -> None:
    if query.from_user is None:
        await query.answer()
        return
    lang = resolve_lang(query.from_user.language_code)
    runtime = _runtime(context)
    if action.payload and action.payload.isdigit():
        from music_links_bot.lookup_control import stop_lookup

        cancelled = await stop_lookup(
            context.application.bot_data,
            chat_id=query.from_user.id,
            draft_id=int(action.payload),
        )
    else:
        cancelled = await runtime.cancel_request_durable(query.from_user.id)
    await query.answer(
        get_text(lang, "request_cancelled" if cancelled else "request_not_running")
    )


async def _dispatch_selection_action(query, context, action: CallbackAction) -> None:
    lang = resolve_lang(query.from_user.language_code if query.from_user else None)
    if action.action != "pick" or ":" not in action.payload:
        await query.answer()
        return
    selection_id, raw_index = action.payload.rsplit(":", 1)
    payload = await _load_search_selection(context, selection_id) or {}
    try:
        index = int(raw_index)
        if index < 0:
            raise IndexError(index)
        source_url = payload["urls"][index]
    except (IndexError, KeyError, TypeError, ValueError):
        await query.answer(get_text(lang, "ed_expired"), show_alert=True)
        return
    if query.from_user and int(payload.get("user_id") or 0) != query.from_user.id:
        await query.answer(get_text(lang, "ed_admin_only"), show_alert=True)
        return

    await query.answer(get_text(lang, "progress_links"))
    if query.message is None:
        return
    await _rerun_lookup(
        query, context, source_url, search_query=str(payload.get("query") or "")
    )


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
            reply_markup=input_prompt_markup(lang),
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

    completed: dict = {}
    value = ""
    if action.action == "failed" and action.payload:
        payload = await _load_retry_sources(context, action.payload)
        if (
            isinstance(payload, dict)
            and int(payload.get("user_id") or 0) == query.from_user.id
        ):
            completed = payload.get("completed") or {}
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
    await _rerun_lookup(query, context, value, completed=completed)


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
    await _rerun_lookup(query, context, "\n".join(urls))
