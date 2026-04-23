import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.bot import (
    MAX_BUTTON_TEXT_LENGTH,
    MAX_USER_NOTE_LENGTH,
    _build_collection_keyboard,
    _build_platform_order,
    _build_spotify_podcast_fallback,
    _shorten_user_note,
)
from music_links_bot.models import TrackMatch


class BotKeyboardTests(unittest.TestCase):
    def test_collection_keyboard_uses_one_songlink_button_per_release(self) -> None:
        keyboard = _build_collection_keyboard(
            [
                TrackMatch(
                    title="Transitions",
                    artist="Youth Code",
                    links={"spotify": "https://open.spotify.com/track/1"},
                    page_url="https://song.link/track-1",
                ),
                TrackMatch(
                    title="Camp Orchestra",
                    artist="Show Me The Body",
                    links={"spotify": "https://open.spotify.com/track/2"},
                    page_url="https://song.link/track-2",
                ),
            ]
        )

        rows = keyboard.inline_keyboard
        self.assertEqual(rows[0][0].text, "1. Youth Code - Transitions")
        self.assertEqual(rows[0][0].url, "https://song.link/track-1")
        self.assertEqual(rows[1][0].text, "2. Show Me The Body - Camp Orchestra")
        self.assertEqual(rows[1][0].url, "https://song.link/track-2")
        self.assertEqual(rows[2][0].text, "🪨 Открыть канал")

    def test_build_platform_order_moves_primary_platform_first(self) -> None:
        order = _build_platform_order("yandexMusic")

        self.assertEqual(order[0], "yandexMusic")
        self.assertIn("spotify", order)

    def test_collection_keyboard_shortens_long_button_text(self) -> None:
        keyboard = _build_collection_keyboard(
            [
                TrackMatch(
                    title="A Very Long Track Title That Would Make A Telegram Button Too Wide",
                    artist="A Very Long Artist Name For The Same Reason",
                    links={"spotify": "https://open.spotify.com/track/1"},
                    page_url="https://song.link/track-1",
                )
            ]
        )

        button_text = keyboard.inline_keyboard[0][0].text
        self.assertLessEqual(len(button_text), MAX_BUTTON_TEXT_LENGTH)
        self.assertTrue(button_text.endswith("…"))

    def test_spotify_episode_fallback_builds_podcast_match(self) -> None:
        source_url = "https://open.spotify.com/episode/abc?si=123"

        track = _build_spotify_podcast_fallback(source_url)

        self.assertIsNotNone(track)
        assert track is not None
        self.assertEqual(track.kind, "podcast")
        self.assertEqual(track.artist, "Spotify")
        self.assertEqual(track.title, "Podcast episode")
        self.assertEqual(track.links, {"spotify": source_url})
        self.assertEqual(track.page_url, source_url)

    def test_spotify_show_fallback_marks_show_format(self) -> None:
        source_url = "https://open.spotify.com/show/abc?si=123"

        track = _build_spotify_podcast_fallback(source_url)

        self.assertIsNotNone(track)
        assert track is not None
        self.assertEqual(track.kind, "podcast")
        self.assertEqual(track.release_format, "show")
        self.assertEqual(track.title, "Podcast show")

    def test_spotify_fallback_ignores_regular_tracks(self) -> None:
        self.assertIsNone(
            _build_spotify_podcast_fallback("https://open.spotify.com/track/abc")
        )

    def test_shorten_user_note_keeps_telegram_posts_safe(self) -> None:
        text = "x" * (MAX_USER_NOTE_LENGTH + 20)

        shortened = _shorten_user_note(text)

        self.assertEqual(len(shortened), MAX_USER_NOTE_LENGTH)
        self.assertTrue(shortened.endswith("…"))


if __name__ == "__main__":
    unittest.main()
