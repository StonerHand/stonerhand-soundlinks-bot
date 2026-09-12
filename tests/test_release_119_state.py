"""Regression checks for real interleavings, storage outages and uncertain sends."""

import asyncio
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from music_links_bot.bot_crate import (
    add_to_crate,
    clear_crate_items,
    crate_item_key,
    crate_revision,
    load_crate,
    move_crate_item,
    pop_crate_item,
    replace_crate_item,
    restore_crate_items,
)
from music_links_bot.bot_runtime import BotRuntime
from music_links_bot.bot_storage import load_draft, load_drafts, store_draft
from music_links_bot.delivery_receipts import (
    DeliveryBlockedError,
    begin_delivery,
    finish_delivery,
    load_delivery,
)
from music_links_bot.draft_model import new_track_draft
from music_links_bot.kvstore import KVUnavailableError
from music_links_bot.models import TrackMatch
from music_links_bot.state_mutations import StateConflictError


class RedisModel:
    """Serialized independent clients yield between GET and atomic compare-and-set."""

    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.available = True
        self.batch_calls = 0

    async def get_required(self, key):
        if not self.available:
            raise KVUnavailableError("offline")
        result = self.values.get(key)
        await asyncio.sleep(0)
        return result

    async def get_json_required(self, key):
        value = await self.get_required(key)
        return json.loads(value) if value is not None else None

    get_json = get_json_required
    get = get_required

    async def compare_set_required(self, key, expected, value, *, ttl_seconds):
        if not self.available:
            raise KVUnavailableError("offline")
        if self.values.get(key) != expected:
            return False
        self.values[key] = value
        self.ttls[key] = ttl_seconds
        return True

    async def mget_json_required(self, keys):
        self.batch_calls += 1
        return [await self.get_json_required(key) for key in keys]

    async def set_json(self, key, value, *, ttl_seconds=None):
        self.values[key] = json.dumps(value)
        self.ttls[key] = ttl_seconds
        return True

    async def delete_required(self, key):
        self.values.pop(key, None)

    delete = delete_required


def ctx(kv):
    return SimpleNamespace(application=SimpleNamespace(bot_data={"kv_store": kv}))


def track(index=0):
    return TrackMatch(
        title=f"Track {index}",
        artist="Artist",
        links={"spotify": f"https://open.spotify.com/track/id{index}"},
    )


def draft():
    return new_track_draft(track(), chat_id=7, lang="ru")


