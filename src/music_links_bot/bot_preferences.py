from __future__ import annotations

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import Application

from music_links_bot.bot_runtime import BotRuntime, UserSession, encode_callback
from music_links_bot.durable_state import state_scope
from music_links_bot.i18n import (
    get_text,
    language_context,
    preferred_language,
    resolve_lang,
)
from music_links_bot.kvstore import KVUnavailableError
from music_links_bot.models import TrackMatch
from music_links_bot.release_preferences import (
    current_presentation,
    preferences_from_session,
    presentation_context,
    release_preference_key,
)
from music_links_bot.release_presentation import apply_preset
from music_links_bot.telegram_buttons import button, disabled_button


class LocalizedApplication(Application):
    """Scope a saved language to one update, including concurrent webhooks."""

    __slots__ = ()

    async def process_update(self, update: object) -> None:
        from music_links_bot.user_state import generation_key, user_state_scope

        with state_scope(), language_context(None), presentation_context():
            runtime = self.bot_data.get("runtime")
            user = update.effective_user if isinstance(update, Update) else None
            kv = self.bot_data.get("kv_store")
            try:
                scope_kwargs: dict = {}
                session_kwargs: dict = {}
                batch = getattr(kv, "mget_required", None)
                if (
                    user is not None
                    and user.id > 0
                    and callable(batch)
                    and isinstance(runtime, BotRuntime)
                    and runtime.kv is kv
                ):
                    # The privacy fence, the session and the owner's cover
                    # label are read in one round trip at the start of an update.
                    from music_links_bot.brand_settings import (
                        BRAND_LABEL_KEY,
                        apply_stored_label,
                    )

                    generation, session_raw, label = await batch(
                        [
                            generation_key(user.id),
                            runtime.session_key(user.id),
                            BRAND_LABEL_KEY,
                        ]
                    )
                    apply_stored_label(label)
                    scope_kwargs["generation"] = generation
                    session_kwargs["prefetched_raw"] = session_raw
                async with user_state_scope(kv, user.id if user else 0, **scope_kwargs):
                    if user is not None and isinstance(runtime, BotRuntime):
                        session = await runtime.get_session(
                            user.id,
                            lang=resolve_lang(user.language_code),
                            **session_kwargs,
                        )
                        preferred_language.set(session.preferred_lang or None)
                        current_presentation.set(preferences_from_session(session))
                    await super().process_update(update)
            except KVUnavailableError as exc:
                await self.process_error(update, error=exc)

    async def process_error(self, update, error, job=None, coroutine=None):
        from music_links_bot.state_mutations import StateConflictError
        from music_links_bot.update_execution import current_execution

        execution = current_execution.get()
        if execution is not None and not isinstance(error, StateConflictError):
            execution.error = error
        return await super().process_error(
            update, error=error, job=job, coroutine=coroutine
        )


def apply_preferences(draft: dict, session: UserSession) -> None:
    if session.preferred_lang:
        draft["lang"] = session.preferred_lang
    if session.default_preset:
        apply_preset(draft, session.default_preset)
    if session.default_hashtags:
        draft["hashtags"] = session.default_hashtags == "auto"
        draft.pop("custom_tags", None)
    if (
        draft.get("item", {}).get("kind") in {"song", "album"}
        and draft.get("publication_mode") != "longread"
    ):
        # The signed release cover is the house style; the old "platform
        # preview" choice never changed what was published, so it is gone.
        draft["as_photo"] = bool(draft.get("item", {}).get("thumbnail_url"))
    track = TrackMatch(**draft["item"])
    saved = session.release_tags.get(release_preference_key(track))
    if saved is not None:
        draft["custom_tags"] = list(saved)
        draft["hashtags"] = bool(saved)


