import time
import unittest
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import InlineKeyboardMarkup
from test_release_119_state import RedisModel, ctx, draft, track

from music_links_bot.bot_editor_state import reset_original, restore_setting_state
from music_links_bot.bot_recent import render_drafts_view
from music_links_bot.bot_runtime import BotRuntime, UserSession
from music_links_bot.bot_storage import load_draft, load_drafts, store_draft
from music_links_bot.bot_ui import editor_rows, version_editor_keyboard
from music_links_bot.bot_workspace import handle_workspace_action, tag_explanation
from music_links_bot.input_routing import collection_input, guard_input
from music_links_bot.lookup_models import LookupBundle, SourceStatus
from music_links_bot.lookup_recovery import capture_sources, completed_sources
from music_links_bot.release_preferences import (
    PresentationPreferences,
    presentation_context,
    release_preference_key,
)
from music_links_bot.release_tags import build_collection_hashtags


def query():
    message = SimpleNamespace(
        chat=SimpleNamespace(type="private"),
        chat_id=7,
        message_id=3,
        reply_text=AsyncMock(return_value=SimpleNamespace(message_id=4)),
    )
    return SimpleNamespace(
        from_user=SimpleNamespace(id=7, language_code="ru"),
        message=message,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )


class Release119Journeys(unittest.IsolatedAsyncioTestCase):
    async def test_long_post_keeps_editor_within_telegram_limit_without_changing_intro(
        self,
    ):
        from music_links_bot.editor_view import render_track_draft
        from music_links_bot.publication_budget import visible_length

        value = draft()
        value["item"].update(title="Long title " * 90, artist="Artist " * 90)
        value["custom_tags"] = ["#" + str(i) + "a" * 60 for i in range(20)]
        value.update(
            prefix="<blockquote>" + "Text " * 600 + "</blockquote>\n\n", quote=True
        )
        original = value["prefix"]
        text, keyboard = render_track_draft(
            value, ctx(RedisModel()), draft_id="d", settings=True
        )
        self.assertLessEqual(visible_length(text), 4096)
        self.assertIn("сокращённый вид", text)
        self.assertEqual(value["prefix"], original)
        self.assertTrue(keyboard.inline_keyboard)

    async def test_explicit_new_collection_does_not_append_to_existing_crate(self):
        from music_links_bot.bot import _send_track_matches

        context = ctx(RedisModel())
        context.bot = SimpleNamespace()
        q = query()
        token = collection_input.set("new")
        try:
            with (
                patch(
                    "music_links_bot.bot._add_track_drafts_to_crate", AsyncMock()
                ) as add,
                patch("music_links_bot.bot._send_track_result", AsyncMock()) as send,
                patch("music_links_bot.bot._record_matches_safely"),
            ):
                await _send_track_matches(
                    q.message,
                    context,
                    [track(0), track(1)],
                    is_private=True,
                    user_id=7,
                    user_prefix="",
                    lang="ru",
                    include_channel_button=False,
                    include_hashtags=True,
                )
                add.assert_not_called()
                send.assert_awaited_once()
                self.assertEqual(send.await_args.kwargs["found_count"], 2)
        finally:
            collection_input.reset(token)

    async def test_replace_does_not_delete_existing_post_on_uncertain_send(self):
        from music_links_bot.bot import _run_primary_editor_action
        from music_links_bot.delivery_receipts import DeliveryBlockedError

        context = ctx(RedisModel())
        context.application.bot_data["admin_chat_id"] = 7
        request = SimpleNamespace(
            action="x",
            context=context,
            user_id=7,
            draft=draft(),
            track=track(),
            query=query(),
            lang="ru",
            draft_id="d",
        )
        with (
            patch(
                "music_links_bot.bot._find_posted_record",
                AsyncMock(return_value={"message_id": 1}),
            ),
            patch(
                "music_links_bot.bot._publish_draft",
                AsyncMock(side_effect=DeliveryBlockedError({"status": "uncertain"})),
            ),
            patch(
                "music_links_bot.bot._delete_duplicate_editor_post", AsyncMock()
            ) as remove,
        ):
            with self.assertRaises(DeliveryBlockedError):
                await _run_primary_editor_action(request)
            remove.assert_not_called()

    async def test_expired_saved_posts_do_not_exhaust_save_limit(self):
        context = ctx(RedisModel())
        runtime = BotRuntime(context.application.bot_data["kv_store"])
        context.application.bot_data["runtime"] = runtime
        session = await runtime.get_session(7)
        session.saved_draft_ids = [str(i) for i in range(30)]
        await runtime.save_session(session)
        value = draft()
        await store_draft(context, "d", value)
        await handle_workspace_action(
            SimpleNamespace(
                action="sv",
                context=context,
                user_id=7,
                draft=value,
                draft_id="d",
                track=track(),
                query=query(),
                lang="ru",
            )
        )
        self.assertEqual(
            (
                await BotRuntime(context.application.bot_data["kv_store"]).get_session(
                    7
                )
            ).saved_draft_ids,
            ["d"],
        )

    async def test_saved_post_is_pinned_and_restored_after_restart(self):
        context = ctx(RedisModel())
        context.application.bot_data["runtime"] = runtime = BotRuntime(
            context.application.bot_data["kv_store"]
        )
        value = draft()
        await store_draft(context, "saved", value)
        session = await runtime.get_session(7)
        session.recent_draft_ids = ["saved"]
        await runtime.save_session(session)
        request = SimpleNamespace(
            action="sv",
            draft=value,
            draft_id="saved",
            user_id=7,
            lang="ru",
            context=context,
            query=query(),
            track=track(),
        )
        self.assertTrue(await handle_workspace_action(request))
        restored = await BotRuntime(
            context.application.bot_data["kv_store"]
        ).get_session(7)
        self.assertEqual(restored.saved_draft_ids, ["saved"])
        self.assertGreater(
            (await load_draft(context, "saved"))["expires_at"], time.time() + 89 * 86400
        )
        request.draft = await load_draft(context, "saved")
        await handle_workspace_action(request)
        self.assertFalse((await load_draft(context, "saved")).get("saved_at"))

    async def test_original_restore_and_undo_do_not_change_delivery_history(self):
        context = ctx(RedisModel())
        value = draft()
        await store_draft(context, "d", value)
        value.update(
            prefix="my new intro", quote=True, custom_tags=["#custom"], published_at=123
        )
        self.assertTrue(reset_original(value))
        self.assertEqual(value["prefix"], "")
        self.assertEqual(value["published_at"], 123)
        self.assertTrue(restore_setting_state(value))
        self.assertEqual(value["prefix"], "my new intro")
        self.assertEqual(value["custom_tags"], ["#custom"])

    async def test_new_url_during_intro_input_does_not_overwrite_draft(self):
        context = ctx(RedisModel())
        runtime = BotRuntime(context.application.bot_data["kv_store"])
        context.application.bot_data["runtime"] = runtime
        session = await runtime.get_session(7)
        session.pending_input = {
            "kind": "intro",
            "draft_id": "d",
            "created_at": int(time.time()),
            "prompt_message_id": 20,
        }
        await runtime.save_session(session)
        q = query()
        update = SimpleNamespace(
            effective_user=q.from_user, effective_message=q.message
        )
        self.assertTrue(
            await guard_input(
                update, context, text="https://open.spotify.com/track/new"
            )
        )
        markup = q.message.reply_text.await_args.kwargs["reply_markup"]
        self.assertEqual(
            [row[0].callback_data.split("|")[2] for row in markup.inline_keyboard],
            ["new", "add", "back"],
        )
        self.assertEqual((await runtime.get_session(7)).pending_input["draft_id"], "d")

    async def test_explicit_collection_input_is_consumed_once(self):
        context = ctx(RedisModel())
        runtime = BotRuntime(context.application.bot_data["kv_store"])
        context.application.bot_data["runtime"] = runtime
        session = await runtime.get_session(7)
        session.pending_input = {
            "kind": "collection_links",
            "created_at": int(time.time()),
        }
        await runtime.save_session(session)
        q = query()
        token = collection_input.set("")
        try:
            self.assertFalse(
                await guard_input(
                    SimpleNamespace(
                        effective_user=q.from_user, effective_message=q.message
                    ),
                    context,
                    text="https://open.spotify.com/track/new",
                )
            )
            self.assertEqual(collection_input.get(), "add")
            self.assertFalse((await runtime.get_session(7)).pending_input)
        finally:
            collection_input.reset(token)

    async def test_library_filters_search_owner_and_deleted_posts_in_one_batch(self):
        context = ctx(RedisModel())
        for i in range(3):
            value = draft()
            value["item"]["title"] = f"Release {i}"
            if i == 1:
                value["published_at"] = 1
            if i == 2:
                value["chat_id"] = 8
            await store_draft(context, str(i), value)
        text, keyboard = await render_drafts_view(
            context,
            user_id=7,
            lang="ru",
            draft_ids=["0", "1", "2", "invalid|id"],
            load_draft=load_draft,
            load_many=load_drafts,
            filter_by="published",
            search="Release",
        )
        self.assertIn("Release 1", text)
        self.assertNotIn("Release 0", text)
        self.assertNotIn("Release 2", text)
        self.assertEqual(context.application.bot_data["kv_store"].batch_calls, 1)
        self.assertTrue(all(len(row) <= 2 for row in keyboard.inline_keyboard))

    async def test_stale_editor_button_refreshes_without_applying_toggle(self):
        from music_links_bot.bot import _handle_editor_action

        context = ctx(RedisModel())
        value = draft()
        await store_draft(context, "d", value)
        await store_draft(context, "d", value)
        q = query()
        await _handle_editor_action(q, context, "h", "d~1")
        self.assertTrue((await load_draft(context, "d"))["hashtags"])
        self.assertTrue(q.answer.await_args.kwargs["show_alert"])
        self.assertTrue(q.edit_message_text.called)

    async def test_retry_resolves_only_failed_source_and_restores_original_order(self):
        from music_links_bot.bot_lookup import resolve_sources

        tracks = [track(i) for i in range(3)]
        urls = [t.links["spotify"] for t in tracks]
        partial = LookupBundle(
            [tracks[0], tracks[2]],
            [urls[1]],
            [],
            [],
            [],
            [],
            [
                SourceStatus(urls[0], "songlink", "success"),
                SourceStatus(urls[1], "songlink", "unavailable"),
                SourceStatus(urls[2], "songlink", "success"),
            ],
        )
        fresh = LookupBundle(
            [tracks[1]],
            [],
            [],
            [],
            [],
            [],
            [SourceStatus(urls[1], "songlink", "success")],
        )
        token = completed_sources.set(capture_sources(partial))
        try:
            with (
                patch(
                    "music_links_bot.bot_lookup.get_cached_lookup",
                    AsyncMock(return_value=None),
                ),
                patch(
                    "music_links_bot.bot_lookup._resolve_sources_uncached",
                    AsyncMock(return_value=fresh),
                ) as resolver,
            ):
                restored = await resolve_sources({}, urls)
                self.assertEqual(resolver.await_args.args[1], [urls[1]])
                self.assertEqual(
                    [t.title for t in restored.tracks], [t.title for t in tracks]
                )
                self.assertTrue(restored.is_complete_for(urls))
        finally:
            completed_sources.reset(token)

    async def test_saved_custom_tags_are_not_misrepresented_as_a_genre(self):
        tracks = [track(0), track(1)]
        prefs = PresentationPreferences(
            tags={
                release_preference_key(t): ["#stonerhand", "#track", "#favourite"]
                for t in tracks
            }
        )
        with presentation_context(prefs):
            self.assertNotIn("#favourite", build_collection_hashtags(tracks))

    async def test_tag_explanation_distinguishes_manual_and_unknown(self):
        value = draft()
        value["custom_tags"] = ["#favourite"]
        text = tag_explanation(value, track(), "ru")
        self.assertIn("твой выбор", text)
        self.assertIn("нет подтверждённых данных", text)
        self.assertIn("#track", text)

    async def test_versioned_controls_fit_telegram_limit_with_longest_ids(self):
        value = draft()
        value["revision"] = 9999999999
        keyboard = version_editor_keyboard(
            InlineKeyboardMarkup(editor_rows("a" * 32, value, settings=True)), value
        )
        for row in keyboard.inline_keyboard:
            for item in row:
                self.assertLessEqual(len(item.callback_data.encode()), 64)

    async def test_legacy_session_defaults_and_new_input_modes_survive_serialization(
        self,
    ):
        restored = UserSession.from_dict({"user_id": 7})
        self.assertEqual(restored.saved_draft_ids, [])
        self.assertEqual(restored.draft_filter, "all")
        restored.pending_input = {
            "kind": "collection_replace",
            "release_key": "a" * 16,
            "created_at": 123,
        }
        self.assertEqual(
            UserSession.from_dict(asdict(restored)).pending_input["release_key"],
            "a" * 16,
        )
