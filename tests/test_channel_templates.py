import unittest
from types import SimpleNamespace

from music_links_bot.channel_templates import (
    apply_channel_template,
    load_channel_template,
    save_channel_template,
)


class ChannelTemplateTests(unittest.IsolatedAsyncioTestCase):
    async def test_last_channel_style_becomes_next_draft_default(self) -> None:
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"kv_store": None})
        )
        await save_channel_template(
            context,
            "@stonerhand",
            {
                "hashtags": False,
                "large_preview": False,
                "as_photo": True,
                "platforms": ["spotify", "tidal", "unknown"],
                "preset": "cover",
                "publication_mode": "card",
                "custom_tags": ["#release-specific"],
            },
        )

        draft = {"hashtags": True, "large_preview": True}
        await apply_channel_template(context, "@StonerHand", draft)

        self.assertFalse(draft["hashtags"])
        self.assertFalse(draft["large_preview"])
        self.assertTrue(draft["as_photo"])
        self.assertEqual(draft["platforms"], ["spotify", "tidal"])
        self.assertEqual(draft["preset"], "cover")
        self.assertNotIn("custom_tags", draft)
        self.assertTrue(draft["channel_template_applied"])

    async def test_templates_are_isolated_per_channel(self) -> None:
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"kv_store": None})
        )
        await save_channel_template(context, "@one", {"hashtags": False})

        self.assertEqual(
            await load_channel_template(context, "@one"),
            {"hashtags": False},
        )
        self.assertEqual(await load_channel_template(context, "@two"), {})
