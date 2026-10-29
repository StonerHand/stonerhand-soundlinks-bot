"""Live progress, confetti on publish and reactions only on the user's message."""

import unittest
import unittest.mock
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import TelegramError

from music_links_bot.core.i18n import get_text
from music_links_bot.lookup.bot_progress import progress_text
from music_links_bot.tg.message_effects import CELEBRATE, celebrate
from music_links_bot.tg.reactions import should_react


class ProgressTextTests(unittest.TestCase):
    def test_single_lookup_shows_a_phrase_and_no_invented_percentage(self) -> None:
        text = progress_text("ru", "progress_links", seed="7:1")

        self.assertTrue(text.startswith("🔎 "))
        self.assertNotIn("%", text)
        self.assertIn(text[2:], get_text("ru", "progress_fun_links").splitlines())

    def test_collections_add_a_count_line(self) -> None:
        text = progress_text(
            "en", "progress_batch_partial", seed="7:1", done=3, total=5
        )

        # A status with its own sign gets no second one.
        self.assertEqual(text.splitlines()[0], "⚠️ 3 of 5 opened")
        found = progress_text("ru", "progress_batch", seed="7:1", done=2, total=5)
        self.assertEqual(found.splitlines()[0], "🔎 Ссылки · 2/5")

    def test_one_request_keeps_its_voice_and_requests_differ(self) -> None:
        phrases = {
            progress_text("ru", "progress_search", seed=f"7:{n}").splitlines()[-1]
            for n in range(40)
        }

        self.assertEqual(
            progress_text("ru", "progress_links", seed="7:1"),
            progress_text("ru", "progress_links", seed="7:1"),
        )
        self.assertGreater(len(phrases), 1)

    def test_every_phrase_pool_matches_between_languages(self) -> None:
        for pool in ("progress_fun_search", "progress_fun_links", "progress_fun_card"):
            with self.subTest(pool=pool):
                ru = get_text("ru", pool).splitlines()
                en = get_text("en", pool).splitlines()
                self.assertEqual(len(ru), len(en))
                self.assertTrue(all(line.endswith("…") for line in ru + en))


def _query(chat_type: str = "private"):
    message = SimpleNamespace(
        chat=SimpleNamespace(type=chat_type),
        chat_id=7,
        message_id=42,
        delete=AsyncMock(),
        edit_reply_markup=AsyncMock(),
    )
    return SimpleNamespace(message=message)


class CelebrateTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_edits_the_card_in_place_and_reacts(self) -> None:
        bot, query, edit = (
            SimpleNamespace(set_message_reaction=AsyncMock()),
            _query(),
            AsyncMock(),
        )

        self.assertTrue(await celebrate(bot, query, edit=edit))

        edit.assert_awaited_once()
        query.message.delete.assert_not_awaited()  # nothing disappears
        reaction = bot.set_message_reaction.await_args.kwargs
        self.assertEqual((reaction["chat_id"], reaction["message_id"]), (7, 42))
        self.assertEqual(reaction["reaction"][0].emoji, "🎉")

    async def test_a_refused_reaction_keeps_the_edited_card(self) -> None:
        bot = SimpleNamespace(
            set_message_reaction=AsyncMock(side_effect=TelegramError("x"))
        )
        query, edit = _query(), AsyncMock()

        self.assertFalse(await celebrate(bot, query, edit=edit))

        edit.assert_awaited_once()
        query.message.delete.assert_not_awaited()


class EditorPublishCelebrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_publishing_from_the_editor_ends_with_confetti(self) -> None:
        from test_release_119_state import RedisModel, ctx, draft, track

        from music_links_bot.editor import editor_delivery as bot_editor
        from music_links_bot.state.bot_runtime import BotRuntime

        context = ctx(RedisModel())
        context.bot = SimpleNamespace(
            send_message=AsyncMock(), set_message_reaction=AsyncMock()
        )
        context.application.bot_data["runtime"] = BotRuntime(
            context.application.bot_data["kv_store"]
        )
        query = _query()
        query.from_user = SimpleNamespace(id=7)
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        request = bot_editor.EditorActionRequest(
            query=query,
            context=context,
            action="pc",
            draft_id="d1",
            draft=draft(),
            lang="ru",
            track=track(),
        )
        published = SimpleNamespace(message_id=42, link="https://t.me/stonerhand/42")

        with (
            unittest.mock.patch.object(
                bot_editor, "_schedule_mark_posted", new=AsyncMock()
            ),
            unittest.mock.patch.object(bot_editor, "_store_draft", new=AsyncMock()),
        ):
            await bot_editor._finish_editor_publish(request, published)

        # The same card becomes the success screen; nothing is deleted or resent.
        edited = query.edit_message_text.await_args.kwargs
        self.assertIn("Опубликовано", edited["text"])
        self.assertIn("@stonerhand", edited["text"])
        context.bot.send_message.assert_not_awaited()
        query.message.delete.assert_not_awaited()
        reaction = context.bot.set_message_reaction.await_args.kwargs
        self.assertEqual(reaction["reaction"][0].emoji, "🎉")
        self.assertEqual(request.draft["published_message_id"], 42)
        self.assertIn("🎉", query.answer.await_args.args[0])


