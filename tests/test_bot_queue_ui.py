import unittest
from types import SimpleNamespace

from music_links_bot.bot_queue import render_queue


class BotQueueUiTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_queue_has_refresh_and_back(self) -> None:
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"publish_queue": []})
        )

        text, keyboard = await render_queue(context, lang="ru")

        self.assertIn("0", text)
        self.assertEqual(len(keyboard.inline_keyboard), 2)

    async def test_queue_lists_release_time_and_cancel_action(self) -> None:
        context = SimpleNamespace(
            application=SimpleNamespace(
                bot_data={
                    "timezone_name": "Europe/Moscow",
                    "publish_queue": [
                        {
                            "id": "job123",
                            "status": "pending",
                            "publish_at": 1_800_000_000,
                            "draft": {
                                "item": {
                                    "artist": "Sleep",
                                    "title": "Dragonaut",
                                }
                            },
                        }
                    ],
                }
            )
        )

        text, keyboard = await render_queue(context, lang="ru")

        self.assertIn("Sleep — Dragonaut", text)
        self.assertIn("<code>", text)
        self.assertEqual(
            keyboard.inline_keyboard[0][0].callback_data,
            "v2|queue|cancel|job123",
        )


if __name__ == "__main__":
    unittest.main()