def preferences_view(
    session: UserSession,
    *,
    lang: str,
    section: str = "open",
    origin: str = "",
    is_admin: bool = False,
):
    """One settings screen; every row shows its current value."""

    def cb(label, action, value="", **kwargs):
        return button(
            label, callback_data=encode_callback("prefs", action, value), **kwargs
        )

    choices = {
        "layout": (
            "collection_layout",
            [
                ("column", "pref_layout_column"),
                ("auto", "pref_layout_auto"),
                ("compact", "pref_layout_compact"),
            ],
        ),
        "grouping": (
            "collection_grouping",
            [
                ("none", "pref_grouping_none"),
                ("artist", "pref_grouping_artist"),
                ("album", "pref_grouping_album"),
            ],
        ),
        "language": (
            "preferred_lang",
            [("", "pref_lang_auto"), ("ru", "pref_lang_ru"), ("en", "pref_lang_en")],
        ),
        "appearance": (
            "default_preset",
            [
                ("", "pref_inherit"),
                ("cover", "pref_cover"),
                ("longread", "pref_longread"),
            ],
        ),
        "tags": (
            "default_hashtags",
            [
                ("", "pref_inherit"),
                ("auto", "pref_tags_auto"),
                ("off", "pref_tags_off"),
            ],
        ),
    }
    back_to_settings = [cb(get_text(lang, "pref_back"), "open")]
    if section in choices:
        field, options = choices[section]
        current = getattr(session, field)
        if field == "default_preset" and current == "minimal":
            current = "cover"
        rows = [
            [
                disabled_button("✓ " + get_text(lang, label))
                if current == value
                else cb(
                    get_text(lang, label),
                    section,
                    ("crate:" if origin == "crate" else "") + (value or "inherit"),
                )
            ]
            for value, label in options
        ]
        if origin == "crate":
            rows.append(
                [
                    button(
                        get_text(lang, "crate_back"),
                        callback_data=encode_callback("crate", "open"),
                    )
                ]
            )
        elif section in {"layout", "grouping"}:
            rows.append([cb(get_text(lang, "pref_back_collection"), "collection")])
        else:
            rows.append(back_to_settings)
        return get_text(lang, f"pref_{section}_title"), InlineKeyboardMarkup(rows)
    if section == "collection":
        rows = [
            [
                cb(
                    get_text(lang, "pref_layout").format(
                        value=get_text(lang, "pref_layout_" + session.collection_layout)
                    ),
                    "layout",
                )
            ],
            [
                cb(
                    get_text(lang, "pref_grouping").format(
                        value=get_text(
                            lang, "pref_grouping_" + session.collection_grouping
                        )
                    ),
                    "grouping",
                )
            ],
            back_to_settings,
        ]
        return get_text(lang, "pref_collection_title"), InlineKeyboardMarkup(rows)

    preset = session.default_preset
    preset = "cover" if preset == "minimal" else preset
    values = {
        "language": get_text(lang, f"pref_lang_{session.preferred_lang or 'auto'}"),
        "appearance": get_text(lang, f"pref_{preset or 'inherit'}"),
        "tags": get_text(lang, f"pref_tags_{session.default_hashtags}")
        if session.default_hashtags
        else get_text(lang, "pref_inherit"),
        "collection": get_text(lang, "pref_layout_" + session.collection_layout),
    }
    rows = [
        [
            cb(
                get_text(lang, "pref_language").format(value=values["language"]),
                "language",
            )
        ],
        [
            cb(
                get_text(lang, "pref_appearance").format(value=values["appearance"]),
                "appearance",
            )
        ],
        [cb(get_text(lang, "pref_tags").format(value=values["tags"]), "tags")],
        [
            cb(
                get_text(lang, "pref_collection_value").format(
                    value=values["collection"]
                ),
                "collection",
            )
        ],
    ]
    if is_admin:
        from music_links_bot.cover_style import brand_label

        rows.append(
            [
                cb(
                    get_text(lang, "pref_brand_label").format(value=brand_label()),
                    "label",
                )
            ]
        )
        rows.append(
            [
                cb(
                    get_text(lang, "pref_quick_publish").format(
                        value=get_text(
                            lang, "pref_on" if session.quick_publish else "pref_off"
                        )
                    ),
                    "quick",
                )
            ]
        )
    rows.append(
        [
            button(
                get_text(lang, "pref_help"),
                callback_data=encode_callback("menu", "help"),
            ),
            button(
                get_text(lang, "tab_privacy"),
                callback_data=encode_callback("menu", "privacy"),
            ),
        ]
    )
    rows.append(
        [
            button(
                get_text(lang, "home_back"),
                callback_data=encode_callback("menu", "start"),
            )
        ]
    )
    return get_text(lang, "pref_title"), InlineKeyboardMarkup(rows)


async def dispatch_preferences(query, context, action) -> None:
    if query.from_user is None:
        await query.answer()
        return
    runtime = context.application.bot_data.get("runtime")
    if not isinstance(runtime, BotRuntime):
        runtime = BotRuntime(context.application.bot_data.get("kv_store"))
        context.application.bot_data["runtime"] = runtime
    session = await runtime.get_session(
        query.from_user.id, lang=resolve_lang(query.from_user.language_code)
    )
    choices = {
        "layout": ("collection_layout", {"auto", "column", "compact"}),
        "grouping": ("collection_grouping", {"none", "artist", "album"}),
        "language": ("preferred_lang", {"", "ru", "en"}),
        "appearance": ("default_preset", {"", "cover", "longread"}),
        "tags": ("default_hashtags", {"", "auto", "off"}),
    }
    admin_chat_id = context.application.bot_data.get("admin_chat_id")
    is_admin = admin_chat_id is not None and admin_chat_id == query.from_user.id
    section = action.action
    if section in {"defaults", "artwork"}:
        # Old keyboards: these screens merged into the main settings screen.
        section = "open"
    if section == "label" and is_admin:
        await _start_brand_label_input(query, context, runtime, session)
        return
    changed = False
    if section == "quick" and is_admin:
        session.quick_publish = not session.quick_publish
        await runtime.save_session(session)
        changed = True
        section = "open"
    payload = action.payload or ""
    origin = "crate" if payload == "crate" or payload.startswith("crate:") else ""
    if origin:
        payload = payload.partition(":")[2]
    if action.action in choices and payload:
        field, allowed = choices[action.action]
        value = "" if payload == "inherit" else payload
        if value in allowed:
            setattr(session, field, value)
            await runtime.save_session(session)
            changed = True
    preferred_language.set(session.preferred_lang or None)
    current_presentation.set(preferences_from_session(session))
    lang = resolve_lang(query.from_user.language_code)
    text, keyboard = preferences_view(
        session, lang=lang, section=section, origin=origin, is_admin=is_admin
    )
    await query.answer(get_text(lang, "settings_saved") if changed else None)
    # Import locally to keep menu rendering and settings independent at import.
    from music_links_bot.bot_menu import safe_edit

    await safe_edit(query, text, keyboard)


async def _start_brand_label_input(query, context, runtime, session) -> None:
    """Ask the owner for the cover signature text with a native reply prompt."""
    import time

    from telegram import ForceReply

    lang = resolve_lang(query.from_user.language_code)
    if query.message is None:
        await query.answer()
        return
    prompt = await query.message.reply_text(
        get_text(lang, "pref_brand_label_prompt"),
        parse_mode="HTML",
        reply_markup=ForceReply(selective=True),
    )
    session.pending_input = {
        "kind": "brand_label",
        "created_at": int(time.time()),
        "prompt_message_id": prompt.message_id,
        "editor_chat_id": query.message.chat_id,
        "editor_message_id": query.message.message_id,
    }
    await runtime.save_session(session)
    await query.answer()
