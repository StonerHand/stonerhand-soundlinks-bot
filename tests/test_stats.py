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
                user={
                    "id": 123,
                    "label": "@listener",
                    "last_seen": "2026-04-23 16:00 UTC",
                },
                chat={
                    "id": -100,
                    "label": "StonerHand (channel)",
                    "last_seen": "2026-04-23 16:00 UTC",
                },
            )

            self.assertEqual(stats["posts"], 1)
            self.assertEqual(stats["song"], 1)
            self.assertEqual(stats["album"], 1)
            self.assertEqual(stats["collections"], 1)
            self.assertEqual(stats["users"]["123"]["count"], 1)
            self.assertEqual(stats["chats"]["-100"]["count"], 1)
            self.assertEqual(load_stats(path), stats)

    def test_format_stats_message(self) -> None:
        message = format_stats_message(
            {
                "posts": 3,
                "song": 2,
                "album": 1,
                "podcast": 1,
                "collections": 1,
            }
        )

        self.assertIn("постов обработано: 3", message)
        self.assertIn("альбомов: 1", message)
        self.assertIn("подкастов: 1", message)

    def test_record_matches_counts_podcasts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stats.json"

            stats = record_matches(
                [
                    TrackMatch(
                        title="Episode",
                        artist="Podcast",
                        links={},
                        kind="podcast",
                    )
                ],
                path=path,
            )

            self.assertEqual(stats["podcast"], 1)
            self.assertEqual(stats["song"], 0)

    def test_format_stats_message_can_include_private_usage(self) -> None:
        message = format_stats_message(
            {
                "posts": 3,
                "song": 2,
                "album": 1,
                "collections": 1,
                "users": {
                    "123": {
                        "count": 2,
                        "label": "@listener",
                        "last_seen": "2026-04-23 16:00 UTC",
                    }
                },
                "chats": {
                    "-100": {
                        "count": 3,
                        "label": "StonerHand (channel)",
                        "last_seen": "2026-04-23 16:00 UTC",
                    }
                },
            },
            include_private=True,
        )

        self.assertIn("топ пользователей:", message)
        self.assertIn("@listener - 2", message)
        self.assertIn("StonerHand (channel) - 3", message)

    def test_load_stats_migrates_old_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stats.json"
            path.write_text(
                '{"posts": 2, "song": 1, "album": 1, "collections": 0}',
                encoding="utf-8",
            )

            stats = load_stats(path)

            self.assertEqual(stats["posts"], 2)
            self.assertEqual(stats["users"], {})
            self.assertEqual(stats["chats"], {})


if __name__ == "__main__":
    unittest.main()
