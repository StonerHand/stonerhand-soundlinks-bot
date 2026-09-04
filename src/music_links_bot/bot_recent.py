from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from html import escape

from telegram import InlineKeyboardMarkup

from music_links_bot.bot_history import load_history_items
from music_links_bot.bot_runtime import encode_callback
from music_links_bot.i18n import get_text
from music_links_bot.telegram_buttons import button as InlineKeyboardButton


async def render_drafts_view(
    context,
    *,
    user_id: int,
    lang: str,
    draft_ids: list[str],
    load_draft: Callable[[object, str], Awaitable[dict | None]],
) -> tuple[str, InlineKeyboardMarkup]:
    """Show editable cards only; published history has its own screen."""
    drafts: list[tuple[str, dict]] = []
    for draft_id in draft_ids[:5]:
        draft = await load_draft(context, draft_id)
        if isinstance(draft, dict) and isinstance(draft.get("item"), dict):
            drafts.append((draft_id, draft))

    if not drafts:
        return _empty_drafts_view(lang)

    lines = [get_text(lang, "drafts_title")]
    rows: list[list[InlineKeyboardButton]] = []
    for index, (draft_id, draft) in enumerate(drafts, start=1):
        item = dict(draft["item"])
        item.setdefault("ts", draft.get("created_at"))
        _append_recent_line(lines, index, item, lang=lang)
        rows.append(
            [
                InlineKeyboardButton(
                    f"{index} · {get_text(lang, 'drafts_open')}",
                    callback_data=encode_callback("editor", "b", draft_id),
                ),
                InlineKeyboardButton(
                    f"{index} · {get_text(lang, 'recent_add')}",
                    callback_data=encode_callback("editor", "c", draft_id),
                ),
            ]
        )

    rows.append([_home_button(lang)])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def render_recent_view(
    context,
    *,
    user_id: int,
    lang: str,
) -> tuple[str, InlineKeyboardMarkup]:
    """Show delivered releases without mixing them with editable drafts."""
    history = await load_history_items(context, user_id)
    if not history:
        return _empty_recent_view(lang)

    lines = [get_text(lang, "recent_title")]
    rows: list[list[InlineKeyboardButton]] = []
    for index, item in enumerate(history[:5], start=1):
        _append_recent_line(lines, index, item, lang=lang)
        rows.append(
            [
                InlineKeyboardButton(
                    f"↻ {index} · {get_text(lang, 'recent_repeat')}",
                    switch_inline_query_current_chat=str(item.get("source_url") or "")[
                        :256
                    ],
                )
            ]
        )
    rows.append([_home_button(lang)])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _append_recent_line(lines: list[str], index: int, item: dict, *, lang: str) -> None:
    emoji = escape(str(item.get("emoji") or "🎧"))
    timestamp = item.get("ts")
    when = ""
    if isinstance(timestamp, (int, float)) and timestamp > 0:
        # Preserve the deployment's local presentation timezone. Runtime
        # timestamps are only a compact relative hint, never schedule input.
        moment = datetime.fromtimestamp(timestamp)
        today = datetime.now().date()
        when = (
            moment.strftime(("today" if lang == "en" else "сегодня") + " · %H:%M")
            if moment.date() == today
            else moment.strftime("%d.%m · %H:%M")
        )
    lines.append(
        f"\n<b>{index}.</b> {emoji} {escape(str(item.get('artist') or '—'))} — "
        f"{escape(str(item.get('title') or '—'))}"
        + (f"\n<i>{escape(when)}</i>" if when else "")
    )


def _empty_recent_view(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    return get_text(lang, "recent_empty"), InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    get_text(lang, "home_create"),
                    callback_data=encode_callback("menu", "create"),
                    style="primary",
                )
            ],
            [_home_button(lang)],
        ]
    )


def _empty_drafts_view(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    return get_text(lang, "drafts_empty"), InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    get_text(lang, "home_create"),
                    callback_data=encode_callback("menu", "create"),
                    style="primary",
                )
            ],
            [_home_button(lang)],
        ]
    )


def _home_button(lang: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        get_text(lang, "home_back"),
        callback_data=encode_callback("menu", "start"),
    )
