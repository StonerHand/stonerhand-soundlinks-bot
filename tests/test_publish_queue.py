import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from telegram.error import BadRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot import publish_queue
from music_links_bot.draft_model import CURRENT_DRAFT_VERSION


class BotStub:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(message_id=1)


def make_context() -> SimpleNamespace:
    application = SimpleNamespace(bot_data={}, bot=BotStub())
    return SimpleNamespace(application=application, bot=application.bot)


def make_draft() -> dict:
    return {
        "v": 1,
        "type": "track",
        "item": {
            "artist": "Sleep",
            "title": "Dragonaut",
            "links": {"spotify": "https://open.spotify.com/track/x"},
            "page_url": "https://song.link/x",
        },
        "prefix": "",
        "hashtags": True,
        "quote": False,
        "large_preview": True,
        "chat_id": 1,
        "lang": "ru",
        "can_publish": True,
    }


class PublishQueueTests(unittest.TestCase):
    def test_durable_write_failure_never_reports_a_scheduled_job(self) -> None:
        from music_links_bot.kvstore import KVUnavailableError

        class FailingDurableKV:
            async def set_required(self, *args, **kwargs):
                return True

            async def get_json_required(self, key):
                return None

            async def set_json_required(self, key, value):
                raise KVUnavailableError("offline")

            async def delete_if_value(self, key, owner):
                return True

        context = make_context()
        context.application.bot_data["kv_store"] = FailingDurableKV()

        async def scenario():
            with self.assertRaises(publish_queue.QueueStorageError):
                await publish_queue.add_job(context, make_draft(), 1000)

        asyncio.run(scenario())
        self.assertEqual(
            context.application.bot_data.get(publish_queue.QUEUE_MEMORY_KEY),
            [],
        )

    def test_claim_keeps_job_durable_until_publish_finishes(self) -> None:
        context = make_context()

        async def scenario():
            job = await publish_queue.add_job(context, make_draft(), 100)
            claimed = await publish_queue._claim_due_jobs(
                context, now=200, owner="worker-a"
            )
            stored = await publish_queue.load_jobs(context)
            return job, claimed, stored

        job, claimed, stored = asyncio.run(scenario())
        self.assertEqual([item["id"] for item in claimed], [job["id"]])
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["status"], publish_queue.JOB_PROCESSING)
        self.assertEqual(stored[0]["lease_owner"], "worker-a")

    def test_expired_processing_lease_is_reclaimed(self) -> None:
        context = make_context()

        async def scenario():
            await publish_queue.add_job(context, make_draft(), 100)
            await publish_queue._claim_due_jobs(context, now=200, owner="dead-worker")
            before = await publish_queue.process_due_jobs(
                context, now=200 + publish_queue.PROCESSING_LEASE_SECONDS - 1
            )
            after = await publish_queue.process_due_jobs(
                context, now=200 + publish_queue.PROCESSING_LEASE_SECONDS
            )
            return before, after, await publish_queue.load_jobs(context)

        before, after, jobs = asyncio.run(scenario())
        self.assertEqual(before, 0)
        self.assertEqual(after, 1)
        self.assertEqual(jobs, [])
        self.assertEqual(len(context.bot.sent), 1)

    def test_memory_queue_mutations_are_serialized(self) -> None:
        context = make_context()

        async def scenario():
            await asyncio.gather(
                *(
                    publish_queue.add_job(context, make_draft(), 1000 + index)
                    for index in range(20)
                )
            )
            return await publish_queue.load_jobs(context)

        jobs = asyncio.run(scenario())
        self.assertEqual(len(jobs), 20)
        self.assertEqual(len({job["id"] for job in jobs}), 20)

    def test_sent_post_is_not_repeated_if_finalization_is_lost(self) -> None:
        context = make_context()

        async def scenario():
            await publish_queue.add_job(context, make_draft(), 100)
            with patch.object(
                publish_queue,
                "_finish_job",
                side_effect=publish_queue.QueueStorageError("offline after delivery"),
            ):
                await publish_queue.process_due_jobs(context, now=200)
            await publish_queue.process_due_jobs(context, now=400)
            await publish_queue.process_due_jobs(context, now=600)
            return await publish_queue.load_jobs(context)

        jobs = asyncio.run(scenario())
        self.assertEqual(len(context.bot.sent), 1)
        self.assertEqual(jobs[0]["status"], publish_queue.JOB_UNCERTAIN)

    def test_manual_retry_cannot_reclaim_an_active_delivery(self) -> None:
        context = make_context()

        async def scenario():
            job = await publish_queue.add_job(context, make_draft(), 100)
            await publish_queue._claim_due_jobs(context, now=200, owner="worker")
            await publish_queue._mark_delivery_started(
                context, job_id=job["id"], owner="worker", now=200
            )
            active = await publish_queue.reschedule_job(context, job["id"], 201)
            await publish_queue._recover_uncertain_jobs(context, now=400)
            resumed = await publish_queue.reschedule_job(
                context, job["id"], 401, only_uncertain=True
            )
            duplicate = await publish_queue.reschedule_job(
                context, job["id"], 401, only_uncertain=True
            )
            return active, resumed, duplicate

        self.assertEqual(asyncio.run(scenario()), (False, True, False))

    def test_lost_telegram_response_quarantines_job_without_retry(self) -> None:
        context = make_context()

        async def accepted_then_timeout(**kwargs):
            context.bot.sent.append(kwargs)
            raise TimeoutError("response lost after Telegram accepted the message")

        async def scenario():
            await publish_queue.add_job(context, make_draft(), 100)
            with patch.object(context.bot, "send_message", accepted_then_timeout):
                await publish_queue.process_due_jobs(context, now=200)
                await publish_queue.process_due_jobs(context, now=500)
            return await publish_queue.load_jobs(context)

        jobs = asyncio.run(scenario())
        self.assertEqual(len(context.bot.sent), 1)
        self.assertEqual(jobs[0]["status"], publish_queue.JOB_UNCERTAIN)

    def test_busy_redis_lock_never_falls_back_to_unsafe_mutation(self) -> None:
        class BusyKV:
            async def set(self, *args, **kwargs):
                return False

        context = make_context()
        context.application.bot_data["kv_store"] = BusyKV()

        async def scenario():
            with self.assertRaises(publish_queue.QueueBusyError):
                await publish_queue.add_job(context, make_draft(), 1000)

        asyncio.run(scenario())
        self.assertNotIn(publish_queue.QUEUE_MEMORY_KEY, context.application.bot_data)

    def test_add_and_list_jobs_sorted_by_time(self) -> None:
        context = make_context()

        async def scenario():
            await publish_queue.add_job(context, make_draft(), 2000)
            await publish_queue.add_job(context, make_draft(), 1000)
            return await publish_queue.load_jobs(context)

        jobs = asyncio.run(scenario())
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["publish_at"], 1000)
        self.assertEqual(jobs[1]["publish_at"], 2000)

    def test_queue_stores_only_normalized_publication_drafts(self) -> None:
        context = make_context()
        draft = make_draft()
        draft["item"]["unknown_future_field"] = "ignored"

        async def scenario():
            job = await publish_queue.add_job(context, draft, 1000)
            return job["draft"]

        stored = asyncio.run(scenario())
        self.assertEqual(stored["v"], CURRENT_DRAFT_VERSION)
        self.assertNotIn("unknown_future_field", stored["item"])

    def test_queue_rejects_invalid_draft_before_storage(self) -> None:
        context = make_context()

        async def scenario():
            with self.assertRaises(ValueError):
                await publish_queue.add_job(context, {"item": {}}, 1000)

        asyncio.run(scenario())
        self.assertNotIn(publish_queue.QUEUE_MEMORY_KEY, context.application.bot_data)

    def test_remove_job(self) -> None:
        context = make_context()

        async def scenario():
            job = await publish_queue.add_job(context, make_draft(), 1000)
            removed = await publish_queue.remove_job(context, job["id"])
            missing = await publish_queue.remove_job(context, "nope")
            return removed, missing, await publish_queue.load_jobs(context)

        removed, missing, jobs = asyncio.run(scenario())
        self.assertTrue(removed)
        self.assertFalse(missing)
        self.assertEqual(jobs, [])

    def test_active_delivery_cannot_be_cancelled_under_the_sender(self) -> None:
        context = make_context()

        async def scenario():
            job = await publish_queue.add_job(context, make_draft(), 100)
            claimed = await publish_queue._claim_due_jobs(
                context, now=200, owner="test-worker"
            )
            self.assertEqual(len(claimed), 1)
            with self.assertRaises(publish_queue.QueueBusyError):
                await publish_queue.remove_job(context, job["id"])
            return await publish_queue.load_jobs(context)

        jobs = asyncio.run(scenario())
        self.assertEqual(jobs[0]["status"], publish_queue.JOB_PROCESSING)

    def test_remove_user_jobs_keeps_other_users_schedule(self) -> None:
        context = make_context()

        async def scenario():
            own = make_draft()
            own["chat_id"] = 7
            other = make_draft()
            other["chat_id"] = 8
            await publish_queue.add_job(context, own, 1000)
            await publish_queue.add_job(context, other, 2000)
            removed = await publish_queue.remove_user_jobs(context, 7)
            return removed, await publish_queue.load_jobs(context)

        removed, jobs = asyncio.run(scenario())
        self.assertEqual(removed, 1)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["draft"]["chat_id"], 8)

    def test_remove_user_jobs_cannot_delete_an_active_delivery(self) -> None:
        context = make_context()

        async def scenario():
            own = make_draft()
            own["chat_id"] = 7
            job = await publish_queue.add_job(context, own, 100)
            await publish_queue._claim_due_jobs(context, now=200, owner="privacy-race")
            with self.assertRaises(publish_queue.QueueBusyError):
                await publish_queue.remove_user_jobs(context, 7)
            return job, await publish_queue.load_jobs(context)

        job, jobs = asyncio.run(scenario())
        self.assertEqual([item["id"] for item in jobs], [job["id"]])
        self.assertEqual(jobs[0]["status"], publish_queue.JOB_PROCESSING)

    def test_remove_user_jobs_ignores_a_corrupt_legacy_owner(self) -> None:
        context = make_context()

        async def scenario():
            own = make_draft()
            own["chat_id"] = 7
            await publish_queue.add_job(context, own, 1000)
            context.application.bot_data[publish_queue.QUEUE_MEMORY_KEY].append(
                {
                    "id": "legacy-corrupt",
                    "status": publish_queue.JOB_PENDING,
                    "publish_at": 2000,
                    "draft": {"chat_id": "not-an-id"},
                }
            )
            removed = await publish_queue.remove_user_jobs(context, 7)
            return removed, await publish_queue.load_jobs(context)

        removed, jobs = asyncio.run(scenario())
        self.assertEqual(removed, 1)
        self.assertEqual([job["id"] for job in jobs], ["legacy-corrupt"])

    def test_process_due_jobs_publishes_and_keeps_future(self) -> None:
        context = make_context()

        async def scenario():
            await publish_queue.add_job(context, make_draft(), 100)
            await publish_queue.add_job(context, make_draft(), 9_999_999_999)
            published = await publish_queue.process_due_jobs(context, now=200)
            return published, await publish_queue.load_jobs(context)

        published, jobs = asyncio.run(scenario())
        self.assertEqual(published, 1)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["publish_at"], 9_999_999_999)
        self.assertEqual(len(context.bot.sent), 1)
        self.assertIn("Dragonaut", context.bot.sent[0]["text"])

    def test_process_due_jobs_noop_when_nothing_due(self) -> None:
        context = make_context()

        async def scenario():
            await publish_queue.add_job(context, make_draft(), 9_999_999_999)
            return await publish_queue.process_due_jobs(context, now=200)

        self.assertEqual(asyncio.run(scenario()), 0)
        self.assertEqual(context.bot.sent, [])

    def test_tick_claims_only_a_bounded_batch(self) -> None:
        context = make_context()

        async def scenario():
            for _ in range(publish_queue.MAX_JOBS_PER_TICK + 2):
                await publish_queue.add_job(context, make_draft(), 100)
            published = await publish_queue.process_due_jobs(context, now=200)
            return published, await publish_queue.load_jobs(context)

        published, jobs = asyncio.run(scenario())
        self.assertEqual(published, publish_queue.MAX_JOBS_PER_TICK)
        self.assertEqual(len(jobs), 2)
        self.assertTrue(all(job["status"] == publish_queue.JOB_PENDING for job in jobs))

    def test_queue_caps_job_count(self) -> None:
        context = make_context()

        async def scenario():
            for index in range(publish_queue.MAX_QUEUE_JOBS):
                await publish_queue.add_job(context, make_draft(), 1000 + index)
            with self.assertRaises(publish_queue.QueueFullError):
                await publish_queue.add_job(context, make_draft(), 9999)
            return await publish_queue.load_jobs(context)

        jobs = asyncio.run(scenario())
        self.assertEqual(len(jobs), publish_queue.MAX_QUEUE_JOBS)
        self.assertEqual(jobs[0]["publish_at"], 1000)


