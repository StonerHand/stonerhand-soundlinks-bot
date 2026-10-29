"""Lookup pipeline: turn incoming links or queries into draft cards."""

from __future__ import annotations

import asyncio
import contextvars
import logging
import secrets
from collections.abc import Awaitable, Coroutine
from dataclasses import asdict
from typing import Any, TypeVar

from telegram import (
    Bot,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from music_links_bot.artwork.collection_collage import branded_artwork_preview_url
from music_links_bot.cards.formatter import (
    format_track_message,
)
from music_links_bot.cards.keyboards import (
    _build_collection_keyboard,
    _build_link_keyboard,
    _select_preview_url,
    _should_include_channel_button,
    _should_include_hashtags,
)
from music_links_bot.cards.sharing import (
    add_share_button,
    build_share_query,
    collection_result_title,
    make_channel_safe_keyboard,
    track_share_url,
)
from music_links_bot.chat.bot_menu import (
    MENU_HELP,
    reply_with_menu as _reply_with_menu,
    runtime_for as _runtime,
    update_lang as _update_lang,
)
from music_links_bot.chat.bot_preferences import apply_preferences
from music_links_bot.chat.bot_ui import (
    build_error_keyboard as _build_error_keyboard_view,
)
from music_links_bot.core.constants import (
    CHANNEL_USERNAME,
    MAX_LINKS_PER_MESSAGE,
    channel_target,
)
from music_links_bot.core.draft_model import new_track_draft
from music_links_bot.core.i18n import get_text
from music_links_bot.core.models import (
    TrackMatch,
)
from music_links_bot.core.url_utils import (
    cache_key_for_url,
    extract_supported_urls,
)
from music_links_bot.editor.bot_editor_state import (
    remember_draft as _remember_session_draft,
)
from music_links_bot.editor.bot_pending import (
    consume_pending_input as _consume_pending_input_impl,
)
from music_links_bot.editor.editor_view import (
    render_track_draft as _render_track_draft,
)
from music_links_bot.lookup import bot_lookup as _bot_lookup
from music_links_bot.lookup.bot_batch import (
    send_partial_lookup_status as _send_partial_lookup_status_impl,
)
from music_links_bot.lookup.bot_lookup import (
    _send_artist_result,
    _send_mixed_result,
    _send_nts_result,
    _send_playlist_result,
    _send_title_result,
    _send_youtube_result,
)
from music_links_bot.lookup.bot_pipeline import LookupRequest, delivery_kind
from music_links_bot.lookup.bot_progress import (
    PROGRESS_DELAY_SECONDS,
    cancel_progress as _cancel_progress,
    settle_progress,
    start_progress as _send_loading_placeholder,
    take_progress as _take_placeholder,
    update_progress as _update_loading_placeholder,
)
from music_links_bot.lookup.bot_stats import (
    build_user_prefix as _build_user_prefix,
    message_entities as _message_entities,
    message_source_urls as _message_source_urls,
    message_text as _message_text,
    record_delivered as _record_delivered,
)
from music_links_bot.lookup.lookup_transport import (
    reply_with_track as _reply_with_track,
    send_track_result as _send_track_result,
    send_track_video_pair_result as _send_track_video_pair_result,
)
from music_links_bot.providers.track_merge import coalesce_equivalent_tracks
from music_links_bot.publishing.channel_templates import (
    apply_channel_template,
)
from music_links_bot.publishing.chat_access import check_publish_access
from music_links_bot.publishing.publication_service import PublicationService
from music_links_bot.publishing.publication_view import editor_preview_url
from music_links_bot.state.bot_crate import (
    add_many_to_crate,
    crate_contains_item,
    load_crate,
)
from music_links_bot.state.bot_history import record_history as _record_recent_item
from music_links_bot.state.bot_runtime import (
    BotErrorCode,
    BotFlowError,
    detect_action,
    encode_callback,
)
from music_links_bot.state.bot_storage import (
    store_draft as _store_draft,
    store_retry_sources as _store_retry_sources,
    store_search_selection as _store_search_selection,
)
from music_links_bot.state.kvstore import KVUnavailableError
from music_links_bot.tg.ephemeral import (
    ephemeral_group_replies_enabled,
    send_ephemeral_message,
)
from music_links_bot.tg.telegram_buttons import (
    button as InlineKeyboardButton,
)
from music_links_bot.tg.telegram_messages import (
    delete_message_safely as _try_delete_message,
)
from music_links_bot.tg.telegram_text import format_user_note_html

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


_INPUT_OVERRIDE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "input_override", default=None
)


