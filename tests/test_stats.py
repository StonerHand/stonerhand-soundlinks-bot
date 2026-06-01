import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.models import (
    ArtistMatch,
    PlaylistMatch,
    RadioMatch,
    TrackMatch,
    VideoMatch,
)
from music_links_bot.stats import (
    format_stats_message,
    load_stats,
    record_artists,
    record_matches,
    record_mixed,
    record_playlists,
    record_radios,
    record_videos,
)


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
        self.assertIn("видео: 0", message)
        self.assertIn("радио: 0", message)
        self.assertIn("плейлистов: 0", message)
        self.assertIn("артистов: 0", message)

    def test_record_videos_counts_posts_and_video_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stats.json"

            stats = record_videos(
                [
                    VideoMatch(title="First", author="One", url="https://youtu.be/1"),
                    VideoMatch(title="Second", author="Two", url="https://youtu.be/2"),
                ],
                path=path,
                user={"id": 123, "label": "@viewer", "last_seen": "2026-04-23 16:00 UTC"},
                chat={"id": 456, "label": "private", "last_seen": "2026-04-23 16:00 UTC"},
            )

            self.assertEqual(stats["posts"], 1)
            self.assertEqual(stats["videos"], 2)
            self.assertEqual(stats["collections"], 1)
            self.assertEqual(stats["users"]["123"]["count"], 1)
            self.assertEqual(load_stats(path), stats)

    def test_record_radios_counts_posts_and_radio_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stats.json"

            stats = record_radios(
                [
                    RadioMatch(
                        title="Dark Energy",
                        station="NTS Radio",
                        url="https://nts.live/1",
                    )
                ],
                path=path,
            )

            self.assertEqual(stats["posts"], 1)
            self.assertEqual(stats["radios"], 1)
            self.assertEqual(stats["collections"], 0)
            self.assertEqual(load_stats(path), stats)

    def test_record_mixed_counts_one_post_with_music_and_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stats.json"

            stats = record_mixed(
                [TrackMatch(title="Song", artist="Artist", links={}, kind="song")],
                [VideoMatch(title="Live", author="Channel", url="https://youtu.be/1")],
                path=path,
            )

            self.assertEqual(stats["posts"], 1)
            self.assertEqual(stats["song"], 1)
            self.assertEqual(stats["videos"], 1)
            self.assertEqual(stats["collections"], 1)
            self.assertEqual(load_stats(path), stats)

    def test_record_mixed_counts_playlists_inside_collections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stats.json"

            stats = record_mixed(
                [],
                [VideoMatch(title="Live", author="Channel", url="https://youtu.be/1")],
                [
                    PlaylistMatch(
                        title="Women of Punk",
                        platform="Spotify",
                        url="https://open.spotify.com/playlist/1",
                    )
                ],
                path=path,
            )

            self.assertEqual(stats["posts"], 1)
            self.assertEqual(stats["videos"], 1)
            self.assertEqual(stats["playlists"], 1)
            self.assertEqual(stats["collections"], 1)

    def test_record_mixed_counts_artists_inside_collections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stats.json"

            stats = record_mixed(
                [],
                [VideoMatch(title="Live", author="Channel", url="https://youtu.be/1")],
                artists=[
                    ArtistMatch(
                        title="1.Kla$",
                        platform="Spotify",
                        url="https://open.spotify.com/artist/1",
                    )
                ],
                path=path,
            )

            self.assertEqual(stats["posts"], 1)
            self.assertEqual(stats["videos"], 1)
            self.assertEqual(stats["artists"], 1)
            self.assertEqual(stats["collections"], 1)

    def test_record_mixed_counts_radios_inside_collections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stats.json"

            stats = record_mixed(
                [],
                [VideoMatch(title="Live", author="Channel", url="https://youtu.be/1")],
                radios=[
                    RadioMatch(
                        title="Dark Energy",
                        station="NTS Radio",
                        url="https://nts.live/1",
                    )
                ],
                path=path,
            )

            self.assertEqual(stats["posts"], 1)
            self.assertEqual(stats["videos"], 1)
            self.assertEqual(stats["radios"], 1)
            self.assertEqual(stats["collections"], 1)

    def test_record_playlists_counts_posts_and_playlist_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stats.json"

            stats = record_playlists(
                [
                    PlaylistMatch(
                        title="Women of Punk",
                        platform="Spotify",
                        url="https://open.spotify.com/playlist/1",
                    )
                ],
                path=path,
            )

            self.assertEqual(stats["posts"], 1)
            self.assertEqual(stats["playlists"], 1)
            self.assertEqual(stats["collections"], 0)
            self.assertEqual(load_stats(path), stats)

    def test_record_artists_counts_posts_and_artist_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stats.json"

            stats = record_artists(
                [
                    ArtistMatch(
                        title="1.Kla$",
                        platform="Spotify",
                        url="https://open.spotify.com/artist/1",
                    )
                ],
                path=path,
            )

            self.assertEqual(stats["posts"], 1)
            self.assertEqual(stats["artists"], 1)
            self.assertEqual(stats["collections"], 0)
            self.assertEqual(load_stats(path), stats)

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
            self.assertEqual(stats["videos"], 0)
            self.assertEqual(stats["radios"], 0)
            self.assertEqual(stats["playlists"], 0)
            self.assertEqual(stats["artists"], 0)
            self.assertEqual(stats["users"], {})
            self.assertEqual(stats["chats"], {})


if __name__ == "__main__":
    unittest.main()
