from __future__ import annotations

from music_links_bot.i18n import get_text
from music_links_bot.models import TrackMatch

PRESET_ORDER = ("clean", "editorial", "poster")


def draft_owned_by(draft: dict, user_id: int) -> bool:
    owner_id = draft.get("chat_id")
    return not isinstance(owner_id, int) or owner_id <= 0 or owner_id == user_id


def remember_draft(session, draft_id: str) -> None:
    session.active_draft_id = draft_id
    session.recent_draft_ids = [
        draft_id,
        *(value for value in session.recent_draft_ids if value != draft_id),
    ][:5]


def draft_status(draft: dict, track: TrackMatch, *, lang: str) -> str:
    preset = str(draft.get("preset") or "clean")
    preset_label = get_text(
        lang,
        f"ed_preset_{preset if preset in PRESET_ORDER else 'clean'}",
    )
    preset_name = preset_label.split("·", 1)[-1].strip()
    selected = draft.get("platforms")
    service_count = (
        len(selected)
        if isinstance(selected, list) and selected
        else min(1, sum(bool(value) for value in track.links.values()))
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
    draft["platforms"] = [
        key for key in platform_order if track.links.get(key)
    ][:6]


def cycle_preset(draft: dict) -> str:
    current = str(draft.get("preset") or "clean")
    index = PRESET_ORDER.index(current) if current in PRESET_ORDER else -1
    preset = PRESET_ORDER[(index + 1) % len(PRESET_ORDER)]
    draft["preset"] = preset
    draft["as_photo"] = preset == "poster"
    draft["large_preview"] = preset != "editorial"
    return preset
