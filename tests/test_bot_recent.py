import unittest
from types import SimpleNamespace

from music_links_bot.chat.bot_recent import render_drafts_view


class RecentNavigationTests(unittest.IsolatedAsyncioTestCase):
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

        self.assertIn("Здесь будут твои посты", text)
        self.assertIn(
            "➕ Новый пост", [b.text for row in keyboard.inline_keyboard for b in row]
        )
        self.assertEqual(
            next(
                b.style
                for row in keyboard.inline_keyboard
                for b in row
                if b.callback_data == "v2|menu|create"
            ),
            "primary",
        )


if __name__ == "__main__":
    unittest.main()