_SEARCH_QUERY_OVERRIDE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "search_query_override", default=None
)


_BYPASS_INTENT_GUARD: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "bypass_intent_guard", default=False
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
        target = channel_target(context.application.bot_data)
        await apply_channel_template(context, target, draft)

    session = await _runtime(context).get_session(user_id, lang=lang)
    apply_preferences(draft, session)
    crate_items = await load_crate(context.application.bot_data, user_id)
    draft["in_crate"] = crate_contains_item(crate_items, draft["item"])
    draft["crate_count"] = len(crate_items)

    await _store_draft(context, draft_id, draft)
    from music_links_bot.editor.bot_quick_publish import try_quick_publish

    if await try_quick_publish(
        message, context, draft_id=draft_id, draft=draft, track=track, user_id=user_id
    ):
        await _record_recent_item(
            context, user_id, track, track_share_url(track) or track.page_url or ""
        )
        return
    text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
    await _reply_with_track(
        message,
        text,
        preview_url=editor_preview_url(draft, track, context),
        reply_markup=keyboard,
        prefer_large_preview=bool(draft.get("large_preview")),
        source_urls=tuple(track.links.values()),
        content_kind=track.kind,
    )
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
    session = await _runtime(context).get_session(user_id, lang=lang)
    apply_preferences(draft, session)
    draft["delivery_mode"] = "classic"
    draft["as_photo"] = False
    await _store_draft(context, draft_id, draft)
    text, keyboard = _render_track_draft(draft, context, draft_id=draft_id)
    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    session = await _runtime(context).get_session(user_id, lang=lang)
    _remember_session_draft(session, draft_id)
    await _runtime(context).save_session(session)


async def _reply_with_error(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    lang: str = "ru",
) -> None:
    from music_links_bot.chat import bot_error_handlers

    return await bot_error_handlers._reply_with_error(
        message=message,
        context=context,
        text=text,
        lang=lang,
        hooks=bot_error_handlers.WorkflowHooks(
            build_error_keyboard=_build_error_keyboard,
            try_ephemeral_error=_try_ephemeral_error,
            take_placeholder=_take_placeholder,
            try_delete_message=_try_delete_message,
            ephemeral_group_replies_enabled=ephemeral_group_replies_enabled,
            send_ephemeral_message=send_ephemeral_message,
        ),
    )


async def _reply_with_flow_error(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    error: BotFlowError,
    *,
    lang: str,
    search_query: str | None = None,
    source_url: str | None = None,
) -> None:
    from music_links_bot.chat import bot_error_handlers

    return await bot_error_handlers._reply_with_flow_error(
        message=message,
        context=context,
        error=error,
        lang=lang,
        search_query=search_query,
        source_url=source_url,
        hooks=bot_error_handlers.WorkflowHooks(
            build_error_keyboard=_build_error_keyboard,
            try_ephemeral_error=_try_ephemeral_error,
            take_placeholder=_take_placeholder,
            try_delete_message=_try_delete_message,
            ephemeral_group_replies_enabled=ephemeral_group_replies_enabled,
            send_ephemeral_message=send_ephemeral_message,
        ),
    )


async def _try_ephemeral_error(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    keyboard: InlineKeyboardMarkup,
    *,
    parse_mode: object | None = None,
) -> bool:
    from music_links_bot.chat import bot_error_handlers

    return await bot_error_handlers._try_ephemeral_error(
        message=message,
        context=context,
        text=text,
        keyboard=keyboard,
        parse_mode=parse_mode,
        hooks=bot_error_handlers.WorkflowHooks(
            build_error_keyboard=_build_error_keyboard,
            try_ephemeral_error=_try_ephemeral_error,
            take_placeholder=_take_placeholder,
            try_delete_message=_try_delete_message,
            ephemeral_group_replies_enabled=ephemeral_group_replies_enabled,
            send_ephemeral_message=send_ephemeral_message,
        ),
    )


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
    from music_links_bot.lookup import bot_search_handlers

    return await bot_search_handlers._resolve_search_sources(
        message=message,
        context=context,
        message_text=message_text,
        user_id=user_id,
        lang=lang,
        hooks=bot_search_handlers.WorkflowHooks(
            reply_with_error=_reply_with_error,
            send_loading_placeholder=_send_loading_placeholder,
            store_search_selection=_store_search_selection,
            take_placeholder=_take_placeholder,
            try_delete_message=_try_delete_message,
            reply_with_flow_error=_reply_with_flow_error,
        ),
    )


