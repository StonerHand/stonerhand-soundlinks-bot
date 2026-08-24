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
            "v2|queue|cancel|0:job123",
        )

    async def test_long_queue_is_paginated_and_preserves_global_numbers(self) -> None:
        jobs = [
            {
                "id": f"job{index}",
                "status": "pending",
                "publish_at": 1_800_000_000 + index,
                "draft": {
                    "item": {"artist": "Artist", "title": f"Track {index}"}
                },
            }
            for index in range(1, 12)
        ]
        context = SimpleNamespace(
            application=SimpleNamespace(
                bot_data={"timezone_name": "Europe/Moscow", "publish_queue": jobs}
            )
        )

        text, keyboard = await render_queue(context, lang="ru", page=1)

        self.assertIn("Страница 2 из 2", text)
        self.assertIn("9. Artist — Track 9", text)
        self.assertNotIn("Track 1</b>", text)
        callbacks = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]
        self.assertIn("v2|queue|cancel|1:job9", callbacks)
        self.assertIn("v2|queue|open|0", callbacks)


if __name__ == "__main__":
    unittest.main()
