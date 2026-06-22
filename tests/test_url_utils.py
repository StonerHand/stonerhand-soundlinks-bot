import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.url_utils import (
    apple_podcasts_url_type,
    cache_key_for_url,
    extract_supported_urls,
    is_nts_url,
    is_spotify_artist_url,
    is_spotify_playlist_url,
    is_soundcloud_url,
    is_supported_music_url,
    is_youtube_video_url,
    spotify_url_type,
    strip_supported_urls,
    strip_supported_urls_with_mapping,
)


class UrlUtilsTests(unittest.TestCase):
    def test_is_supported_music_url_accepts_supported_hosts(self) -> None:
        self.assertTrue(is_supported_music_url("https://open.spotify.com/track/123"))
        self.assertTrue(is_supported_music_url("https://open.spotify.com/playlist/abc"))
        self.assertTrue(is_supported_music_url("https://open.spotify.com/artist/abc"))
        self.assertTrue(is_supported_music_url("https://open.spotify.com:443/track/123"))
        self.assertTrue(is_supported_music_url("https://podcasts.apple.com/us/podcast/apple-events/id1473854035"))
        self.assertTrue(is_supported_music_url("https://music.youtube.com/watch?v=abc"))
        self.assertTrue(is_supported_music_url("https://www.youtube.com/watch?v=abc"))
        self.assertTrue(is_supported_music_url("https://youtu.be/abc"))
        self.assertTrue(is_supported_music_url("https://music.yandex.ru/album/1/track/2"))
        self.assertTrue(is_supported_music_url("https://soundcloud.com/artist/track"))
        self.assertTrue(is_supported_music_url("https://m.soundcloud.com/artist/track"))
        self.assertTrue(is_supported_music_url("https://on.soundcloud.com/abc123"))
        self.assertTrue(is_supported_music_url("https://www.nts.live/shows/example"))
        self.assertTrue(is_supported_music_url("https://nts.live/episodes/example"))

    def test_is_supported_music_url_rejects_other_hosts(self) -> None:
        self.assertFalse(is_supported_music_url("https://example.com/track/123"))
        self.assertFalse(is_supported_music_url("https://www.youtube.com/@channel"))
        self.assertFalse(is_supported_music_url("https://www.youtube.com/channel/abc"))
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

    def test_extract_supported_urls_deduplicates_tracking_variants(self) -> None:
        text = (
            "https://open.spotify.com/track/1?si=aaa "
            "https://open.spotify.com/track/1?si=bbb&utm_source=share"
        )

        self.assertEqual(
            extract_supported_urls(text),
            ["https://open.spotify.com/track/1?si=aaa"],
        )

    def test_cache_key_for_url_strips_tracking_query_values(self) -> None:
        self.assertEqual(
            cache_key_for_url(
                "https://open.spotify.com/track/1?si=aaa&utm_source=share&foo=bar#frag"
            ),
            "https://open.spotify.com/track/1?foo=bar",
        )

    def test_strip_supported_urls_keeps_remaining_user_text(self) -> None:
        text = (
            "мой текст https://open.spotify.com/track/1 "
            "и еще https://music.apple.com/us/album/test/123?i=456"
        )

        self.assertEqual(
            strip_supported_urls(text),
            "мой текст и еще",
        )

    def test_strip_supported_urls_preserves_editorial_layout(self) -> None:
        text = (
            "Первый абзац с  двумя пробелами\n\n"
            "  - пункт с отступом\n"
            "  - второй пункт\n\n"
            "https://open.spotify.com/track/1?si=aaa\n\n"
            "Финальная строка"
        )

        self.assertEqual(
            strip_supported_urls(text),
            (
                "Первый абзац с  двумя пробелами\n\n"
                "  - пункт с отступом\n"
                "  - второй пункт\n\n\n\n"
                "Финальная строка"
            ),
        )

    def test_strip_supported_urls_keeps_unrelated_links_and_punctuation(self) -> None:
        text = (
            "Подробнее: https://example.com/article\n\n"
            "Слушать: https://open.spotify.com/track/1?si=aaa."
        )

        self.assertEqual(
            strip_supported_urls(text),
            "Подробнее: https://example.com/article\n\nСлушать:",
        )

    def test_strip_supported_urls_mapping_points_to_original_characters(self) -> None:
        text = "🎧 текст\nhttps://open.spotify.com/track/1"

        stripped, mapping = strip_supported_urls_with_mapping(text)

        self.assertEqual(stripped, "🎧 текст")
        self.assertEqual("".join(text[index] for index in mapping), stripped)

    def test_spotify_url_type_detects_episode_and_show(self) -> None:
        self.assertEqual(
            spotify_url_type("https://open.spotify.com/episode/abc?si=123"),
            "episode",
        )
        self.assertEqual(
            spotify_url_type("https://open.spotify.com/show/abc?si=123"),
            "show",
        )

    def test_is_spotify_playlist_url_detects_playlists(self) -> None:
        self.assertTrue(
            is_spotify_playlist_url("https://open.spotify.com/playlist/abc?si=123")
        )
        self.assertFalse(is_spotify_playlist_url("https://open.spotify.com/track/abc"))

    def test_is_spotify_artist_url_detects_artists(self) -> None:
        self.assertTrue(
            is_spotify_artist_url("https://open.spotify.com/artist/abc?si=123")
        )
        self.assertFalse(is_spotify_artist_url("https://open.spotify.com/playlist/abc"))

    def test_spotify_url_type_ignores_other_hosts(self) -> None:
        self.assertIsNone(spotify_url_type("https://example.com/show/abc"))

    def test_apple_podcasts_url_type_detects_episode_and_show(self) -> None:
        self.assertEqual(
            apple_podcasts_url_type(
                "https://podcasts.apple.com/us/podcast/apple-events/id1473854035?i=1000479125753"
            ),
            "episode",
        )
        self.assertEqual(
            apple_podcasts_url_type("https://podcasts.apple.com/us/podcast/apple-events/id1473854035"),
            "show",
        )

    def test_apple_podcasts_url_type_ignores_other_hosts(self) -> None:
        self.assertIsNone(apple_podcasts_url_type("https://music.apple.com/us/album/abc"))

    def test_is_youtube_video_url_detects_regular_video_links(self) -> None:
        self.assertTrue(is_youtube_video_url("https://www.youtube.com/watch?v=abc"))
        self.assertTrue(is_youtube_video_url("https://youtu.be/abc"))
        self.assertTrue(is_youtube_video_url("https://youtube.com/shorts/abc"))
        self.assertTrue(is_youtube_video_url("https://m.youtube.com/live/abc"))

    def test_is_youtube_video_url_ignores_music_and_non_video_links(self) -> None:
        self.assertFalse(is_youtube_video_url("https://music.youtube.com/watch?v=abc"))
        self.assertFalse(is_youtube_video_url("https://www.youtube.com/@channel"))
        self.assertFalse(is_youtube_video_url("https://example.com/watch?v=abc"))

    def test_is_soundcloud_url_detects_soundcloud_variants(self) -> None:
        self.assertTrue(is_soundcloud_url("https://soundcloud.com/artist/track"))
        self.assertTrue(is_soundcloud_url("https://m.soundcloud.com/artist/track"))
        self.assertTrue(is_soundcloud_url("https://on.soundcloud.com/abc123"))
        self.assertFalse(is_soundcloud_url("https://example.com/artist/track"))

    def test_is_nts_url_detects_nts_variants(self) -> None:
        self.assertTrue(is_nts_url("https://www.nts.live/shows/example"))
        self.assertTrue(is_nts_url("https://nts.live/episodes/example"))
        self.assertTrue(is_nts_url("https://archive.nts.live/example"))
        self.assertFalse(is_nts_url("https://example.com/shows/example"))


if __name__ == "__main__":
    unittest.main()
