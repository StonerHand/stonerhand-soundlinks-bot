"""The owner's cover signature survives restarts and can be reset."""

import unittest

from music_links_bot.artwork import cover_style
from music_links_bot.artwork.brand_settings import (
    BRAND_LABEL_KEY,
    load_brand_label,
    save_brand_label,
)


class _KV:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> bool:
        self.data[key] = value
        return True

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


class BrandSettingsTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        cover_style.set_brand_label_override(None)

    async def test_saved_label_is_cleaned_stored_and_applied(self) -> None:
        kv = _KV()
        saved = await save_brand_label(kv, "  @my   channel  " + "x" * 60)

        self.assertTrue(saved.startswith("@my channel "))
        self.assertEqual(len(saved), cover_style.MAX_BRAND_LABEL_LENGTH)
        self.assertEqual(kv.data[BRAND_LABEL_KEY], saved)
        self.assertEqual(cover_style.brand_label(), saved)

    async def test_another_instance_picks_up_the_stored_label(self) -> None:
        kv = _KV()
        kv.data[BRAND_LABEL_KEY] = "@night"

        await load_brand_label(kv)

        self.assertEqual(cover_style.brand_label(), "@night")

    async def test_empty_label_resets_to_the_default(self) -> None:
        kv = _KV()
        await save_brand_label(kv, "@night")
        await save_brand_label(kv, "   ")

        self.assertNotIn(BRAND_LABEL_KEY, kv.data)
        self.assertIsNone(cover_style.brand_label_override())

    async def test_without_storage_the_label_still_applies_locally(self) -> None:
        await load_brand_label(None)
        self.assertEqual(await save_brand_label(None, "@solo"), "@solo")
        self.assertEqual(cover_style.brand_label(), "@solo")


if __name__ == "__main__":
    unittest.main()
