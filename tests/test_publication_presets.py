import unittest
from types import SimpleNamespace

from music_links_bot.publication_presets import (
    MAX_PRESET_NAME_LENGTH,
    apply_named_preset,
    delete_named_preset,
    load_presets,
    normalize_preset_name,
    save_named_preset,
)


def make_context() -> SimpleNamespace:
    return SimpleNamespace(
        application=SimpleNamespace(bot_data={}),
    )


class PublicationPresetTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_apply_replace_and_delete(self) -> None:
        context = make_context()
        original = {
            "hashtags": False,
            "quote": True,
            "large_preview": False,
            "platforms": ["spotify", "youtube"],
            "preset": "minimal",
            "delivery_mode": "classic",
        }

        saved = await save_named_preset(context, 7, "  Канал   без шума  ", original)

        self.assertEqual(saved[0]["name"], "Канал без шума")
        target = {"hashtags": True, "delivery_mode": "auto"}
        name = await apply_named_preset(context, 7, 0, target)
        self.assertEqual(name, "Канал без шума")
        self.assertFalse(target["hashtags"])
        self.assertEqual(target["delivery_mode"], "classic")

        original["hashtags"] = True
        replaced = await save_named_preset(context, 7, "канал без шума", original)
        self.assertEqual(len(replaced), 1)
        self.assertTrue(replaced[0]["template"]["hashtags"])

        self.assertTrue(await delete_named_preset(context, 7, 0))
        self.assertEqual(await load_presets(context, 7), [])
        self.assertFalse(await delete_named_preset(context, 7, 0))

    def test_name_is_compact_and_bounded(self) -> None:
        self.assertEqual(normalize_preset_name(" a   b "), "a b")
        self.assertEqual(
            len(normalize_preset_name("x" * 100)),
            MAX_PRESET_NAME_LENGTH,
        )


if __name__ == "__main__":
    unittest.main()