class FailingBot:
    """Publishing to the channel fails; DMs to the admin (alerts) succeed."""

    def __init__(self, admin_id: int) -> None:
        self.sent: list[dict] = []
        self._admin_id = admin_id

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        if kwargs.get("chat_id") == self._admin_id:
            return SimpleNamespace(message_id=1)
        raise BadRequest("channel unavailable")


class RetryTests(unittest.TestCase):
    def _context(self, admin_id: int = 42) -> SimpleNamespace:
        application = SimpleNamespace(
            bot_data={"admin_chat_id": admin_id}, bot=FailingBot(admin_id)
        )
        return SimpleNamespace(application=application, bot=application.bot)

    def test_failed_publish_is_requeued_with_backoff_not_dropped(self) -> None:
        context = self._context()

        async def scenario():
            await publish_queue.add_job(context, make_draft(), 100)
            published = await publish_queue.process_due_jobs(context, now=200)
            return published, await publish_queue.load_jobs(context)

        published, jobs = asyncio.run(scenario())
        self.assertEqual(published, 0)
        # the post is NOT lost — it is put back with an attempt count and backoff
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["attempts"], 1)
        self.assertEqual(
            jobs[0]["publish_at"], 200 + publish_queue.RETRY_BACKOFF_SECONDS[0]
        )

    def test_dropped_and_alerted_after_max_attempts(self) -> None:
        context = self._context(admin_id=42)

        async def scenario():
            job = {
                "id": "j1",
                "publish_at": 100,
                "attempts": publish_queue.MAX_JOB_ATTEMPTS - 1,
                "draft": make_draft(),
            }
            context.application.bot_data["publish_queue"] = [job]
            published = await publish_queue.process_due_jobs(context, now=200)
            return published, await publish_queue.load_jobs(context)

        published, jobs = asyncio.run(scenario())
        self.assertEqual(published, 0)
        self.assertEqual(jobs, [])  # exhausted — dropped
        alerts = [m for m in context.bot.sent if m.get("chat_id") == 42]
        self.assertEqual(len(alerts), 1)
        self.assertIn("Dragonaut", alerts[0]["text"])


class RescheduleTests(unittest.TestCase):
    def test_reschedule_moves_job_and_resorts(self) -> None:
        context = make_context()

        async def scenario():
            a = await publish_queue.add_job(context, make_draft(), 5000)
            await publish_queue.add_job(context, make_draft(), 2000)
            moved = await publish_queue.reschedule_job(context, a["id"], 1000)
            missing = await publish_queue.reschedule_job(context, "nope", 1000)
            return moved, missing, await publish_queue.load_jobs(context)

        moved, missing, jobs = asyncio.run(scenario())
        self.assertTrue(moved)
        self.assertFalse(missing)
        self.assertEqual(jobs[0]["publish_at"], 1000)
        self.assertEqual(jobs[1]["publish_at"], 2000)


if __name__ == "__main__":
    unittest.main()
