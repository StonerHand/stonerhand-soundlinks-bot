from __future__ import annotations

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import Application

from music_links_bot.bot_runtime import BotRuntime, UserSession, encode_callback
from music_links_bot.i18n import (
    get_text,
    language_context,
    preferred_language,
    resolve_lang,
)
from music_links_bot.models import TrackMatch
from music_links_bot.release_preferences import (
    current_presentation,
    preferences_from_session,
    presentation_context,
    release_preference_key,
)
from music_links_bot.release_presentation import apply_preset
from music_links_bot.telegram_buttons import button


class LocalizedApplication(Application):
    """Scope a saved language to one update, including concurrent webhooks."""

    __slots__ = ()

    async def process_update(self, update: object) -> None:
        with language_context(None), presentation_context():
            runtime = self.bot_data.get("runtime")
            user = update.effective_user if isinstance(update, Update) else None
            if user is not None and isinstance(runtime, BotRuntime):
                session = await runtime.get_session(
                    user.id, lang=resolve_lang(user.language_code)
                )
                preferred_language.set(session.preferred_lang or None)
                current_presentation.set(preferences_from_session(session))
            await super().process_update(update)


def apply_preferences(draft: dict, session: UserSession) -> None:
    if session.preferred_lang:
        draft["lang"] = session.preferred_lang
    if session.default_preset:
        apply_preset(draft, session.default_preset)
    if session.default_hashtags:
        draft["hashtags"] = session.default_hashtags == "auto"
        draft.pop("custom_tags", None)
    if (
        session.default_artwork == "clean"
        and draft.get("item", {}).get("kind") != "video"
    ):
        draft["as_photo"] = bool(draft.get("item", {}).get("thumbnail_url"))
    elif (
        session.default_artwork == "native"
        and draft.get("publication_mode") != "longread"
    ):
        draft["delivery_mode"] = "classic"
    track = TrackMatch(**draft["item"])
    saved = session.release_tags.get(release_preference_key(track))
    if saved is not None:
        draft["custom_tags"] = list(saved)
        draft["hashtags"] = bool(saved)


def preferences_view(session: UserSession, *, lang: str, section: str = "open"):
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
        "artwork": (
            "default_artwork",
            [("native", "pref_artwork_native"), ("clean", "pref_artwork_clean")],
        ),
        "language": (
            "preferred_lang",
            [("", "pref_lang_auto"), ("ru", "pref_lang_ru"), ("en", "pref_lang_en")],
        ),
        "appearance": (
            "default_preset",
            [
                ("", "pref_inherit"),
                ("minimal", "pref_minimal"),
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
    if section in choices:
        field, options = choices[section]
        rows = [
            [
                cb(
                    ("✓ " if getattr(session, field) == value else "")
                    + get_text(lang, label),
                    section,
                    value or "inherit",
                )
            ]
            for value, label in options
        ]
        rows.append([cb(get_text(lang, "back"), "open")])
        return get_text(lang, f"pref_{section}_title"), InlineKeyboardMarkup(rows)
    language = get_text(lang, f"pref_lang_{session.preferred_lang or 'auto'}")
    preset = get_text(lang, f"pref_{session.default_preset or 'inherit'}")
    tags = (
        get_text(lang, f"pref_tags_{session.default_hashtags}")
        if session.default_hashtags
        else get_text(lang, "pref_inherit")
    )
    rows = [
        [cb(get_text(lang, "pref_language").format(value=language), "language")],
        [cb(get_text(lang, "pref_appearance").format(value=preset), "appearance")],
        [cb(get_text(lang, "pref_tags").format(value=tags), "tags")],
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
                    value=get_text(lang, "pref_grouping_" + session.collection_grouping)
                ),
                "grouping",
            )
        ],
        [
            cb(
                get_text(lang, "pref_artwork").format(
                    value=get_text(lang, "pref_artwork_" + session.default_artwork)
                ),
                "artwork",
            )
        ],
        [
            button(
                get_text(lang, "tab_help"),
                callback_data=encode_callback("menu", "help"),
            ),
            button(
                get_text(lang, "tab_privacy"),
                callback_data=encode_callback("menu", "privacy"),
            ),
        ],
        [
            button(
                get_text(lang, "home_back"),
                callback_data=encode_callback("menu", "start"),
            )
        ],
    ]
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
        "artwork": ("default_artwork", {"native", "clean"}),
        "language": ("preferred_lang", {"", "ru", "en"}),
        "appearance": ("default_preset", {"", "minimal", "cover", "longread"}),
        "tags": ("default_hashtags", {"", "auto", "off"}),
    }
    changed = False
    if action.action in choices and action.payload:
        field, allowed = choices[action.action]
        value = "" if action.payload == "inherit" else action.payload
        if value in allowed:
            setattr(session, field, value)
            await runtime.save_session(session)
            changed = True
    preferred_language.set(session.preferred_lang or None)
    current_presentation.set(preferences_from_session(session))
    lang = resolve_lang(query.from_user.language_code)
    text, keyboard = preferences_view(session, lang=lang, section=action.action)
    await query.answer(get_text(lang, "settings_saved") if changed else None)
    # Import locally to keep menu rendering and settings independent at import.
    from music_links_bot.bot_menu import safe_edit

    await safe_edit(query, text, keyboard)
