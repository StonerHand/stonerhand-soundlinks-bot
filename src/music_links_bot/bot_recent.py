from __future__ import annotations

from collections.abc import Awaitable, Callable
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from music_links_bot.bot_runtime import encode_callback
from music_links_bot.i18n import get_text
from music_links_bot.studio_storage import _load_history_items


async def render_recent_view(
    context,
    *,
    user_id: int,
    lang: str,
    draft_ids: list[str],
    load_draft: Callable[[object, str], Awaitable[dict | None]],
) -> tuple[str, InlineKeyboardMarkup]:
    drafts: list[tuple[str, dict]] = []
    for draft_id in draft_ids[:5]:
        draft = await load_draft(context, draft_id)
        if isinstance(draft, dict) and isinstance(draft.get("item"), dict):
            drafts.append((draft_id, draft))

    lines = [get_text(lang, "recent_title")]
    rows: list[list[InlineKeyboardButton]] = []
    for index, (draft_id, draft) in enumerate(drafts, start=1):
        _append_recent_line(lines, index, draft["item"])
        rows.append(
            [
                InlineKeyboardButton(
                    f"↻ {index} · {get_text(lang, 'recent_repeat')}",
                    callback_data=encode_callback("editor", "b", draft_id),
                    api_kwargs={"style": "primary"},
                ),
                InlineKeyboardButton(
                    f"{index} · {get_text(lang, 'recent_add')}",
                    callback_data=encode_callback("editor", "c", draft_id),
                ),
            ]
        )

    if not drafts:
        history = await _load_history_items(context, user_id)
        if not history:
            return _empty_recent_view(lang)
        for index, item in enumerate(history[:5], start=1):
            _append_recent_line(lines, index, item)
            rows.append(
                [
                    InlineKeyboardButton(
                        f"↻ {index} · {get_text(lang, 'recent_repeat')}",
                        switch_inline_query_current_chat=str(
                            item.get("source_url") or ""
                        )[:256],
                        api_kwargs={"style": "primary"},
                    )
                ]
            )

    rows.append([_home_button(lang)])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _append_recent_line(lines: list[str], index: int, item: dict) -> None:
    lines.append(
        f"\n<b>{index}.</b> {escape(str(item.get('artist') or '—'))} — "
        f"{escape(str(item.get('title') or '—'))}"
    )


def _empty_recent_view(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    return get_text(lang, "recent_empty"), InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    get_text(lang, "home_create"),
                    switch_inline_query_current_chat="",
                    api_kwargs={"style": "primary"},
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
