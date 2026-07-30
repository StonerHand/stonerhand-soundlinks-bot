from __future__ import annotations

from html import escape
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from music_links_bot.bot_runtime import encode_callback
from music_links_bot.i18n import get_text
from music_links_bot.publication_state import webapp_url


def _crate_button(lang: str, crate_count: int) -> InlineKeyboardButton:
    """Make a non-empty collection visible without adding another menu row."""
    safe_count = max(0, min(10, crate_count))
    kwargs = {"api_kwargs": {"style": "success"}} if safe_count else {}
    return InlineKeyboardButton(
        get_text(lang, "home_crate").format(count=safe_count),
        callback_data=encode_callback("crate", "open"),
        **kwargs,
    )


def build_home_text(
    *,
    lang: str,
    first_name: str = "",
    crate_count: int = 0,
    is_admin: bool = False,
    first_visit: bool = False,
) -> str:
    safe_name = escape(first_name.strip()[:40])
    greeting = get_text(lang, "home_title_new" if first_visit else "home_title")
    if safe_name and not first_visit:
        greeting = greeting.replace("{name}", f", {safe_name}")
    else:
        greeting = greeting.replace("{name}", "")
    mode = get_text(lang, "home_mode_admin" if is_admin else "home_mode_user")
    return get_text(lang, "home_body").format(
        greeting=greeting,
        crate_count=max(0, min(10, crate_count)),
        mode=mode,
    )


def build_start_keyboard(
    bot_username: str | None,
    *,
    lang: str,
    crate_count: int = 0,
    is_admin: bool = False,
    show_tour: bool = False,
    include_studio: bool = True,
) -> InlineKeyboardMarkup:
    del bot_username, is_admin, show_tour
    rows: list[list[InlineKeyboardButton]] = []
    studio_url = webapp_url()
    if studio_url and include_studio:
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "open_studio"),
                    web_app=WebAppInfo(url=studio_url),
                    api_kwargs={"style": "success"},
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "quick_search"),
                switch_inline_query_current_chat="",
                api_kwargs={"style": "primary"},
            ),
            _crate_button(lang, crate_count),
        ]
    )
    return InlineKeyboardMarkup(rows)


def build_section_keyboard(
    bot_username: str | None,
    *,
    lang: str,
    crate_count: int = 0,
    include_studio: bool = True,
    active: str | None = None,
) -> InlineKeyboardMarkup:
    del bot_username
    rows: list[list[InlineKeyboardButton]] = []
    studio_url = webapp_url()
    if studio_url and include_studio:
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "open_studio"),
                    web_app=WebAppInfo(url=studio_url),
                    api_kwargs={"style": "success"},
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "quick_search"),
                switch_inline_query_current_chat="",
                api_kwargs={"style": "primary"},
            ),
            _crate_button(lang, crate_count),
        ]
    )

    related_actions = {
        "help": ("platforms", "guide"),
        "platforms": ("help", "guide"),
        "guide": ("help", "platforms"),
        "demo": ("help", "platforms"),
    }.get(active, ("help", "platforms"))
    label_keys = {
        "help": "tab_help",
        "platforms": "tab_platforms",
        "guide": "tab_guide",
        "demo": "tab_demo",
    }
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, label_keys[action]),
                callback_data=encode_callback("menu", action),
            )
            for action in related_actions
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "home_back"),
                callback_data=encode_callback("menu", "start"),
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def build_error_keyboard(
    bot_username: str | None,
    *,
    lang: str = "ru",
    retryable: bool = False,
) -> InlineKeyboardMarkup:
    """Keep recovery contextual: one primary action and one predictable back."""
    if retryable:
        primary = InlineKeyboardButton(
            get_text(lang, "retry"),
            callback_data=encode_callback("retry", "last"),
            api_kwargs={"style": "primary"},
        )
    else:
        primary = InlineKeyboardButton(
            get_text(lang, "quick_search"),
            switch_inline_query_current_chat="",
            api_kwargs={"style": "primary"},
        )
    del bot_username
    return InlineKeyboardMarkup(
        [
            [primary],
            [
                InlineKeyboardButton(
                    get_text(lang, "home_back"),
                    callback_data=encode_callback("menu", "start"),
                )
            ],
        ]
    )


def build_duplicate_post_keyboard(
    draft_id: str,
    record: dict,
    *,
    lang: str,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                get_text(lang, "duplicate_repeat"),
                callback_data=encode_callback("editor", "r", draft_id),
                api_kwargs={"style": "primary"},
            )
        ]
    ]
    if isinstance(record.get("message_id"), int):
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "duplicate_replace"),
                    callback_data=encode_callback("editor", "x", draft_id),
                    api_kwargs={"style": "danger"},
                )
            ]
        )
    if record.get("url"):
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "duplicate_open"),
                    url=str(record["url"]),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "cancel"),
                callback_data=encode_callback("editor", "b", draft_id),
            )
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
        row.insert(
            0,
            InlineKeyboardButton(
                get_text(lang, "back"),
                callback_data=encode_callback(
                    "menu", f"onboard{step - 1}" if step > 1 else "start"
                ),
            ),
        )
        rows.append(row)
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "back"),
                    callback_data=encode_callback("menu", "onboard2"),
                ),
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
    if draft.get("in_crate"):
        label = get_text(lang, "ed_crate_count").format(
            count=max(0, min(10, int(draft.get("crate_count") or 0)))
        )
        button = InlineKeyboardButton(
            label,
            callback_data=encode_callback("crate", "open"),
            api_kwargs={"style": "success"},
        )
    else:
        button = InlineKeyboardButton(
            get_text(lang, "ed_add_crate"),
            callback_data=encode_callback("editor", "c", draft_id),
        )
    return [[button]]


def editor_more_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"

    def state(flag: str) -> str:
        return get_text(lang, "ed_on" if draft.get(flag) else "ed_off")

    toggles = [
        InlineKeyboardButton(
            f"{get_text(lang, 'ed_hashtags')} {state('hashtags')}",
            callback_data=encode_callback("editor", "h", draft_id),
        )
    ]
    if draft.get("prefix"):
        toggles.append(
            InlineKeyboardButton(
                f"{get_text(lang, 'ed_quote')} {state('quote')}",
                callback_data=encode_callback("editor", "q", draft_id),
            )
        )
    preview_state = get_text(
        lang,
        "ed_preview_large" if draft.get("large_preview") else "ed_preview_small",
    )
    toggles.append(
        InlineKeyboardButton(
            f"{get_text(lang, 'ed_preview')} {preview_state}",
            callback_data=encode_callback("editor", "v", draft_id),
        )
    )
    return [
        toggles,
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
                f"<b>{index}.</b> {escape(str(item.get('artist') or '—'))} — "
                f"{escape(str(item.get('title') or '—'))}"
            )
        lines.extend(["", get_text(lang, "crate_hint")])
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
                    get_text(lang, "crate_up"),
                    callback_data=encode_callback("crate", "up", str(index)),
                )
            )
        if index < len(items) - 1:
            controls.append(
                InlineKeyboardButton(
                    get_text(lang, "crate_down"),
                    callback_data=encode_callback("crate", "down", str(index)),
                )
            )
        controls.append(
            InlineKeyboardButton(
                get_text(lang, "crate_remove"),
                callback_data=encode_callback("crate", "remove", str(index)),
                api_kwargs={"style": "danger"},
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
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "home_back"),
                callback_data=encode_callback("menu", "start"),
            )
        ]
    )
    return text, InlineKeyboardMarkup(rows)
