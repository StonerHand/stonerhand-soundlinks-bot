from __future__ import annotations

from music_links_bot.i18n import get_text
from music_links_bot.constants import PLATFORM_LABELS
from music_links_bot.models import TrackMatch
from music_links_bot.release_presentation import (
    PRESET_ORDER,
    apply_preset,
    normalize_preset,
)


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
    selected = draft.get("platforms")
    service_count = (
        len(selected)
        if isinstance(selected, list)
        else min(
            6,
            sum(bool(track.links.get(platform)) for platform in PLATFORM_LABELS),
        )
    )
    return get_text(lang, "ed_status").format(
        preset=preset_name,
        services=service_count,
    )


def toggle_platform_selection(
    draft: dict,
    track: TrackMatch,
    platform_order: tuple[str, ...],
) -> None:
    if draft.get("platforms"):
        draft.pop("platforms", None)
        return
    draft["platforms"] = [key for key in platform_order if track.links.get(key)][:6]


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
