from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from music_links_bot.bot_crate import add_to_crate, load_crate
from music_links_bot.bot_runtime import BotRuntime
from music_links_bot.privacy import delete_user_data
from music_links_bot.publish_queue import add_job, load_jobs


def _draft(user_id: int, title: str) -> dict:
    return {
        "v": 5,
        "type": "track",
        "item": {
            "artist": "Sleep",
            "title": title,
            "links": {"spotify": "https://open.spotify.com/track/1"},
        },
        "chat_id": user_id,
        "lang": "ru",
    }


class PrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_user_data_clears_owned_state_only(self) -> None:
        runtime = BotRuntime()
        bot_data = {
            "runtime": runtime,
            "drafts": {
                "own": _draft(7, "Dragonaut"),
                "other": _draft(8, "Flood"),
            },
            "search_selections": {
                "s1": {"user_id": 7, "urls": ["https://example.test/1"]},
                "s2": {"user_id": 8, "urls": ["https://example.test/2"]},
            },
            "retry_sources": {},
            "bot_history": {7: [{"title": "Dragonaut"}]},
            "inline_history": {7: ["https://example.test/1"]},
        }
        application = SimpleNamespace(bot_data=bot_data)
        context = SimpleNamespace(application=application)
        session = await runtime.get_session(7)
        session.active_draft_id = "own"
        session.recent_draft_ids = ["own"]
        await add_to_crate(
            bot_data,
            7,
            draft_id="own",
            item=_draft(7, "Dragonaut")["item"],
        )
        await add_job(context, _draft(7, "Dragonaut"), 1000)
        await add_job(context, _draft(8, "Flood"), 2000)

        with patch("music_links_bot.privacy.remove_identity") as remove_identity:
            result = await delete_user_data(context, 7)

        self.assertEqual(result.drafts, 1)
        self.assertEqual(result.scheduled_posts, 1)
        self.assertTrue(result.queue_available)
        self.assertNotIn("own", bot_data["drafts"])
        self.assertIn("other", bot_data["drafts"])
        self.assertEqual(await load_crate(bot_data, 7), [])
        self.assertNotIn(7, runtime.sessions)
        self.assertNotIn("s1", bot_data["search_selections"])
        self.assertIn("s2", bot_data["search_selections"])
        self.assertNotIn(7, bot_data["bot_history"])
        self.assertNotIn(7, bot_data["inline_history"])
        jobs = await load_jobs(context)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["draft"]["chat_id"], 8)
        remove_identity.assert_called_once_with(7)
