from __future__ import annotations

import unittest
from types import SimpleNamespace

from music_links_bot.telegram_media_cache import (
    get_cached_file_id,
    remember_photo_file_id,
)


class TelegramMediaCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_photo_file_id_round_trips_in_memory(self) -> None:
        context = SimpleNamespace(application=SimpleNamespace(bot_data={}))
        message = SimpleNamespace(
            photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id="large")]
        )

        await remember_photo_file_id(context, "https://img.example/cover.jpg", message)

        self.assertEqual(
            await get_cached_file_id(context, "https://img.example/cover.jpg"),
            "large",
        )

    async def test_missing_photo_is_not_cached(self) -> None:
        context = SimpleNamespace(application=SimpleNamespace(bot_data={}))

        await remember_photo_file_id(
            context,
            "https://img.example/cover.jpg",
            SimpleNamespace(photo=[]),
        )

        self.assertIsNone(
            await get_cached_file_id(context, "https://img.example/cover.jpg")
        )


if __name__ == "__main__":
    unittest.main()
