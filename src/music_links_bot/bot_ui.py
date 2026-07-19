from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from music_links_bot.bot_runtime import encode_callback
from music_links_bot.i18n import get_text
from music_links_bot.keyboards import _channel_button
from music_links_bot.publication_state import webapp_url


def build_start_keyboard(bot_username: str | None, *, lang: str) -> InlineKeyboardMarkup:
    del bot_username
    rows = [
        [
            InlineKeyboardButton(
                get_text(lang, "quick_search"),
                switch_inline_query_current_chat="",
                api_kwargs={"style": "primary"},
            ),
            InlineKeyboardButton(
                get_text(lang, "quick_tour"),
                callback_data=encode_callback("menu", "onboard1"),
            ),
        ]
    ]
    studio_url = webapp_url()
    if studio_url:
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "open_studio"), web_app=WebAppInfo(url=studio_url)
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "tab_help"),
                callback_data=encode_callback("menu", "help"),
            ),
            _channel_button(),
        ]
    )
    return InlineKeyboardMarkup(rows)


def build_onboarding_keyboard(step: int, lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if step < 3:
        row = [
            InlineKeyboardButton(
                get_text(lang, "next"),
                callback_data=encode_callback("menu", f"onboard{step + 1}"),
                api_kwargs={"style": "primary"},
            )
        ]
        if step > 1:
            row.insert(
                0,
                InlineKeyboardButton(
                    get_text(lang, "back"),
                    callback_data=encode_callback("menu", f"onboard{step - 1}"),
                ),
            )
        rows.append(row)
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "start_using"),
                    callback_data=encode_callback("menu", "onboarddone"),
                    api_kwargs={"style": "success"},
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def editor_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"

    def state(flag: str) -> str:
        return get_text(lang, "ed_on" if draft.get(flag) else "ed_off")

    toggle_row = [
        InlineKeyboardButton(
            f"{get_text(lang, 'ed_hashtags')} {state('hashtags')}",
            callback_data=encode_callback("editor", "h", draft_id),
        )
    ]
    if draft.get("prefix"):
        toggle_row.append(
            InlineKeyboardButton(
                f"{get_text(lang, 'ed_quote')} {state('quote')}",
                callback_data=encode_callback("editor", "q", draft_id),
            )
        )
    preview_state = get_text(
        lang,
        "ed_preview_large" if draft.get("large_preview") else "ed_preview_small",
    )
    toggle_row.append(
        InlineKeyboardButton(
            f"{get_text(lang, 'ed_preview')} {preview_state}",
            callback_data=encode_callback("editor", "v", draft_id),
        )
    )

    primary_row = [
        InlineKeyboardButton(
            get_text(lang, "ed_send_self"),
            callback_data=encode_callback("editor", "s", draft_id),
            api_kwargs={"style": "success"},
        )
    ]
    if draft.get("can_publish"):
        primary_row.append(
            InlineKeyboardButton(
                get_text(lang, "ed_publish"),
                callback_data=encode_callback("editor", "p", draft_id),
                api_kwargs={"style": "primary"},
            )
        )

    secondary_row: list[InlineKeyboardButton] = []
    studio_url = webapp_url()
    if studio_url:
        secondary_row.append(
            InlineKeyboardButton(
                get_text(lang, "ed_studio"),
                web_app=WebAppInfo(url=f"{studio_url}?draft={draft_id}"),
            )
        )
    secondary_row.extend(
        [
            InlineKeyboardButton(
                get_text(lang, "ed_add_crate"),
                callback_data=encode_callback("editor", "c", draft_id),
            ),
            InlineKeyboardButton(
                get_text(lang, "ed_more"),
                callback_data=encode_callback("editor", "m", draft_id),
            ),
        ]
    )
    return [primary_row, toggle_row, secondary_row]


def editor_more_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"
    return [
        [
            InlineKeyboardButton(
                get_text(lang, "ed_done"),
                callback_data=encode_callback("editor", "f", draft_id),
                api_kwargs={"style": "success"},
            ),
            InlineKeyboardButton(
                get_text(lang, "ed_delete"),
                callback_data=encode_callback("editor", "d", draft_id),
                api_kwargs={"style": "danger"},
            ),
        ],
        [
            InlineKeyboardButton(
                get_text(lang, "back"),
                callback_data=encode_callback("editor", "b", draft_id),
            )
        ],
    ]


def render_crate(items: list[dict], *, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    if not items:
        text = get_text(lang, "crate_empty")
    else:
        heading = get_text(lang, "crate_title").replace("{count}", str(len(items)))
        lines = [heading, ""]
        for index, entry in enumerate(items, 1):
            item = entry.get("item") or {}
            lines.append(
                f"<b>{index}.</b> {item.get('artist') or '—'} — {item.get('title') or '—'}"
            )
        lines.extend(
            ["", "Меняй порядок стрелками; изменения сохраняются автоматически."]
        )
        text = "\n".join(lines)

    rows: list[list[InlineKeyboardButton]] = []
    for index, entry in enumerate(items):
        item = entry.get("item") or {}
        rows.append(
            [
                InlineKeyboardButton(
                    f"{index + 1}. {item.get('artist') or '—'} — {item.get('title') or '—'}"[:64],
                    callback_data=encode_callback("noop", "item"),
                )
            ]
        )
        controls: list[InlineKeyboardButton] = []
        if index > 0:
            controls.append(
                InlineKeyboardButton(
                    "↑", callback_data=encode_callback("crate", "up", str(index))
                )
            )
        if index < len(items) - 1:
            controls.append(
                InlineKeyboardButton(
                    "↓", callback_data=encode_callback("crate", "down", str(index))
                )
            )
        controls.append(
            InlineKeyboardButton(
                "Удалить",
                callback_data=encode_callback("crate", "remove", str(index)),
            )
        )
        rows.append(controls)
    studio_url = webapp_url()
    if studio_url:
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "crate_open_studio"),
                    web_app=WebAppInfo(url=f"{studio_url}?view=crate"),
                    api_kwargs={"style": "primary"},
                )
            ]
        )
    return text, InlineKeyboardMarkup(rows)
