from __future__ import annotations

from html import escape
import logging

from telegram import InlineKeyboardMarkup, Message, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

from music_links_bot.bot_admin import stats_text
from music_links_bot.bot_builder import active_card_label
from music_links_bot.bot_crate import load_crate
from music_links_bot.bot_recent import render_recent_view
from music_links_bot.bot_runtime import BotRuntime, CallbackAction, UserSession
from music_links_bot.bot_storage import load_draft
from music_links_bot.bot_ui import (
    build_create_keyboard,
    build_home_text,
    build_onboarding_keyboard,
    build_section_keyboard,
    build_start_keyboard,
)
from music_links_bot.i18n import get_text, resolve_lang
from music_links_bot.keyboards import _channel_button

LOGGER = logging.getLogger(__name__)

MENU_START = "menu:start"
MENU_HELP = "menu:help"
MENU_GUIDE = "menu:guide"
MENU_PLATFORMS = "menu:platforms"
MENU_DEMO = "menu:demo"
MENU_MORE = "menu:more"
MENU_RECENT = "menu:recent"
MENU_KEYS = frozenset(
    {
        MENU_START,
        MENU_HELP,
        MENU_GUIDE,
        MENU_PLATFORMS,
        MENU_DEMO,
        MENU_MORE,
        MENU_RECENT,
    }
)


def update_lang(update: Update) -> str:
    user = update.effective_user
    return resolve_lang(user.language_code if user else None)


def runtime_for(context: ContextTypes.DEFAULT_TYPE) -> BotRuntime:
    runtime = context.application.bot_data.get("runtime")
    if not isinstance(runtime, BotRuntime):
        runtime = BotRuntime(context.application.bot_data.get("kv_store"))
        context.application.bot_data["runtime"] = runtime
    return runtime


