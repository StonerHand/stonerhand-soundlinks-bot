import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from music_links_bot.bot_crate import (
    add_many_to_crate,
    add_to_crate,
    load_crate,
    load_crate_title,
    move_crate_item,
    remove_crate_item,
    restore_crate_item,
    save_crate_title,
)
from music_links_bot.bot_progress import (
    adopt_progress_message,
    cancel_progress,
    start_progress,
    take_progress,
    update_progress,
)
from music_links_bot.bot_runtime import (
    BotRuntime,
    UserSession,
    decode_callback,
    detect_action,
    encode_callback,
)


class CallbackContractTests(unittest.TestCase):
    def test_v2_callback_round_trip(self) -> None:
        encoded = encode_callback("editor", "publish", "draft123")
        decoded = decode_callback(encoded)

        self.assertEqual(encoded, "v2|editor|publish|draft123")
        self.assertIsNotNone(decoded)
        assert decoded is not None
        self.assertEqual(
            (decoded.scope, decoded.action, decoded.payload),
            ("editor", "publish", "draft123"),
        )

    def test_legacy_callbacks_remain_readable(self) -> None:
        editor = decode_callback("ed|h|draft123")
        menu = decode_callback("menu:platforms")

        self.assertEqual(
            (editor.scope, editor.action, editor.payload), ("editor", "h", "draft123")
        )
        self.assertEqual((menu.scope, menu.action), ("menu", "platforms"))

    def test_callback_limit_is_enforced(self) -> None:
        with self.assertRaises(ValueError):
            encode_callback("editor", "x", "a" * 64)

    def test_action_detection_routes_multi_link_to_crate(self) -> None:
        self.assertEqual(detect_action("links", ["a", "b"], is_private=True), "crate")
        self.assertEqual(detect_action("помощь", [], is_private=True), "help")
        self.assertEqual(detect_action("artist track", [], is_private=True), "search")

    def test_session_restores_home_message_pointer(self) -> None:
        session = UserSession.from_dict(
            {
                "user_id": 7,
                "home_chat_id": 7,
                "home_message_id": 321,
            }
        )

        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual((session.home_chat_id, session.home_message_id), (7, 321))

    def test_session_restores_new_editor_inputs(self) -> None:
        for kind in ("cover", "template_name"):
            with self.subTest(kind=kind):
                session = UserSession.from_dict(
                    {
                        "user_id": 7,
                        "pending_input": {
                            "kind": kind,
                            "draft_id": "draft123",
                            "created_at": 123,
                        },
                    }
                )

                self.assertIsNotNone(session)
                assert session is not None
                self.assertEqual(session.pending_input["kind"], kind)
                self.assertEqual(session.pending_input["draft_id"], "draft123")


class RuntimeSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_progress_can_use_rich_streaming_draft(self) -> None:
        rich = AsyncMock(return_value=True)

        class Incoming:
            chat_id = 17
            message_id = 23
            chat = SimpleNamespace(type="private")

            def get_bot(self):
                return object()

        with patch(
            "music_links_bot.bot_progress.send_rich_progress_draft",
            rich,
        ):
            await start_progress(Incoming())
            await update_progress("ru", "progress_links")

        self.assertEqual(rich.await_count, 2)
        self.assertIsNone(take_progress(17))

    async def test_cancelled_lookup_retires_progress_message(self) -> None:
        class ProgressMessage:
            chat_id = 17

            def __init__(self) -> None:
                self.deleted = False

            async def delete(self) -> None:
                self.deleted = True

        message = ProgressMessage()
        adopt_progress_message(message)

        await cancel_progress(17)

        self.assertTrue(message.deleted)
        self.assertIsNone(take_progress(17))

    async def test_callback_is_claimed_only_once(self) -> None:
        runtime = BotRuntime()
        self.assertTrue(await runtime.claim_callback("callback-1"))
        self.assertFalse(await runtime.claim_callback("callback-1"))

    async def test_action_lock_blocks_parallel_duplicate(self) -> None:
        runtime = BotRuntime()
        token = await runtime.acquire_action("7:publish:d1")

        self.assertIsNotNone(token)
        self.assertIsNone(await runtime.acquire_action("7:publish:d1"))
        await runtime.release_action("7:publish:d1", token)
        self.assertIsNotNone(await runtime.acquire_action("7:publish:d1"))

    async def test_equal_intents_are_debounced_but_distinct_ones_pass(self) -> None:
        runtime = BotRuntime()

        self.assertTrue(
            await runtime.claim_intent(7, kind="search", value=" Sleep   Dragonaut ")
        )
        self.assertFalse(
            await runtime.claim_intent(7, kind="search", value="sleep dragonaut")
        )
        self.assertTrue(
            await runtime.claim_intent(7, kind="search", value="Sleep Dopesmoker")
        )

    async def test_new_request_cancels_stale_task(self) -> None:
        runtime = BotRuntime()
        ready = asyncio.Event()

        async def first() -> None:
            runtime.register_request(7)
            ready.set()
            await asyncio.sleep(60)

        task = asyncio.create_task(first())
        await ready.wait()
        runtime.register_request(7)
        await asyncio.sleep(0)

        self.assertTrue(task.cancelled())
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_user_rate_limit_is_bounded_and_reports_retry(self) -> None:
        runtime = BotRuntime()

        first = await runtime.allow_user_request(7, max_requests=2)
        second = await runtime.allow_user_request(7, max_requests=2)
        limited = await runtime.allow_user_request(7, max_requests=2)

        self.assertTrue(first[0])
        self.assertTrue(second[0])
        self.assertFalse(limited[0])
        self.assertGreaterEqual(limited[1], 1)
        self.assertEqual(runtime.metrics_snapshot()["rate_limited"], 1)

    async def test_funnel_metrics_are_anonymous_counters(self) -> None:
        runtime = BotRuntime()
        for stage in ("started", "resolved", "edited"):
            runtime.record_funnel(stage)
        runtime.record_publication(ok=True)

        snapshot = runtime.metrics_snapshot()
        self.assertEqual(snapshot["funnel_started"], 1)
        self.assertEqual(snapshot["funnel_resolved"], 1)
        self.assertEqual(snapshot["funnel_edited"], 1)
        self.assertEqual(snapshot["funnel_published"], 1)

    async def test_request_generation_cancels_stale_cross_instance_result(self) -> None:
        class SharedKV:
            def __init__(self) -> None:
                self.values: dict[str, str] = {}

            async def set(self, key, value, **kwargs):
                del kwargs
                self.values[key] = value
                return True

            async def get(self, key):
                return self.values.get(key)

            async def delete_if_value(self, key, value):
                if self.values.get(key) != value:
                    return False
                self.values.pop(key, None)
                return True

        kv = SharedKV()
        first = BotRuntime(kv)  # type: ignore[arg-type]
        second = BotRuntime(kv)  # type: ignore[arg-type]

        first_token = await first.begin_request(7)
        second_token = await second.begin_request(7)

        self.assertFalse(await first.request_is_current(7, first_token))
        self.assertTrue(await second.request_is_current(7, second_token))
        self.assertTrue(await first.cancel_request_durable(7))
        self.assertFalse(await second.request_is_current(7, second_token))

    async def test_session_remembers_retry_action(self) -> None:
        runtime = BotRuntime()
        await runtime.remember_action(7, kind="search", value="Youth Code", lang="ru")

        session = await runtime.get_session(7)
        self.assertEqual(session.last_query, "Youth Code")
        self.assertEqual(session.last_action["kind"], "search")

    async def test_session_preserves_ten_link_collection_for_inline_recovery(
        self,
    ) -> None:
        runtime = BotRuntime()
        value = "\n".join(
            f"https://open.spotify.com/track/{index:022d}?si={'x' * 20}"
            for index in range(10)
        )

        await runtime.remember_action(7, kind="resolve", value=value, lang="ru")

        session = await runtime.get_session(7)
        self.assertGreater(len(value), 500)
        self.assertEqual(session.last_action["value"], value)

    async def test_provider_diagnostics_expose_latest_state(self) -> None:
        runtime = BotRuntime()
        runtime.record_provider(
            "songlink", ok=False, latency_ms=250, error=TimeoutError()
        )

        snapshot = runtime.provider_snapshot()
        self.assertEqual(snapshot[0]["provider"], "songlink")
        self.assertFalse(snapshot[0]["ok"])
        self.assertEqual(snapshot[0]["last_error"], "TimeoutError")
        self.assertEqual(snapshot[0]["timeouts"], 1)
        self.assertEqual(snapshot[0]["avg_latency_ms"], 250)
        self.assertEqual(snapshot[0]["success_rate_percent"], 0.0)

    async def test_provider_metrics_aggregate_success_latency_and_fallbacks(
        self,
    ) -> None:
        runtime = BotRuntime()
        runtime.record_provider("songlink", ok=True, latency_ms=100)
        runtime.record_provider(
            "songlink",
            ok=False,
            latency_ms=300,
            error=RuntimeError("429 too many requests"),
            partial=True,
        )

        item = runtime.provider_snapshot()[0]
        self.assertEqual(item["requests"], 2)
        self.assertEqual(item["avg_latency_ms"], 200)
        self.assertEqual(item["success_rate_percent"], 50.0)
        self.assertEqual(item["partials"], 1)
        self.assertEqual(item["rate_limits"], 1)
        self.assertEqual(
            runtime.metrics_snapshot()["providers"]["songlink"]["requests"],
            2,
        )

    async def test_rich_message_metrics_track_fallbacks(self) -> None:
        runtime = BotRuntime()
        runtime.record_rich_message(ok=True)
        runtime.record_rich_message(ok=False, fallback=True)

        snapshot = runtime.metrics_snapshot()
        self.assertEqual(snapshot["rich_messages"], 2)
        self.assertEqual(snapshot["rich_message_errors"], 1)
        self.assertEqual(snapshot["rich_message_fallbacks"], 1)

    async def test_request_metrics_expose_bounded_p95_and_cache_ratio(self) -> None:
        runtime = BotRuntime()
        for latency in (100, 200, 300, 700, 1_500, 3_000, 21_000):
            runtime.record_request(latency_ms=latency, ok=True)
        runtime.record_cache(hit=True)
        runtime.record_cache(hit=True)
        runtime.record_cache(hit=False)

        snapshot = runtime.metrics_snapshot()

        self.assertEqual(snapshot["request_ms_p95"], 21_000)
        self.assertEqual(snapshot["request_latency_overflow"], 1)
        self.assertEqual(snapshot["cache_hit_rate_percent"], 66.7)


