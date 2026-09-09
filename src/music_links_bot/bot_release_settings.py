"""Per-release tag corrections and artwork controls for the existing editor."""

from __future__ import annotations

import hashlib

from music_links_bot.bot_editor_state import remember_setting_state
from music_links_bot.bot_runtime import BotRuntime
from music_links_bot.i18n import get_text
from music_links_bot.publication_view import resolve_draft_hashtags
from music_links_bot.release_preferences import (
    current_presentation,
    preferences_from_session,
    release_preference_key,
    remember_release_tags,
)
from music_links_bot.release_tags import suggested_track_tags, unique_tags


def tag_code(tag: str) -> str:
    return "hg" + hashlib.sha256(tag.encode()).hexdigest()[:8]


def tag_choices(draft: dict, track) -> list[str]:
    return unique_tags(
        [
            *suggested_track_tags(track),
            *(draft.get("tag_options") or []),
            *(resolve_draft_hashtags(draft, track) or "").split(),
        ],
        limit=12,
    )


async def apply_release_setting(request) -> str | None:
    """Return the destination screen, or None when this is another action."""
    action, draft, track = request.action, request.draft, request.track
    if action in {"ca", "cn"}:
        if action == "ca" and (
            track.kind == "video"
            or draft.get("source_audio_file_id")
            or not (track.thumbnail_url or draft.get("custom_cover_file_id"))
        ):
            await request.query.answer(
                get_text(request.lang, "ed_clean_unavailable"), show_alert=True
            )
            return "answered"
        remember_setting_state(draft)
        draft["as_photo"] = action == "ca"
        if action == "cn":
            draft["delivery_mode"] = "classic"
        return "ap"
    if action not in {"hp", "hr"} and not action.startswith("hg"):
        return None
    runtime = request.context.application.bot_data.get("runtime")
    if not isinstance(runtime, BotRuntime):
        runtime = BotRuntime(request.context.application.bot_data.get("kv_store"))
        request.context.application.bot_data["runtime"] = runtime
    if action in {"hp", "hr"}:
        session = await runtime.get_session(request.user_id, lang=request.lang)
        if action == "hp":
            selected = (resolve_draft_hashtags(draft, track) or "").split()
            remember_setting_state(draft)
            draft["custom_tags"] = selected
            draft["hashtags"] = bool(selected)
            remember_release_tags(session, track, selected)
        else:
            remember_setting_state(draft)
            session.release_tags.pop(release_preference_key(track), None)
            current_presentation.set(preferences_from_session(session))
            draft.pop("custom_tags", None)
            draft.pop("tag_options", None)
            draft["hashtags"] = True
        await runtime.save_session(session)
        return "hs"
    choices = tag_choices(draft, track)
    matches = [tag for tag in choices if tag_code(tag) == action]
    if len(matches) != 1:
        await request.query.answer(
            get_text(request.lang, "ed_expired"), show_alert=True
        )
        return "answered"
    selected = (resolve_draft_hashtags(draft, track) or "").split()
    tag = matches[0]
    if tag not in selected and len(selected) >= 5:
        await request.query.answer(
            get_text(request.lang, "ed_tags_limit"), show_alert=True
        )
        return "answered"
    remember_setting_state(draft)
    draft["tag_options"] = choices
    draft["custom_tags"] = (
        [value for value in selected if value != tag]
        if tag in selected
        else [*selected, tag]
    )
    draft["hashtags"] = bool(draft["custom_tags"])
    return "hs"
