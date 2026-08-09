from __future__ import annotations

from html import escape
from telegram import InlineKeyboardMarkup

from music_links_bot.bot_runtime import encode_callback
from music_links_bot.i18n import get_text
from music_links_bot.models import TrackMatch
from music_links_bot.telegram_buttons import (
    ButtonTone,
    button as InlineKeyboardButton,
    callback_button,
)


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
    active_draft_id: str | None = None,
) -> InlineKeyboardMarkup:
    del bot_username, is_admin
    rows: list[list[InlineKeyboardButton]] = []
    if show_tour:
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "quick_tour"),
                    callback_data=encode_callback("menu", "onboard1"),
                )
            ]
        )
    if active_draft_id:
        create_button = InlineKeyboardButton(
            get_text(lang, "home_continue"),
            callback_data=encode_callback("editor", "b", active_draft_id),
            api_kwargs={"style": "primary"},
        )
    else:
        create_button = InlineKeyboardButton(
            get_text(lang, "home_create"),
            switch_inline_query_current_chat="",
            api_kwargs={"style": "primary"},
        )
    rows.append([create_button])
    rows.append(
        [
            _crate_button(lang, crate_count),
            InlineKeyboardButton(
                get_text(lang, "home_recent"),
                callback_data=encode_callback("menu", "recent"),
            ),
        ]
    )
    return InlineKeyboardMarkup(rows)


def build_section_keyboard(
    bot_username: str | None,
    *,
    lang: str,
    crate_count: int = 0,
    active: str | None = None,
) -> InlineKeyboardMarkup:
    del bot_username
    rows: list[list[InlineKeyboardButton]] = []
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "quick_search"),
                switch_inline_query_current_chat="",
                api_kwargs={"style": "primary"},
            )
        ]
    )
    rows.append(
        [
            _crate_button(lang, crate_count),
            InlineKeyboardButton(
                get_text(lang, "home_more"),
                callback_data=encode_callback("menu", "more"),
            ),
        ]
    )

    if active == "more":
        rows.extend(
            [
                InlineKeyboardButton(
                    get_text(lang, f"tab_{action}"),
                    callback_data=encode_callback("menu", action),
                )
                for action in action_row
            ]
            for action_row in (("help", "platforms"), ("guide", "demo"))
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
    search_query: str | None = None,
    source_url: str | None = None,
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
    rows = [[primary]]
    secondary_row: list[InlineKeyboardButton] = []
    if search_query:
        secondary_row.append(
            InlineKeyboardButton(
                get_text(lang, "search_change"),
                switch_inline_query_current_chat=search_query[:120],
            )
        )
    if source_url and source_url.startswith(("http://", "https://")):
        secondary_row.append(
            InlineKeyboardButton(
                get_text(lang, "error_open_source"),
                url=source_url,
            )
        )
    del bot_username
    if secondary_row:
        rows.append(secondary_row)
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "home_back"),
                callback_data=encode_callback("menu", "start"),
            )
        ]
    )
    return InlineKeyboardMarkup(
        rows
    )


def build_publish_confirmation(
    draft_id: str,
    draft: dict,
    track: TrackMatch,
    *,
    target: str,
    lang: str,
) -> tuple[str, InlineKeyboardMarkup]:
    """Compact last check before the only externally visible action."""
    text = get_text(lang, "publish_confirm").format(
        artist=escape(track.artist),
        title=escape(track.title),
        target=escape(target),
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                callback_button(
                    get_text(lang, "publish_confirm_button"),
                    encode_callback("editor", "pc", draft_id),
                    tone=ButtonTone.SUCCESS,
                )
            ],
            [
                callback_button(
                    get_text(lang, "back"),
                    encode_callback("editor", "o", draft_id),
                )
            ],
        ]
    )
    return text, keyboard


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
    return [
        [
            InlineKeyboardButton(
                get_text(lang, "ed_edit"),
                callback_data=encode_callback("editor", "m", draft_id),
            ),
            button,
        ]
    ]


def editor_more_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    """Four quick controls; destructive and delivery actions stay in overflow."""
    lang = draft.get("lang") or "ru"

    def state(flag: str) -> str:
        return get_text(lang, "ed_on" if draft.get(flag) else "ed_off")

    from music_links_bot.release_presentation import normalize_preset

    preset = normalize_preset(draft.get("preset"), draft)
    toggle_rows = [
        [
            InlineKeyboardButton(
                get_text(lang, f"ed_preset_{preset}"),
                callback_data=encode_callback("editor", "z", draft_id),
            ),
            InlineKeyboardButton(
                get_text(
                    lang,
                    "ed_text_on" if draft.get("quote") else "ed_text_off",
                ),
                callback_data=encode_callback("editor", "t", draft_id),
            ),
        ],
        [
            InlineKeyboardButton(
                f"{get_text(lang, 'ed_hashtags')} {state('hashtags')}",
                callback_data=encode_callback("editor", "h", draft_id),
            ),
            InlineKeyboardButton(
                get_text(
                    lang,
                    "ed_platforms_all"
                    if draft.get("platforms")
                    else "ed_platforms_compact",
                ),
                callback_data=encode_callback("editor", "l", draft_id),
            ),
        ]
    ]
    rows = [
        *toggle_rows,
        [
            InlineKeyboardButton(
                get_text(lang, "ed_done"),
                callback_data=encode_callback("editor", "f", draft_id),
                api_kwargs={"style": "success"},
            ),
            InlineKeyboardButton(
                get_text(lang, "ed_more"),
                callback_data=encode_callback("editor", "o", draft_id),
            ),
        ],
    ]
    return rows


