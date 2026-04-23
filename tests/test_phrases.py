import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.phrases import PHRASES, pick_phrase


class PhrasesTests(unittest.TestCase):
    def test_each_phrase_group_has_twenty_variants(self) -> None:
        for phrases in PHRASES.values():
            self.assertEqual(len(phrases), 20)

    def test_pick_phrase_is_stable_for_seed(self) -> None:
        self.assertEqual(
            pick_phrase("track_cta", "Artist:Song:song"),
            pick_phrase("track_cta", "Artist:Song:song"),
        )


if __name__ == "__main__":
    unittest.main()
