import unittest

from music_links_bot.button_styles import bot_button, button_style_kwargs


class ButtonStylesTests(unittest.TestCase):
    def test_neutral_button_has_no_style_field(self) -> None:
        button = bot_button("Назад", callback_data="back")

        self.assertEqual(dict(button.api_kwargs), {})
        self.assertNotIn("style", button.to_dict())

    def test_semantic_style_reaches_bot_api_payload(self) -> None:
        button = bot_button("Опубликовать", callback_data="publish", style="success")

        self.assertEqual(button.api_kwargs, {"style": "success"})
        self.assertEqual(button.to_dict()["style"], "success")

    def test_invalid_style_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            button_style_kwargs("orange")  # type: ignore[arg-type]
