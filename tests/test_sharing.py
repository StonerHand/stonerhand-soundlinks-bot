import unittest

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from music_links_bot.sharing import (
    MAX_SHARE_QUERY_LENGTH,
    add_share_button,
    build_share_query,
    make_channel_safe_keyboard,
    parse_share_query,
)


class SharingTests(unittest.TestCase):
    def test_spotify_collection_is_compact_and_round_trips(self) -> None:
        urls = [
            f"https://open.spotify.com/track/{item_id}?si=tracking"
            for item_id in ("abc123", "def456", "ghi789", "jkl012", "mno345", "pqr678")
        ]

        query = build_share_query(urls)

        self.assertIsNotNone(query)
        assert query is not None
        self.assertLessEqual(len(query), MAX_SHARE_QUERY_LENGTH)
        self.assertEqual(
            parse_share_query(query),
            [
                f"https://open.spotify.com/track/{item_id}"
                for item_id in ("abc123", "def456", "ghi789", "jkl012", "mno345", "pqr678")
            ],
        )

    def test_youtube_url_round_trips(self) -> None:
        query = build_share_query(["https://www.youtube.com/watch?v=abc123&feature=share"])

        self.assertEqual(query, "sh|yabc123")
        self.assertEqual(parse_share_query(query), ["https://youtu.be/abc123"])

    def test_ten_spotify_tracks_fit_telegram_query_limit(self) -> None:
        query = build_share_query(
            [
                f"https://open.spotify.com/track/{index:022d}"
                for index in range(10)
            ]
        )

        self.assertIsNotNone(query)
        assert query is not None
        self.assertLessEqual(len(query), MAX_SHARE_QUERY_LENGTH)
        self.assertEqual(len(parse_share_query(query) or []), 10)

    def test_collection_is_not_partially_encoded(self) -> None:
        self.assertIsNone(
            build_share_query(
                [
                    "https://open.spotify.com/track/abc",
                    "https://example.com/not-supported",
                ]
            )
        )

    def test_malformed_share_query_is_rejected(self) -> None:
        self.assertEqual(parse_share_query("sh|tgood|bad"), [])
        self.assertIsNone(parse_share_query("normal search"))

    def test_share_button_preserves_existing_keyboard(self) -> None:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Spotify", url="https://open.spotify.com/track/abc")]]
        )

        result = add_share_button(
            keyboard,
            share_query="sh|tabc",
            label="↗️ Поделиться с кнопками",
        )

        self.assertEqual(result.inline_keyboard[0][0].text, "Spotify")
        self.assertEqual(result.inline_keyboard[1][0].switch_inline_query, "sh|tabc")

    def test_channel_keyboard_keeps_urls_and_removes_inline_switches(self) -> None:
        keyboard = add_share_button(
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("Spotify", url="https://open.spotify.com/track/abc")]]
            ),
            share_query="sh|tabc",
            label="↗️ Поделиться с кнопками",
        )

        result = make_channel_safe_keyboard(keyboard)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result.inline_keyboard), 1)
        self.assertEqual(result.inline_keyboard[0][0].text, "Spotify")
        self.assertEqual(
            result.inline_keyboard[0][0].url,
            "https://open.spotify.com/track/abc",
        )
