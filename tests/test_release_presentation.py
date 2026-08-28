import unittest

from music_links_bot.models import TrackMatch
from music_links_bot.release_presentation import (
    apply_preset,
    compact_release_title,
    normalize_preset,
    shared_collection_artist,
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

    def test_compact_release_title_hides_only_trailing_remaster_metadata(self) -> None:
        self.assertEqual(
            compact_release_title("There's No Other Way - 2012 Remaster"),
            "There's No Other Way",
        )
        self.assertEqual(compact_release_title("Fool (Remastered 2012)"), "Fool")
        self.assertEqual(
            compact_release_title("Remastering the Past"), "Remastering the Past"
        )

    def test_shared_collection_artist_requires_every_item_to_match(self) -> None:
        matching = [
            self.track,
            TrackMatch(title="Holy Mountain", artist="sleep", links={}),
        ]
        mixed = [
            self.track,
            TrackMatch(title="Funeralopolis", artist="Electric Wizard", links={}),
        ]

        self.assertEqual(shared_collection_artist(matching), "Sleep")
        self.assertIsNone(shared_collection_artist(mixed))
