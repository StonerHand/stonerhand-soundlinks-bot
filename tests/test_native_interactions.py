"""User journeys for guest replies, private panels, copying and stopping work."""

import asyncio
import unittest
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import ChosenInlineResult, Message, Update, User
from telegram.error import BadRequest, TimedOut
from telegram.ext import ApplicationHandlerStop
from test_bot import ContextStub, PrivateMessageStub, UpdateStub

from music_links_bot import bot_lookup
from music_links_bot.bot_native import (
    guest_input,
    guest_message_handler,
    native_update_handler,
)
from music_links_bot.bot_progress import _PLACEHOLDER, start_progress, take_progress
from music_links_bot.inline_feedback import (
    chosen_inline_result_handler,
    feedback_text,
    remember_results,
)
from music_links_bot.keyboards import _build_link_keyboard
from music_links_bot.lookup_control import (
    LookupStopped,
    interruptible,
    search_control,
    stop_lookup,
)
from music_links_bot.lookup_models import LookupBundle
from music_links_bot.lookup_recovery import merge_recovered
from music_links_bot.models import TrackMatch
from music_links_bot.release_panel import (
    add_release_panel,
    copy_rows,
    load_panel,
    release_panel_callback,
    start_release_panel,
)
from music_links_bot.search import SearchCandidate, SearchClient
from music_links_bot.telegram_updates import ALLOWED_UPDATES

URL = "https://open.spotify.com/track/one"
OTHER_URL = "https://open.spotify.com/track/two"


def track(url=URL, title="Dig"):
    return TrackMatch(title=title, artist="From This Point On", links={"spotify": url})


def message(**extra):
    payload = {
        "message_id": 42,
        "date": 1,
        "chat": {"id": 7, "type": "private"},
        "from": {"id": 7, "first_name": "User", "is_bot": False},
        "text": URL,
    }
    payload.update(extra)
    return Message.de_json(payload, None)


class Store:
    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, **kwargs):
        self.data[key] = value
        return True

    async def delete_if_value(self, key, value):
        if self.data.get(key) == value:
            self.data.pop(key)
            return True
        return False

    async def compare_set_required(self, key, expected, value, **kwargs):
        if self.data.get(key) != expected:
            return False
        self.data[key] = value
        return True


class StopTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_lookup_does_not_join_a_cancelling_job(self):
        started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls = 0

        async def resolve(*_args):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaning.set()
                    await release.wait()
            return LookupBundle([track()], [], [], [], [], [])

        data = {"lookup_cache_namespace": self.id()}
        with patch.object(bot_lookup, "_resolve_sources_uncached", resolve):
            first = asyncio.create_task(bot_lookup.resolve_sources(data, [URL]))
            await started.wait()
            first.cancel()
            await cleaning.wait()
            try:
                fresh = await asyncio.wait_for(
                    bot_lookup.resolve_sources(data, [URL]), 1
                )
                self.assertEqual(fresh.item_count, 1)
                self.assertEqual(calls, 2)
            finally:
                release.set()
                await asyncio.gather(first, return_exceptions=True)

    async def test_new_search_does_not_join_a_cancelling_job(self):
        started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        calls = 0
        client = SearchClient()

        async def resolve(*_args):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaning.set()
                    await release.wait()
            return [SearchCandidate(artist="Artist", title="Song", url=URL)]

        try:
            with patch.object(client, "_search_and_cache", resolve):
                first = asyncio.create_task(
                    client.search_release_candidates("Artist - Song")
                )
                await started.wait()
                first.cancel()
                await cleaning.wait()
                try:
                    fresh = await asyncio.wait_for(
                        client.search_release_candidates("Artist - Song"), 1
                    )
                    self.assertEqual(fresh[0].url, URL)
                    self.assertEqual(calls, 2)
                finally:
                    release.set()
                    await asyncio.gather(first, return_exceptions=True)
        finally:
            await client.aclose()

    async def test_native_raw_stop_targets_exact_private_draft(self):
        data = {}
        ctx = SimpleNamespace(application=SimpleNamespace(bot_data=data))
        async with search_control(data, message()) as control:
            raw = {
                "update_id": 1,
                "stopped_message_generation": {
                    "chat": {"id": 7, "type": "private"},
                    "draft_id": 42,
                },
            }
            update = Update.de_json(raw, None)
            with self.assertRaises(ApplicationHandlerStop):
                await native_update_handler(update, ctx)
            self.assertTrue(control.stopped.is_set())
        self.assertFalse(await stop_lookup(data, chat_id=7, draft_id=42))

    async def test_old_or_other_users_stop_cannot_cancel_new_lookup(self):
        data = {}
        async with search_control(data, message()) as control:
            self.assertFalse(await stop_lookup(data, chat_id=8, draft_id=42))
            self.assertFalse(await stop_lookup(data, chat_id=7, draft_id=41))
            self.assertFalse(control.stopped.is_set())

    async def test_stop_reaches_a_different_worker(self):
        store = Store()
        data = {"kv_store": store}
        cancelled = asyncio.Event()

        async def slow():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        async with search_control(data, message()) as control:
            task = asyncio.create_task(interruptible(slow()))
            self.assertTrue(
                await stop_lookup({"kv_store": store}, chat_id=7, draft_id=42)
            )
            with self.assertRaises(LookupStopped):
                await asyncio.wait_for(task, 2)
            self.assertTrue(cancelled.is_set())
        self.assertNotIn(control.key, store.data)

    async def test_stop_keeps_completed_source_and_cancels_unneeded_provider(self):
        slow_started = asyncio.Event()
        cancelled = asyncio.Event()
        fast_done = asyncio.Event()

        async def lookup(url):
            if url == URL:
                fast_done.set()
                return track()
            slow_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        data = {
            "songlink_client": SimpleNamespace(lookup_track=lookup),
            "soundcloud_client": None,
            "lookup_cache_namespace": self.id(),
        }
        async with search_control(data, message()):
            task = asyncio.create_task(
                interruptible(bot_lookup.resolve_sources(data, [URL, OTHER_URL]))
            )
            await asyncio.wait_for(slow_started.wait(), 2)
            await asyncio.wait_for(fast_done.wait(), 2)
            await stop_lookup(data, chat_id=7, draft_id=42)
            with self.assertRaises(LookupStopped) as caught:
                await asyncio.wait_for(task, 2)
        bundle = merge_recovered(
            [URL, OTHER_URL],
            caught.exception.completed,
            LookupBundle([], [], [], [], [], []),
        )
        self.assertEqual([item.title for item in bundle.tracks], ["Dig"])
        self.assertEqual(
            [status.state for status in bundle.statuses], ["success", "unavailable"]
        )
        self.assertTrue(cancelled.is_set())
        self.assertFalse(data["lookup_inflight"])
        self.assertFalse(data["lookup_subscribers"])

    async def test_cancelling_one_subscriber_does_not_cancel_another(self):
        entered = asyncio.Event()
        finish = asyncio.Event()
        lookup = AsyncMock()

        async def resolve(url):
            entered.set()
            await finish.wait()
            return track()

        lookup.side_effect = resolve
        data = {
            "songlink_client": SimpleNamespace(lookup_track=lookup),
            "soundcloud_client": None,
            "lookup_cache_namespace": self.id(),
        }
        first = asyncio.create_task(bot_lookup.resolve_sources(data, [URL]))
        await entered.wait()
        second = asyncio.create_task(bot_lookup.resolve_sources(data, [URL]))
        # Wait until both await the same job, not an arbitrary time delay.
        for _ in range(100):
            if 2 in data.get("lookup_subscribers", {}).values():
                break
            await asyncio.sleep(0)
        self.assertIn(2, data["lookup_subscribers"].values())
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        finish.set()
        self.assertEqual((await second).item_count, 1)
        self.assertEqual(lookup.await_count, 1)

    async def test_progress_created_in_worker_reaches_final_delivery(self):
        msg = message()
        data = {}
        marker = SimpleNamespace(chat_id=7)
        token = _PLACEHOLDER.set(None)
        try:
            with patch.object(Message, "reply_text", AsyncMock(return_value=marker)):
                async with search_control(data, msg):
                    await interruptible(start_progress(msg))
                self.assertIs(take_progress(7), marker)
        finally:
            _PLACEHOLDER.reset(token)

    async def test_complete_private_lookup_reuses_progress_and_creates_editor(self):
        from music_links_bot.bot import track_lookup_message

        msg = PrivateMessageStub()
        msg.message_id = 42
        msg.text = URL
        ctx = ContextStub()
        with patch("music_links_bot.bot_stats.record_matches"):
            await track_lookup_message(UpdateStub(msg), ctx)
        self.assertEqual(len(msg.replies), 1)
        self.assertIn("Transitions", msg.replies[0])
        self.assertTrue(ctx.application.bot_data["drafts"])

    async def test_full_stop_journey_delivers_found_cards_without_publishing(self):
        from music_links_bot.bot import track_lookup_message

        started = asyncio.Event()

        async def lookup(url):
            if url == URL:
                return track()
            started.set()
            await asyncio.Event().wait()

        msg = PrivateMessageStub()
        msg.message_id = 77
        msg.text = URL + "\n" + OTHER_URL
        ctx = ContextStub(songlink_client=SimpleNamespace(lookup_track=lookup))
        ctx.application.bot_data["lookup_cache_namespace"] = self.id()
        with patch("music_links_bot.bot_stats.record_matches"):
            job = asyncio.create_task(track_lookup_message(UpdateStub(msg), ctx))
            await asyncio.wait_for(started.wait(), 2)
            self.assertTrue(
                await stop_lookup(
                    ctx.application.bot_data, chat_id=msg.chat_id, draft_id=77
                )
            )
            await asyncio.wait_for(job, 2)
        self.assertTrue(any("Поиск остановлен" in text for text in msg.replies))
        self.assertTrue(any("Dig" in text for text in msg.replies))
        self.assertEqual(len(ctx.application.bot_data["drafts"]), 1)

    async def test_last_search_subscriber_cancels_network_work(self):
        client = SearchClient()
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def work(*args):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        try:
            with patch.object(client, "_search_and_cache", work):
                task = asyncio.create_task(
                    client.search_release_candidates("Artist Track")
                )
                await started.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(cancelled.is_set())
                self.assertFalse(client._inflight)
        finally:
            await client.aclose()