class ReactionTargetTests(unittest.TestCase):
    def test_only_the_users_own_message_gets_a_reaction(self) -> None:
        typed = SimpleNamespace(callback_query=None)
        tapped = SimpleNamespace(callback_query=object())

        self.assertTrue(should_react(typed, is_private=True))
        self.assertFalse(should_react(tapped, is_private=True))
        self.assertFalse(should_react(typed, is_private=False))


if __name__ == "__main__":
    unittest.main()


class LookupRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_direct_link_costs_one_progress_message_and_one_edit(self) -> None:
        from test_bot import (
            ContextStub,
            EditableReplyStub,
            PrivateSpotifyTrackMessageStub,
            UpdateStub,
        )

        from music_links_bot.lookup.bot_lookup_flow import track_lookup_message

        edits: list[str] = []
        original = EditableReplyStub.edit_text

        async def counting(stub, text, **kwargs):
            edits.append(text)
            return await original(stub, text, **kwargs)

        message = PrivateSpotifyTrackMessageStub()
        with (
            unittest.mock.patch.object(EditableReplyStub, "edit_text", counting),
            unittest.mock.patch("music_links_bot.lookup.bot_stats.record_post"),
            # A slow lookup: the progress line is shown at once.
            unittest.mock.patch(
                "music_links_bot.lookup.bot_lookup_flow.PROGRESS_DELAY_SECONDS", 0
            ),
        ):
            await track_lookup_message(UpdateStub(message), ContextStub())

        # The progress opens at the platform step and is edited once: into
        # the finished card. Every extra edit is a Telegram round trip.
        self.assertEqual(len(message.replies), 1)
        self.assertEqual(len(edits), 1)
        self.assertNotIn("▰", edits[0])


def test_a_stale_selection_still_shows_the_crate_hint() -> None:
    from music_links_bot.chat.crate_view import render_crate

    items = [{"item": {"artist": "Kyuss", "title": "Gardenia", "links": {}}}]
    text, _ = render_crate(items, lang="ru", selected_index=5)

    assert text.endswith(get_text("ru", "crate_hint"))


class ScheduledNoticeTests(unittest.IsolatedAsyncioTestCase):
    def _draft(self, chat_id: int) -> dict:
        return {
            "chat_id": chat_id,
            "lang": "en",
            "item": {"artist": "Sleep", "title": "<Holy>"},
        }

    async def test_the_author_gets_a_link_to_the_scheduled_post(self) -> None:
        from music_links_bot.publishing.publish_queue import _celebrate_job

        send = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send))
        delivered = SimpleNamespace(message_id=9, link=None)

        await _celebrate_job(context, self._draft(7), delivered, "@stonerhand")

        sent = send.await_args.kwargs
        self.assertEqual(sent["message_effect_id"], CELEBRATE)
        self.assertIn("Out on schedule", sent["text"])
        self.assertIn("&lt;Holy&gt;", sent["text"])
        url = sent["reply_markup"].inline_keyboard[0][0].url
        self.assertEqual(url, "https://t.me/stonerhand/9")

    async def test_group_drafts_and_failures_stay_quiet(self) -> None:
        from music_links_bot.publishing.publish_queue import _celebrate_job

        send = AsyncMock(side_effect=TelegramError("blocked"))
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send))

        await _celebrate_job(context, self._draft(-100), True, "@stonerhand")
        send.assert_not_awaited()
        # A blocked bot or a network error never fails the published job.
        await _celebrate_job(context, self._draft(7), True, "@stonerhand")
        send.assert_awaited()


