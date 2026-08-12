from __future__ import annotations

from html import escape
import time
from telegram import InlineKeyboardMarkup

from music_links_bot.bot_builder import available_platforms, selected_platforms
from music_links_bot.bot_runtime import encode_callback
from music_links_bot.constants import PLATFORM_LABELS
from music_links_bot.i18n import get_text
from music_links_bot.models import TrackMatch
from music_links_bot.release_presentation import PRESET_ORDER, normalize_preset
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
    body_key = "home_body_new" if first_visit else "home_body"
    return get_text(lang, body_key).format(
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
    active_draft_label: str | None = None,
) -> InlineKeyboardMarkup:
    del bot_username, is_admin
    rows: list[list[InlineKeyboardButton]] = []
    create_button = InlineKeyboardButton(
        get_text(lang, "home_create"),
        callback_data=encode_callback("menu", "create"),
        api_kwargs={"style": "primary"},
    )
    rows.append([create_button])
    if active_draft_id:
        continue_text = (
            get_text(lang, "home_continue_named").format(release=active_draft_label)
            if active_draft_label
            else get_text(lang, "home_continue")
        )
        rows.append(
            [
                InlineKeyboardButton(
                    continue_text,
                    callback_data=encode_callback("editor", "b", active_draft_id),
                )
            ]
        )
    rows.append(
        [
            _crate_button(lang, crate_count),
            InlineKeyboardButton(
                get_text(lang, "home_recent"),
                callback_data=encode_callback("menu", "recent"),
            ),
        ]
    )
    if show_tour:
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "quick_tour"),
                    callback_data=encode_callback("menu", "onboard1"),
                )
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
                callback_data=encode_callback("menu", "create"),
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


def build_create_keyboard(*, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    get_text(lang, "error_platforms_button"),
                    callback_data=encode_callback("menu", "platforms"),
                )
            ],
            [
                InlineKeyboardButton(
                    get_text(lang, "home_back"),
                    callback_data=encode_callback("menu", "start"),
                )
            ],
        ]
    )


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
            callback_data=encode_callback("menu", "create"),
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
    return InlineKeyboardMarkup(rows)


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
                ),
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
    if draft.get("can_publish"):
        secondary = InlineKeyboardButton(
            get_text(lang, "ed_publish"),
            callback_data=encode_callback("editor", "p", draft_id),
            api_kwargs={"style": "success"},
        )
    else:
        secondary = button
    return [
        [
            InlineKeyboardButton(
                get_text(lang, "ed_edit"),
                callback_data=encode_callback("editor", "m", draft_id),
            ),
            secondary,
        ]
    ]


def editor_more_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    """Main builder screen: explicit destinations instead of hidden cycles."""
    lang = draft.get("lang") or "ru"
    preset = normalize_preset(draft.get("preset"), draft)
    custom_tags = draft.get("custom_tags")
    if isinstance(custom_tags, list) and custom_tags and draft.get("hashtags"):
        tags_label = get_text(lang, "ed_hashtags_custom").format(count=len(custom_tags))
    else:
        tags_label = get_text(
            lang,
            "ed_hashtags_auto" if draft.get("hashtags", True) else "ed_hashtags_none",
        )
    stored_platforms = draft.get("platforms")
    platform_count: int | str = (
        len(stored_platforms)
        if isinstance(stored_platforms, list)
        else get_text(lang, "ed_platforms_all_short")
    )
    platform_label = get_text(lang, "ed_platforms_selected").format(
        count=platform_count
    )
    return [
        [
            InlineKeyboardButton(
                get_text(lang, f"ed_preset_{preset}"),
                callback_data=encode_callback("editor", "zs", draft_id),
            ),
            InlineKeyboardButton(
                get_text(lang, "ed_text_on" if draft.get("quote") else "ed_text_off"),
                callback_data=encode_callback("editor", "ts", draft_id),
            ),
        ],
        [
            InlineKeyboardButton(
                tags_label,
                callback_data=encode_callback("editor", "hs", draft_id),
            ),
            InlineKeyboardButton(
                platform_label,
                callback_data=encode_callback("editor", "ls", draft_id),
            ),
        ],
        [
            InlineKeyboardButton(
                get_text(lang, "ed_done"),
                callback_data=encode_callback("editor", "f", draft_id),
                api_kwargs={"style": "primary"},
            ),
            InlineKeyboardButton(
                get_text(lang, "ed_more"),
                callback_data=encode_callback("editor", "o", draft_id),
                api_kwargs={"style": "success"},
            ),
        ],
    ]


def editor_style_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"
    selected = normalize_preset(draft.get("preset"), draft)
    rows = [
        [
            InlineKeyboardButton(
                ("✓ " if preset == selected else "")
                + get_text(lang, f"ed_preset_name_{preset}"),
                callback_data=encode_callback("editor", f"z{index}", draft_id),
                **({"api_kwargs": {"style": "primary"}} if preset == selected else {}),
            )
        ]
        for index, preset in enumerate(PRESET_ORDER)
    ]
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "back"),
                callback_data=encode_callback("editor", "m", draft_id),
            )
        ]
    )
    return append_setting_undo(rows, draft_id, draft)


def editor_platform_rows(
    draft_id: str,
    draft: dict,
    track: TrackMatch,
    platform_order: list[str],
) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"
    available = available_platforms(track, platform_order)
    selected = selected_platforms(draft, track, platform_order)
    buttons = [
        InlineKeyboardButton(
            ("✓ " if key in selected else "") + PLATFORM_LABELS[key],
            callback_data=encode_callback("editor", f"l{index}", draft_id),
            **({"api_kwargs": {"style": "primary"}} if key in selected else {}),
        )
        for index, key in enumerate(available)
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "ed_platforms_select_all"),
                callback_data=encode_callback("editor", "la", draft_id),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "back"),
                callback_data=encode_callback("editor", "m", draft_id),
            )
        ]
    )
    return append_setting_undo(rows, draft_id, draft)


