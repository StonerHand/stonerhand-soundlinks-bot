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


if __name__ == "__main__":
    unittest.main()
