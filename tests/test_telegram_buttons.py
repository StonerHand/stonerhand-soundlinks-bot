import os
import unittest
from unittest.mock import patch

from telegram import InlineKeyboardMarkup

from music_links_bot.rich_publications import rich_button_rows_html
from music_links_bot.telegram_buttons import (
    ButtonIcon,
    ButtonTone,
    callback_button,
)


class TelegramButtonTests(unittest.TestCase):
    def test_regular_emoji_is_complete_custom_icon_fallback(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            button = callback_button(
                "+ Создать пост",
                "v2|menu|create",
                tone=ButtonTone.PRIMARY,
                icon=ButtonIcon.ADD,
            )

        self.assertEqual(button.text, "＋ Создать пост")
        self.assertEqual(button.style, "primary")
        self.assertIsNone(button.icon_custom_emoji_id)

    def test_configured_custom_icon_replaces_fallback_and_survives_rich_render(
        self,
    ) -> None:
        emoji_id = "5368324170671202286"
        with patch.dict(
            os.environ,
            {"TELEGRAM_BUTTON_ICON_ADD_ID": emoji_id},
            clear=True,
        ):
            button = callback_button(
                "+ Создать пост",
                "v2|menu|create",
                tone=ButtonTone.PRIMARY,
                icon=ButtonIcon.ADD,
            )
            html = rich_button_rows_html(InlineKeyboardMarkup([[button]]))

        self.assertEqual(button.text, "Создать пост")
        self.assertEqual(button.icon_custom_emoji_id, emoji_id)
        self.assertIn(f'<tg-emoji emoji-id="{emoji_id}">', html)
        self.assertIn('style="primary"', html)

    def test_invalid_custom_icon_id_falls_back_safely(self) -> None:
        with patch.dict(
            os.environ,
            {"TELEGRAM_BUTTON_ICON_READY_ID": "not-an-id"},
            clear=True,
        ):
            button = callback_button(
                "Готово",
                "v2|editor|done",
                icon=ButtonIcon.READY,
            )

        self.assertEqual(button.text, "✓ Готово")
        self.assertIsNone(button.icon_custom_emoji_id)


if __name__ == "__main__":
    unittest.main()
