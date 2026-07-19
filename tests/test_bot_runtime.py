import asyncio
import unittest

from music_links_bot.bot_crate import (
    add_to_crate,
    load_crate,
    move_crate_item,
    remove_crate_item,
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
        self.assertEqual((decoded.scope, decoded.action, decoded.payload), ("editor", "publish", "draft123"))

    def test_legacy_callbacks_remain_readable(self) -> None:
        editor = decode_callback("ed|h|draft123")
        menu = decode_callback("menu:platforms")

        self.assertEqual((editor.scope, editor.action, editor.payload), ("editor", "h", "draft123"))
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


class RuntimeSafetyTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_session_remembers_retry_action(self) -> None:
        runtime = BotRuntime()
        await runtime.remember_action(7, kind="search", value="Youth Code", lang="ru")

        session = await runtime.get_session(7)
        self.assertEqual(session.last_query, "Youth Code")
        self.assertEqual(session.last_action["kind"], "search")

    async def test_provider_diagnostics_expose_latest_state(self) -> None:
        runtime = BotRuntime()
        runtime.record_provider("songlink", ok=False, latency_ms=250, error=TimeoutError())

        snapshot = runtime.provider_snapshot()
        self.assertEqual(snapshot[0]["provider"], "songlink")
        self.assertFalse(snapshot[0]["ok"])
        self.assertEqual(snapshot[0]["last_error"], "TimeoutError")


class BotCrateTests(unittest.IsolatedAsyncioTestCase):
    async def test_crate_dedupes_reorders_and_removes(self) -> None:
        bot_data = {}
        first = {"artist": "Sleep", "title": "Dopesmoker", "links": {"spotify": "https://s/1"}}
        second = {"artist": "Boris", "title": "Flood", "links": {"spotify": "https://s/2"}}

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