async def home_state(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> tuple[int, bool]:
    items = await load_crate(context.application.bot_data, user_id)
    admin_chat_id = context.application.bot_data.get("admin_chat_id")
    return len(items), admin_chat_id is not None and user_id == admin_chat_id


async def _active_home_card(
    context: ContextTypes.DEFAULT_TYPE,
    runtime: BotRuntime,
    session: UserSession,
    *,
    lang: str,
) -> tuple[str | None, str | None]:
    draft_id = session.active_draft_id
    if not draft_id:
        return None, None
    draft = await load_draft(context, draft_id)
    if draft is None or draft.get("deleted_at"):
        session.active_draft_id = ""
        await runtime.save_session(session)
        return None, None
    return draft_id, active_card_label(draft, get_text(lang, "home_continue"))


async def remember_fresh_home_message(
    context: ContextTypes.DEFAULT_TYPE,
    runtime: BotRuntime,
    session: UserSession,
    *,
    chat_id: int,
    sent: Message,
) -> None:
    """Keep one current navigation message in a private chat."""
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
        LOGGER.debug("Could not retire previous home message", exc_info=True)


async def home_view(query, context, *, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    user = query.from_user
    user_id = user.id if user else 0
    crate_count, is_admin = await home_state(context, user_id)
    runtime = runtime_for(context)
    session = await runtime.get_session(user_id, lang=lang)
    active_draft_id, active_draft_label = await _active_home_card(
        context, runtime, session, lang=lang
    )
    return (
        build_home_text(
            lang=lang,
            first_name=user.first_name if user else "",
            crate_count=crate_count,
            is_admin=is_admin,
        ),
        build_start_keyboard(
            context.bot.username,
            lang=lang,
            crate_count=crate_count,
            is_admin=is_admin,
            active_draft_id=active_draft_id,
            active_draft_label=active_draft_label,
        ),
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return
    lang = update_lang(update)
    user_id = update.effective_user.id if update.effective_user else message.chat_id
    runtime = runtime_for(context)
    if not await runtime.claim_intent(user_id, kind="command", value="start"):
        return
    session = await runtime.get_session(user_id, lang=lang)
    active_draft_id, active_draft_label = await _active_home_card(
        context, runtime, session, lang=lang
    )
    crate_count, is_admin = await home_state(context, user_id)
    sent = await message.reply_text(
        build_home_text(
            lang=lang,
            first_name=update.effective_user.first_name
            if update.effective_user
            else "",
            crate_count=crate_count,
            is_admin=is_admin,
            first_visit=not session.onboarding_seen,
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=build_start_keyboard(
            context.bot.username,
            lang=lang,
            crate_count=crate_count,
            is_admin=is_admin,
            show_tour=not session.onboarding_seen,
            active_draft_id=active_draft_id,
            active_draft_label=active_draft_label,
        ),
    )
    if message.chat.type == "private":
        await remember_fresh_home_message(
            context, runtime, session, chat_id=message.chat_id, sent=sent
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is not None:
        await reply_with_menu(
            update.message, context, MENU_HELP, lang=update_lang(update)
        )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    lang = update_lang(update)
    runtime = runtime_for(context)
    session = await runtime.get_session(user.id, lang=lang)
    pending = dict(session.pending_input)
    if not pending:
        await message.reply_text(get_text(lang, "input_nothing"))
        return
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
                LOGGER.debug("Could not clean up cancelled native input", exc_info=True)
    await message.reply_text(get_text(lang, "input_cancelled"))


async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    lang = update_lang(update)
    if message.chat.type == "private":
        await reply_with_menu(message, context, MENU_GUIDE, lang=lang)
        return
    user_id = update.effective_user.id if update.effective_user else message.chat_id
    crate_count, _is_admin = await home_state(context, user_id)
    sent = await message.reply_text(
        menu_text(MENU_GUIDE, lang=lang),
        parse_mode=ParseMode.HTML,
        reply_markup=build_section_keyboard(
            context.bot.username,
            lang=lang,
            crate_count=crate_count,
            active="guide",
        ),
    )
    if message.chat.type in {"group", "supergroup", "channel"}:
        try:
            await sent.pin(disable_notification=True)
        except (BadRequest, Forbidden):
            LOGGER.info("Could not pin guide in chat %s", message.chat_id)


async def platforms_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is not None:
        await reply_with_menu(
            update.message,
            context,
            MENU_PLATFORMS,
            lang=update_lang(update),
        )


async def channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if update.message is not None:
        await update.message.reply_text(
            "StonerHand рядом",
            reply_markup=InlineKeyboardMarkup([[_channel_button()]]),
        )


async def recent_view(
    query, context: ContextTypes.DEFAULT_TYPE, *, lang: str
) -> tuple[str, InlineKeyboardMarkup]:
    user_id = query.from_user.id if query.from_user else 0
    session = await runtime_for(context).get_session(user_id, lang=lang)
    return await render_recent_view(
        context,
        user_id=user_id,
        lang=lang,
        draft_ids=session.recent_draft_ids,
        load_draft=load_draft,
    )


async def safe_edit(query, text: str, keyboard: InlineKeyboardMarkup | None) -> None:
    try:
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


async def dispatch_menu_action(query, context, action: CallbackAction) -> None:
    lang = resolve_lang(query.from_user.language_code if query.from_user else None)
    if action.action.startswith("onboard"):
        step = action.action.removeprefix("onboard") or "1"
        if step == "done":
            session = await runtime_for(context).get_session(
                query.from_user.id, lang=lang
            )
            session.onboarding_seen = True
            await runtime_for(context).save_session(session)
            text, keyboard = await home_view(query, context, lang=lang)
        else:
            step_number = max(1, min(3, int(step)))
            text = get_text(lang, f"onboarding_{step_number}")
            keyboard = build_onboarding_keyboard(step_number, lang)
        await query.answer()
        await safe_edit(query, text, keyboard)
        return
    if action.action == "stats":
        user_id = query.from_user.id if query.from_user else 0
        crate_count, is_admin = await home_state(context, user_id)
        if not is_admin:
            await query.answer(get_text(lang, "ed_admin_only"), show_alert=True)
            return
        await query.answer()
        await safe_edit(
            query,
            escape(await stats_text(context, include_private=True)),
            build_section_keyboard(
                context.bot.username,
                lang=lang,
                crate_count=crate_count,
                active=None,
            ),
        )
        return
    if action.action == "start":
        text, keyboard = await home_view(query, context, lang=lang)
    elif action.action == "recent":
        text, keyboard = await recent_view(query, context, lang=lang)
    elif action.action == "create":
        text, keyboard = (
            get_text(lang, "create_prompt"),
            build_create_keyboard(lang=lang),
        )
    else:
        menu_key = {
            "help": MENU_HELP,
            "guide": MENU_GUIDE,
            "platforms": MENU_PLATFORMS,
            "demo": MENU_DEMO,
            "more": MENU_MORE,
        }.get(action.action, MENU_START)
        user_id = query.from_user.id if query.from_user else 0
        crate_count, _is_admin = await home_state(context, user_id)
        text = menu_text(menu_key, lang=lang)
        keyboard = build_section_keyboard(
            context.bot.username,
            lang=lang,
            crate_count=crate_count,
            active=action.action,
        )
    await query.answer()
    await safe_edit(query, text, keyboard)


async def legacy_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    lang = resolve_lang(query.from_user.language_code if query.from_user else None)
    menu_key = query.data if query.data in MENU_KEYS else MENU_START
    if menu_key == MENU_START:
        text, keyboard = await home_view(query, context, lang=lang)
    else:
        user_id = query.from_user.id if query.from_user else 0
        crate_count, _is_admin = await home_state(context, user_id)
        text = menu_text(menu_key, lang=lang)
        keyboard = build_section_keyboard(
            context.bot.username,
            lang=lang,
            crate_count=crate_count,
            active=menu_key.removeprefix("menu:"),
        )
    await safe_edit(query, text, keyboard)


async def reply_with_menu(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    menu_key: str,
    *,
    lang: str = "ru",
) -> None:
    runtime = runtime_for(context)
    subject_id = message.from_user.id if message.from_user else message.chat_id
    crate_count, _is_admin = await home_state(context, subject_id)
    session = (
        await runtime.get_session(subject_id, lang=lang)
        if message.chat.type == "private"
        else None
    )
    sent = await message.reply_text(
        menu_text(menu_key, lang=lang),
        parse_mode=ParseMode.HTML,
        reply_markup=build_section_keyboard(
            context.bot.username,
            lang=lang,
            crate_count=crate_count,
            active=menu_key.removeprefix("menu:"),
        ),
    )
    if session is not None:
        await remember_fresh_home_message(
            context,
            runtime,
            session,
            chat_id=message.chat_id,
            sent=sent,
        )


def menu_text(menu_key: str, *, lang: str = "ru") -> str:
    return get_text(
        lang,
        {
            MENU_HELP: "menu_help",
            MENU_DEMO: "menu_demo",
            MENU_GUIDE: "menu_guide",
            MENU_PLATFORMS: "menu_platforms",
            MENU_MORE: "menu_more",
        }.get(menu_key, "menu_start"),
    )
