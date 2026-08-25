import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.phrases import PHRASES, pick_phrase


class PhrasesTests(unittest.TestCase):
    def test_only_concise_recovery_phrase_groups_remain(self) -> None:
        self.assertEqual(
            set(PHRASES),
            {"no_url", "service_unavailable", "not_found"},
        )
        for phrases in PHRASES.values():
            self.assertEqual(len(phrases), 3)

    def test_pick_phrase_is_stable_for_seed(self) -> None:
        self.assertEqual(
            pick_phrase("not_found", "Artist:Song:song"),
            pick_phrase("not_found", "Artist:Song:song"),
        )


if __name__ == "__main__":
    unittest.main()
