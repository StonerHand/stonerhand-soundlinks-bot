import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.models import TrackMatch
from music_links_bot.stats import format_stats_message, load_stats, record_matches


class StatsTests(unittest.TestCase):
    def test_record_matches_counts_posts_and_release_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stats.json"

            stats = record_matches(
                [
                    TrackMatch(title="Song", artist="Artist", links={}, kind="song"),
                    TrackMatch(title="Album", artist="Artist", links={}, kind="album"),
                ],
                path=path,
            )

            self.assertEqual(stats["posts"], 1)
            self.assertEqual(stats["song"], 1)
            self.assertEqual(stats["album"], 1)
            self.assertEqual(stats["collections"], 1)
            self.assertEqual(load_stats(path), stats)

    def test_format_stats_message(self) -> None:
        message = format_stats_message(
            {
                "posts": 3,
                "song": 2,
                "album": 1,
                "collections": 1,
            }
        )

        self.assertIn("постов обработано: 3", message)
        self.assertIn("альбомов: 1", message)


if __name__ == "__main__":
    unittest.main()
