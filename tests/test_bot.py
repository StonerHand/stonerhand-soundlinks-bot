import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.bot import (
    MAX_BUTTON_TEXT_LENGTH,
    MAX_USER_NOTE_LENGTH,
    _build_collection_keyboard,
    _build_intro_keyboard,
    _build_link_keyboard,
    _build_mixed_collection_keyboard,
    _build_platform_order,
    _build_podcast_fallback,
    _build_youtube_keyboard,
    _lookup_tracks,
    _lookup_youtube_videos,
    _message_text,
    _should_include_channel_button,
    _shorten_user_note,
    track_lookup_message,
)
from music_links_bot.models import TrackMatch, VideoMatch
from music_links_bot.songlink import SonglinkError
from music_links_bot.youtube import YouTubeLookupError


class FailingLookupClient:
    async def lookup_track(self, source_url: str) -> TrackMatch:
        del source_url
        raise SonglinkError("service down")


class SuccessfulLookupClient:
    async def lookup_track(self, source_url: str) -> TrackMatch:
        return TrackMatch(
            title="Transitions",
            artist="Youth Code",
            links={"spotify": "https://open.spotify.com/track/1"},
            page_url="https://song.link/transitions",
        )


class YouTubeClientStub:
    async def lookup_video(self, source_url: str) -> VideoMatch:
        return VideoMatch(
            title="SANSAE Live Session Vol.3 - Melon",
            author="SANSAE",
            url=source_url,
        )


class FailingYouTubeClientStub:
    async def lookup_video(self, source_url: str) -> VideoMatch:
        del source_url
        raise YouTubeLookupError("metadata down")


class BotStub:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []

    async def send_message(self, **kwargs: object) -> None:
        self.sent_messages.append(kwargs)


class ContextStub:
    def __init__(
        self,
        *,
        songlink_client: object | None = None,
        youtube_client: object | None = None,
    ) -> None:
        self.bot = BotStub()
        self.application = type(
            "ApplicationStub",
            (),
            {
                "bot_data": {
                    "admin_chat_id": 123,
                    "songlink_client": songlink_client or SuccessfulLookupClient(),
                    "youtube_client": youtube_client or YouTubeClientStub(),
                }
            },
        )()


class ChannelMessageStub:
    text = "https://www.instagram.com/sansaetown"
    caption = None
    chat_id = -1002903607636
    from_user = None
    chat = type(
        "ChatStub",
        (),
        {
            "id": -1002903607636,
            "type": "channel",
            "title": "StonerHand",
            "username": "stonerhand",
        },
    )()

    def __init__(self) -> None:
        self.replies: list[str] = []
        self.reply_kwargs: list[dict[str, object]] = []

    async def reply_text(self, text: str, **kwargs: object) -> None:
        self.replies.append(text)
        self.reply_kwargs.append(kwargs)


class GroupMessageStub(ChannelMessageStub):
    chat_id = -100123
    chat = type(
        "ChatStub",
        (),
        {
            "id": -100123,
            "type": "supergroup",
            "title": "Music chat",
            "username": None,
        },
    )()


class PrivateMessageStub(ChannelMessageStub):
    text = "привет"
    chat_id = 456
    chat = type(
        "ChatStub",
        (),
        {
            "id": 456,
            "type": "private",
            "title": None,
            "username": None,
        },
    )()


class PrivateYouTubeMessageStub(PrivateMessageStub):
    text = "https://www.youtube.com/watch?v=abc123"


