"""User journeys through the compact editor, including saved-state boundaries."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram import ForceReply

from music_links_bot.bot import _consume_pending_input, _handle_editor_action
from music_links_bot.bot_menu import dispatch_menu_action
from music_links_bot.bot_preferences import dispatch_preferences, preferences_view
from music_links_bot.bot_runtime import (
    BotRuntime,
    CallbackAction,
    UserSession,
    decode_callback,
)
from music_links_bot.bot_storage import load_draft, store_draft
from music_links_bot.bot_ui import editor_appearance_rows, editor_tag_options_rows
from music_links_bot.channel_templates import (
    load_channel_template,
    save_channel_template,
)
from music_links_bot.i18n import STRINGS, language_context
from music_links_bot.models import TrackMatch
from music_links_bot.release_preferences import (
    preferences_from_session,
    presentation_context,
    release_preference_key,
)
from tests.test_ui_refresh import MemoryKV, context_for, draft_for, query_for


def callbacks(keyboard):
    return [
        decode_callback(b.callback_data)
        for row in keyboard.inline_keyboard
        for b in row
        if b.callback_data
    ]


class SimplifiedEditorJourneys(unittest.IsolatedAsyncioTestCase):
    async def test_text_one_tap_survives_restart_and_returns_to_same_post(self):
        kv = MemoryKV()
        context = context_for(kv_store=kv)
        context.application.bot_data["runtime"] = BotRuntime(kv)
        draft = draft_for()
        await store_draft(context, "post", draft)
        await save_channel_template(context, "user:7", draft)
        before = await load_channel_template(context, "user:7")
        query = query_for()
        query.message.message_id = 20
        query.message.reply_text = AsyncMock(
            return_value=SimpleNamespace(message_id=21)
        )
        await _handle_editor_action(query, context, "ti", "post")
        assert isinstance(
            query.message.reply_text.call_args.kwargs["reply_markup"], ForceReply
        )
        session = await BotRuntime(kv).get_session(7)
        assert session.pending_input["kind"] == "intro"
        assert session.pending_input["editor_message_id"] == 20
        assert "settings" not in session.pending_input
        restarted = context_for(kv_store=kv)
        restarted.application.bot_data["runtime"] = BotRuntime(kv)
        restarted.bot.edit_message_text = AsyncMock()
        restarted.bot.delete_message = AsyncMock()
        message = SimpleNamespace(
            chat=SimpleNamespace(type="private"),
            chat_id=7,
            text="Моя заметка",
            caption=None,
            entities=(),
            reply_text=AsyncMock(),
        )
        update = SimpleNamespace(
            effective_message=message, effective_user=query.from_user
        )
        assert await _consume_pending_input(update, restarted)
        stored = await load_draft(restarted, "post")
        assert "Моя заметка" in stored["prefix"]
        assert await load_channel_template(restarted, "user:7") == before
        assert not (await BotRuntime(kv).get_session(7)).pending_input
        restored = restarted.bot.edit_message_text.call_args.kwargs
        assert restored["message_id"] == 20
        assert callbacks(restored["reply_markup"])[0].action == "ti"
        message.reply_text.assert_not_awaited()

    async def test_current_style_and_undo_never_overwrite_saved_defaults(self):
        context = context_for()
        draft = draft_for()
        await store_draft(context, "post", draft)
        await save_channel_template(context, "user:7", draft)
        before = await load_channel_template(context, "user:7")
        for action in ("z0", "hn", "u"):
            await _handle_editor_action(query_for(), context, action, "post")
            assert await load_channel_template(context, "user:7") == before
        stored = await load_draft(context, "post")
        assert stored["preset"] == "minimal"
        assert stored["hashtags"]

    async def test_selecting_original_or_native_clears_custom_cover_and_undo_restores_it(
        self,
    ):
        for action in ("ca", "cn"):
            with self.subTest(action=action):
                context = context_for()
                draft = draft_for()
                draft["item"]["thumbnail_url"] = "https://example.com/original.png"
                draft.update(
                    custom_cover_file_id="uploaded",
                    custom_cover_unique_id="unique",
                    as_photo=True,
                )
                await store_draft(context, "post", draft)
                await _handle_editor_action(query_for(), context, action, "post")
                stored = await load_draft(context, "post")
                assert "custom_cover_file_id" not in stored
                assert stored["as_photo"] is (action == "ca")
                if action == "cn":
                    assert stored["delivery_mode"] == "classic"
                await _handle_editor_action(query_for(), context, "u", "post")
                restored = await load_draft(context, "post")
                assert restored["custom_cover_file_id"] == "uploaded"
                assert restored["custom_cover_unique_id"] == "unique"

    async def test_missing_original_does_not_silently_delete_custom_cover(self):
        context = context_for()
        draft = draft_for()
        draft["custom_cover_file_id"] = "uploaded"
        await store_draft(context, "post", draft)
        query = query_for()
        await _handle_editor_action(query, context, "ca", "post")
        assert query.answer.call_args.kwargs["show_alert"]
        assert (await load_draft(context, "post"))["custom_cover_file_id"] == "uploaded"
        assert all(
            b.callback_data != "v2|editor|ca|post"
            for row in editor_appearance_rows("post", draft)
            for b in row
        )

    async def test_library_contains_separate_drafts_collection_and_search_history(self):
        context, query = context_for(), query_for()
        await dispatch_menu_action(
            query, context, CallbackAction("menu", "library", "")
        )
        routes = [
            (a.scope, a.action)
            for a in callbacks(query.edit_message_text.call_args.kwargs["reply_markup"])
        ]
        assert routes == [
            ("menu", "drafts"),
            ("crate", "open"),
            ("menu", "recent"),
            ("menu", "start"),
        ]

    async def test_collection_settings_remember_return_target_after_saving(self):
        context, query = context_for(), query_for()
        with language_context(None), presentation_context():
            await dispatch_preferences(
                query, context, CallbackAction("prefs", "layout", "crate")
            )
            keyboard = query.edit_message_text.call_args.kwargs["reply_markup"]
            actions = callbacks(keyboard)
            assert actions[-1].scope == "crate"
            choice = next(a for a in actions if a.payload == "crate:compact")
            await dispatch_preferences(query, context, choice)
            assert (
                await context.application.bot_data["runtime"].get_session(7)
            ).collection_layout == "compact"
            assert (
                callbacks(query.edit_message_text.call_args.kwargs["reply_markup"])[
                    -1
                ].scope
                == "crate"
            )
            await dispatch_preferences(
                query, context, CallbackAction("prefs", "layout", "crate:unknown")
            )
            assert (
                await context.application.bot_data["runtime"].get_session(7)
            ).collection_layout == "compact"

    async def test_publication_menu_and_legacy_navigation_never_send_a_post(self):
        context = context_for(publish_chat_id="@stonerhand")
        context.bot.send_message = AsyncMock()
        await store_draft(context, "post", draft_for())
        for action in ("m", "b", "f", "tx", "ts", "hs", "ht", "tools", "rs", "o", "p"):
            query = query_for()
            await _handle_editor_action(query, context, action, "post")
            assert query.edit_message_text.await_count == 1, action
        assert [
            a.action
            for a in callbacks(query.edit_message_text.call_args.kwargs["reply_markup"])
        ] == ["pc", "qs", "s", "b"]
        context.bot.send_message.assert_not_awaited()

    async def test_new_tag_options_reject_another_user(self):
        context = context_for()
        await store_draft(context, "post", draft_for())
        query = query_for(user_id=8)
        await _handle_editor_action(query, context, "ht", "post")
        assert query.answer.call_args.kwargs["show_alert"]
        query.edit_message_text.assert_not_awaited()


def test_tag_options_only_offer_relevant_saved_actions():
    draft = draft_for()
    draft["custom_tags"] = ["#doom"]
    session = UserSession(user_id=7)
    key = release_preference_key(TrackMatch(**draft["item"]))
    session.release_tags[key] = ["#doom"]
    with presentation_context(preferences_from_session(session)):
        actions = [
            decode_callback(b.callback_data).action
            for row in editor_tag_options_rows("post", draft)
            for b in row
        ]
        assert "hp" not in actions
        assert "hr" in actions
    with presentation_context():
        actions = [
            decode_callback(b.callback_data).action
            for row in editor_tag_options_rows("post", draft)
            for b in row
        ]
        assert "hp" in actions
        assert "hr" not in actions


def test_settings_sections_return_to_their_parent():
    for section, parent in [
        ("tags", "defaults"),
        ("artwork", "defaults"),
        ("appearance", "defaults"),
        ("layout", "collection"),
        ("grouping", "collection"),
        ("language", "open"),
    ]:
        _, keyboard = preferences_view(
            UserSession(user_id=7), lang="ru", section=section
        )
        assert callbacks(keyboard)[-1].action == parent


def test_catalog_never_displays_escaped_line_breaks():
    assert all(
        "\\n" not in text for entry in STRINGS.values() for text in entry.values()
    )
