"""The collection screens: the list itself, its style and "more" menus."""

from __future__ import annotations

from html import escape

from telegram import InlineKeyboardMarkup

from music_links_bot.core.i18n import get_text
from music_links_bot.core.models import TrackMatch
from music_links_bot.state.bot_crate import crate_item_key, crate_revision
from music_links_bot.state.bot_runtime import encode_callback
from music_links_bot.tg.telegram_buttons import button

Rows = list[list]


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
    cb = _crate_button(lang)
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
                [_prefs_button(lang, "crate_layout", "layout")],
                [_prefs_button(lang, "crate_grouping", "grouping")],
                [cb("crate_back", "open")],
            ]
        )
    if screen == "more" and items:
        return get_text(lang, "crate_more_title"), InlineKeyboardMarkup(
            [
                [cb("crate_preview", "preview")],
                [cb("crate_clear", "clear")],
                [cb("crate_back", "open")],
            ]
        )

    if not items:
        rows = _empty_rows(lang, cb, can_undo=can_undo)
        return get_text(lang, "crate_empty"), InlineKeyboardMarkup(rows)

    from music_links_bot.cards.collection_plan import collection_issues

    if selected_index is not None and not 0 <= selected_index < len(items):
        selected_index = None
    blocking = sorted(
        {issue.index for issue in collection_issues(items) if issue.blocking}
    )
    rows = [[cb("crate_add_links", "add")]]
    rows.extend(_item_rows(items, selected_index))
    if selected_index is not None:
        rows.extend(_selected_rows(items, selected_index, cb))
    if can_undo:
        rows.append([cb("crate_undo", "undo")])
    rows.append([cb("crate_style", "style"), cb("crate_rename", "rename")])
    rows.extend(
        _main_action_rows(
            items,
            lang,
            cb,
            blocking=blocking,
            can_publish=can_publish,
            share_query=share_query,
        )
    )
    rows.append([cb("crate_more", "more")])
    rows.append([_home_button(lang)])
    return _crate_text(items, lang, title=title, selected=selected_index), (
        InlineKeyboardMarkup(rows)
    )


def _crate_button(lang: str):
    def cb(key, action, payload="", **kwargs):
        return button(
            get_text(lang, key),
            callback_data=encode_callback("crate", action, payload),
            **kwargs,
        )

    return cb


def _prefs_button(lang: str, key: str, action: str):
    return button(
        get_text(lang, key), callback_data=encode_callback("prefs", action, "crate")
    )


def _home_button(lang: str):
    return button(
        get_text(lang, "home_back"), callback_data=encode_callback("menu", "start")
    )


def _crate_text(items: list[dict], lang: str, *, title: str, selected) -> str:
    from music_links_bot.cards.collection_plan import collection_check_text

    heading = (
        f"🎶 <b>{escape(title)} · {len(items)}/10</b>"
        if title
        else get_text(lang, "crate_title").replace("{count}", str(len(items)))
    )
    lines = [heading, ""]
    for index, entry in enumerate(items, 1):
        item = entry.get("item") or {}
        # Same list style as the published collection: "01 · Artist — Title".
        lines.append(
            f"<code>{index:02}</code> · "
            f"<b>{escape(str(item.get('artist') or '—'))}</b> — "
            f"{escape(str(item.get('title') or '—'))}"
        )
    lines.extend(["", collection_check_text(items, lang)])
    if selected is None:
        lines.extend(["", get_text(lang, "crate_hint")])
    return "\n".join(lines)


def item_button_label(entry: dict, index: int, *, selected: bool) -> str:
    item = entry.get("item") if isinstance(entry, dict) else None
    item = item if isinstance(item, dict) else {}
    artist = " ".join(str(item.get("artist") or "—").split())
    title = " ".join(str(item.get("title") or "—").split())
    prefix = "✓ " if selected else ""
    label = f"{prefix}{index + 1} · {artist} — {title}"
    return label if len(label) <= 52 else label[:51].rstrip() + "…"


def _item_rows(items: list[dict], selected_index: int | None) -> Rows:
    return [
        [
            button(
                item_button_label(entry, index, selected=index == selected_index),
                callback_data=encode_callback("crate", "select", crate_item_key(entry)),
            )
        ]
        for index, entry in enumerate(items)
    ]


def _selected_rows(items: list[dict], selected_index: int, cb) -> Rows:
    """Move, remove, replace, note and section for the tapped release."""
    from music_links_bot.core.release_preferences import release_preference_key

    key = crate_item_key(items[selected_index])
    rows: Rows = []
    moves = []
    if selected_index > 0:
        moves.append(cb("crate_up", "up", key))
    if selected_index < len(items) - 1:
        moves.append(cb("crate_down", "down", key))
    if moves:
        rows.append(moves)
    rows.append(
        [cb("crate_remove", "remove", key), cb("crate_replace", "replace", key)]
    )
    selected_key = release_preference_key(
        TrackMatch(**{"links": {}, **items[selected_index]["item"]})
    )
    rows.append(
        [
            cb("crate_note", "note", selected_key),
            cb("crate_section", "section", selected_key),
        ]
    )
    return rows


def _main_action_rows(
    items: list[dict],
    lang: str,
    cb,
    *,
    blocking: list[int],
    can_publish: bool,
    share_query: str | None,
) -> Rows:
    """One primary action: fix the problem, publish, or share."""
    if blocking:
        first = items[blocking[0] - 1]
        label = get_text(lang, "crate_fix").format(
            items=", ".join(f"№{index}" for index in blocking)
        )
        return [
            [
                button(
                    label,
                    callback_data=encode_callback(
                        "crate", "select", crate_item_key(first)
                    ),
                    style="primary",
                )
            ]
        ]
    share = (
        [
            button(
                get_text(lang, "crate_share"),
                switch_inline_query=share_query,
                **({} if can_publish else {"style": "primary"}),
            )
        ]
        if share_query
        else None
    )
    if can_publish:
        publish = [
            cb("crate_publish", "publish", crate_revision(items), style="primary")
        ]
        return [publish, share] if share else [publish]
    return [share] if share else []


def _empty_rows(lang: str, cb, *, can_undo: bool) -> Rows:
    rows: Rows = [[cb("crate_add_links", "add")]]
    if can_undo:
        rows.append([cb("crate_undo", "undo", style="primary")])
    rows.append(
        [
            button(
                get_text(lang, "crate_find"),
                callback_data=encode_callback("menu", "create"),
                style="primary",
            )
        ]
    )
    rows.append([_home_button(lang)])
    return rows
