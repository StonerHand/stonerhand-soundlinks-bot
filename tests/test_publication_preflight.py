import unittest

from music_links_bot.models import TrackMatch
from music_links_bot.publication_preflight import validate_publication


class PublicationPreflightTests(unittest.TestCase):
    def test_regular_release_with_links_is_ready(self) -> None:
        result = validate_publication(
            {},
            TrackMatch(
                title="Dragonaut",
                artist="Sleep",
                links={"spotify": "https://open.spotify.com/track/abc"},
            ),
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.issues, ())

    def test_explicitly_empty_platform_selection_blocks_delivery(self) -> None:
        result = validate_publication(
            {"platforms": []},
            TrackMatch(
                title="Dragonaut",
                artist="Sleep",
                links={"spotify": "https://open.spotify.com/track/abc"},
            ),
        )

        self.assertFalse(result.ready)
        self.assertEqual([issue.code for issue in result.issues], ["no_platforms"])

    def test_uploaded_audio_does_not_require_external_links(self) -> None:
        result = validate_publication(
            {
                "source_audio_file_id": "telegram-audio",
                "platforms": [],
            },
            TrackMatch(title="Demo", artist="Local artist", links={}),
        )

        self.assertTrue(result.ready)

    def test_photo_without_cover_is_warning_not_blocker(self) -> None:
        result = validate_publication(
            {"as_photo": True},
            TrackMatch(
                title="Dragonaut",
                artist="Sleep",
                links={"spotify": "https://open.spotify.com/track/abc"},
            ),
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.warning_count, 1)
        self.assertEqual(result.issues[0].code, "missing_cover")


if __name__ == "__main__":
    unittest.main()
