import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot import publish_queue


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

    def test_queue_caps_job_count(self) -> None:
        context = make_context()

        async def scenario():
            for index in range(publish_queue.MAX_QUEUE_JOBS + 5):
                await publish_queue.add_job(context, make_draft(), 1000 + index)
            return await publish_queue.load_jobs(context)

        jobs = asyncio.run(scenario())
        self.assertEqual(len(jobs), publish_queue.MAX_QUEUE_JOBS)


class FailingBot:
    """Publishing to the channel fails; DMs to the admin (alerts) succeed."""

    def __init__(self, admin_id: int) -> None:
        self.sent: list[dict] = []
        self._admin_id = admin_id

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        if kwargs.get("chat_id") == self._admin_id:
            return SimpleNamespace(message_id=1)
        raise RuntimeError("channel unavailable")


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
        self.assertEqual(jobs[0]["publish_at"], 200 + publish_queue.RETRY_BACKOFF_SECONDS[0])

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