class ProviderErrorTextTests(unittest.IsolatedAsyncioTestCase):
    async def _text(self, provider: str | None) -> str:
        from music_links_bot.chat.bot_error_handlers import (
            WorkflowHooks,
            _reply_with_flow_error,
        )
        from music_links_bot.state.bot_runtime import BotErrorCode, BotFlowError

        message = SimpleNamespace(chat_id=7, reply_text=AsyncMock())
        hooks = WorkflowHooks(
            build_error_keyboard=lambda *args, **kwargs: None,
            try_ephemeral_error=AsyncMock(return_value=False),
            take_placeholder=lambda chat_id: None,
            try_delete_message=AsyncMock(),
            ephemeral_group_replies_enabled=lambda: False,
            send_ephemeral_message=AsyncMock(),
        )
        await _reply_with_flow_error(
            message,
            SimpleNamespace(bot=SimpleNamespace(username="StonerHandBot")),
            BotFlowError(
                BotErrorCode.PROVIDER_UNAVAILABLE, retryable=True, provider=provider
            ),
            hooks=hooks,
            lang="ru",
        )
        return message.reply_text.await_args.args[0]

    async def test_known_services_are_named(self) -> None:
        self.assertIn("<b>SoundCloud</b>", await self._text("soundcloud"))

    async def test_internal_ids_never_reach_the_chat(self) -> None:
        for provider in ("playlists", None):
            with self.subTest(provider=provider):
                text = await self._text(provider)
                self.assertNotIn("playlists", text)
                self.assertIn(get_text("ru", "error_provider"), text)


class ErrorDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def _hooks(self, *, placeholder=None, ephemeral=False, delivered=True):
        from music_links_bot.chat.bot_error_handlers import WorkflowHooks

        return WorkflowHooks(
            build_error_keyboard=lambda *args, **kwargs: "keyboard",
            try_ephemeral_error=AsyncMock(return_value=False),
            take_placeholder=lambda chat_id: placeholder,
            try_delete_message=AsyncMock(),
            ephemeral_group_replies_enabled=lambda: ephemeral,
            send_ephemeral_message=AsyncMock(return_value=delivered),
        )

    def _message(self, chat_type: str = "private"):
        return SimpleNamespace(
            chat=SimpleNamespace(type=chat_type),
            chat_id=-5 if chat_type != "private" else 7,
            message_id=3,
            from_user=SimpleNamespace(id=7),
            reply_text=AsyncMock(),
        )

    def _context(self):
        return SimpleNamespace(bot=SimpleNamespace(username="StonerHandBot", token="t"))

    async def test_the_progress_message_turns_into_the_error(self) -> None:
        from music_links_bot.chat.bot_error_handlers import _reply_with_error

        placeholder = SimpleNamespace(edit_text=AsyncMock())
        message = self._message()

        await _reply_with_error(
            message, self._context(), "oops", hooks=self._hooks(placeholder=placeholder)
        )

        placeholder.edit_text.assert_awaited_once_with("oops", reply_markup="keyboard")
        message.reply_text.assert_not_awaited()

    async def test_an_uneditable_progress_message_is_replaced(self) -> None:
        from music_links_bot.chat.bot_error_handlers import _reply_with_error

        placeholder = SimpleNamespace(
            edit_text=AsyncMock(side_effect=TelegramError("gone"))
        )
        message = self._message()
        hooks = self._hooks(placeholder=placeholder)

        await _reply_with_error(message, self._context(), "oops", hooks=hooks)

        hooks.try_delete_message.assert_awaited_once_with(placeholder)
        message.reply_text.assert_awaited_once_with("oops", reply_markup="keyboard")

    async def test_group_errors_go_privately_to_the_sender(self) -> None:
        from music_links_bot.chat.bot_error_handlers import _try_ephemeral_error

        placeholder = object()
        hooks = self._hooks(placeholder=placeholder, ephemeral=True)

        sent = await _try_ephemeral_error(
            self._message("supergroup"), self._context(), "oops", "kb", hooks=hooks
        )

        self.assertTrue(sent)
        self.assertEqual(hooks.send_ephemeral_message.await_args.args[2], 7)
        hooks.try_delete_message.assert_awaited_once_with(placeholder)

    async def test_private_chats_and_refusals_fall_back_to_a_reply(self) -> None:
        from music_links_bot.chat.bot_error_handlers import _try_ephemeral_error

        private = await _try_ephemeral_error(
            self._message(),
            self._context(),
            "oops",
            "kb",
            hooks=self._hooks(ephemeral=True),
        )
        refused = await _try_ephemeral_error(
            self._message("group"),
            self._context(),
            "oops",
            "kb",
            hooks=self._hooks(ephemeral=True, delivered=False),
        )

        self.assertFalse(private)
        self.assertFalse(refused)
