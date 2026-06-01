import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.soundcloud import build_soundcloud_fallback, parse_soundcloud_metadata


class SoundCloudTests(unittest.TestCase):
    def test_parse_soundcloud_metadata_removes_author_suffix(self) -> None:
        track = parse_soundcloud_metadata(
            "https://soundcloud.com/bondage-fairies/star-signs",
            {
                "title": "Star Signs by Bondage Fairies",
                "author_name": "Bondage Fairies",
            },
        )

        self.assertEqual(track.title, "Star Signs")
        self.assertEqual(track.artist, "Bondage Fairies")
        self.assertEqual(
            track.links,
            {"soundcloud": "https://soundcloud.com/bondage-fairies/star-signs"},
        )

    def test_parse_soundcloud_metadata_can_guess_artist_from_title(self) -> None:
        track = parse_soundcloud_metadata(
            "https://soundcloud.com/youth-code/transitions",
            {"title": "Youth Code - Transitions"},
        )

        self.assertEqual(track.title, "Transitions")
        self.assertEqual(track.artist, "Youth Code")

    def test_soundcloud_sets_are_treated_as_album_like_releases(self) -> None:
        track = parse_soundcloud_metadata(
            "https://soundcloud.com/artist/sets/demo",
            {"title": "Demo by Artist", "author_name": "Artist"},
        )

        self.assertEqual(track.kind, "album")

    def test_build_soundcloud_fallback_keeps_the_original_link(self) -> None:
        track = build_soundcloud_fallback("https://on.soundcloud.com/abc123")

        self.assertIsNotNone(track)
        assert track is not None
        self.assertEqual(track.artist, "SoundCloud")
        self.assertEqual(track.title, "SoundCloud")
        self.assertEqual(track.links, {"soundcloud": "https://on.soundcloud.com/abc123"})


if __name__ == "__main__":
    unittest.main()
