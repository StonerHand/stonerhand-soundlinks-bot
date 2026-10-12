"""Redis round-trip budget for the hot lookup path and the helpers behind it.

Every Upstash command is a sequential HTTPS request and counts against the
monthly quota, so a regression here is both latency and cost.
"""

import json
import time
import unittest

from test_audit_reliability import RedisREST
from test_bot import ContextStub, PrivateSpotifyTrackMessageStub, UpdateStub

from music_links_bot.bot import track_lookup_message
from music_links_bot.bot_runtime import BotRuntime
from music_links_bot.durable_state import state_scope
from music_links_bot.kvstore import KVUnavailableError
from music_links_bot.state_mutations import mutate_json, mutate_json_raw
from music_links_bot.user_state import (
    generation_key,
    register_owned_key,
    user_state_scope,
)

# Measured at 18 after batching; leave a little room for deliberate additions.
LOOKUP_ROUND_TRIP_BUDGET = 19


class CountingRedis(RedisREST):
    def __init__(self):
        super().__init__()
        self.commands: list[list] = []

    async def respond(self, request):
        self.commands.append(json.loads(request.content))
        return await super().respond(request)


class LookupBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.kv = CountingRedis()

    async def asyncTearDown(self):
        await self.kv.aclose()

    async def lookup(self):
        """Mirror LocalizedApplication.process_update for a private message."""
        context = ContextStub()
        runtime = BotRuntime(self.kv)
        context.application.bot_data.update(kv_store=self.kv, runtime=runtime)
        message = PrivateSpotifyTrackMessageStub()
        user_id = message.chat_id
        self.kv.commands.clear()
        with state_scope():
            generation, raw = await self.kv.mget_required(
                [generation_key(user_id), runtime.session_key(user_id)]
            )
            async with user_state_scope(self.kv, user_id, generation=generation):
                await runtime.get_session(user_id, prefetched_raw=raw)
                await track_lookup_message(UpdateStub(message), context)

    async def test_first_lookup_stays_within_round_trip_budget(self):
        await self.lookup()

        # The lookup really ran to the editor card, which persists a draft.
        self.assertTrue(await self.kv.redis.keys("draft:*"))
        self.assertLessEqual(len(self.kv.commands), LOOKUP_ROUND_TRIP_BUDGET)
        names = [command[0] for command in self.kv.commands]
        # The session is never re-read after the batched prefetch.
        self.assertEqual(
            sum(
                1
                for command in self.kv.commands
                if command[0] == "GET" and command[1].startswith("session:")
            ),
            0,
        )
        self.assertNotIn("hist:lock:456", json.dumps(self.kv.commands))
        self.assertIn("MGET", names)


class StorageHelperTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.kv = CountingRedis()

    async def asyncTearDown(self):
        await self.kv.aclose()

    async def test_known_raw_value_skips_the_read(self):
        await self.kv.set_json_required("k", {"n": 1}, ttl_seconds=60)
        raw = await self.kv.get_required("k")
        self.kv.commands.clear()

        value, stored = await mutate_json_raw(
            self.kv,
            "k",
            lambda current: {"n": current["n"] + 1},
            ttl_seconds=60,
            expected_raw=raw,
        )

        self.assertEqual(value, {"n": 2})
        self.assertEqual(stored, await self.kv.get_required("k"))
        self.assertEqual([command[0] for command in self.kv.commands[:1]], ["EVAL"])

    async def test_stale_raw_value_rereads_instead_of_overwriting(self):
        await self.kv.set_json_required("k", {"n": 5}, ttl_seconds=60)

        value = await mutate_json(
            self.kv,
            "k",
            lambda current: {"n": current["n"] + 1},
            ttl_seconds=60,
            expected_raw=json.dumps({"n": 1}),
        )

        self.assertEqual(value, {"n": 6})

    async def test_expected_missing_key_detects_an_existing_value(self):
        await self.kv.set_json_required("k", {"n": 3}, ttl_seconds=60)

        value = await mutate_json(
            self.kv,
            "k",
            lambda current: {"seen": current},
            ttl_seconds=60,
            expected_raw=None,
        )

        self.assertEqual(value, {"seen": {"n": 3}})

    async def test_owned_key_index_prunes_expired_entries_in_one_command(self):
        now = int(time.time())
        await self.kv.set_json_required(
            "user-keys:v1:7",
            {"draft:old": now - 5, "draft:live": now + 500},
            ttl_seconds=60,
        )
        self.kv.commands.clear()

        await register_owned_key(self.kv, 7, "draft:new", ttl_seconds=100)

        self.assertEqual(len(self.kv.commands), 1)
        index = await self.kv.get_json_required("user-keys:v1:7")
        self.assertEqual(set(index), {"draft:live", "draft:new"})
        self.assertGreaterEqual(index["draft:new"], now + 100)
        self.assertGreater(await self.kv.redis.ttl("user-keys:v1:7"), 100)

    async def test_owned_key_index_respects_the_privacy_fence(self):
        await self.kv.set_required(generation_key(7), "g1", ttl_seconds=60)
        async with user_state_scope(self.kv, 7):
            await self.kv.set_required(generation_key(7), "g2", ttl_seconds=60)
            with self.assertRaises(KVUnavailableError):
                await register_owned_key(self.kv, 7, "draft:new", ttl_seconds=100)
        self.assertIsNone(await self.kv.get_required("user-keys:v1:7"))


class StatsBlobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.kv = CountingRedis()

    async def asyncTearDown(self):
        await self.kv.aclose()

    async def test_identity_maps_are_capped_keeping_the_most_active(self):
        from music_links_bot.kvstore import MAX_STATS_IDENTITIES

        crowd = {
            str(index): {"count": index + 1, "label": f"u{index}", "last_seen": ""}
            for index in range(MAX_STATS_IDENTITIES + 50)
        }
        await self.kv.set_json_required("stats", {"posts": 1, "users": crowd})

        await self.kv.record_activity_event(
            "stats",
            "event-1",
            {
                "posts": 1,
                "users": {"new": {"count": 1, "label": "@new", "last_seen": ""}},
            },
        )

        stats = await self.kv.get_json_required("stats")
        users = stats["users"]
        self.assertEqual(stats["posts"], 2)
        self.assertLessEqual(len(users), MAX_STATS_IDENTITIES + 1)
        self.assertIn("new", users)  # the active user is never dropped mid-event
        self.assertIn(str(MAX_STATS_IDENTITIES + 49), users)  # the busiest stays
        self.assertNotIn("0", users)  # the least active goes first

    async def test_small_maps_are_untouched_and_events_stay_idempotent(self):
        delta = {"posts": 1, "users": {"a": {"count": 1, "label": "a"}}}
        await self.kv.record_activity_event("stats", "same", delta)
        await self.kv.record_activity_event("stats", "same", delta)

        stats = await self.kv.get_json_required("stats")
        self.assertEqual(stats["posts"], 1)
        self.assertEqual(stats["users"]["a"]["count"], 1)
