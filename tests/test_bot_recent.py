import unittest
from types import SimpleNamespace

from music_links_bot.bot_recent import render_drafts_view, render_recent_view


class RecentNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_drafts_and_published_history_are_separate(self) -> None:
        context = SimpleNamespace(
            application=SimpleNamespace(
                bot_data={
                    "bot_history": {
                        7: [
                            {
                                "artist": "Published Artist",
                                "title": "Published Track",
                                "source_url": "https://open.spotify.com/track/1",
                            }
                        ]
                    }
                }
            )
        )

        async def load_draft(_context, draft_id: str):
            if draft_id != "draft1":
                return None
            return {
                "item": {"artist": "Draft Artist", "title": "Draft Track"},
                "created_at": 1,
            }

        drafts_text, drafts_keyboard = await render_drafts_view(
            context,
            user_id=7,
            lang="ru",
            draft_ids=["draft1"],
            load_draft=load_draft,
        )
        recent_text, recent_keyboard = await render_recent_view(
            context,
            user_id=7,
            lang="ru",
        )

        self.assertIn("Draft Artist", drafts_text)
        self.assertNotIn("Published Artist", drafts_text)
        self.assertEqual(
            drafts_keyboard.inline_keyboard[0][0].callback_data,
            "v2|editor|b|draft1",
        )
        self.assertIn("Published Artist", recent_text)
        self.assertNotIn("Draft Artist", recent_text)
        self.assertEqual(
            recent_keyboard.inline_keyboard[0][0].switch_inline_query_current_chat,
            "https://open.spotify.com/track/1",
        )

    async def test_empty_drafts_have_one_clear_creation_action(self) -> None:
        context = SimpleNamespace(application=SimpleNamespace(bot_data={}))

        async def load_draft(_context, _draft_id: str):
            return None

        text, keyboard = await render_drafts_view(
            context,
            user_id=7,
            lang="ru",
            draft_ids=[],
            load_draft=load_draft,
        )

        self.assertIn("Черновиков пока нет", text)
        self.assertEqual(keyboard.inline_keyboard[0][0].text, "＋ Создать пост")
        self.assertEqual(keyboard.inline_keyboard[0][0].style, "primary")


if __name__ == "__main__":
    unittest.main()