class GuestTests(unittest.IsolatedAsyncioTestCase):
    async def test_reply_link_and_hidden_link_are_extracted(self):
        reply = message(
            text="Listen",
            entities=[{"type": "text_link", "offset": 0, "length": 6, "url": URL}],
        )
        msg = message(text="@StonerHandBot!", reply_to_message=reply.to_dict())
        self.assertEqual(guest_input(msg, "StonerHandBot")[1], [URL])

    async def test_guest_uses_one_classic_reply_with_no_private_editor_state(self):
        ctx = ContextStub()
        msg = message(text="@StonerHandBot " + URL, guest_query_id="guest-1")
        with patch(
            "music_links_bot.bot_native.TelegramApiGateway.request",
            AsyncMock(return_value={}),
        ) as send:
            await guest_message_handler(msg, ctx)
        self.assertEqual(send.await_count, 1)
        method, body = send.await_args.args
        self.assertEqual(method, "answerGuestQuery")
        self.assertEqual(body["guest_query_id"], "guest-1")
        self.assertIn("message_text", body["result"]["input_message_content"])
        self.assertFalse(ctx.application.bot_data["drafts"])

    async def test_ambiguous_search_offers_choices_instead_of_guessing(self):
        candidates = [
            SearchCandidate(URL, "Track A", "Artist"),
            SearchCandidate(OTHER_URL, "Track B", "Artist"),
        ]
        ctx = ContextStub(
            search_client=SimpleNamespace(
                search_release_candidates=AsyncMock(return_value=candidates)
            )
        )
        with patch(
            "music_links_bot.bot_native.TelegramApiGateway.request",
            AsyncMock(return_value={}),
        ) as send:
            await guest_message_handler(
                message(text="@StonerHandBot artist track", guest_query_id="g"), ctx
            )
        result = send.await_args.args[1]["result"]
        self.assertIn("Выбери", result["input_message_content"]["message_text"])
        self.assertEqual(len(result["reply_markup"]["inline_keyboard"]), 2)

    async def test_guest_does_not_retry_unknown_send_outcome(self):
        ctx = ContextStub()
        with patch(
            "music_links_bot.bot_native.TelegramApiGateway.request",
            AsyncMock(side_effect=TimedOut()),
        ) as send:
            with self.assertRaises(TimedOut):
                await guest_message_handler(message(guest_query_id="g"), ctx)
        self.assertEqual(send.await_count, 1)

    async def test_guest_update_is_routed_without_entering_normal_lookup(self):
        update = Update.de_json(
            {"update_id": 1, "guest_message": message(guest_query_id="g").to_dict()},
            None,
        )
        with patch(
            "music_links_bot.bot_native.guest_message_handler", AsyncMock()
        ) as handle:
            with self.assertRaises(ApplicationHandlerStop):
                await native_update_handler(update, ContextStub())
            handle.assert_awaited_once()
        self.assertTrue(
            {"guest_message", "chosen_inline_result", "stopped_message_generation"}
            <= set(ALLOWED_UPDATES)
        )


class PanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_panel_is_stable_and_keeps_full_copy_text(self):
        ctx = ContextStub()
        keyboard = _build_link_keyboard(track().links)
        one = await add_release_panel(keyboard, ctx, track())
        two = await add_release_panel(keyboard, ctx, track())
        self.assertEqual(one, two)
        token = one.inline_keyboard[-1][0].callback_data.rsplit(":", 1)[1]
        self.assertEqual(asdict(await load_panel(ctx, token)), asdict(track()))
        self.assertEqual(
            copy_rows(track(), lang="ru")[0][0].copy_text.text,
            "From This Point On — Dig",
        )
        self.assertEqual(len(copy_rows(track(title="🎧" * 130), lang="ru")), 1)

    async def test_group_panel_is_private_and_never_edits_shared_post(self):
        ctx = ContextStub()
        keyboard = await add_release_panel(
            _build_link_keyboard(track().links), ctx, track()
        )
        q = SimpleNamespace(
            from_user=User(7, "User", False),
            id="q",
            data=keyboard.inline_keyboard[-1][0].callback_data,
            message=message(chat={"id": -123, "type": "supergroup"}),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        with patch(
            "music_links_bot.release_panel.TelegramApiGateway.request",
            AsyncMock(return_value=True),
        ) as send:
            await release_panel_callback(SimpleNamespace(callback_query=q), ctx)
        data = send.await_args.args[1]
        self.assertEqual(data["chat_id"], -123)
        self.assertEqual(
            data["ephemeral_message_parameters"],
            {
                "receiver_user_id": 7,
                "callback_query_id": "q",
                "replace_callback_query_message": True,
            },
        )
        q.edit_message_text.assert_not_called()

    async def test_existing_ephemeral_panel_uses_ephemeral_edit(self):
        ctx = ContextStub()
        keyboard = await add_release_panel(
            _build_link_keyboard(track().links), ctx, track()
        )
        q = SimpleNamespace(
            from_user=User(7, "User", False),
            id="q",
            data=keyboard.inline_keyboard[-1][0].callback_data,
            message=message(
                chat={"id": -123, "type": "supergroup"}, ephemeral_message_id=88
            ),
            answer=AsyncMock(),
        )
        with patch(
            "music_links_bot.release_panel.TelegramApiGateway.request",
            AsyncMock(return_value=True),
        ) as send:
            await release_panel_callback(SimpleNamespace(callback_query=q), ctx)
        self.assertEqual(send.await_args.args[0], "editEphemeralMessageText")
        self.assertEqual(send.await_args.args[1]["ephemeral_message_id"], 88)

    async def test_overlay_failure_only_offers_private_deep_link(self):
        ctx = ContextStub()
        keyboard = await add_release_panel(
            _build_link_keyboard(track().links), ctx, track()
        )
        q = SimpleNamespace(
            from_user=User(7, "User", False),
            id="q",
            data=keyboard.inline_keyboard[-1][0].callback_data,
            message=message(chat={"id": -123, "type": "supergroup"}),
            answer=AsyncMock(),
        )
        with patch(
            "music_links_bot.release_panel.TelegramApiGateway.request",
            AsyncMock(side_effect=BadRequest("unsupported")),
        ) as send:
            await release_panel_callback(SimpleNamespace(callback_query=q), ctx)
        self.assertEqual(send.await_count, 1)
        self.assertIn("?start=release_", q.answer.await_args.kwargs["url"])

    async def test_inline_panel_deep_link_opens_details_in_private_chat(self):
        ctx = ContextStub()
        keyboard = await add_release_panel(
            _build_link_keyboard(track().links), ctx, track(), inline=True
        )
        ctx.args = [keyboard.inline_keyboard[-1][0].url.split("?start=", 1)[1]]
        with patch.object(Message, "reply_text", AsyncMock()) as send:
            self.assertTrue(
                await start_release_panel(Update(1, message=message()), ctx)
            )
        self.assertIn("Dig", send.await_args.args[0])
        self.assertEqual(
            send.await_args.kwargs["reply_markup"]
            .inline_keyboard[-1][0]
            .copy_text.text,
            URL,
        )


class FeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_chosen_results_are_counted_once_without_query_or_identity(self):
        ctx = ContextStub()
        await remember_results(
            ctx.application.bot_data,
            [SimpleNamespace(id="result-1", title="Artist — Track")],
        )
        update = Update(
            2,
            chosen_inline_result=ChosenInlineResult(
                "result-1", User(77777, "Private Name", False), "private query"
            ),
        )
        await chosen_inline_result_handler(update, ctx)
        await chosen_inline_result_handler(update, ctx)
        text = await feedback_text(ctx.application.bot_data)
        self.assertIn("Artist — Track — 1", text)
        data = repr(
            {
                key: value
                for key, value in ctx.application.bot_data.items()
                if key.startswith("inline_")
            }
        )
        for forbidden in ("77777", "Private Name", "private query"):
            self.assertNotIn(forbidden, data)

    async def test_unknown_result_counts_as_anonymous_without_echoing_query(self):
        ctx = ContextStub()
        update = Update(
            3,
            chosen_inline_result=ChosenInlineResult(
                "expired", User(7, "User", False), "secret"
            ),
        )
        await chosen_inline_result_handler(update, ctx)
        self.assertNotIn("secret", await feedback_text(ctx.application.bot_data))
