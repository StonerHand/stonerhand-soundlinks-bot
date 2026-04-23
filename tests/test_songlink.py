import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.models import TrackMatch
from music_links_bot.songlink import SonglinkClient


class SonglinkClientTests(unittest.TestCase):
    def test_merge_matches_combines_platform_links(self) -> None:
        client = SonglinkClient(user_countries=("RU", "US"))
        matches = [
            TrackMatch(
                title="Song",
                artist="Artist",
                links={"spotify": "https://spotify.example", "yandexMusic": "https://yandex.example"},
                kind="song",
            ),
            TrackMatch(
                title="Song",
                artist="Artist",
                links={"appleMusic": "https://apple.example", "youtubeMusic": "https://youtube.example"},
                release_year="2006",
                kind="song",
            ),
        ]

        merged = client._merge_matches(matches)

        self.assertEqual(
            merged.links,
            {
                "spotify": "https://spotify.example",
                "yandexMusic": "https://yandex.example",
                "appleMusic": "https://apple.example",
                "youtubeMusic": "https://youtube.example",
            },
        )
        self.assertEqual(merged.release_year, "2006")

    def test_extract_release_year_from_entities_uses_matching_type(self) -> None:
        client = SonglinkClient(user_countries=("US",))

        release_year = client._extract_release_year_from_entities(
            {
                "spotify:song:1": {"type": "song", "releaseDate": "1993-01-01"},
                "spotify:album:1": {"type": "album", "releaseDate": "1992-01-01"},
            },
            "song",
        )

        self.assertEqual(release_year, "1993")


if __name__ == "__main__":
    unittest.main()
