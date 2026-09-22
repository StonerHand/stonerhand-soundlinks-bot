"""Regression tests across real PTB dispatch and Redis Lua transactions."""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import httpx
from redis.exceptions import RedisError
from telegram.error import BadRequest, NetworkError, TimedOut
from telegram.ext import Application, TypeHandler

from api import telegram as webhook
from music_links_bot import ephemeral, mixed_post, publish_queue
from music_links_bot.bot_preferences import LocalizedApplication
from music_links_bot.bot_stats import record_tracks
from music_links_bot.bot_storage import (
    load_search_selection,
    store_draft,
    store_retry_sources,
    store_search_selection,
)
from music_links_bot.constants import STATS_KV_KEY
from music_links_bot.draft_model import new_track_draft
from music_links_bot.kvstore import KVStore, KVUnavailableError
from music_links_bot.loop_runner import start_background_loop, stop_background_loop
from music_links_bot.models import TrackMatch
from music_links_bot.privacy import delete_user_data
from music_links_bot.update_execution import (
    DeliveryAwareBot,
    UpdateExecution,
    current_execution,
)
from music_links_bot.user_state import user_state_scope


def track():
    return TrackMatch(
        artist="Artist",
        title="Song",
        links={"spotify": "https://open.spotify.com/track/x"},
        thumbnail_url="https://i.scdn.co/image/a",
    )


def context(kv=None):
    return SimpleNamespace(
        application=SimpleNamespace(bot_data={"kv_store": kv}), bot=AsyncMock()
    )


class RedisREST(KVStore):
    """Use production KVStore encoding and Lua against an isolated Redis engine."""

    def __init__(self):
        self.redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        self._client = httpx.AsyncClient(
            base_url="https://redis.test", transport=httpx.MockTransport(self.respond)
        )

    async def respond(self, request):
        command = json.loads(request.content)
        try:
            result = await self.redis.execute_command(*command)
            if command[0] == "SET" and result is True:
                result = "OK"
            return httpx.Response(200, json={"result": result})
        except RedisError as exc:
            return httpx.Response(200, json={"error": str(exc)})

    async def aclose(self):
        await super().aclose()
        await self.redis.aclose()


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def mixed(self, bot):
        return await mixed_post.send_track_video_album(
            bot,
            chat_id=7,
            track=track(),
            video_title="Video",
            video_url="https://youtu.be/abcdef",
            video_thumbnail_url="https://i.ytimg.com/vi/abcdef/default.jpg",
            caption="<b>MY_AUTHOR_INTRO</b>\nSong",
            reply_markup=None,
        )

    async def test_rich_timeout_never_sends_album(self):
        bot = SimpleNamespace(send_media_group=AsyncMock(), send_message=AsyncMock())
        with (
            patch.object(mixed_post, "rich_messages_enabled", return_value=True),
            patch.object(
                mixed_post, "send_rich_publication", AsyncMock(side_effect=TimedOut())
            ),
        ):
            with self.assertRaises(TimedOut):
                await self.mixed(bot)
        bot.send_media_group.assert_not_awaited()
        bot.send_message.assert_not_awaited()

    async def test_album_timeout_never_returns_fallback_signal(self):
        bot = SimpleNamespace(
            send_media_group=AsyncMock(side_effect=TimedOut()), send_message=AsyncMock()
        )
        with (
            patch.object(mixed_post, "rich_messages_enabled", return_value=False),
            self.assertRaises(TimedOut),
        ):
            await self.mixed(bot)
        bot.send_message.assert_not_awaited()

    async def test_definitive_rich_rejection_allows_album(self):
        bot = SimpleNamespace(
            send_media_group=AsyncMock(return_value=[]), send_message=AsyncMock()
        )
        with (
            patch.object(mixed_post, "rich_messages_enabled", return_value=True),
            patch.object(
                mixed_post,
                "send_rich_publication",
                AsyncMock(side_effect=BadRequest("unsupported")),
            ),
        ):
            await self.mixed(bot)
        bot.send_media_group.assert_awaited_once()

    async def test_rich_preserves_intro_without_adding_tags(self):
        send = AsyncMock(return_value=True)
        with (
            patch.object(mixed_post, "rich_messages_enabled", return_value=True),
            patch.object(mixed_post, "send_rich_publication", send),
        ):
            await self.mixed(SimpleNamespace())
        html = send.call_args.kwargs["rich_html"]
        self.assertIn("MY_AUTHOR_INTRO", html)
        self.assertNotIn("#stonerhand", html)

    async def test_ephemeral_timeout_is_typed_and_not_public_fallback(self):
        with (
            patch(
                "music_links_bot.telegram_gateway.httpx.AsyncClient.post",
                AsyncMock(side_effect=httpx.ReadTimeout("lost")),
            ),
            self.assertRaises(NetworkError),
        ):
            await ephemeral.send_ephemeral_message("123:fake", -1, 7, "Test")

    async def test_dispatch_respects_eight_update_limit(self):
        app = (
            Application.builder()
            .application_class(LocalizedApplication)
            .token("123:fake")
            .concurrent_updates(8)
            .build()
        )
        app._initialized = True
        active = peak = 0

        async def handle(update, context):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

        app.add_handler(TypeHandler(object, handle))
        await asyncio.gather(
            *(
                webhook._dispatch_update(app, object(), UpdateExecution())
                for _ in range(20)
            )
        )
        self.assertEqual(peak, 8)

    async def test_failed_storage_protection_prevents_network_send(self):
        execution = UpdateExecution(
            before_send=AsyncMock(side_effect=KVUnavailableError("offline"))
        )
        token = current_execution.set(execution)
        try:
            bot = DeliveryAwareBot("123:fake")
            with (
                patch("telegram.ext.ExtBot._do_post", AsyncMock()) as send,
                self.assertRaises(KVUnavailableError),
            ):
                await bot._do_post("sendMessage", {})
            send.assert_not_awaited()
            self.assertEqual(execution.deliveries, 0)
        finally:
            current_execution.reset(token)