async def track_lookup_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    from music_links_bot.lookup.input_routing import collection_input

    route_token = collection_input.set(
        collection_input.get() if _INPUT_OVERRIDE.get() else ""
    )
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
        collection_input.reset(route_token)
        settle_progress()
        runtime = _runtime(context)
        runtime.record_request(
            latency_ms=int((asyncio.get_running_loop().time() - started) * 1000),
            ok=completed,
        )
        # A failure is written at once, so health shows what just broke.
        metrics = runtime.persist_metrics(force=not completed)
        if private_user_id is None:
            await metrics
        else:
            await _alongside(runtime.finish_request_durable(private_user_id), metrics)


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
        # Name the service only when every failed link points at the same one.
        failed = {s.provider for s in bundle.statuses if s.state == "unavailable"}
        await _reply_with_flow_error(
            message,
            context,
            BotFlowError(
                BotErrorCode.PROVIDER_UNAVAILABLE,
                retryable=True,
                provider=failed.pop() if len(failed) == 1 else None,
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
    if is_private:
        from music_links_bot.lookup.input_routing import deliver_collection_input

        if await deliver_collection_input(
            message, context, tracks, user_id=user_id, lang=lang
        ):
            return
    total = max(len(tracks), int(requested_count or len(tracks)))
    if total > 1:
        title = collection_result_title(
            lang,
            found=len(tracks),
            total=total,
        )
        from music_links_bot.lookup.input_routing import collection_input

        if is_private and collection_input.get() != "new":
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
            ]
            if allow_share:
                share_query = build_share_query(
                    [track_share_url(track) or "" for track in tracks]
                )
                if share_query:
                    rows.append(
                        [
                            InlineKeyboardButton(
                                get_text(lang, "share_post"),
                                switch_inline_query=share_query,
                            )
                        ]
                    )
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
        from music_links_bot.cards.collection_plan import build_collection_plan

        plan = build_collection_plan(
            tracks,
            context=context,
            title=title,
            include_hashtags=include_hashtags,
            include_channel_button=include_channel_button,
            intro_html=user_prefix,
            complete=len(tracks) == total,
        )
        collection_text, collection_preview, collection_sources = (
            plan.text,
            plan.preview_url,
            plan.source_urls,
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
        await _record_delivered(message, context=context, tracks=tracks)
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
    elif message.chat.type == "channel":
        # A link posted directly in a channel must use the same publication
        # pipeline as an editor card (photo, branding, caption and buttons).
        draft = new_track_draft(
            track, chat_id=message.chat_id, lang=lang, prefix=user_prefix
        )
        draft["hashtags"] = include_hashtags
        sent = await PublicationService(
            context, channel_username=CHANNEL_USERNAME
        ).preview(draft, target=message.chat_id)
        if sent is not None and sent is not False:
            await _try_delete_message(message)
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
        from music_links_bot.chat.release_panel import add_release_panel
        from music_links_bot.core.release_preferences import use_clean_artwork

        keyboard = await add_release_panel(keyboard, context, track, lang=lang)
        await _send_track_result(
            context.bot,
            message,
            user_prefix
            + format_track_message(
                track,
                include_hashtags=include_hashtags,
            ),
            preview_url=branded_artwork_preview_url(track.thumbnail_url)
            or (
                track.thumbnail_url
                if use_clean_artwork(track)
                else _select_preview_url(track.links, context) or track.thumbnail_url
            ),
            reply_markup=keyboard,
            source_urls=tuple(track.links.values()),
            content_kind=track.kind,
        )
    await _record_delivered(message, context=context, tracks=[track])


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
    via_bot = getattr(message, "via_bot", None)
    if via_bot is not None and via_bot.id == getattr(context.bot, "id", None):
        return True
    if not _INPUT_OVERRIDE.get():
        from music_links_bot.lookup.input_routing import guard_input

        if await guard_input(update, context, text=_message_text(message) or ""):
            return True
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
    intent_value = (
        "\n".join(sorted(cache_key_for_url(url) for url in request.source_urls))
        if request.source_urls
        else request.message_text
    )

    async def fresh_intent() -> bool:
        if _BYPASS_INTENT_GUARD.get():
            return True
        return await runtime.claim_intent(
            request.user_id, kind=action_kind, value=intent_value
        )

    # Every Redis call is a network round trip before the card: the
    # independent ones run together. A claimed intent of a rate-limited
    # request is harmless (it expires in seconds).
    (allowed, retry_after), fresh = await asyncio.gather(
        runtime.allow_user_request(request.user_id), fresh_intent()
    )
    if not allowed:
        await _reply_with_flow_error(
            message,
            context,
            BotFlowError(BotErrorCode.RATE_LIMITED, detail=str(retry_after)),
            lang=request.lang,
        )
        return False, None
    if not fresh:
        return False, None
    if action_kind == "help":
        await _reply_with_menu(message, context, MENU_HELP, lang=request.lang)
        return False, None
    remembered_value = request.search_query or request.message_text
    if not request.search_query and len(request.source_urls) == 1:
        remembered_value = request.source_urls[0]
    # begin_request registers this handler's task (a newer request cancels
    # it), so it runs here; remembering the action goes alongside.
    request_token = await _alongside(
        runtime.begin_request(request.user_id),
        runtime.remember_action(
            request.user_id,
            kind="search"
            if request.search_query or not request.source_urls
            else "resolve",
            value=remembered_value,
            lang=request.lang,
        ),
    )
    runtime.record_funnel("started")
    return True, request_token


async def _alongside(main: Awaitable[T], side: Coroutine[Any, Any, Any]) -> T:
    """Await ``main`` in this task while ``side`` runs concurrently.

    asyncio.gather would run ``main`` in a task of its own, and the request
    bookkeeping that recognises this handler by its task would miss it.
    """
    side_task = asyncio.create_task(side)
    try:
        result = await main
    except BaseException:
        side_task.cancel()
        await asyncio.gather(side_task, return_exceptions=True)
        raise
    await side_task
    return result


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
    total = max(1, len(request.source_urls))
    key = "progress_batch_links" if total > 1 else "progress_links"
    # The links are known now: open straight at the platform step. After a
    # text search the search placeholder already exists and just moves on.
    # A result faster than a second needs no progress line at all: the 👀
    # reaction already says the bot is on it.
    await _send_loading_placeholder(
        message, request.lang, total=total, key=key, delay=PROGRESS_DELAY_SECONDS
    )


async def _update_resolved_progress(request: LookupRequest, bundle) -> None:
    # A single card replaces the progress message milliseconds later, so an
    # extra "building the post" edit would only cost a Telegram round trip.
    if not request.is_private or len(request.source_urls) == 1:
        return
    await _update_loading_placeholder(
        request.lang,
        "progress_batch"
        if bundle.is_complete_for(request.source_urls)
        else "progress_batch_partial",
        done=bundle.item_count,
        total=len(request.source_urls),
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
    if not accepted:
        return
    from music_links_bot.tg.reactions import (
        finish_reaction,
        should_react,
        start_reaction,
    )

    reaction = (
        start_reaction(context.bot, message)
        if should_react(update, is_private=request.is_private)
        else None
    )
    delivered = False
    try:
        delivered = await _run_admitted_lookup(message, context, request, request_token)
    except Exception as exc:
        if request.is_private and not isinstance(exc, KVUnavailableError):
            await _report_failed_lookup(message, context, request.lang)
        raise
    finally:
        if reaction is not None:
            await finish_reaction(reaction, context.bot, message, success=delivered)


async def _report_failed_lookup(message, context, lang: str) -> None:
    """Never leave a private chat on a frozen progress line: say it and offer
    Retry. The error itself still reaches the error handler and the logs."""
    await _cancel_progress(message.chat_id, lang)
    try:
        await _reply_with_flow_error(
            message,
            context,
            BotFlowError(BotErrorCode.DELIVERY_FAILED, retryable=True),
            lang=lang,
        )
    except TelegramError:
        LOGGER.warning("Could not report a failed lookup", exc_info=True)


async def _run_admitted_lookup(message, context, request, request_token) -> bool:
    """Resolve and deliver one admitted request; True once a post went out."""
    from music_links_bot.lookup.lookup_control import (
        LookupStopped,
        interruptible,
        search_control,
    )

    async def resolve():
        searched = not request.source_urls
        if not await _resolve_request_sources(message, context, request):
            return None
        if searched:
            # Direct links reach this point microseconds after begin_request;
            # only a slow search can be overtaken by a newer message. The
            # check before delivery still covers every path.
            await _ensure_current_lookup(context, request, request_token)
        if not await _ensure_channel_publish_access(message, context):
            return None
        await _start_lookup_progress(message, context, request)
        return await _bot_lookup.resolve_sources(
            context.application.bot_data, request.source_urls
        )

    try:
        if request.is_private:
            async with search_control(context.application.bot_data, message):
                bundle = await interruptible(resolve())
        else:
            bundle = await resolve()
    except LookupStopped as stopped:
        await _ensure_current_lookup(context, request, request_token)
        await _cancel_progress(message.chat_id, request.lang)
        from music_links_bot.lookup.lookup_recovery import merge_recovered

        bundle = merge_recovered(
            request.source_urls,
            stopped.completed,
            _bot_lookup.LookupBundle([], [], [], [], [], []),
        )
        await message.reply_text(
            get_text(
                request.lang,
                "lookup_stopped_partial" if bundle.item_count else "lookup_stopped",
            ).format(found=bundle.item_count, total=len(request.source_urls))
        )
        if bundle.item_count:
            await _deliver_lookup_bundle(
                message,
                context,
                bundle,
                request=request,
                user_prefix=""
                if request.prefix_is_noise
                else _build_user_prefix(message, bot_username=context.bot.username),
            )
        return False
    if bundle is None:
        return False
    user_prefix = (
        ""
        if request.prefix_is_noise
        else _build_user_prefix(message, bot_username=context.bot.username)
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
        return False
    await _deliver_lookup_bundle(
        message,
        context,
        bundle,
        request=request,
        user_prefix=user_prefix,
    )
    return True


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
    if partial and not request.is_private:
        # Public replacement is atomic: never publish a shortened collection
        # and never delete the original group/channel message.
        await _send_partial_lookup_status(
            message,
            context,
            bundle,
            user_id=request.user_id,
            lang=request.lang,
        )
        return
    if request.is_private and not partial and len(request.source_urls) > 1:
        await _runtime(context).remember_collection(
            request.user_id,
            urls=request.source_urls,
            intro_html=user_prefix,
            lang=request.lang,
        )
    # Different platform URLs often point to the exact same release. Keep the
    # per-source statuses for retries and diagnostics, but show one merged card
    # with all discovered service buttons instead of duplicate releases.
    if bundle.tracks:
        from music_links_bot.lookup.lookup_recovery import capture_sources

        bundle.source_results = capture_sources(bundle)
        bundle.tracks = coalesce_equivalent_tracks(bundle.tracks)
    kind = delivery_kind(bundle)
    # ``build_user_prefix`` already removes supported source URLs while
    # preserving the user's prose and Telegram formatting. Keep that prose
    # for collections instead of treating the whole multi-link message as an
    # instruction and silently discarding its editorial introduction.
    prefix = user_prefix
    common = {
        "user_prefix": prefix,
        "include_channel_button": request.include_channel_button,
        "include_hashtags": request.include_hashtags,
        "lang": request.lang,
    }
    if bundle.titles:
        # Films and series are always their own cards, even beside music.
        await _send_title_result(
            context.bot, message, bundle.titles, allow_share=not partial, **common
        )
        bundle.titles = []
        common["user_prefix"] = ""
        kind = delivery_kind(bundle)
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
        await _record_delivered(message, context=context, videos=bundle.videos)
    elif kind == "radios":
        await _send_nts_result(
            context.bot,
            message,
            bundle.radios,
            requested_count=len(request.source_urls),
            allow_share=not partial,
            **common,
        )
        await _record_delivered(message, context=context, radios=bundle.radios)
    elif kind == "playlists":
        import_id = None
        if (
            request.is_private
            and len(bundle.playlists) == 1
            and bundle.playlists[0].track_urls
        ):
            import_id = await _store_retry_sources(
                context,
                user_id=request.user_id,
                urls=bundle.playlists[0].track_urls[:MAX_LINKS_PER_MESSAGE],
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
        await _record_delivered(message, context=context, playlists=bundle.playlists)
    elif kind == "artists":
        await _send_artist_result(
            context.bot,
            message,
            bundle.artists,
            requested_count=len(request.source_urls),
            allow_share=not partial,
            **common,
        )
        await _record_delivered(message, context=context, artists=bundle.artists)
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
        await _record_delivered(
            message,
            context=context,
            tracks=bundle.tracks,
            videos=bundle.videos,
            radios=bundle.radios,
            playlists=bundle.playlists,
            artists=bundle.artists,
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


def _build_error_keyboard(
    bot_username: str | None,
    *,
    lang: str = "ru",
    retryable: bool = False,
    search_query: str | None = None,
    source_url: str | None = None,
    recovery: str | None = None,
) -> InlineKeyboardMarkup:
    return _build_error_keyboard_view(
        bot_username,
        lang=lang,
        retryable=retryable,
        search_query=search_query,
        source_url=source_url,
        recovery=recovery,
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