class PrivateMixedMessageStub(PrivateMessageStub):
    text = (
        "вечерний набор "
        "https://open.spotify.com/track/abc "
        "https://www.youtube.com/watch?v=abc123"
    )


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

    def test_release_keyboard_can_hide_channel_button(self) -> None:
        keyboard = _build_link_keyboard(
            {"spotify": "https://open.spotify.com/track/1"},
            include_channel_button=False,
        )

        button_texts = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(button_texts, ["Spotify"])

    def test_collection_keyboard_can_hide_channel_button(self) -> None:
        keyboard = _build_collection_keyboard(
            [
                TrackMatch(
                    title="Transitions",
                    artist="Youth Code",
                    links={"spotify": "https://open.spotify.com/track/1"},
                    page_url="https://song.link/track-1",
                )
            ],
            include_channel_button=False,
        )

        button_texts = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(button_texts, ["1. Youth Code - Transitions"])

    def test_youtube_keyboard_can_hide_channel_button(self) -> None:
        keyboard = _build_youtube_keyboard(
            "https://www.youtube.com/watch?v=abc",
            include_channel_button=False,
        )

        button_texts = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(button_texts, ["▶️ Смотреть на YouTube"])

    def test_mixed_collection_keyboard_lists_music_and_video_buttons(self) -> None:
        keyboard = _build_mixed_collection_keyboard(
            [
                TrackMatch(
                    title="Transitions",
                    artist="Youth Code",
                    links={"spotify": "https://open.spotify.com/track/1"},
                    page_url="https://song.link/transitions",
                )
            ],
            [VideoMatch(title="Live Session", author="Channel", url="https://youtu.be/1")],
        )

        rows = keyboard.inline_keyboard
        self.assertEqual(rows[0][0].text, "1. Youth Code - Transitions")
        self.assertEqual(rows[0][0].url, "https://song.link/transitions")
        self.assertEqual(rows[1][0].text, "2. Live Session")
        self.assertEqual(rows[1][0].url, "https://youtu.be/1")

    def test_channel_button_is_hidden_only_in_stonerhand_channel(self) -> None:
        self.assertFalse(_should_include_channel_button(ChannelMessageStub()))
        self.assertTrue(_should_include_channel_button(GroupMessageStub()))

    def test_intro_keyboard_puts_main_buttons_on_one_row(self) -> None:
        keyboard = _build_intro_keyboard("StonerHandBot")

        rows = keyboard.inline_keyboard
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0].text, "🪨 Открыть канал")
        self.assertEqual(rows[0][1].text, "Поделиться ботом")

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

    async def test_group_messages_without_supported_urls_stay_silent(self) -> None:
        message = GroupMessageStub()
        context = ContextStub()

        await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(message.replies, [])
        self.assertEqual(context.bot.sent_messages, [])

    async def test_private_messages_without_supported_urls_get_hint(self) -> None:
        message = PrivateMessageStub()
        context = ContextStub()

        await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(len(message.replies), 1)
        self.assertIn("Пришлите ссылку из сервисов:", message.replies[0])
        self.assertEqual(context.bot.sent_messages, [])

    async def test_youtube_video_links_use_video_post(self) -> None:
        message = PrivateYouTubeMessageStub()
        context = ContextStub()

        with patch("music_links_bot.bot.record_videos") as record_videos:
            await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(len(message.replies), 1)
        self.assertIn("📺 · <b>SANSAE Live Session Vol.3 - Melon</b>", message.replies[0])
        self.assertIn("канал: SANSAE", message.replies[0])
        keyboard = message.reply_kwargs[0]["reply_markup"].inline_keyboard
        preview_options = message.reply_kwargs[0]["link_preview_options"]
        self.assertEqual(keyboard[0][0].text, "▶️ Смотреть на YouTube")
        self.assertEqual(keyboard[0][0].url, "https://www.youtube.com/watch?v=abc123")
        self.assertTrue(preview_options.prefer_large_media)
        self.assertFalse(preview_options.prefer_small_media)
        record_videos.assert_called_once()

    async def test_mixed_music_and_youtube_links_use_collection_post(self) -> None:
        message = PrivateMixedMessageStub()
        context = ContextStub()

        with patch("music_links_bot.bot.record_mixed") as record_mixed:
            await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(len(message.replies), 1)
        self.assertTrue(message.replies[0].startswith("вечерний набор\n\n"))
        self.assertIn("<b>Youth Code</b> - Transitions", message.replies[0])
        self.assertIn("📺 · <b>SANSAE Live Session Vol.3 - Melon</b>", message.replies[0])
        keyboard = message.reply_kwargs[0]["reply_markup"].inline_keyboard
        self.assertEqual(keyboard[0][0].text, "1. Youth Code - Transitions")
        self.assertEqual(keyboard[1][0].text, "2. SANSAE Live Session Vol.3 - Melon")
        record_mixed.assert_called_once()

    async def test_youtube_lookup_uses_fallback_when_metadata_fails(self) -> None:
        videos = await _lookup_youtube_videos(
            FailingYouTubeClientStub(),
            ["https://youtu.be/abc123"],
        )

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0].title, "YouTube video")
        self.assertEqual(videos[0].author, "YouTube")

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
