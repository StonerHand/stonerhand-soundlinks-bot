import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.url_utils import extract_supported_urls, is_supported_music_url


class UrlUtilsTests(unittest.TestCase):
    def test_is_supported_music_url_accepts_supported_hosts(self) -> None:
        self.assertTrue(is_supported_music_url("https://open.spotify.com/track/123"))
        self.assertTrue(is_supported_music_url("https://music.youtube.com/watch?v=abc"))
        self.assertTrue(is_supported_music_url("https://music.yandex.ru/album/1/track/2"))

    def test_is_supported_music_url_rejects_other_hosts(self) -> None:
        self.assertFalse(is_supported_music_url("https://example.com/track/123"))
        self.assertFalse(is_supported_music_url("not-a-url"))

    def test_extract_supported_urls_skips_unsupported_urls(self) -> None:
        text = (
            "Сначала https://example.com/test, потом "
            "https://open.spotify.com/track/123?si=456."
        )

        self.assertEqual(
            extract_supported_urls(text),
            ["https://open.spotify.com/track/123?si=456"],
        )

    def test_extract_supported_urls_returns_unique_supported_urls(self) -> None:
        text = (
            "https://open.spotify.com/track/1 "
            "https://example.com/nope "
            "https://music.apple.com/us/album/test/123?i=456 "
            "https://open.spotify.com/track/1"
        )

        self.assertEqual(
            extract_supported_urls(text),
            [
                "https://open.spotify.com/track/1",
                "https://music.apple.com/us/album/test/123?i=456",
            ],
        )


if __name__ == "__main__":
    unittest.main()
