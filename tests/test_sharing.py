import unittest

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from music_links_bot.bot_lookup import LookupBundle
from music_links_bot.models import TrackMatch
from music_links_bot.sharing import (
    MAX_SHARE_QUERY_LENGTH,
    add_share_button,
    build_share_query,
    collection_result_title,
    collection_title,
    make_channel_safe_keyboard,
    parse_share_query,
    render_inline_share_card,
)


class SharingTests(unittest.TestCase):
    def test_collection_titles_are_compact_and_use_correct_plural(self) -> None:
        self.assertEqual(collection_title("ru", 1), "Подборка · 1 релиз")
        self.assertEqual(collection_title("ru", 4), "Подборка · 4 релиза")
        self.assertEqual(collection_title("ru", 12), "Подборка · 12 релизов")
        self.assertEqual(collection_title("en", 2), "Collection · 2 releases")

    def test_partial_collection_title_shows_warning_and_progress(self) -> None:
        self.assertEqual(
            collection_result_title("ru", found=3, total=4),
            "⚠️ Подборка · 3 из 4",
        )
        self.assertEqual(
            collection_result_title("en", found=3, total=4),
            "⚠️ Collection · 3 of 4",
        )

    def test_inline_collection_never_hides_missing_source_count(self) -> None:
        tracks = [
            TrackMatch(
                title=f"Track {index}",
                artist="Artist",
                links={"spotify": f"https://open.spotify.com/track/{index}"},
            )
            for index in range(3)
        ]
        bundle = LookupBundle(
            tracks=tracks,
            unavailable_urls=[],
            videos=[],
            radios=[],
            playlists=[],
            artists=[],
        )

        card = render_inline_share_card(
            bundle,
            context=None,
            lang="ru",
            share_query=None,
            share_label="Поделиться",
            requested_count=6,
        )

        self.assertEqual(card.title, "⚠️ Подборка · 3 из 6")
        self.assertIn("<b>⚠️ Подборка · 3 из 6</b>", card.text)

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

        self.assertEqual(query, "sh2|yabc123")
        self.assertEqual(parse_share_query(query), ["https://youtu.be/abc123"])

    def test_legacy_share_query_still_opens_existing_posts(self) -> None:
        self.assertEqual(
            parse_share_query("sh|tabc123"),
            ["https://open.spotify.com/track/abc123"],
        )

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
            share_query="sh2|tabc",
            label="↗️ Поделиться с кнопками",
        )

        self.assertEqual(result.inline_keyboard[0][0].text, "Spotify")
        self.assertEqual(result.inline_keyboard[1][0].switch_inline_query, "sh2|tabc")

    def test_channel_keyboard_keeps_urls_and_removes_inline_switches(self) -> None:
        keyboard = add_share_button(
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("Spotify", url="https://open.spotify.com/track/abc")]]
            ),
            share_query="sh2|tabc",
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
