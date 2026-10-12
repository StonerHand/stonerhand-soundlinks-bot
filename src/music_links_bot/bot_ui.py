from __future__ import annotations

import time
from html import escape

from telegram import InlineKeyboardMarkup

from music_links_bot.bot_builder import (
    available_platforms,
    schedule_timestamp,
    selected_platforms,
)
from music_links_bot.bot_runtime import encode_callback
from music_links_bot.constants import (
    DRAFT_SHARE_PREFIX,
    INLINE_EXAMPLE_QUERY,
    PLATFORM_LABELS,
)
from music_links_bot.human_time import human_datetime
from music_links_bot.i18n import get_text
from music_links_bot.models import TrackMatch
from music_links_bot.release_presentation import normalize_preset
from music_links_bot.telegram_buttons import (
    ButtonIcon,
    ButtonTone,
    button as InlineKeyboardButton,
    callback_button,
    current_chat_button,
    disabled_button,
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
    summary: str = "",
) -> str:
    safe_name = escape(first_name.strip()[:40])
    greeting = get_text(lang, "home_title_new" if first_visit else "home_title")
    if safe_name and not first_visit:
        greeting = greeting.replace("{name}", f", {safe_name}")
    else:
        greeting = greeting.replace("{name}", "")
    mode = get_text(lang, "home_mode_admin" if is_admin else "home_mode_user")
    body_key = "home_body_new" if first_visit else "home_body"
    text = get_text(lang, body_key).format(
        greeting=greeting,
        crate_count=max(0, min(10, crate_count)),
        mode=mode,
    )
    if summary and not first_visit:
        # The owner's dashboard line sits right under the greeting.
        head, _, rest = text.partition("\n\n")
        text = f"{head}\n{summary}\n\n{rest}" if rest else f"{head}\n{summary}"
    return text


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
    queue_count: int = 0,
    first_visit: bool = False,
) -> InlineKeyboardMarkup:
    """Home: only what is relevant right now — the bot already waits for a link."""
    del bot_username, is_admin
    rows = []
    if first_visit:
        rows.append(
            [
                callback_button(
                    get_text(lang, "home_create"),
                    encode_callback("menu", "create"),
                    tone=ButtonTone.PRIMARY,
                )
            ]
        )
    if active_draft_id:
        label = (
            get_text(lang, "home_continue_named").format(release=active_draft_label)
            if active_draft_label
            else get_text(lang, "home_continue")
        )
        rows.append(
            [
                callback_button(
                    label,
                    encode_callback("editor", "b", active_draft_id),
                    tone=None if first_visit else ButtonTone.PRIMARY,
                )
            ]
        )
    status_row = []
    if crate_count:
        status_row.append(_crate_button(lang, crate_count))
    if queue_count:
        status_row.append(
            callback_button(
                get_text(lang, "home_queue").format(count=queue_count),
                encode_callback("queue", "open"),
            )
        )
    if status_row:
        rows.append(status_row)
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
    if show_tour:
        rows.append(
            [
                callback_button(
                    get_text(lang, "quick_tour"), encode_callback("menu", "onboard1")
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


HELP_TOPICS = ("help", "guide", "platforms")


def build_section_keyboard(
    bot_username: str | None,
    *,
    lang: str,
    crate_count: int = 0,
    active: str | None = None,
) -> InlineKeyboardMarkup:
    """Help is one place with three topics; each topic links to the other two."""
    del bot_username, crate_count
    rows = []
    if active in {*HELP_TOPICS, "more", "demo"}:
        rows.extend(
            [
                InlineKeyboardButton(
                    get_text(lang, f"tab_{topic}"),
                    callback_data=encode_callback("menu", topic),
                )
            ]
            for topic in HELP_TOPICS
            if topic != active
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


def build_publish_success_keyboard(
    draft_id: str, *, lang: str, link: str | None = None
) -> InlineKeyboardMarkup:
    """After publishing: open it, share it, undo it (2 minutes) or start anew."""
    rows: list[list[InlineKeyboardButton]] = []
    if link:
        rows.append(
            [
                InlineKeyboardButton(
                    get_text(lang, "ed_open_publication"), url=link, style="success"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "share_post"),
                switch_inline_query=draft_share_query(draft_id),
            ),
            InlineKeyboardButton(
                get_text(lang, "unpublish"),
                callback_data=encode_callback("editor", "un", draft_id),
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                get_text(lang, "ed_create_more"),
                callback_data=encode_callback("menu", "create"),
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
                )
            ],
            [
                callback_button(
                    get_text(lang, "ed_send_self_copy"),
                    encode_callback("editor", "s", draft_id),
                )
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


def editor_rows(
    draft_id: str, draft: dict, *, settings: bool = False
) -> list[list[InlineKeyboardButton]]:
    """The card shows the finished post; frequent actions are one tap away."""
    lang = draft.get("lang") or "ru"

    def cb(key, action, **kwargs):
        return callback_button(
            get_text(lang, key), encode_callback("editor", action, draft_id), **kwargs
        )

    if not settings:
        collection_button = (
            callback_button(
                get_text(lang, "ed_crate_count").format(
                    count=draft.get("crate_count", 0)
                ),
                encode_callback("crate", "open"),
            )
            if draft.get("in_crate")
            else cb("ed_add_crate", "c")
        )
        save_button = cb("ed_saved" if draft.get("saved_at") else "ed_save", "sv")
        rows = [[cb("ed_edit_post", "m"), collection_button]]
        if draft.get("can_publish"):
            share_button = _draft_share_button(draft_id, lang)
            rows.append([button for button in (share_button, save_button) if button])
            rows.append([cb("ed_publish_menu", "p", tone=ButtonTone.PRIMARY)])
        else:
            # Without a channel, sharing to a chat is the main way to send.
            share_button = _draft_share_button(draft_id, lang, primary=True)
            rows.append([cb("ed_send_self_short", "s"), save_button])
            if share_button is not None:
                rows.append([share_button])
        return rows
    rows = [[cb("ed_quick_text", "ti"), cb("ed_quick_tags", "hs")]]
    if not draft.get("source_audio_file_id"):
        rows.append([cb("ed_quick_look", "ap"), cb("ed_quick_buttons", "ls")])
    rows.append([cb("ed_quick_more", "tools")])
    rows.append([cb("ed_done_editing", "b", tone=ButtonTone.PRIMARY)])
    return append_setting_undo(rows, draft_id, draft)


def draft_share_query(draft_id: str) -> str:
    """Inline query that shares this exact edited post, not a fresh lookup."""
    return f"{DRAFT_SHARE_PREFIX}{draft_id}"


def _draft_share_button(
    draft_id: str, lang: str, *, primary: bool = False
) -> InlineKeyboardButton | None:
    if not draft_id:
        return None
    return InlineKeyboardButton(
        get_text(lang, "share_post"),
        switch_inline_query=draft_share_query(draft_id),
        style="primary" if primary else None,
    )


def _back_to_editor(draft_id: str, lang: str) -> list[InlineKeyboardButton]:
    return [
        callback_button(
            get_text(lang, "ed_back_editor"), encode_callback("editor", "m", draft_id)
        )
    ]


def editor_more_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    """Keep old settings callbacks compatible with the single editor."""
    return editor_rows(draft_id, draft, settings=True)


def editor_appearance_rows(
    draft_id: str, draft: dict
) -> list[list[InlineKeyboardButton]]:
    """One "Вид" screen: cover or story layout, plus an optional own cover."""
    lang = draft.get("lang") or "ru"

    def cb(key, action, *, selected=False):
        if selected:
            return disabled_button("✓ " + get_text(lang, key))
        return callback_button(
            get_text(lang, key), encode_callback("editor", action, draft_id)
        )

    preset = normalize_preset(draft.get("preset"), draft)
    custom = bool(draft.get("custom_cover_file_id"))
    rows = [
        [cb("ed_look_cover", "z1", selected=preset != "longread")],
        [cb("ed_look_story", "z2", selected=preset == "longread")],
    ]
    if (
        not draft.get("source_audio_file_id")
        and draft.get("item", {}).get("kind") != "video"
    ):
        rows.append([cb("ed_cover_upload", "ci", selected=custom)])
        if custom:
            rows.append([cb("ed_cover_reset", "cr")])
    rows.append(_back_to_editor(draft_id, lang))
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
            ("ed_back_editor", "m"),
        )
    ]


def editor_tools_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    """Rare actions only: everything frequent already sits on the card or editor."""
    from music_links_bot.release_panel import copy_link_button

    lang = draft.get("lang") or "ru"

    def cb(key, action, **kwargs):
        return callback_button(
            get_text(lang, key), encode_callback("editor", action, draft_id), **kwargs
        )

    first = [cb("ed_templates", "tp")]
    if draft.get("item"):
        link = copy_link_button(TrackMatch(**draft["item"]), lang=lang)
        if link is not None:
            first.append(link)
    rows = [first]
    query = str(draft.get("search_query") or "").strip()
    if query:
        rows.append(
            [
                cb("search_other", "a"),
                current_chat_button(get_text(lang, "search_change"), query[:120]),
            ]
        )
    rows.append(
        [cb("ed_reset_original", "reset"), cb("ed_delete", "d", tone=ButtonTone.DANGER)]
    )
    rows.append(_back_to_editor(draft_id, lang))
    return rows


def editor_template_rows(
    draft_id: str, draft: dict, presets: list[dict]
) -> list[list[InlineKeyboardButton]]:
    lang = draft.get("lang") or "ru"
    rows: list[list[InlineKeyboardButton]] = []
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
    rows.append(_back_to_editor(draft_id, lang))
    return rows


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
    rows.append(_back_to_editor(draft_id, lang))
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
    rows.append(_back_to_editor(draft_id, lang))
    return append_setting_undo(rows, draft_id, draft)


def editor_hashtag_rows(draft_id: str, draft: dict) -> list[list[InlineKeyboardButton]]:
    """Every tag control on one screen: toggles, own tags, auto/none and pin."""
    from music_links_bot.bot_release_settings import tag_choices, tag_code
    from music_links_bot.publication_view import resolve_draft_hashtags
    from music_links_bot.release_preferences import (
        current_presentation,
        release_preference_key,
    )

    track = TrackMatch(**draft["item"])
    lang = draft.get("lang") or "ru"
    selected = (resolve_draft_hashtags(draft, track) or "").split()
    saved = current_presentation.get().tags.get(release_preference_key(track))

    def cb(key, action):
        return callback_button(
            get_text(lang, key), encode_callback("editor", action, draft_id)
        )

    buttons = [
        callback_button(
            ("✓ " if tag in selected else "") + tag,
            encode_callback("editor", tag_code(tag), draft_id),
        )
        for tag in tag_choices(draft, track)
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([cb("ed_tags_custom", "hi"), cb("ed_why_tags", "why_tags")])
    reset = (
        cb("ed_tags_auto", "ha")
        if "custom_tags" in draft or not draft.get("hashtags", True)
        else cb("ed_tags_none", "hn")
        if selected
        else None
    )
    pin = (
        callback_button(
            "✓ " + get_text(lang, "ed_tags_pinned"),
            encode_callback("editor", "hr", draft_id),
        )
        if saved is not None and saved == selected
        else cb("ed_tags_pin", "hp")
        if selected
        else None
    )
    extra = [button for button in (pin, reset) if button is not None]
    if extra:
        rows.append(extra)
    rows.append(_back_to_editor(draft_id, lang))
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
        label = "🕒 " + human_datetime(
            timestamp, timezone_name=timezone_name, lang=lang, now=_now_value(now)
        )
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


def _now_value(now) -> float | None:
    if now is None:
        return None
    return now.timestamp() if hasattr(now, "timestamp") else float(now)


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
    can_publish: bool = False,
    screen: str = "main",
) -> tuple[str, InlineKeyboardMarkup]:
    """The collection: items, one clear main action, rare actions one tap away."""
    from music_links_bot.bot_crate import crate_item_key, crate_revision

    def cb(key, action, payload="", **kwargs):
        return InlineKeyboardButton(
            get_text(lang, key),
            callback_data=encode_callback("crate", action, payload),
            **kwargs,
        )

    back_to_crate = [cb("crate_back", "open")]
    if confirm_clear:
        return get_text(lang, "crate_clear_confirm"), InlineKeyboardMarkup(
            [
                [
                    cb(
                        "crate_clear_confirm_button",
                        "clear_confirm",
                        crate_revision(items),
                        style="danger",
                    )
                ],
                [cb("cancel", "clear_cancel")],
            ]
        )
    if screen == "style" and items:
        return get_text(lang, "crate_style_title"), InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        get_text(lang, "crate_layout"),
                        callback_data=encode_callback("prefs", "layout", "crate"),
                    )
                ],
                [
                    InlineKeyboardButton(
                        get_text(lang, "crate_grouping"),
                        callback_data=encode_callback("prefs", "grouping", "crate"),
                    )
                ],
                back_to_crate,
            ]
        )
    if screen == "more" and items:
        return get_text(lang, "crate_more_title"), InlineKeyboardMarkup(
            [
                [cb("crate_preview", "preview")],
                [cb("crate_clear", "clear", style="danger")],
                back_to_crate,
            ]
        )

    blocking: list[int] = []
    if not items:
        text = get_text(lang, "crate_empty")
    else:
        heading = (
            f"🎶 <b>{escape(title)} · {len(items)}/10</b>"
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
        from music_links_bot.collection_plan import (
            collection_check_text,
            collection_issues,
        )

        lines.extend(["", collection_check_text(items, lang)])
        if selected_index is None:
            lines.extend(["", get_text(lang, "crate_hint")])
        blocking = sorted(
            {issue.index for issue in collection_issues(items) if issue.blocking}
        )
        text = "\n".join(lines)

    rows: list[list[InlineKeyboardButton]] = [[cb("crate_add_links", "add")]]
    if items:
        selected_index = (
            selected_index
            if selected_index is not None and 0 <= selected_index < len(items)
            else None
        )
        rows.extend(
            [
                InlineKeyboardButton(
                    _crate_item_button_label(
                        entry, index, selected=index == selected_index
                    ),
                    callback_data=encode_callback(
                        "crate", "select", crate_item_key(entry)
                    ),
                )
            ]
            for index, entry in enumerate(items)
        )
        if selected_index is not None:
            key = crate_item_key(items[selected_index])
            controls: list[InlineKeyboardButton] = []
            if selected_index > 0:
                controls.append(cb("crate_up", "up", key))
            if selected_index < len(items) - 1:
                controls.append(cb("crate_down", "down", key))
            if controls:
                rows.append(controls)
            rows.append(
                [
                    cb("crate_remove", "remove", key, style="danger"),
                    cb("crate_replace", "replace", key),
                ]
            )
            from music_links_bot.release_preferences import release_preference_key

            selected_key = release_preference_key(
                TrackMatch(**{"links": {}, **items[selected_index]["item"]})
            )
            rows.append(
                [
                    cb("crate_note", "note", selected_key),
                    cb("crate_section", "section", selected_key),
                ]
            )
        if can_undo:
            rows.append([cb("crate_undo", "undo")])
        rows.append([cb("crate_style", "style"), cb("crate_rename", "rename")])
        if blocking:
            first = items[blocking[0] - 1]
            rows.append(
                [
                    InlineKeyboardButton(
                        get_text(lang, "crate_fix").format(
                            items=", ".join(f"№{index}" for index in blocking)
                        ),
                        callback_data=encode_callback(
                            "crate", "select", crate_item_key(first)
                        ),
                        style="primary",
                    )
                ]
            )
        elif can_publish:
            rows.append(
                [
                    cb(
                        "crate_publish",
                        "publish",
                        crate_revision(items),
                        style="primary",
                    )
                ]
            )
            if share_query:
                rows.append(
                    [
                        InlineKeyboardButton(
                            get_text(lang, "crate_share"),
                            switch_inline_query=share_query,
                        )
                    ]
                )
        elif share_query:
            rows.append(
                [
                    InlineKeyboardButton(
                        get_text(lang, "crate_share"),
                        switch_inline_query=share_query,
                        style="primary",
                    )
                ]
            )
        rows.append([cb("crate_more", "more")])
    else:
        if can_undo:
            rows.append([cb("crate_undo", "undo", style="primary")])
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


def version_editor_keyboard(keyboard, draft):
    if keyboard is None or "revision" not in draft:
        return keyboard
    from telegram import InlineKeyboardButton as TelegramButton

    rows = []
    for row in keyboard.inline_keyboard:
        values = []
        for item in row:
            data = item.to_dict()
            callback = data.get("callback_data")
            if isinstance(callback, str) and callback.startswith("v2|editor|"):
                data["callback_data"] = (
                    callback.split("~", 1)[0] + "~" + str(draft["revision"])
                )
                if len(data["callback_data"].encode()) > 64:
                    raise ValueError("Versioned editor callback exceeds Telegram limit")
            values.append(TelegramButton.de_json(data, None))
        rows.append(values)
    return InlineKeyboardMarkup(rows)
