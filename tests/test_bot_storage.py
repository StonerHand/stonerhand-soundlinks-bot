import unittest
from types import SimpleNamespace

from music_links_bot.bot_storage import load_draft, remember_bounded, valid_state_id


class BotStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_external_state_id_never_reaches_storage(self) -> None:
        class KVSpy:
            called = False

            async def get_json(self, _key):
                self.called = True
                return {"type": "track"}

        kv = KVSpy()
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"kv_store": kv})
        )

        self.assertIsNone(await load_draft(context, "x" * 1000))
        self.assertFalse(kv.called)
        self.assertTrue(valid_state_id("draft_ABC-123"))
        self.assertFalse(valid_state_id("../draft"))

    async def test_generic_warm_cache_stays_bounded(self) -> None:
        memory = {}
        for index in range(10):
            remember_bounded(memory, index, [index], max_size=3)

        self.assertEqual(list(memory), [7, 8, 9])
        with self.assertRaises(ValueError):
            remember_bounded(memory, 10, [10], max_size=0)


if __name__ == "__main__":
    unittest.main()