def editor_intro_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"
    rows = [
        [
            InlineKeyboardButton(
                get_text(
                    lang, "ed_intro_change" if draft.get("quote") else "ed_intro_add"
                ),
                callback_data=encode_callback("editor", "ti", draft_id),
                api_kwargs={"style": "primary"},
            )
        ]
    ]
    if draft.get("quote"):
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "ed_intro_remove"),
                    callback_data=encode_callback("editor", "t0", draft_id),
                    api_kwargs={"style": "danger"},
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "back"),
                callback_data=encode_callback("editor", "m", draft_id),
            )
        ]
    )
    return append_setting_undo(rows, draft_id, draft)


def editor_hashtag_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"
    custom = bool(draft.get("hashtags")) and bool(draft.get("custom_tags"))
    auto = bool(draft.get("hashtags", True)) and not custom
    none = not draft.get("hashtags")
    rows = [
        [
            InlineKeyboardButton(
                ("✓ " if auto else "") + get_text(lang, "ed_tags_auto"),
                callback_data=encode_callback("editor", "ha", draft_id),
            )
        ],
        [
            InlineKeyboardButton(
                ("✓ " if custom else "") + get_text(lang, "ed_tags_custom"),
                callback_data=encode_callback("editor", "hi", draft_id),
                api_kwargs={"style": "primary"},
            )
        ],
        [
            InlineKeyboardButton(
                ("✓ " if none else "") + get_text(lang, "ed_tags_none"),
                callback_data=encode_callback("editor", "hn", draft_id),
            )
        ],
        [
            InlineKeyboardButton(
                get_text(lang, "back"),
                callback_data=encode_callback("editor", "m", draft_id),
            )
        ],
    ]
    return append_setting_undo(rows, draft_id, draft)


def editor_preview_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"
    rows = [
        [
            InlineKeyboardButton(
                get_text(lang, "ed_more"),
                callback_data=encode_callback("editor", "o", draft_id),
                api_kwargs={"style": "primary"},
            )
        ],
        [
            InlineKeyboardButton(
                get_text(lang, "back_to_editor"),
                callback_data=encode_callback("editor", "m", draft_id),
            )
        ],
    ]
    return rows


def editor_schedule_rows(
    draft_id: str, draft: dict
) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"
    return [
        [
            InlineKeyboardButton(
                get_text(lang, "schedule_1h"),
                callback_data=encode_callback("editor", "q1", draft_id),
            ),
            InlineKeyboardButton(
                get_text(lang, "schedule_evening"),
                callback_data=encode_callback("editor", "qe", draft_id),
            ),
        ],
        [
            InlineKeyboardButton(
                get_text(lang, "schedule_1d"),
                callback_data=encode_callback("editor", "qd", draft_id),
            )
        ],
        [
            InlineKeyboardButton(
                get_text(lang, "schedule_custom"),
                callback_data=encode_callback("editor", "qi", draft_id),
                api_kwargs={"style": "primary"},
            )
        ],
        [
            InlineKeyboardButton(
                get_text(lang, "back"),
                callback_data=encode_callback("editor", "o", draft_id),
            )
        ],
    ]


def append_setting_undo(
    rows: list[list[InlineKeyboardButton]], draft_id: str, draft: dict
) -> list[list[InlineKeyboardButton]]:
    state = draft.get("undo_state")
    if not isinstance(state, dict) or int(state.get("expires_at") or 0) < int(
        time.time()
    ):
        return rows
    lang = draft.get("lang") or "ru"
    insert_at = max(0, len(rows) - 1)
    rows.insert(
        insert_at,
        [
            InlineKeyboardButton(
                get_text(lang, "settings_undo"),
                callback_data=encode_callback("editor", "u", draft_id),
            )
        ],
    )
    return rows


def editor_overflow_rows(
    draft_id: str, draft: dict
) -> list[list[InlineKeyboardButton]]:
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
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "ed_schedule"),
                    callback_data=encode_callback("editor", "qs", draft_id),
                )
            ]
        )
        if draft.get("in_crate"):
            crate_action = _crate_button(lang, int(draft.get("crate_count") or 0))
        else:
            crate_action = InlineKeyboardButton(
                get_text(lang, "ed_add_crate"),
                callback_data=encode_callback("editor", "c", draft_id),
            )
        rows.append([crate_action])
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
    title: str = "",
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
        heading = (
            f"🧺 <b>{escape(title)} · {len(items)}/10</b>"
            if title
            else get_text(lang, "crate_title").replace("{count}", str(len(items)))
        )
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
            selectors[index : index + 2] for index in range(0, len(selectors), 2)
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
        if controls:
            rows.append(controls)
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "crate_remove"),
                    callback_data=encode_callback(
                        "crate", "remove", str(selected_index)
                    ),
                    api_kwargs={"style": "danger"},
                )
            ]
        )
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
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "crate_rename"),
                    callback_data=encode_callback("crate", "rename"),
                ),
                InlineKeyboardButton(
                    get_text(lang, "crate_preview"),
                    callback_data=encode_callback("crate", "preview"),
                    api_kwargs={"style": "primary"},
                ),
            ]
        )
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
                    callback_data=encode_callback("menu", "create"),
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