class Release119StateTests(unittest.IsolatedAsyncioTestCase):
    async def test_deleted_session_cannot_be_restored_by_stale_worker(self):
        kv = RedisModel()
        runtime = BotRuntime(kv)
        session = await runtime.get_session(7)
        await runtime.save_session(session)
        old = await BotRuntime(kv).get_session(7)
        await runtime.forget_session(7)
        old.active_draft_id = "stale"
        with self.assertRaises(StateConflictError):
            await BotRuntime(kv).save_session(old)
        self.assertNotIn("session:v2:7", kv.values)

    async def test_receipt_index_keeps_all_unexpired_entries_for_privacy(self):
        kv = RedisModel()
        context = ctx(kv)
        for index in range(125):
            value = {**draft(), "editor_draft_id": f"d{index}"}
            await begin_delivery(context, value, 7)
        self.assertEqual(len(await kv.get_json("receipt-index:v1:7")), 125)

    async def test_failed_receipt_index_write_prevents_untracked_intent(self):
        class FailingIndex(RedisModel):
            async def compare_set_required(self, key, *args, **kwargs):
                if key.startswith("receipt-index:"):
                    raise KVUnavailableError("offline")
                return await super().compare_set_required(key, *args, **kwargs)

        kv = FailingIndex()
        with self.assertRaises(KVUnavailableError):
            await begin_delivery(ctx(kv), {**draft(), "editor_draft_id": "d"}, 7)
        self.assertFalse(kv.values)

    async def test_100_simultaneous_users_keep_their_own_ten_item_limit(self):
        kv = RedisModel()

        async def fill(user):
            for batch in range(3):
                await asyncio.gather(
                    *(
                        add_to_crate(
                            ctx(kv).application.bot_data,
                            user,
                            draft_id=f"{user}_{i}",
                            item={"title": f"{user}_{i}"},
                        )
                        for i in range(batch * 4, batch * 4 + 4)
                    )
                )
            items = await load_crate(ctx(kv).application.bot_data, user)
            self.assertEqual(len(items), 10)
            self.assertEqual(len({entry["draft_id"] for entry in items}), 10)
            self.assertTrue(
                all(entry["draft_id"].startswith(f"{user}_") for entry in items)
            )

        await asyncio.gather(*(fill(user) for user in range(100)))

    async def test_two_workers_add_to_same_collection_without_lost_item(self):
        kv = RedisModel()
        a, b = ctx(kv), ctx(kv)
        await asyncio.gather(
            *(
                add_to_crate(
                    c.application.bot_data, 7, draft_id=str(i), item={"title": str(i)}
                )
                for i, c in enumerate((a, b))
            )
        )
        self.assertEqual(
            {e["item"]["title"] for e in await load_crate(a.application.bot_data, 7)},
            {"0", "1"},
        )

    async def test_concurrent_additions_respect_ten_item_limit(self):
        kv = RedisModel()
        context = ctx(kv)
        for i in range(9):
            await add_to_crate(
                context.application.bot_data, 7, draft_id=str(i), item={"title": str(i)}
            )
        results = await asyncio.gather(
            *(
                add_to_crate(
                    ctx(kv).application.bot_data,
                    7,
                    draft_id=str(i),
                    item={"title": str(i)},
                )
                for i in (9, 10)
            )
        )
        self.assertEqual(sum(added for _, added in results), 1)
        self.assertEqual(len(await load_crate(context.application.bot_data, 7)), 10)

    async def test_stale_position_moves_and_removes_the_original_item(self):
        data = ctx(RedisModel()).application.bot_data
        for i in range(3):
            await add_to_crate(data, 7, draft_id=str(i), item={"title": str(i)})
        entries = await load_crate(data, 7)
        selected = crate_item_key(entries[1])
        await move_crate_item(data, 7, selected, -1)
        _, (_, removed) = await pop_crate_item(data, 7, selected)
        self.assertEqual(removed["item"]["title"], "1")
        self.assertEqual(
            [e["item"]["title"] for e in await load_crate(data, 7)], ["0", "2"]
        )

    async def test_clear_rejects_collection_changed_after_confirmation(self):
        data = ctx(RedisModel()).application.bot_data
        before = crate_revision([])
        await add_to_crate(data, 7, draft_id="a", item={"title": "A"})
        with self.assertRaises(StateConflictError):
            await clear_crate_items(data, 7, before)
        self.assertEqual(len(await load_crate(data, 7)), 1)

    async def test_undo_clear_keeps_newly_added_items(self):
        data = ctx(RedisModel()).application.bot_data
        await add_to_crate(data, 7, draft_id="new", item={"title": "New"})
        items, restored = await restore_crate_items(
            data, 7, [{"draft_id": "old", "item": {"title": "Old"}}]
        )
        self.assertTrue(restored)
        self.assertEqual([e["item"]["title"] for e in items], ["Old", "New"])

    async def test_replacement_preserves_position_and_rejects_removed_item(self):
        data = ctx(RedisModel()).application.bot_data
        entries, _ = await add_to_crate(data, 7, draft_id="old", item={"title": "Old"})
        key = crate_item_key(entries[0])
        updated = await replace_crate_item(data, 7, key, {"title": "New"})
        self.assertEqual(updated[0]["item"]["title"], "New")
        with self.assertRaises(StateConflictError):
            await replace_crate_item(data, 7, key, {"title": "Other"})

    async def test_parallel_session_preferences_merge_independent_fields(self):
        kv = RedisModel()
        a, b = BotRuntime(kv), BotRuntime(kv)
        left, right = await asyncio.gather(a.get_session(7), b.get_session(7))
        left.default_artwork = "clean"
        right.preferred_lang = "en"
        await asyncio.gather(a.save_session(left), b.save_session(right))
        result = await BotRuntime(kv).get_session(7)
        self.assertEqual(
            (result.default_artwork, result.preferred_lang), ("clean", "en")
        )

    async def test_conflicting_preference_is_rejected(self):
        kv = RedisModel()
        a, b = BotRuntime(kv), BotRuntime(kv)
        left, right = await asyncio.gather(a.get_session(7), b.get_session(7))
        left.collection_layout = "compact"
        right.collection_layout = "auto"
        await a.save_session(left)
        with self.assertRaises(StateConflictError):
            await b.save_session(right)
        self.assertEqual((await a.get_session(7)).collection_layout, "compact")

    async def test_stale_draft_cannot_overwrite_newer_text(self):
        kv = RedisModel()
        a, b = ctx(kv), ctx(kv)
        await store_draft(a, "d", draft())
        left, right = await asyncio.gather(load_draft(a, "d"), load_draft(b, "d"))
        left["prefix"] = "first edit"
        await store_draft(a, "d", left)
        right["prefix"] = "stale edit"
        with self.assertRaises(StateConflictError):
            await store_draft(b, "d", right)
        self.assertEqual((await load_draft(b, "d"))["prefix"], "first edit")

    async def test_draft_outage_does_not_mutate_cached_value(self):
        kv = RedisModel()
        context = ctx(kv)
        await store_draft(context, "d", draft())
        changed = await load_draft(context, "d")
        changed["prefix"] = "not saved"
        kv.available = False
        with self.assertRaises(KVUnavailableError):
            await store_draft(context, "d", changed)
        self.assertEqual(context.application.bot_data["drafts"]["d"]["prefix"], "")

    async def test_saved_draft_ttl_and_batched_library(self):
        kv = RedisModel()
        context = ctx(kv)
        value = draft()
        await store_draft(context, "d", value)
        self.assertEqual(kv.ttls["draft:d"], 7 * 86400)
        value["saved_at"] = int(time.time())
        await store_draft(context, "d", value)
        self.assertEqual(kv.ttls["draft:d"], 90 * 86400)
        restored = await load_drafts(context, ["d", "missing"])
        self.assertEqual(kv.batch_calls, 1)
        self.assertTrue(restored[0]["saved_at"])
        self.assertIsNone(restored[1])

    async def test_manual_send_network_ambiguity_survives_worker_restart(self):
        kv = RedisModel()
        first = ctx(kv)
        value = {"editor_draft_id": "d"}
        intent = await begin_delivery(first, value, "@channel")
        await finish_delivery(first, intent, sent=None, confirmed_not_sent=False)
        with self.assertRaises(DeliveryBlockedError):
            await begin_delivery(ctx(kv), value, "@channel")
        retried = await begin_delivery(
            ctx(kv), {**value, "repeat_delivery": "reviewed"}, "@channel"
        )
        await finish_delivery(
            ctx(kv),
            retried,
            sent=SimpleNamespace(message_id=5),
            confirmed_not_sent=False,
        )
        with self.assertRaises(DeliveryBlockedError):
            await begin_delivery(
                ctx(kv), {**value, "repeat_delivery": "reviewed"}, "@channel"
            )
        self.assertEqual(
            (await load_delivery(ctx(kv), "d", "@channel"))["message_id"], 5
        )

    async def test_confirmed_rejection_can_be_retried_but_active_send_cannot(self):
        context = ctx(RedisModel())
        value = {"editor_draft_id": "d"}
        intent = await begin_delivery(context, value, 7)
        with self.assertRaises(DeliveryBlockedError):
            await begin_delivery(context, {**value, "repeat_delivery": True}, 7)
        await finish_delivery(context, intent, sent=None, confirmed_not_sent=True)
        self.assertIsNotNone(await begin_delivery(context, value, 7))

    async def test_no_telegram_send_if_intent_cannot_be_persisted(self):
        from unittest.mock import patch

        from music_links_bot.bot import _deliver_draft

        kv = RedisModel()
        kv.available = False
        sender = AsyncMock()
        with patch("music_links_bot.bot.PublicationService", sender):
            with self.assertRaises(KVUnavailableError):
                await _deliver_draft(
                    ctx(kv), {"editor_draft_id": "d"}, target=7, channel_style=False
                )
        sender.assert_not_called()