class WebhookTests(unittest.TestCase):
    def test_real_handler_failure_is_released_and_not_success(self):
        app = (
            Application.builder()
            .application_class(LocalizedApplication)
            .token("123:fake")
            .build()
        )
        app._initialized = True

        async def fail(update, context):
            raise RuntimeError("failed before delivery")

        app.add_handler(TypeHandler(object, fail))
        app.add_error_handler(AsyncMock())
        loop, thread = start_background_loop("audit-regression")
        try:
            with (
                patch.object(webhook.Update, "de_json", return_value=object()),
                patch.object(webhook, "_note_failure_locked"),
                patch.object(webhook, "_note_success_locked") as success,
            ):
                with self.assertRaises(RuntimeError):
                    webhook._process_claimed_update(loop, app, {"update_id": 9891})
                success.assert_not_called()
                self.assertNotIn(9891, webhook._SEEN_UPDATE_IDS)
        finally:
            stop_background_loop(loop, thread)

    def test_inflight_duplicate_does_not_acknowledge_success(self):
        app = SimpleNamespace(bot_data={})
        loop, thread = start_background_loop("audit-duplicate")
        try:
            from music_links_bot.loop_runner import run_on_loop

            run_on_loop(
                loop,
                webhook._claim_update(app, 9892, owner="processing:first"),
                timeout=2,
            )
            with self.assertRaises(webhook.UpdateBusyError):
                webhook._process_claimed_update(loop, app, {"update_id": 9892})
        finally:
            stop_background_loop(loop, thread)

    def test_failure_after_delivery_is_quarantined_without_replay(self):
        app = (
            Application.builder()
            .application_class(LocalizedApplication)
            .bot(DeliveryAwareBot("123:fake"))
            .build()
        )
        app._initialized = True

        async def send_then_fail(update, context):
            await context.bot._do_post("sendMessage", {})
            raise RuntimeError("failed after delivery")

        app.add_handler(TypeHandler(object, send_then_fail))
        app.add_error_handler(AsyncMock())
        loop, thread = start_background_loop("audit-uncertain")
        try:
            with (
                patch.object(webhook.Update, "de_json", return_value=object()),
                patch.object(webhook, "_note_failure_locked"),
                patch.object(webhook, "_note_success_locked") as success,
                patch(
                    "telegram.ext.ExtBot._do_post",
                    AsyncMock(return_value={"message_id": 1}),
                ) as send,
            ):
                webhook._process_claimed_update(loop, app, {"update_id": 9894})
                webhook._process_claimed_update(loop, app, {"update_id": 9894})
                send.assert_awaited_once()
                success.assert_not_called()
                self.assertEqual(webhook._UPDATE_STATES[9894], "uncertain")
        finally:
            stop_background_loop(loop, thread)

    def test_queue_http_returns_503_for_storage_outage(self):
        from http import HTTPStatus
        from unittest.mock import Mock

        from api import queue_worker

        app = SimpleNamespace(bot_data={}, bot=AsyncMock())
        loop, thread = start_background_loop("audit-queue-http")
        handler = queue_worker.handler.__new__(queue_worker.handler)
        handler.headers = {}
        handler._send_json = Mock()
        try:
            with (
                patch.object(queue_worker, "is_authorized", return_value=True),
                patch.object(
                    queue_worker, "_ensure_application", return_value=(loop, app)
                ),
                patch.object(
                    queue_worker,
                    "process_due_jobs",
                    AsyncMock(side_effect=publish_queue.QueueStorageError("offline")),
                ),
            ):
                handler.do_GET()
            self.assertEqual(
                handler._send_json.call_args.args[1], HTTPStatus.SERVICE_UNAVAILABLE
            )
            self.assertFalse(handler._send_json.call_args.args[0]["ok"])
        finally:
            stop_background_loop(loop, thread)


