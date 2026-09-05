import unittest

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from music_links_bot.publication_contract import (
    RenderedPublication,
    validate_rendered_publication,
)


class PublicationContractTests(unittest.TestCase):
    def test_accepts_a_complete_classic_card(self) -> None:
        result = validate_rendered_publication(
            RenderedPublication(
                text="🎧 · <b>Artist</b>\nSong\n\n#stonerhand #track",
                keyboard=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🟢 Spotify",
                                url="https://open.spotify.com/track/abc",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "🪩 Все платформы",
                                url="https://song.link/s/abc",
                            )
                        ],
                    ]
                ),
                preview_url="https://images.example/cover.jpg",
                cover_url="https://images.example/cover.jpg",
                source_urls=("https://open.spotify.com/track/abc",),
                cover_expected=True,
            )
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.issues, ())

    def test_blocks_a_visible_music_source_url(self) -> None:
        result = validate_rendered_publication(
            RenderedPublication(
                text="Текст https://open.spotify.com/track/abc",
            )
        )

        self.assertIn("visible_source_url", result.blocking_codes)

    def test_partial_collection_requires_an_exact_count(self) -> None:
        result = validate_rendered_publication(
            RenderedPublication(
                text="<b>Подборка</b>\n1. Artist — Song",
                found_count=1,
                requested_count=4,
                content_kind="collection",
            )
        )

        self.assertIn("missing_partial_count", result.blocking_codes)

    def test_universal_button_must_not_fall_back_to_provider(self) -> None:
        result = validate_rendered_publication(
            RenderedPublication(
                text="Artist — Song",
                keyboard=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🪩 Все платформы",
                                url="https://open.spotify.com/track/abc",
                            )
                        ]
                    ]
                ),
            )
        )

        self.assertIn("universal_button_mismatch", result.blocking_codes)

    def test_platform_label_must_match_destination_host(self) -> None:
        result = validate_rendered_publication(
            RenderedPublication(
                text="Artist — Song",
                keyboard=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🟢 Spotify",
                                url="https://evil.example/track/abc",
                            )
                        ]
                    ]
                ),
            )
        )

        self.assertIn("platform_button_mismatch", result.blocking_codes)

    def test_release_title_ending_in_platform_name_is_not_a_platform_button(
        self,
    ) -> None:
        result = validate_rendered_publication(
            RenderedPublication(
                text="Подборка · 1 релиз",
                keyboard=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "1 · Artist — Lost on Spotify",
                                url="https://song.link/s/abc",
                            )
                        ]
                    ]
                ),
                found_count=1,
                requested_count=1,
                content_kind="collection",
            )
        )

        self.assertTrue(result.ready)

    def test_rejects_oversized_callback_data(self) -> None:
        result = validate_rendered_publication(
            RenderedPublication(
                text="Artist — Song",
                keyboard=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Изменить", callback_data="я" * 33)]]
                ),
            )
        )

        self.assertIn("invalid_callback_data", result.blocking_codes)

    def test_rejects_oversized_inline_query(self) -> None:
        result = validate_rendered_publication(
            RenderedPublication(
                text="Artist — Song",
                keyboard=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "Поделиться",
                                switch_inline_query="x" * 257,
                            )
                        ]
                    ]
                ),
            )
        )

        self.assertIn("invalid_inline_query", result.blocking_codes)

    def test_rejects_raw_multi_url_inline_collection(self) -> None:
        query = (
            "https://open.spotify.com/track/first https://open.spotify.com/track/second"
        )
        result = validate_rendered_publication(
            RenderedPublication(
                text="Подборка · 2 релиза",
                keyboard=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Поделиться", switch_inline_query=query)]]
                ),
                found_count=2,
                requested_count=2,
                content_kind="collection",
            )
        )

        self.assertIn("raw_collection_inline_query", result.blocking_codes)

    def test_accepts_compact_collection_inline_token(self) -> None:
        result = validate_rendered_publication(
            RenderedPublication(
                text="Подборка · 2 релиза",
                keyboard=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "Поделиться",
                                switch_inline_query="sh5|tabc|tdef",
                            )
                        ]
                    ]
                ),
                found_count=2,
                requested_count=2,
                content_kind="collection",
            )
        )

        self.assertTrue(result.ready)


if __name__ == "__main__":
    unittest.main()
