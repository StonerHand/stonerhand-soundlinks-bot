from __future__ import annotations

import time
from html import escape

from telegram import InlineKeyboardMarkup

from music_links_bot.bot_builder import (
    available_platforms,
    format_schedule_datetime,
    schedule_timestamp,
    selected_platforms,
)
from music_links_bot.bot_runtime import encode_callback
from music_links_bot.constants import INLINE_EXAMPLE_QUERY, PLATFORM_LABELS
from music_links_bot.i18n import get_text
from music_links_bot.models import TrackMatch
from music_links_bot.release_presentation import PRESET_ORDER, normalize_preset
from music_links_bot.telegram_buttons import (
    ButtonIcon,
    ButtonTone,
    button as InlineKeyboardButton,
    callback_button,
    current_chat_button,
)


def _crate_button(lang: str, crate_count: int) -> InlineKeyboardButton:
    """Make a non-empty collection visible without adding another menu row."""
    safe_count = max(0, min(10, crate_count))
    return InlineKeyboardButton(
        get_text(lang, "home_crate").format(count=safe_count),
        callback_data=encode_callback("crate", "open"),
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
    show_example: bool = False,
    active_draft_id: str | None = None,
    active_draft_label: str | None = None,
) -> InlineKeyboardMarkup:
    del bot_username, crate_count
    rows = [
        [
            callback_button(
                get_text(lang, "home_create"),
                encode_callback("menu", "create"),
                tone=ButtonTone.PRIMARY,
            )
        ]
    ]
    if active_draft_id:
        label = (
            get_text(lang, "home_continue_named").format(release=active_draft_label)
            if active_draft_label
            else get_text(lang, "home_continue")
        )
        rows.append(
            [callback_button(label, encode_callback("editor", "b", active_draft_id))]
        )
    if show_example:
        rows.append(
            [
                current_chat_button(
                    get_text(lang, "home_try_example"), INLINE_EXAMPLE_QUERY
                )
            ]
        )
    rows.append(
        [
            callback_button(
                get_text(lang, "home_library"), encode_callback("menu", "library")
            ),
            callback_button(
                get_text(lang, "home_more"), encode_callback("prefs", "open")
            ),
        ]
    )
    if is_admin:
        rows.append(
            [
                callback_button(
                    get_text(lang, "home_queue"), encode_callback("queue", "open")
                )
            ]
        )
    if show_tour:
        rows.append(
            [
                callback_button(
                    get_text(lang, "quick_tour"), encode_callback("menu", "onboard1")
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def build_library_keyboard(*, lang: str, crate_count: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                callback_button(
                    get_text(lang, "home_drafts"), encode_callback("menu", "drafts")
                )
            ],
            [_crate_button(lang, crate_count)],
            [
                callback_button(
                    get_text(lang, "home_recent"), encode_callback("menu", "recent")
                )
            ],
            [
                callback_button(
                    get_text(lang, "home_back"), encode_callback("menu", "start")
                )
            ],
        ]
    )


def build_section_keyboard(
    bot_username: str | None,
    *,
    lang: str,
    crate_count: int = 0,
    active: str | None = None,
) -> InlineKeyboardMarkup:
    del bot_username, crate_count
    rows = []
    if active in {"help", "more", "guide", "platforms", "demo"}:
        rows.extend(
            [
                InlineKeyboardButton(
                    get_text(
                        lang,
                        "quick_tour" if action == "onboard1" else f"tab_{action}",
                    ),
                    callback_data=encode_callback("menu", action),
                )
                for action in pair
                if action != active
            ]
            for pair in (("guide", "platforms"), ("demo", "onboard1"))
        )
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "home_back"),
                callback_data=encode_callback("menu", "start"),
            )
        ]
    )
    return InlineKeyboardMarkup([row for row in rows if row])


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


