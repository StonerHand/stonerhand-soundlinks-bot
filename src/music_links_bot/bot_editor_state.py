from __future__ import annotations

import time
from copy import deepcopy

from music_links_bot.bot_builder import (
    remove_intro,
    remove_tags,
    select_all_platforms,
    select_preset,
    toggle_platform,
    use_auto_tags,
)
from music_links_bot.constants import PLATFORM_LABELS
from music_links_bot.i18n import get_text
from music_links_bot.models import TrackMatch
from music_links_bot.release_presentation import (
    PRESET_ORDER,
    apply_preset,
    normalize_preset,
)
from music_links_bot.url_utils import is_platform_destination_url

UNDO_SETTING_SECONDS = 30
MAX_UNDO_STEPS = 5
_EDITABLE_FIELDS = (
    "prefix",
    "quote",
    "hashtags",
    "custom_tags",
    "platforms",
    "preset",
    "large_preview",
    "as_photo",
    "publication_mode",
    "delivery_mode",
    "custom_cover_file_id",
    "custom_cover_unique_id",
)


def remember_setting_state(draft: dict) -> None:
    state = {
        "expires_at": int(time.time()) + UNDO_SETTING_SECONDS,
        "values": {
            key: deepcopy(draft[key]) if key in draft else None
            for key in _EDITABLE_FIELDS
        },
    }
    stack = [
        value
        for value in draft.get("undo_stack", [])
        if isinstance(value, dict)
        and int(value.get("expires_at") or 0) >= int(time.time())
    ]
    stack.append(state)
    draft["undo_stack"] = stack[-MAX_UNDO_STEPS:]
    draft["undo_state"] = state


def restore_setting_state(draft: dict, *, now: int | None = None) -> bool:
    current_time = now or int(time.time())
    stack = [
        value
        for value in draft.get("undo_stack", [])
        if isinstance(value, dict) and int(value.get("expires_at") or 0) >= current_time
    ]
    state = stack.pop() if stack else draft.get("undo_state")
    if not isinstance(state, dict):
        return False
    if int(state.get("expires_at") or 0) < current_time:
        draft.pop("undo_state", None)
        draft.pop("undo_stack", None)
        return False
    values = state.get("values")
    if not isinstance(values, dict):
        draft.pop("undo_state", None)
        return False
    for key in _EDITABLE_FIELDS:
        value = values.get(key)
        if value is None:
            draft.pop(key, None)
        else:
            draft[key] = deepcopy(value)
    if stack:
        draft["undo_stack"] = stack
        draft["undo_state"] = stack[-1]
    else:
        draft.pop("undo_stack", None)
        draft.pop("undo_state", None)
    return True


def draft_owned_by(draft: dict, user_id: int) -> bool:
    owner_id = draft.get("chat_id")
    return isinstance(owner_id, int) and owner_id > 0 and owner_id == user_id


def remember_draft(session, draft_id: str) -> None:
    session.active_draft_id = draft_id
    session.recent_draft_ids = [
        draft_id,
        *(value for value in session.recent_draft_ids if value != draft_id),
    ][:5]


def draft_status(draft: dict, track: TrackMatch, *, lang: str) -> str:
    preset = normalize_preset(draft.get("preset"), draft)
    preset_label = get_text(
        lang,
        f"ed_preset_{preset}",
    )
    preset_name = preset_label.split("·", 1)[-1].strip()
    if draft.get("custom_cover_file_id"):
        preset_name = get_text(lang, "ed_status_custom_cover")
    custom_tags = draft.get("custom_tags")
    if not draft.get("hashtags", True):
        tags = get_text(lang, "ed_status_tags_none")
    elif isinstance(custom_tags, list) and custom_tags:
        tags = get_text(lang, "ed_status_tags_custom").format(count=len(custom_tags))
    else:
        tags = get_text(lang, "ed_status_tags_auto")
    if draft.get("source_audio_file_id"):
        return get_text(lang, "ed_status_audio").format(tags=tags)
    selected = draft.get("platforms")
    service_count = (
        len(selected)
        if isinstance(selected, list)
        else min(
            6,
            sum(
                is_platform_destination_url(platform, track.links.get(platform))
                for platform in PLATFORM_LABELS
            ),
        )
    )
    services = _platform_count_label(service_count, lang=lang)
    delivery = get_text(
        lang,
        "ed_status_delivery_classic"
        if draft.get("delivery_mode") == "classic"
        else "ed_status_delivery_auto",
    )
    return get_text(lang, "ed_status").format(
        preset=preset_name,
        tags=tags,
        services=services,
        delivery=delivery,
    )