def editor_overflow_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"
    rows = [
        [
            InlineKeyboardButton(
                get_text(lang, "ed_send_self"),
                callback_data=encode_callback("editor", "s", draft_id),
                api_kwargs={"style": "primary"},
            )
        ]
    ]
    if draft.get("can_publish"):
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "ed_publish"),
                    callback_data=encode_callback("editor", "p", draft_id),
                    api_kwargs={"style": "success"},
                )
            ]
        )
    search_query = str(draft.get("search_query") or "").strip()
    if search_query:
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "search_other"),
                    callback_data=encode_callback("editor", "a", draft_id),
                ),
                InlineKeyboardButton(
                    get_text(lang, "search_change"),
                    switch_inline_query_current_chat=search_query[:120],
                ),
            ]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    get_text(lang, "ed_delete"),
                    callback_data=encode_callback("editor", "d", draft_id),
                    api_kwargs={"style": "danger"},
                )
            ],
            [
                InlineKeyboardButton(
                    get_text(lang, "back"),
                    callback_data=encode_callback("editor", "m", draft_id),
                )
            ],
        ]
    )
    return rows


def build_deleted_draft_keyboard(draft_id: str, *, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    get_text(lang, "ed_undo_delete"),
                    callback_data=encode_callback("editor", "du", draft_id),
                    api_kwargs={"style": "primary"},
                )
            ]
        ]
    )


def build_delete_confirmation_keyboard(
    draft_id: str, *, lang: str
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    get_text(lang, "ed_delete_confirm_button"),
                    callback_data=encode_callback("editor", "dc", draft_id),
                    api_kwargs={"style": "danger"},
                )
            ],
            [
                InlineKeyboardButton(
                    get_text(lang, "cancel"),
                    callback_data=encode_callback("editor", "b", draft_id),
                )
            ],
        ]
    )


def render_crate(
    items: list[dict],
    *,
    lang: str,
    selected_index: int | None = None,
    can_undo: bool = False,
    confirm_clear: bool = False,
) -> tuple[str, InlineKeyboardMarkup]:
    if confirm_clear:
        return get_text(lang, "crate_clear_confirm"), InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        get_text(lang, "crate_clear_confirm_button"),
                        callback_data=encode_callback("crate", "clear_confirm"),
                        api_kwargs={"style": "danger"},
                    )
                ],
                [
                    InlineKeyboardButton(
                        get_text(lang, "cancel"),
                        callback_data=encode_callback("crate", "clear_cancel"),
                    )
                ],
            ]
        )

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
    if items:
        selected_index = (
            selected_index
            if selected_index is not None and 0 <= selected_index < len(items)
            else 0
        )
        selectors = [
            InlineKeyboardButton(
                f"{'● ' if index == selected_index else ''}{index + 1}",
                callback_data=encode_callback("crate", "select", str(index)),
                **(
                    {"api_kwargs": {"style": "primary"}}
                    if index == selected_index
                    else {}
                ),
            )
            for index in range(len(items))
        ]
        rows.extend(
            selectors[index : index + 5] for index in range(0, len(selectors), 5)
        )

        controls: list[InlineKeyboardButton] = []
        if selected_index > 0:
            controls.append(
                InlineKeyboardButton(
                    get_text(lang, "crate_up"),
                    callback_data=encode_callback("crate", "up", str(selected_index)),
                )
            )
        if selected_index < len(items) - 1:
            controls.append(
                InlineKeyboardButton(
                    get_text(lang, "crate_down"),
                    callback_data=encode_callback("crate", "down", str(selected_index)),
                )
            )
        controls.append(
            InlineKeyboardButton(
                get_text(lang, "crate_remove"),
                callback_data=encode_callback("crate", "remove", str(selected_index)),
                api_kwargs={"style": "danger"},
            )
        )
        rows.append(controls)
        footer: list[InlineKeyboardButton] = []
        if can_undo:
            footer.append(
                InlineKeyboardButton(
                    get_text(lang, "crate_undo"),
                    callback_data=encode_callback("crate", "undo"),
                )
            )
        footer.append(
            InlineKeyboardButton(
                get_text(lang, "crate_clear"),
                callback_data=encode_callback("crate", "clear"),
                api_kwargs={"style": "danger"},
            )
        )
        rows.append(footer)
    else:
        if can_undo:
            rows.append(
                [
                    InlineKeyboardButton(
                        get_text(lang, "crate_undo"),
                        callback_data=encode_callback("crate", "undo"),
                        api_kwargs={"style": "primary"},
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "crate_find"),
                    switch_inline_query_current_chat="",
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
