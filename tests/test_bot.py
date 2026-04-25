import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.bot import (
    MAX_BUTTON_TEXT_LENGTH,
    MAX_USER_NOTE_LENGTH,
    _build_collection_keyboard,
    _build_platform_order,
    _build_podcast_fallback,
    _lookup_tracks,
    _message_text,
    _shorten_user_note,
    track_lookup_message,
)
from music_links_bot.models import TrackMatch
from music_links_bot.songlink import SonglinkError


class FailingLookupClient:
    async def lookup_track(self, source_url: str) -> TrackMatch:
        del source_url
        raise SonglinkError("service down")


class BotStub:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []

    async def send_message(self, **kwargs: object) -> None:
        self.sent_messages.append(kwargs)


class ContextStub:
    def __init__(self) -> None:
        self.bot = BotStub()
        self.application = type(
            "ApplicationStub",
            (),
            {"bot_data": {"admin_chat_id": 123}},
        )()


class ChannelMessageStub:
    text = "https://www.instagram.com/sansaetown"
    caption = None
    chat_id = -1002903607636
    from_user = None
    chat = type("ChatStub", (), {"type": "channel"})()

    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs: object) -> None:
        del kwargs
        self.replies.append(text)


class UpdateStub:
    def __init__(self, message: ChannelMessageStub) -> None:
        self.effective_message = message


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

        track = _build_podcast_fallback(source_url)

        self.assertIsNotNone(track)
        assert track is not None
        self.assertEqual(track.kind, "podcast")
        self.assertEqual(track.artist, "Spotify")
        self.assertEqual(track.title, "Podcast episode")
        self.assertEqual(track.links, {"spotify": source_url})
        self.assertEqual(track.page_url, source_url)

    def test_spotify_show_fallback_marks_show_format(self) -> None:
        source_url = "https://open.spotify.com/show/abc?si=123"

        track = _build_podcast_fallback(source_url)

        self.assertIsNotNone(track)
        assert track is not None
        self.assertEqual(track.kind, "podcast")
        self.assertEqual(track.release_format, "show")
        self.assertEqual(track.title, "Podcast show")

    def test_spotify_fallback_ignores_regular_tracks(self) -> None:
        self.assertIsNone(
            _build_podcast_fallback("https://open.spotify.com/track/abc")
        )

    def test_apple_podcast_episode_fallback_builds_podcast_match(self) -> None:
        source_url = "https://podcasts.apple.com/us/podcast/apple-events/id1473854035?i=1000479125753"

        track = _build_podcast_fallback(source_url)

        self.assertIsNotNone(track)
        assert track is not None
        self.assertEqual(track.kind, "podcast")
        self.assertEqual(track.artist, "Apple Podcasts")
        self.assertEqual(track.title, "Podcast episode")
        self.assertEqual(track.links, {"applePodcasts": source_url})

    def test_apple_podcast_show_fallback_marks_show_format(self) -> None:
        source_url = "https://podcasts.apple.com/us/podcast/apple-events/id1473854035"

        track = _build_podcast_fallback(source_url)

        self.assertIsNotNone(track)
        assert track is not None
        self.assertEqual(track.kind, "podcast")
        self.assertEqual(track.release_format, "show")
        self.assertEqual(track.title, "Podcast show")

    def test_shorten_user_note_keeps_telegram_posts_safe(self) -> None:
        text = "x" * (MAX_USER_NOTE_LENGTH + 20)

        shortened = _shorten_user_note(text)

        self.assertEqual(len(shortened), MAX_USER_NOTE_LENGTH)
        self.assertTrue(shortened.endswith("…"))

    def test_message_text_falls_back_to_caption(self) -> None:
        message = type("MessageStub", (), {"text": None, "caption": "caption link"})()

        self.assertEqual(_message_text(message), "caption link")


class BotLookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_channel_posts_without_supported_urls_do_not_notify_admin(self) -> None:
        message = ChannelMessageStub()
        context = ContextStub()

        await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(message.replies, [])
        self.assertEqual(context.bot.sent_messages, [])

    async def test_lookup_tracks_uses_podcast_fallback_when_songlink_is_down(self) -> None:
        tracks, unavailable_urls = await _lookup_tracks(
            FailingLookupClient(),
            ["https://open.spotify.com/episode/abc?si=123"],
        )

        self.assertEqual(unavailable_urls, [])
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].kind, "podcast")
        self.assertEqual(
            tracks[0].links,
            {"spotify": "https://open.spotify.com/episode/abc?si=123"},
        )


if __name__ == "__main__":
    unittest.main()