def _platform_count_label(count: int, *, lang: str) -> str:
    count = max(0, int(count))
    if lang == "en":
        return f"{count} platform" + ("" if count == 1 else "s")
    remainder_100 = count % 100
    remainder_10 = count % 10
    if remainder_10 == 1 and remainder_100 != 11:
        noun = "площадка"
    elif 2 <= remainder_10 <= 4 and not 12 <= remainder_100 <= 14:
        noun = "площадки"
    else:
        noun = "площадок"
    return f"{count} {noun}"


def toggle_platform_selection(
    draft: dict,
    track: TrackMatch,
    platform_order: tuple[str, ...],
) -> None:
    if draft.get("platforms"):
        draft.pop("platforms", None)
        return
    draft["platforms"] = [
        key
        for key in platform_order
        if is_platform_destination_url(key, track.links.get(key))
    ][:6]


def cycle_preset(draft: dict) -> str:
    current = normalize_preset(draft.get("preset"), draft)
    index = PRESET_ORDER.index(current)
    preset = PRESET_ORDER[(index + 1) % len(PRESET_ORDER)]
    return apply_preset(draft, preset)


def apply_setting_action(
    draft: dict,
    action: str,
    *,
    track: TrackMatch,
    platform_order: tuple[str, ...],
) -> bool:
    """Apply one pure editor setting and report whether it was recognized."""
    if action == "h":
        draft["hashtags"] = not draft.get("hashtags")
    elif action in {"q", "t"}:
        draft["quote"] = not draft.get("quote")
    elif action == "v":
        draft["large_preview"] = not draft.get("large_preview")
    elif action == "l":
        toggle_platform_selection(draft, track, platform_order)
    elif action == "z":
        cycle_preset(draft)
    else:
        return False
    return True


def apply_editor_shortcut(
    draft: dict,
    action: str,
    *,
    track: TrackMatch,
    platform_order: tuple[str, ...],
) -> str | None:
    """Apply a setting-screen action and return the screen to render next."""
    if action in {"z0", "z1", "z2"}:
        remember_setting_state(draft)
        select_preset(draft, int(action[1]))
        return "zs"
    if len(action) >= 2 and action.startswith("l") and action[1:].isdigit():
        remember_setting_state(draft)
        toggle_platform(draft, track, list(platform_order), int(action[1:]))
        return "ls"
    if action == "la":
        remember_setting_state(draft)
        select_all_platforms(draft, track, list(platform_order))
        return "ls"
    mutations = {
        "ha": (use_auto_tags, "hs"),
        "hn": (remove_tags, "hs"),
        "t0": (remove_intro, "ts"),
    }
    mutation = mutations.get(action)
    if mutation is None:
        return None
    remember_setting_state(draft)
    apply, screen = mutation
    apply(draft)
    return screen


def apply_delivery_action(draft: dict, action: str) -> bool:
    """Apply delivery-only settings without Telegram side effects."""
    if action not in {"ra", "rc", "cr"}:
        return False
    remember_setting_state(draft)
    if action == "ra":
        draft["delivery_mode"] = "auto"
    elif action == "rc":
        draft["delivery_mode"] = "classic"
    else:
        draft.pop("custom_cover_file_id", None)
        draft.pop("custom_cover_unique_id", None)
    return True