class BotCrateTests(unittest.IsolatedAsyncioTestCase):
    async def test_crate_title_round_trips_in_memory(self) -> None:
        bot_data = {}
        await save_crate_title(bot_data, 7, "Ночной сет")

        self.assertEqual(await load_crate_title(bot_data, 7), "Ночной сет")

    async def test_crate_dedupes_reorders_and_removes(self) -> None:
        bot_data = {}
        first = {
            "artist": "Sleep",
            "title": "Dopesmoker",
            "links": {"spotify": "https://s/1"},
        }
        second = {
            "artist": "Boris",
            "title": "Flood",
            "links": {"spotify": "https://s/2"},
        }

        items, added = await add_to_crate(bot_data, 7, draft_id="d1", item=first)
        self.assertTrue(added)
        items, added = await add_to_crate(bot_data, 7, draft_id="d1x", item=first)
        self.assertFalse(added)
        items, _ = await add_to_crate(bot_data, 7, draft_id="d2", item=second)
        self.assertEqual(len(items), 2)

        items = await move_crate_item(bot_data, 7, 1, -1)
        self.assertEqual(items[0]["draft_id"], "d2")
        items = await remove_crate_item(bot_data, 7, 0)
        self.assertEqual([item["draft_id"] for item in items], ["d1"])
        self.assertEqual(len(await load_crate(bot_data, 7)), 1)

        items, restored = await restore_crate_item(
            bot_data,
            7,
            index=0,
            entry={"draft_id": "d2", "item": second},
        )
        self.assertTrue(restored)
        self.assertEqual([item["draft_id"] for item in items], ["d2", "d1"])

    async def test_batch_add_dedupes_and_persists_once(self) -> None:
        class KVStub:
            def __init__(self) -> None:
                self.writes = 0

            async def get_json(self, key: str):
                del key
                return []

            async def set_json(self, key: str, value, *, ttl_seconds: int):
                del key, value, ttl_seconds
                self.writes += 1
                return True

        kv = KVStub()
        first = {
            "artist": "Sleep",
            "title": "Dopesmoker",
            "links": {"spotify": "https://s/1"},
        }
        duplicate = dict(first)
        second = {
            "artist": "Boris",
            "title": "Flood",
            "links": {"spotify": "https://s/2"},
        }

        items, added_count = await add_many_to_crate(
            {"kv_store": kv},
            7,
            entries=[("d1", first), ("d1x", duplicate), ("d2", second)],
        )

        self.assertEqual(added_count, 2)
        self.assertEqual([item["draft_id"] for item in items], ["d1", "d2"])
        self.assertEqual(kv.writes, 1)