class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.kv = RedisREST()

    async def asyncTearDown(self):
        await self.kv.aclose()

    async def test_privacy_removes_remote_and_legacy_orphan_keys(self):
        writer = context(self.kv)
        for index in range(35):
            await store_draft(
                writer, f"owned{index}", new_track_draft(track(), chat_id=7, lang="ru")
            )
        await self.kv.set_json_required("draft:legacy", {"chat_id": 7, "item": {}})
        await store_draft(
            writer, "other", new_track_draft(track(), chat_id=8, lang="ru")
        )
        selection = await store_search_selection(
            writer, user_id=7, query="private", urls=[]
        )
        retry = await store_retry_sources(
            writer, user_id=7, urls=["https://example.test"]
        )
        reader = context(self.kv)
        with patch("music_links_bot.privacy.remove_identity"):
            result = await delete_user_data(reader, 7)
        self.assertEqual(result.drafts, 36)
        self.assertIsNone(await self.kv.get("draft:owned0"))
        self.assertIsNone(await self.kv.get("draft:legacy"))
        self.assertIsNotNone(await self.kv.get("draft:other"))
        self.assertIsNone(await self.kv.get(f"selection:v1:{selection}"))
        self.assertIsNone(await self.kv.get(f"retry:v1:{retry}"))
        self.assertIsNone(await load_search_selection(writer, selection))

    async def test_old_request_cannot_restore_data_after_deletion(self):
        ready, resume = asyncio.Event(), asyncio.Event()

        async def stale():
            async with user_state_scope(self.kv, 7):
                ready.set()
                await resume.wait()
                with self.assertRaises(KVUnavailableError):
                    await self.kv.set_json_required("hist:7", ["stale"])
                with self.assertRaises(KVUnavailableError):
                    await self.kv.compare_set_required(
                        "draft:old", None, "{}", ttl_seconds=100
                    )

        old = asyncio.create_task(stale())
        await ready.wait()
        async with user_state_scope(self.kv, 7):
            with patch("music_links_bot.privacy.remove_identity"):
                await delete_user_data(context(self.kv), 7)
        resume.set()
        await old
        self.assertIsNone(await self.kv.get("hist:7"))
        async with user_state_scope(self.kv, 7):
            await self.kv.set_json_required("hist:7", ["new"])
        self.assertEqual(await self.kv.get_json("hist:7"), ["new"])

    async def test_stats_count_independent_events_once(self):
        def message(user):
            return SimpleNamespace(
                chat_id=user,
                message_id=1,
                from_user=SimpleNamespace(id=user, username=None, full_name="Owner"),
                chat=SimpleNamespace(
                    id=user, title=None, username=None, type="private"
                ),
            )

        await asyncio.gather(
            record_tracks([track()], message(7), context=context(self.kv)),
            record_tracks([track()], message(8), context=context(self.kv)),
        )
        await record_tracks([track()], message(7), context=context(self.kv))
        stats = await self.kv.get_json(STATS_KV_KEY)
        self.assertEqual(stats["posts"], 2)
        self.assertEqual(stats["song"], 2)
        self.assertEqual(stats["users"]["7"]["count"], 1)

    async def test_selections_expire_in_memory_and_redis_payload(self):
        for kv in (None, self.kv):
            ctx = context(kv)
            with patch("music_links_bot.bot_storage.time.time", return_value=100):
                key = await store_search_selection(ctx, user_id=7, query="q", urls=[])
            with patch(
                "music_links_bot.bot_storage.time.time", return_value=100 + 86400
            ):
                self.assertIsNone(await load_search_selection(ctx, key))

    async def test_queue_outage_is_not_an_empty_success(self):
        ctx = context(self.kv)
        with (
            patch.object(
                publish_queue,
                "_recover_uncertain_jobs",
                AsyncMock(side_effect=publish_queue.QueueStorageError("offline")),
            ),
            self.assertRaises(publish_queue.QueueStorageError),
        ):
            await publish_queue.process_due_jobs(ctx)

    async def test_delivery_marker_survives_worker_crash(self):
        ctx = context(self.kv)
        self.assertTrue(
            await webhook._claim_update(ctx.application, 9893, owner="processing:first")
        )
        await webhook._finish_update(
            ctx.application, 9893, "processing:first", "delivering:first"
        )
        self.assertFalse(
            await webhook._claim_update(
                context(self.kv).application, 9893, owner="processing:second"
            )
        )
        self.assertEqual(
            await self.kv.redis.ttl("seen_update:9893"),
            webhook.DELIVERED_UPDATE_TTL_SECONDS,
        )

    async def test_polling_worker_processes_due_jobs_and_stops(self):
        from music_links_bot.polling_worker import run_queue, stop_polling_services

        ctx = context()
        await publish_queue.add_job(
            ctx, new_track_draft(track(), chat_id=7, lang="ru"), 1
        )
        sent = asyncio.Event()

        async def publish(*args, **kwargs):
            sent.set()
            return SimpleNamespace(message_id=1)

        ctx.application.bot = ctx.bot
        with patch(
            "music_links_bot.publication_service.PublicationService.publish", publish
        ):
            task = asyncio.create_task(run_queue(ctx.application))
            ctx.application.bot_data["polling_queue_task"] = task
            await asyncio.wait_for(sent.wait(), timeout=2)
            await stop_polling_services(ctx.application)
        self.assertTrue(task.done())
