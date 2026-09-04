from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ActionKind(str, Enum):
    NAVIGATION = "navigation"
    SETTING = "setting"
    INPUT = "input"
    DELIVERY = "delivery"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True, slots=True)
class ActionSpec:
    scope: str
    code: str
    name: str
    kind: ActionKind

    @property
    def mutating(self) -> bool:
        return self.kind is not ActionKind.NAVIGATION


# One semantic registry for callbacks rendered by the current UI. Dynamic
# actions (platform index, onboarding step and crate item index) are validated
# by the patterns below instead of being scattered through handlers.
ACTION_SPECS = tuple(
    ActionSpec(scope, code, name, kind)
    for scope, code, name, kind in (
        ("menu", "start", "home", ActionKind.NAVIGATION),
        ("menu", "create", "create", ActionKind.NAVIGATION),
        ("menu", "drafts", "drafts", ActionKind.NAVIGATION),
        ("menu", "recent", "history", ActionKind.NAVIGATION),
        ("menu", "help", "help", ActionKind.NAVIGATION),
        ("menu", "guide", "guide", ActionKind.NAVIGATION),
        ("menu", "platforms", "services", ActionKind.NAVIGATION),
        ("menu", "demo", "demo", ActionKind.NAVIGATION),
        ("menu", "more", "more", ActionKind.NAVIGATION),
        ("menu", "privacy", "privacy", ActionKind.NAVIGATION),
        ("menu", "stats", "stats", ActionKind.NAVIGATION),
        ("editor", "b", "card", ActionKind.NAVIGATION),
        ("editor", "m", "settings", ActionKind.NAVIGATION),
        ("editor", "zs", "style", ActionKind.NAVIGATION),
        ("editor", "ls", "platforms", ActionKind.NAVIGATION),
        ("editor", "ts", "intro", ActionKind.NAVIGATION),
        ("editor", "hs", "hashtags", ActionKind.NAVIGATION),
        ("editor", "pv", "preview", ActionKind.NAVIGATION),
        ("editor", "o", "actions", ActionKind.NAVIGATION),
        ("editor", "qs", "schedule", ActionKind.NAVIGATION),
        ("editor", "rs", "telegram_format", ActionKind.NAVIGATION),
        ("editor", "tp", "templates", ActionKind.NAVIGATION),
        ("editor", "f", "finish_settings", ActionKind.NAVIGATION),
        ("editor", "a", "another_release", ActionKind.NAVIGATION),
        ("editor", "z0", "minimal_style", ActionKind.SETTING),
        ("editor", "z1", "cover_style", ActionKind.SETTING),
        ("editor", "z2", "longread_style", ActionKind.SETTING),
        ("editor", "la", "all_platforms", ActionKind.SETTING),
        ("editor", "ha", "auto_hashtags", ActionKind.SETTING),
        ("editor", "hn", "no_hashtags", ActionKind.SETTING),
        ("editor", "t0", "remove_intro", ActionKind.SETTING),
        ("editor", "u", "undo_setting", ActionKind.SETTING),
        ("editor", "lp", "last_template", ActionKind.SETTING),
        ("editor", "ra", "telegram_format_auto", ActionKind.SETTING),
        ("editor", "rc", "telegram_format_classic", ActionKind.SETTING),
        ("editor", "ci", "custom_cover", ActionKind.INPUT),
        ("editor", "tn", "save_template", ActionKind.INPUT),
        ("editor", "cr", "reset_cover", ActionKind.SETTING),
        ("editor", "h", "toggle_hashtags_legacy", ActionKind.SETTING),
        ("editor", "q", "toggle_quote_legacy", ActionKind.SETTING),
        ("editor", "t", "toggle_text_legacy", ActionKind.SETTING),
        ("editor", "v", "toggle_preview_legacy", ActionKind.SETTING),
        ("editor", "l", "toggle_platforms_legacy", ActionKind.SETTING),
        ("editor", "z", "cycle_style_legacy", ActionKind.SETTING),
        ("editor", "ti", "write_intro", ActionKind.INPUT),
        ("editor", "hi", "write_hashtags", ActionKind.INPUT),
        ("editor", "qi", "custom_schedule", ActionKind.INPUT),
        ("editor", "q1", "schedule_hour", ActionKind.DELIVERY),
        ("editor", "q3", "schedule_three_hours_legacy", ActionKind.DELIVERY),
        ("editor", "qe", "schedule_evening", ActionKind.DELIVERY),
        ("editor", "qd", "schedule_tomorrow", ActionKind.DELIVERY),
        ("editor", "p", "publish_confirmation", ActionKind.NAVIGATION),
        ("editor", "pc", "publish", ActionKind.DELIVERY),
        ("editor", "r", "repeat_publish", ActionKind.DELIVERY),
        ("editor", "x", "replace_publish", ActionKind.DELIVERY),
        ("editor", "s", "send_self", ActionKind.DELIVERY),
        ("editor", "c", "add_to_crate", ActionKind.SETTING),
        ("editor", "d", "delete_confirmation", ActionKind.NAVIGATION),
        ("editor", "dc", "delete", ActionKind.DESTRUCTIVE),
        ("editor", "du", "restore", ActionKind.SETTING),
        ("crate", "open", "open_crate", ActionKind.NAVIGATION),
        ("crate", "preview", "crate_preview", ActionKind.NAVIGATION),
        ("crate", "select", "select_item", ActionKind.NAVIGATION),
        ("crate", "rename", "rename_crate", ActionKind.INPUT),
        ("crate", "up", "move_up", ActionKind.SETTING),
        ("crate", "down", "move_down", ActionKind.SETTING),
        ("crate", "remove", "remove_item", ActionKind.DESTRUCTIVE),
        ("crate", "undo", "undo_crate", ActionKind.SETTING),
        ("crate", "clear", "clear_confirmation", ActionKind.NAVIGATION),
        ("crate", "clear_confirm", "clear", ActionKind.DESTRUCTIVE),
        ("crate", "clear_cancel", "cancel_clear", ActionKind.NAVIGATION),
        ("retry", "last", "retry", ActionKind.DELIVERY),
        ("retry", "failed", "retry_failed", ActionKind.DELIVERY),
        ("retry", "replace", "replace_failed_source", ActionKind.INPUT),
        ("select", "pick", "pick_search_result", ActionKind.NAVIGATION),
        ("noop", "busy", "busy", ActionKind.NAVIGATION),
        ("progress", "cancel", "cancel_search", ActionKind.DESTRUCTIVE),
        ("privacy", "confirm", "confirm_delete_data", ActionKind.NAVIGATION),
        ("privacy", "delete", "delete_data", ActionKind.DESTRUCTIVE),
        ("queue", "open", "open_queue", ActionKind.NAVIGATION),
        ("playlist", "import", "import_playlist", ActionKind.DELIVERY),
    )
)

ACTION_REGISTRY = {(spec.scope, spec.code): spec for spec in ACTION_SPECS}
_DYNAMIC_ACTIONS = (
    re.compile(r"^menu:onboard(?:[123]|done)$"),
    re.compile(r"^editor:l\d+$"),
    re.compile(r"^editor:t[ad]\d+$"),
    re.compile(r"^queue:cancel$"),
)


def action_spec(scope: str, code: str) -> ActionSpec | None:
    spec = ACTION_REGISTRY.get((scope, code))
    if spec is not None:
        return spec
    value = f"{scope}:{code}"
    if any(pattern.fullmatch(value) for pattern in _DYNAMIC_ACTIONS):
        kind = ActionKind.SETTING if scope == "editor" else ActionKind.NAVIGATION
        return ActionSpec(scope, code, value, kind)
    return None


def is_mutating_action(scope: str, code: str) -> bool:
    spec = action_spec(scope, code)
    return bool(spec and spec.mutating)