def build_privacy_keyboard(*, lang: str, confirm: bool = False) -> InlineKeyboardMarkup:
    primary = callback_button(
        get_text(lang, "privacy_delete_confirm" if confirm else "privacy_delete"),
        encode_callback("privacy", "delete" if confirm else "confirm"),
        tone=ButtonTone.DANGER if confirm else None,
    )
    return InlineKeyboardMarkup(
        [
            [primary],
            [
                callback_button(
                    get_text(lang, "home_back"),
                    encode_callback("menu", "start"),
                )
            ],
        ]
    )


def build_delivery_success_keyboard(
    *, lang: str, share_query: str | None = None
) -> InlineKeyboardMarkup:
    """Render the terminal delivery state with one clear next action."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                get_text(lang, "ed_create_more"),
                callback_data=encode_callback("menu", "create"),
                style="primary",
            )
        ]
    ]
    if share_query:
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "share_post"),
                    switch_inline_query=share_query,
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
    recovery: str | None = None,
) -> InlineKeyboardMarkup:
    """Keep errors calm: one contextual recovery action and one way home."""
    del bot_username, source_url
    recovery = recovery or ("retry" if retryable else "search")
    if recovery == "retry":
        primary = InlineKeyboardButton(
            get_text(lang, "retry"),
            callback_data=encode_callback("retry", "last"),
            style="primary",
        )
    elif recovery == "platforms":
        primary = InlineKeyboardButton(
            get_text(lang, "error_platforms_button"),
            callback_data=encode_callback("menu", "platforms"),
            style="primary",
        )
    elif recovery == "crate":
        primary = InlineKeyboardButton(
            get_text(lang, "error_back_crate"),
            callback_data=encode_callback("crate", "open"),
            style="primary",
        )
    elif recovery == "change":
        if search_query:
            primary = InlineKeyboardButton(
                get_text(lang, "search_change"),
                switch_inline_query_current_chat=search_query[:120],
                style="primary",
            )
        else:
            primary = InlineKeyboardButton(
                get_text(lang, "search_change"),
                callback_data=encode_callback("menu", "create"),
                style="primary",
            )
    else:
        primary = InlineKeyboardButton(
            get_text(lang, "quick_search"),
            callback_data=encode_callback("menu", "create"),
            style="primary",
        )
    rows = [[primary]]
    if recovery == "change":
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "error_send_link"),
                    callback_data=encode_callback("menu", "create"),
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
                    icon=ButtonIcon.READY,
                )
            ],
            [
                callback_button(
                    get_text(lang, "ed_schedule"),
                    encode_callback("editor", "qs", draft_id),
                ),
                callback_button(
                    get_text(lang, "ed_send_self"),
                    encode_callback("editor", "s", draft_id),
                ),
            ],
            [
                callback_button(
                    get_text(lang, "ed_back_card"),
                    encode_callback("editor", "b", draft_id),
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
                style="primary",
            )
        ]
    ]
    if isinstance(record.get("message_id"), int):
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "duplicate_replace"),
                    callback_data=encode_callback("editor", "x", draft_id),
                    style="danger",
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
                style="primary",
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
                    icon=ButtonIcon.READY,
                    style="success",
                ),
            ]
        )
    return InlineKeyboardMarkup(rows)


def editor_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    """The card is the editor; frequent changes require one tap."""
    lang = draft.get("lang") or "ru"

    def cb(key, action, **kwargs):
        return callback_button(
            get_text(lang, key), encode_callback("editor", action, draft_id), **kwargs
        )

    rows = [[cb("ed_quick_text", "ti"), cb("ed_quick_tags", "hs")]]
    if not draft.get("source_audio_file_id"):
        media = []
        if draft.get("item", {}).get("kind") != "video":
            media.append(cb("ed_quick_cover", "ap"))
        media.append(cb("ed_quick_buttons", "ls"))
        rows.append(media)
    rows.append([cb("ed_clean_preview", "pv"), cb("ed_quick_more", "tools")])
    rows.append(
        [
            cb(
                "ed_publish_menu" if draft.get("can_publish") else "ed_send_menu",
                "p" if draft.get("can_publish") else "o",
                tone=ButtonTone.PRIMARY,
            )
        ]
    )
    return append_setting_undo(rows, draft_id, draft)


def editor_more_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    """Keep old settings callbacks compatible with the single editor."""
    return editor_rows(draft_id, draft)


def editor_appearance_rows(
    draft_id: str, draft: dict
) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"

    def cb(key, action, *, selected=False):
        return callback_button(
            ("✓ " if selected else "") + get_text(lang, key),
            encode_callback("editor", action, draft_id),
        )

    rows = []
    custom = bool(draft.get("custom_cover_file_id"))
    if (
        not draft.get("source_audio_file_id")
        and draft.get("item", {}).get("kind") != "video"
    ):
        if draft.get("item", {}).get("thumbnail_url"):
            rows.append(
                [
                    cb(
                        "ed_artwork_clean",
                        "ca",
                        selected=bool(draft.get("as_photo")) and not custom,
                    )
                ]
            )
        rows.append(
            [
                cb(
                    "ed_artwork_native",
                    "cn",
                    selected=not draft.get("as_photo") and not custom,
                )
            ]
        )
        rows.append([cb("ed_cover_upload", "ci", selected=custom)])
    rows.append([cb("ed_back_card", "b")])
    return append_setting_undo(rows, draft_id, draft)


def editor_text_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"
    custom_tags = draft.get("custom_tags")
    tags_label = (
        get_text(lang, "ed_hashtags_custom").format(count=len(custom_tags))
        if draft.get("hashtags") and isinstance(custom_tags, list) and custom_tags
        else get_text(
            lang,
            "ed_hashtags_auto" if draft.get("hashtags", True) else "ed_hashtags_none",
        )
    )
    return [
        [
            InlineKeyboardButton(
                tags_label if key == "tags" else get_text(lang, key),
                callback_data=encode_callback("editor", action, draft_id),
            )
        ]
        for key, action in (
            ("ed_text_on" if draft.get("quote") else "ed_text_off", "ts"),
            ("tags", "hs"),
            ("back", "m"),
        )
    ]


def editor_tools_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"

    def cb(key, action, **kwargs):
        return callback_button(
            get_text(lang, key), encode_callback("editor", action, draft_id), **kwargs
        )

    rows = []
    if draft.get("in_crate"):
        rows.append(
            [
                callback_button(
                    get_text(lang, "ed_crate_count").format(
                        count=max(0, min(10, int(draft.get("crate_count") or 0)))
                    ),
                    encode_callback("crate", "open"),
                )
            ]
        )
    else:
        rows.append([cb("ed_add_crate", "c")])
    rows.append([cb("ed_templates", "tp"), cb("ed_style_short", "zs")])
    rows.append([cb("ed_delivery_settings", "rs")])
    query = str(draft.get("search_query") or "").strip()
    if query:
        rows.append(
            [
                cb("search_other", "a"),
                current_chat_button(get_text(lang, "search_change"), query[:120]),
            ]
        )
    if draft.get("quote"):
        rows.append([cb("ed_intro_remove", "t0")])
    rows.append([cb("ed_delete", "d", tone=ButtonTone.DANGER)])
    rows.append(
        [
            cb("ed_back_card", "b"),
            callback_button(
                get_text(lang, "home_back"), encode_callback("menu", "start")
            ),
        ]
    )
    return rows


def editor_delivery_rows(
    draft_id: str, draft: dict
) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"
    selected = draft.get("delivery_mode", "auto")
    rows = [
        [
            callback_button(
                ("✓ " if selected == value else "") + get_text(lang, key),
                encode_callback("editor", action, draft_id),
            )
        ]
        for value, key, action in (
            ("auto", "ed_delivery_auto_name", "ra"),
            ("classic", "ed_delivery_classic_name", "rc"),
        )
    ]
    rows.append(
        [
            callback_button(
                get_text(lang, "ed_back_card"), encode_callback("editor", "b", draft_id)
            )
        ]
    )
    return append_setting_undo(rows, draft_id, draft)


def editor_template_rows(
    draft_id: str, draft: dict, presets: list[dict]
) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"
    rows: list[list[InlineKeyboardButton]] = []
    if draft.get("last_template_available"):
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "ed_last_template"),
                    callback_data=encode_callback("editor", "lp", draft_id),
                )
            ]
        )
    for index, item in enumerate(presets[:8]):
        name = str(item.get("name") or get_text(lang, "ed_template_unnamed"))
        rows.append(
            [
                InlineKeyboardButton(
                    name,
                    callback_data=encode_callback("editor", f"ta{index}", draft_id),
                ),
                InlineKeyboardButton(
                    get_text(lang, "ed_template_delete"),
                    callback_data=encode_callback("editor", f"td{index}", draft_id),
                    style="danger",
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "ed_template_save"),
                callback_data=encode_callback("editor", "tn", draft_id),
                style="primary",
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
    return rows


def editor_style_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"
    selected = normalize_preset(draft.get("preset"), draft)
    rows = [
        [
            InlineKeyboardButton(
                ("✓ " if preset == selected else "")
                + get_text(lang, f"ed_preset_name_{preset}"),
                callback_data=encode_callback("editor", f"z{index}", draft_id),
            )
        ]
        for index, preset in enumerate(PRESET_ORDER)
    ]
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "back"),
                callback_data=encode_callback("editor", "ap", draft_id),
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
                style="primary",
            )
        ]
    ]
    if draft.get("quote"):
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "ed_intro_remove"),
                    callback_data=encode_callback("editor", "t0", draft_id),
                    style="danger",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "back"),
                callback_data=encode_callback("editor", "tx", draft_id),
            )
        ]
    )
    return append_setting_undo(rows, draft_id, draft)


def editor_hashtag_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    from music_links_bot.bot_release_settings import tag_choices, tag_code
    from music_links_bot.publication_view import resolve_draft_hashtags

    track = TrackMatch(**draft["item"])
    lang = draft.get("lang") or "ru"
    selected = (resolve_draft_hashtags(draft, track) or "").split()
    buttons = [
        callback_button(
            ("✓ " if tag in selected else "") + tag,
            encode_callback("editor", tag_code(tag), draft_id),
        )
        for tag in tag_choices(draft, track)
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append(
        [
            callback_button(
                get_text(lang, "ed_tags_custom"),
                encode_callback("editor", "hi", draft_id),
            ),
            callback_button(
                get_text(lang, "ed_tag_options"),
                encode_callback("editor", "ht", draft_id),
            ),
        ]
    )
    rows.append(
        [
            callback_button(
                get_text(lang, "ed_back_card"), encode_callback("editor", "b", draft_id)
            )
        ]
    )
    return append_setting_undo(rows, draft_id, draft)


def editor_tag_options_rows(
    draft_id: str, draft: dict
) -> list[list[InlineKeyboardButton]]:
    from music_links_bot.publication_view import resolve_draft_hashtags
    from music_links_bot.release_preferences import (
        current_presentation,
        release_preference_key,
    )

    lang = draft.get("lang") or "ru"
    track = TrackMatch(**draft["item"])
    selected = (resolve_draft_hashtags(draft, track) or "").split()
    saved = current_presentation.get().tags.get(release_preference_key(track))

    def cb(key, action):
        return callback_button(
            get_text(lang, key), encode_callback("editor", action, draft_id)
        )

    rows = []
    if "custom_tags" in draft or not draft.get("hashtags", True):
        rows.append([cb("ed_tags_auto", "ha")])
    if selected:
        rows.append([cb("ed_tags_none", "hn")])
    if saved != selected:
        rows.append([cb("ed_tags_pin", "hp")])
    if saved is not None:
        rows.append([cb("ed_tags_reset", "hr")])
    rows.append([cb("ed_back_tags", "hs")])
    return append_setting_undo(rows, draft_id, draft)


def editor_schedule_rows(
    draft_id: str, draft: dict, *, timezone_name: str = "Europe/Moscow", now=None
) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"
    rows = []
    seen: set[int] = set()
    for action in ("q1", "qe", "qd"):
        timestamp = schedule_timestamp(action, timezone_name=timezone_name, now=now)
        if timestamp in seen:
            continue
        seen.add(timestamp)
        # The callback carries the exact displayed instant. An old keyboard
        # must never silently schedule a different day.
        label = format_schedule_datetime(timestamp, timezone_name=timezone_name)
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=encode_callback(
                        "editor", "qt", f"{draft_id}:{timestamp}"
                    ),
                )
            ]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    get_text(lang, "schedule_custom"),
                    callback_data=encode_callback("editor", "qi", draft_id),
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    get_text(lang, "ed_back_card"),
                    callback_data=encode_callback("editor", "b", draft_id),
                )
            ],
        ]
    )
    return rows


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
    """Delivery destinations for users without channel publishing rights."""
    lang = draft.get("lang") or "ru"
    rows = [
        [
            callback_button(
                get_text(lang, "ed_send_self"),
                encode_callback("editor", "s", draft_id),
                tone=ButtonTone.PRIMARY,
            )
        ]
    ]
    if draft.get("can_publish"):
        rows.append(
            [
                callback_button(
                    get_text(lang, "ed_publish_menu"),
                    encode_callback("editor", "p", draft_id),
                )
            ]
        )
    rows.append(
        [
            callback_button(
                get_text(lang, "ed_back_card"), encode_callback("editor", "b", draft_id)
            )
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
                    style="primary",
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
                    style="danger",
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


def _crate_item_button_label(entry: dict, index: int, *, selected: bool) -> str:
    item = entry.get("item") if isinstance(entry, dict) else None
    item = item if isinstance(item, dict) else {}
    artist = " ".join(str(item.get("artist") or "—").split())
    title = " ".join(str(item.get("title") or "—").split())
    prefix = "✓ " if selected else ""
    label = f"{prefix}{index + 1} · {artist} — {title}"
    return label if len(label) <= 52 else label[:51].rstrip() + "…"


def render_crate(
    items: list[dict],
    *,
    lang: str,
    selected_index: int | None = None,
    can_undo: bool = False,
    confirm_clear: bool = False,
    title: str = "",
    share_query: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    if confirm_clear:
        return get_text(lang, "crate_clear_confirm"), InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        get_text(lang, "crate_clear_confirm_button"),
                        callback_data=encode_callback("crate", "clear_confirm"),
                        style="danger",
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
                _crate_item_button_label(
                    entry, index, selected=index == selected_index
                ),
                callback_data=encode_callback("crate", "select", str(index)),
            )
            for index, entry in enumerate(items)
        ]
        rows.extend([button] for button in selectors)

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
                    style="danger",
                )
            ]
        )
        from music_links_bot.release_preferences import release_preference_key

        selected_key = release_preference_key(
            TrackMatch(**{"links": {}, **items[selected_index]["item"]})
        )
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "crate_note"),
                    callback_data=encode_callback("crate", "note", selected_key),
                ),
                InlineKeyboardButton(
                    get_text(lang, "crate_section"),
                    callback_data=encode_callback("crate", "section", selected_key),
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "crate_layout"),
                    callback_data=encode_callback("prefs", "layout", "crate"),
                ),
                InlineKeyboardButton(
                    get_text(lang, "crate_grouping"),
                    callback_data=encode_callback("prefs", "grouping", "crate"),
                ),
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
                style="danger",
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
                    style="primary",
                ),
            ]
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
    else:
        if can_undo:
            rows.append(
                [
                    InlineKeyboardButton(
                        get_text(lang, "crate_undo"),
                        callback_data=encode_callback("crate", "undo"),
                        style="primary",
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "crate_find"),
                    callback_data=encode_callback("menu", "create"),
                    style="primary",
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
