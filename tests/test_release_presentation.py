import unittest

from music_links_bot.models import TrackMatch
from music_links_bot.release_presentation import (
    apply_preset,
    normalize_preset,
)


class ReleasePresentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.track = TrackMatch(
            title="Dragonaut",
            artist="Sleep",
            links={"spotify": "https://open.spotify.com/track/1"},
            thumbnail_url="https://example.com/cover.jpg",
        )

    def test_legacy_presets_have_stable_migrations(self) -> None:
        self.assertEqual(normalize_preset("clean"), "cover")
        self.assertEqual(normalize_preset("editorial"), "minimal")
        self.assertEqual(
            normalize_preset("clean", {"publication_mode": "longread"}),
            "longread",
        )

    def test_preset_applies_all_delivery_flags_atomically(self) -> None:
        draft = {"large_preview": False, "as_photo": True}
        self.assertEqual(apply_preset(draft, "longread"), "longread")
        self.assertTrue(draft["large_preview"])
        self.assertFalse(draft["as_photo"])
        self.assertEqual(draft["publication_mode"], "longread")
