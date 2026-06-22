import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from telegram import MessageEntity

from music_links_bot.telegram_text import format_user_note_html


def utf16_offset(text: str, index: int) -> int:
    return len(text[:index].encode("utf-16-le")) // 2


class TelegramTextTests(unittest.TestCase):
    def test_preserves_formatting_and_paragraphs_after_source_url_removal(self) -> None:
        text = (
            "🎧 Жирный текст\n\n"
            "Курсивная строка\n"
            "https://open.spotify.com/track/1?si=test"
        )
        bold_start = text.index("Жирный")
        italic_start = text.index("Курсивная")
        entities = (
            MessageEntity(
                MessageEntity.BOLD,
                utf16_offset(text, bold_start),
                utf16_offset(text, bold_start + len("Жирный текст"))
                - utf16_offset(text, bold_start),
            ),
            MessageEntity(
                MessageEntity.ITALIC,
                utf16_offset(text, italic_start),
                utf16_offset(text, italic_start + len("Курсивная строка"))
                - utf16_offset(text, italic_start),
            ),
        )

        self.assertEqual(
            format_user_note_html(text, entities, max_length=700),
            "🎧 <b>Жирный текст</b>\n\n<i>Курсивная строка</i>",
        )

    def test_preserves_safe_text_links(self) -> None:
        text = "читать статью\nhttps://open.spotify.com/track/1"
        entity = MessageEntity(
            MessageEntity.TEXT_LINK,
            offset=0,
            length=utf16_offset(text, len("читать статью")),
            url="https://example.com/?a=1&b=2",
        )

        self.assertEqual(
            format_user_note_html(text, (entity,), max_length=700),
            '<a href="https://example.com/?a=1&amp;b=2">читать статью</a>',
        )

    def test_preserves_nested_bold_and_italic_entities(self) -> None:
        text = "очень важный текст"
        entities = (
            MessageEntity(
                MessageEntity.BOLD,
                offset=0,
                length=utf16_offset(text, len(text)),
            ),
            MessageEntity(
                MessageEntity.ITALIC,
                offset=utf16_offset(text, text.index("важный")),
                length=utf16_offset("важный", len("важный")),
            ),
        )

        self.assertEqual(
            format_user_note_html(text, entities, max_length=700),
            "<b>очень <i>важный</i> текст</b>",
        )

    def test_drops_unsafe_link_markup_but_keeps_its_text(self) -> None:
        text = "открыть"
        entity = MessageEntity(
            MessageEntity.TEXT_LINK,
            offset=0,
            length=utf16_offset(text, len(text)),
            url="javascript:alert(1)",
        )

        self.assertEqual(
            format_user_note_html(text, (entity,), max_length=700),
            "открыть",
        )

    def test_truncation_keeps_html_balanced(self) -> None:
        text = "очень длинная жирная строка"
        entity = MessageEntity(
            MessageEntity.BOLD,
            offset=0,
            length=utf16_offset(text, len(text)),
        )

        self.assertEqual(
            format_user_note_html(text, (entity,), max_length=12),
            "<b>очень длинн</b>…",
        )


if __name__ == "__main__":
    unittest.main()
