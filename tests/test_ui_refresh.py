from __future__ import annotations

import asyncio
import copy
import time
import unittest
from dataclasses import asdict
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import Chat, Message, Update, User
from telegram.ext import Application

from music_links_bot.bot import _handle_editor_action
from music_links_bot.bot_builder import format_schedule_datetime
from music_links_bot.bot_editor_state import remember_draft
from music_links_bot.bot_preferences import (
    LocalizedApplication,
    apply_preferences,
    dispatch_preferences,
    preferences_view,
)
from music_links_bot.bot_recent import render_drafts_view, render_recent_view
from music_links_bot.bot_runtime import (
    BotRuntime,
    CallbackAction,
    UserSession,
    decode_callback,
)
from music_links_bot.bot_storage import load_draft, store_draft
from music_links_bot.bot_ui import (
    editor_more_rows,
    editor_overflow_rows,
    editor_schedule_rows,
)
from music_links_bot.draft_model import new_track_draft
from music_links_bot.i18n import (
    get_text,
    language_context,
    preferred_language,
    resolve_lang,
)
from music_links_bot.models import TrackMatch
from music_links_bot.publish_queue import (
    add_job,
    load_jobs,
    process_due_jobs,
    remove_job,
)


def draft_for(user_id=7):
    return new_track_draft(
        TrackMatch(
            artist="Sleep",
            title="Dragonaut",
            links={"spotify": "https://open.spotify.com/track/a"},
        ),
        chat_id=user_id,
        lang="ru",
        can_publish=True,
    )


def context_for(**data):
    return SimpleNamespace(
        application=SimpleNamespace(
            bot_data={"admin_chat_id": 7, "runtime": BotRuntime(), **data}
        ),
        bot=SimpleNamespace(),
    )


def query_for(user_id=7):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id, language_code="ru"),
        message=SimpleNamespace(chat_id=user_id),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )


class MemoryKV:
    def __init__(self):
        self.values = {}

    async def get_json(self, key):
        return copy.deepcopy(self.values.get(key))

    async def set_json(self, key, value, **kwargs):
        self.values[key] = copy.deepcopy(value)
        return True


class PreferencesTests(unittest.IsolatedAsyncioTestCase):
    async def test_defaults_and_language_survive_restart_and_are_user_scoped(self):
        kv = MemoryKV()
        runtime = BotRuntime(kv)
        context = context_for(runtime=runtime)
        query = query_for()
        with language_context(None):
            for action, value in (
                ("language", "en"),
                ("appearance", "minimal"),
                ("tags", "off"),
            ):
                await dispatch_preferences(
                    query, context, CallbackAction("prefs", action, value)
                )
            self.assertIn(
                "New post tags", query.edit_message_text.call_args.kwargs["text"]
            )
        restarted = BotRuntime(kv)
        saved = await restarted.get_session(7, lang="ru")
        self.assertEqual(
            (saved.preferred_lang, saved.default_preset, saved.default_hashtags),
            ("en", "minimal", "off"),
        )
        draft = draft_for()
        draft["prefix"] = "My original intro"
        apply_preferences(draft, saved)
        self.assertEqual(draft["lang"], "en")
        self.assertFalse(draft["large_preview"])
        self.assertFalse(draft["hashtags"])
        self.assertEqual(draft["prefix"], "My original intro")
        other = draft_for(8)
        apply_preferences(other, await restarted.get_session(8))
        self.assertTrue(other["hashtags"])
        self.assertTrue(other["large_preview"])

    async def test_invalid_settings_callbacks_do_not_change_preferences(self):
        context = context_for()
        with language_context(None):
            await dispatch_preferences(
                query_for(), context, CallbackAction("prefs", "language", "de")
            )
        self.assertEqual(
            (
                await context.application.bot_data["runtime"].get_session(7)
            ).preferred_lang,
            "",
        )
        session = UserSession.from_dict(
            {
                "user_id": 7,
                "preferred_lang": [],
                "default_preset": "bogus",
                "default_hashtags": False,
            }
        )
        self.assertEqual(
            (session.preferred_lang, session.default_preset, session.default_hashtags),
            ("", "", ""),
        )

    async def test_language_is_scoped_to_concurrent_updates_and_reset_on_error(self):
        app = (
            Application.builder()
            .application_class(LocalizedApplication)
            .token("123:TEST")
            .build()
        )
        runtime = BotRuntime()
        (await runtime.get_session(7)).preferred_lang = "en"
        (await runtime.get_session(8)).preferred_lang = "ru"
        app.bot_data["runtime"] = runtime
        values = {}

        async def capture(_app, update):
            await asyncio.sleep(0)
            values[update.effective_user.id] = (
                resolve_lang("ru"),
                get_text("ru", "home_create"),
            )
            if update.effective_user.id == 7:
                raise ValueError("handler failed")

        def update_for(user_id):
            return Update(
                user_id,
                message=Message(
                    user_id,
                    datetime.now(timezone.utc),
                    Chat(user_id, "private"),
                    from_user=User(user_id, "Listener", False, language_code="ru"),
                ),
            )

        with (
            language_context(None),
            patch.object(Application, "process_update", capture),
        ):
            results = await asyncio.gather(
                *(app.process_update(update_for(user_id)) for user_id in (7, 8)),
                return_exceptions=True,
            )
            self.assertIsInstance(results[0], ValueError)
            self.assertEqual(
                values, {7: ("en", "➕ New post"), 8: ("ru", "➕ Новый пост")}
            )
            self.assertIsNone(preferred_language.get())

    def test_default_choices_do_not_rewrite_existing_draft(self):
        existing = draft_for()
        session = UserSession(user_id=7, default_preset="minimal")
        preferences_view(session, lang="ru")
        self.assertTrue(existing["large_preview"])
        self.assertEqual(existing["preset"], "cover")


class EditorJourneyTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_groups_and_focused_send_menu_have_working_destinations(
        self,
    ):
        context = context_for()
        await store_draft(context, "card", draft_for())
        query = query_for()
        for action, heading in (
            ("m", "Sleep"),
            ("ap", "Обложка поста"),
            ("tx", "Текст"),
            ("ls", "Кнопки поста"),
            ("tools", "Ещё"),
            ("o", "Куда отправить"),
        ):
            with self.subTest(action=action):
                await _handle_editor_action(query, context, action, "card")
                self.assertIn(heading, query.edit_message_text.call_args.kwargs["text"])
        actions = [
            decode_callback(button.callback_data).action
            for row in editor_overflow_rows("card", draft_for())
            for button in row
        ]
        self.assertEqual(actions, ["s", "p", "b"])
        self.assertNotIn("dc", actions)
        rows = editor_more_rows("card", draft_for())
        self.assertTrue(all(len(row) <= 2 for row in rows))

    async def test_schedule_uses_displayed_instant_and_rejects_old_keyboard(self):
        # A card saved before editor_draft_id existed must also be idempotent.
        context = context_for(drafts={"card": draft_for()})
        query = query_for()
        now = datetime.now(timezone.utc)
        rows = editor_schedule_rows(
            "card", draft_for(), timezone_name="Europe/Moscow", now=now
        )
        parsed = decode_callback(rows[0][0].callback_data)
        timestamp = int(parsed.payload.split(":")[1])
        self.assertEqual(rows[0][0].text, format_schedule_datetime(timestamp))
        with patch("music_links_bot.bot.time.time", return_value=now.timestamp() + 60):
            await _handle_editor_action(query, context, parsed.action, parsed.payload)
            await _handle_editor_action(query, context, parsed.action, parsed.payload)
        self.assertEqual(len(await load_jobs(context)), 1)
        self.assertEqual((await load_jobs(context))[0]["publish_at"], timestamp)
        self.assertEqual((await load_draft(context, "card"))["scheduled_at"], timestamp)
        with patch("music_links_bot.bot.time.time", return_value=timestamp + 1):
            await _handle_editor_action(query, context, parsed.action, parsed.payload)
        self.assertEqual(len(await load_jobs(context)), 1)
        self.assertIn("уже недоступно", query.answer.call_args.args[0])

    async def test_schedule_rejects_forged_owner_invalid_and_far_future_times(self):
        context = context_for()
        await store_draft(context, "card", draft_for())
        for query, payload in (
            (query_for(8), f"card:{int(time.time()) + 3600}"),
            (query_for(), "card:abc"),
            (query_for(), "card:99999999999"),
        ):
            await _handle_editor_action(query, context, "qt", payload)
        self.assertEqual(await load_jobs(context), [])


class DraftLibraryTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_draft_gets_its_storage_id_after_restart(self):
        kv = MemoryKV()
        kv.values["draft:card"] = draft_for()
        draft = await load_draft(context_for(kv_store=kv), "card")
        self.assertEqual(draft["editor_draft_id"], "card")

    async def test_pagination_filters_deleted_expired_and_other_users_and_survives_restart(
        self,
    ):
        context = context_for()
        session = UserSession(user_id=7)
        for number in range(13):
            draft = draft_for(8 if number == 12 else 7)
            draft["item"]["title"] = f"Release {number}"
            draft["deleted_at"] = 1 if number == 11 else 0
            await store_draft(context, f"draft{number}", draft)
            remember_draft(session, f"draft{number}")
        restored = UserSession.from_dict(asdict(session))
        self.assertEqual(len(restored.recent_draft_ids), 13)
        text, keyboard = await render_drafts_view(
            context,
            user_id=7,
            lang="ru",
            draft_ids=restored.recent_draft_ids,
            load_draft=load_draft,
            page=1,
        )
        self.assertIn("Страница 2 из 3", text)
        self.assertNotIn("Release 11", text)
        self.assertNotIn("Release 12", text)
        self.assertIn(
            "Release 5",
            next(
                b.text
                for row in keyboard.inline_keyboard
                for b in row
                if (b.callback_data or "").startswith("v2|editor|")
            ),
        )
        self.assertEqual(
            keyboard.inline_keyboard[-2][0].callback_data, "v2|menu|drafts|0"
        )
        self.assertEqual(
            keyboard.inline_keyboard[-2][1].callback_data, "v2|menu|drafts|2"
        )

    async def test_cancelled_scheduled_item_reverts_to_draft_status(self):
        context = context_for()
        draft = draft_for()
        draft["scheduled_at"] = int(time.time()) + 3600
        await store_draft(context, "card", draft)
        job = await add_job(
            context, await load_draft(context, "card"), draft["scheduled_at"]
        )
        text, _ = await render_drafts_view(
            context, user_id=7, lang="ru", draft_ids=["card"], load_draft=load_draft
        )
        self.assertIn("Запланирован", text)
        await remove_job(context, job["id"])
        text, _ = await render_drafts_view(
            context, user_id=7, lang="ru", draft_ids=["card"], load_draft=load_draft
        )
        self.assertNotIn("Запланирован", text)
        self.assertIn("Черновик", text)

    async def test_recent_releases_are_paged(self):
        context = context_for(
            bot_history={
                7: [
                    {
                        "title": f"Release {n}",
                        "artist": "Artist",
                        "source_url": f"https://open.spotify.com/track/{n}",
                    }
                    for n in range(10)
                ]
            }
        )
        text, keyboard = await render_recent_view(context, user_id=7, lang="ru", page=1)
        self.assertIn("Release 9", text)
        self.assertEqual(
            keyboard.inline_keyboard[-2][0].callback_data, "v2|menu|recent|0"
        )

    async def test_queue_success_updates_linked_draft(self):
        context = context_for()
        await store_draft(context, "card", draft_for())
        await add_job(context, await load_draft(context, "card"), 100)
        service = SimpleNamespace(
            publish=AsyncMock(return_value=SimpleNamespace(message_id=1)),
            confirmed_not_sent=False,
        )
        with patch(
            "music_links_bot.publication_service.PublicationService",
            return_value=service,
        ):
            count = await process_due_jobs(context, now=101)
        self.assertEqual(count, 1)
        self.assertEqual((await load_draft(context, "card"))["published_at"], 101)
        self.assertEqual(await load_jobs(context), [])

    async def test_queue_delivery_does_not_restore_removed_editor_cards(self):
        for deleted in (False, True):
            with self.subTest(deleted=deleted):
                context = context_for()
                await store_draft(context, "card", draft_for())
                await add_job(context, await load_draft(context, "card"), 100)
                if deleted:
                    context.application.bot_data["drafts"]["card"]["deleted_at"] = 90
                else:
                    context.application.bot_data["drafts"].clear()
                service = SimpleNamespace(
                    publish=AsyncMock(return_value=SimpleNamespace(message_id=1)),
                    confirmed_not_sent=False,
                )
                with patch(
                    "music_links_bot.publication_service.PublicationService",
                    return_value=service,
                ):
                    self.assertEqual(await process_due_jobs(context, now=101), 1)
                draft = await load_draft(context, "card")
                if deleted:
                    self.assertEqual(draft["deleted_at"], 90)
                    self.assertNotIn("published_at", draft)
                else:
                    self.assertIsNone(draft)
