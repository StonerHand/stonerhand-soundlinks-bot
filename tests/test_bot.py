import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.bot import (
    MAX_BUTTON_TEXT_LENGTH,
    MAX_USER_NOTE_LENGTH,
    PUBLIC_BOT_COMMANDS,
    _build_collection_keyboard,
    _build_artist_keyboard,
    _build_intro_keyboard,
    _build_link_keyboard,
    _build_mixed_collection_keyboard,
    _build_playlist_keyboard,
    _build_platform_order,
    _build_podcast_fallback,
    _build_youtube_keyboard,
    _format_not_found_message,
    _lookup_playlists,
    _lookup_artists,
    _lookup_tracks,
    _lookup_youtube_videos,
    _message_text,
    _should_include_channel_button,
    _should_include_hashtags,
    _split_source_urls,
    _shorten_user_note,
    track_lookup_message,
)
from music_links_bot.artist import ArtistLookupError
from music_links_bot.models import ArtistMatch, PlaylistMatch, TrackMatch, VideoMatch
from music_links_bot.playlist import PlaylistLookupError
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


class PlaylistClientStub:
    async def lookup_playlist(self, source_url: str) -> PlaylistMatch:
        return PlaylistMatch(
            title="Women of Punk",
            platform="Spotify",
            url=source_url,
        )


class FailingPlaylistClientStub:
    async def lookup_playlist(self, source_url: str) -> PlaylistMatch:
        del source_url
        raise PlaylistLookupError("metadata down")


class ArtistClientStub:
    async def lookup_artist(self, source_url: str) -> ArtistMatch:
        return ArtistMatch(
            title="1.Kla$",
            platform="Spotify",
            url=source_url,
        )


class FailingArtistClientStub:
    async def lookup_artist(self, source_url: str) -> ArtistMatch:
        del source_url
        raise ArtistLookupError("metadata down")


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
        playlist_client: object | None = None,
        artist_client: object | None = None,
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
                    "playlist_client": playlist_client or PlaylistClientStub(),
                    "artist_client": artist_client or ArtistClientStub(),
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


class PrivateSpotifyPlaylistMessageStub(PrivateMessageStub):
    text = "https://open.spotify.com/playlist/37i9dQZF1DX51TD2wakW3K?si=123"


class PrivateSpotifyArtistMessageStub(PrivateMessageStub):
    text = "https://open.spotify.com/artist/2KbKmQQgFN6MabWViBVlO6?si=123"


class PrivateMixedMessageStub(PrivateMessageStub):
    text = (
        "вечерний набор "
        "https://open.spotify.com/track/abc "
        "https://www.youtube.com/watch?v=abc123"
    )


class PrivateMixedPlaylistMessageStub(PrivateMessageStub):
    text = (
        "пачка ссылок "
        "https://open.spotify.com/playlist/37i9dQZF1DX51TD2wakW3K "
        "https://www.youtube.com/watch?v=abc123"
    )


class UpdateStub:
    def __init__(self, message: ChannelMessageStub) -> None:
        self.effective_message = message


class BotKeyboardTests(unittest.TestCase):
    def test_public_command_menu_stays_curated(self) -> None:
        self.assertEqual(
            [(command.command, command.description) for command in PUBLIC_BOT_COMMANDS],
            [
                ("start", "начать"),
                ("help", "как кидать ссылки"),
                ("platforms", "что умею открыть"),
                ("channel", "канал StonerHand"),
                ("stats", "статистика бота"),
            ],
        )

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
        self.assertEqual(rows[0][0].text, "🎧 1. Youth Code - Transitions")
        self.assertEqual(rows[0][0].url, "https://song.link/track-1")
        self.assertEqual(rows[0][1].text, "🎧 2. Show Me The Body - Camp Orchestra")
        self.assertEqual(rows[0][1].url, "https://song.link/track-2")
        self.assertEqual(rows[1][0].text, "🪨 Открыть канал")

    def test_release_keyboard_can_hide_channel_button(self) -> None:
        keyboard = _build_link_keyboard(
            {"spotify": "https://open.spotify.com/track/1"},
            include_channel_button=False,
        )

        button_texts = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(button_texts, ["🟢 Spotify"])

    def test_release_keyboard_uses_two_columns(self) -> None:
        keyboard = _build_link_keyboard(
            {
                "spotify": "https://open.spotify.com/track/1",
                "appleMusic": "https://music.apple.com/song/1",
                "deezer": "https://deezer.example/track/1",
                "tidal": "https://tidal.example/track/1",
            },
            include_channel_button=False,
        )

        rows = keyboard.inline_keyboard
        self.assertEqual(rows[0][0].text, "🟢 Spotify")
        self.assertEqual(rows[0][1].text, "🍎 Apple")
        self.assertEqual(rows[1][0].text, "🟦 Deezer")
        self.assertEqual(rows[1][1].text, "🌊 Tidal")

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
        self.assertEqual(button_texts, ["🎧 1. Youth Code - Transitions"])

    def test_youtube_keyboard_can_hide_channel_button(self) -> None:
        keyboard = _build_youtube_keyboard(
            "https://www.youtube.com/watch?v=abc",
            include_channel_button=False,
        )

        button_texts = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(button_texts, ["📺 Смотреть на YouTube"])

    def test_playlist_keyboard_can_hide_channel_button(self) -> None:
        keyboard = _build_playlist_keyboard(
            "https://open.spotify.com/playlist/abc",
            include_channel_button=False,
        )

        button_texts = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(button_texts, ["🎛 Открыть плейлист"])

    def test_artist_keyboard_can_hide_channel_button(self) -> None:
        keyboard = _build_artist_keyboard(
            "https://open.spotify.com/artist/abc",
            include_channel_button=False,
        )

        button_texts = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(button_texts, ["🧬 Открыть артиста"])

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
        self.assertEqual(rows[0][0].text, "🎧 1. Youth Code - Transitions")
        self.assertEqual(rows[0][0].url, "https://song.link/transitions")
        self.assertEqual(rows[0][1].text, "📺 2. Live Session")
        self.assertEqual(rows[0][1].url, "https://youtu.be/1")

    def test_channel_button_is_hidden_only_in_stonerhand_channel(self) -> None:
        self.assertFalse(_should_include_channel_button(ChannelMessageStub()))
        self.assertTrue(_should_include_channel_button(GroupMessageStub()))

    def test_hashtags_are_hidden_only_in_private_chats(self) -> None:
        self.assertFalse(_should_include_hashtags(PrivateMessageStub()))
        self.assertTrue(_should_include_hashtags(GroupMessageStub()))

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

    def test_split_source_urls_separates_playlists_from_music_and_youtube(self) -> None:
        artist_urls, playlist_urls, youtube_urls, music_urls = _split_source_urls(
            [
                "https://open.spotify.com/artist/abc",
                "https://open.spotify.com/playlist/abc",
                "https://youtu.be/video",
                "https://open.spotify.com/track/123",
            ]
        )

        self.assertEqual(artist_urls, ["https://open.spotify.com/artist/abc"])
        self.assertEqual(playlist_urls, ["https://open.spotify.com/playlist/abc"])
        self.assertEqual(youtube_urls, ["https://youtu.be/video"])
        self.assertEqual(music_urls, ["https://open.spotify.com/track/123"])

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

    def test_not_found_message_uses_editorial_copy(self) -> None:
        message = _format_not_found_message(["https://example.com/release"])

        self.assertIn(
            "проверь, что это ссылка на трек, альбом, подкаст, плейлист или артиста",
            message,
        )
        self.assertNotIn("Проверьте", message)


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
        self.assertIn("кинь ссылку из:", message.replies[0])
        self.assertEqual(context.bot.sent_messages, [])

    async def test_youtube_video_links_use_video_post(self) -> None:
        message = PrivateYouTubeMessageStub()
        context = ContextStub()

        with patch("music_links_bot.bot.record_videos") as record_videos:
            await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(len(message.replies), 1)
        self.assertIn("📺 · <b>SANSAE Live Session Vol.3 - Melon</b>", message.replies[0])
        self.assertIn("канал: SANSAE", message.replies[0])
        self.assertNotIn("#stonerhand", message.replies[0])
        keyboard = message.reply_kwargs[0]["reply_markup"].inline_keyboard
        preview_options = message.reply_kwargs[0]["link_preview_options"]
        self.assertEqual(keyboard[0][0].text, "📺 Смотреть на YouTube")
        self.assertEqual(keyboard[0][0].url, "https://www.youtube.com/watch?v=abc123")
        self.assertTrue(preview_options.prefer_large_media)
        self.assertFalse(preview_options.prefer_small_media)
        record_videos.assert_called_once()

    async def test_spotify_playlist_links_use_playlist_post(self) -> None:
        message = PrivateSpotifyPlaylistMessageStub()
        context = ContextStub()

        with patch("music_links_bot.bot.record_playlists") as record_playlists:
            await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(len(message.replies), 1)
        self.assertIn("🎛 · <b>Women of Punk</b>", message.replies[0])
        self.assertNotIn("#stonerhand #playlist", message.replies[0])
        keyboard = message.reply_kwargs[0]["reply_markup"].inline_keyboard
        self.assertEqual(keyboard[0][0].text, "🎛 Открыть плейлист")
        self.assertEqual(
            keyboard[0][0].url,
            "https://open.spotify.com/playlist/37i9dQZF1DX51TD2wakW3K?si=123",
        )
        record_playlists.assert_called_once()

    async def test_spotify_artist_links_use_artist_post(self) -> None:
        message = PrivateSpotifyArtistMessageStub()
        context = ContextStub()

        with patch("music_links_bot.bot.record_artists") as record_artists:
            await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(len(message.replies), 1)
        self.assertIn("🧬 · <b>1.Kla$</b>", message.replies[0])
        self.assertIn("артист: Spotify", message.replies[0])
        self.assertNotIn("#stonerhand #artist", message.replies[0])
        keyboard = message.reply_kwargs[0]["reply_markup"].inline_keyboard
        self.assertEqual(keyboard[0][0].text, "🧬 Открыть артиста")
        self.assertEqual(
            keyboard[0][0].url,
            "https://open.spotify.com/artist/2KbKmQQgFN6MabWViBVlO6?si=123",
        )
        record_artists.assert_called_once()

    async def test_mixed_music_and_youtube_links_use_collection_post(self) -> None:
        message = PrivateMixedMessageStub()
        context = ContextStub()

        with patch("music_links_bot.bot.record_mixed") as record_mixed:
            await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(len(message.replies), 1)
        self.assertTrue(message.replies[0].startswith("<blockquote>вечерний набор</blockquote>\n\n"))
        self.assertIn("<b>Youth Code</b> - Transitions", message.replies[0])
        self.assertIn("📺 · <b>SANSAE Live Session Vol.3 - Melon</b>", message.replies[0])
        self.assertNotIn("#stonerhand", message.replies[0])
        keyboard = message.reply_kwargs[0]["reply_markup"].inline_keyboard
        self.assertEqual(keyboard[0][0].text, "🎧 1. Youth Code - Transitions")
        self.assertEqual(keyboard[0][1].text, "📺 2. SANSAE Live Session Vol.3 - Melon")
        record_mixed.assert_called_once()

    async def test_mixed_playlist_and_youtube_links_keep_both_items(self) -> None:
        message = PrivateMixedPlaylistMessageStub()
        context = ContextStub()

        with patch("music_links_bot.bot.record_mixed") as record_mixed:
            await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(len(message.replies), 1)
        self.assertTrue(message.replies[0].startswith("<blockquote>пачка ссылок</blockquote>\n\n"))
        self.assertIn("🎛 · <b>Women of Punk</b>", message.replies[0])
        self.assertIn("📺 · <b>SANSAE Live Session Vol.3 - Melon</b>", message.replies[0])
        self.assertNotIn("#playlist #video", message.replies[0])
        keyboard = message.reply_kwargs[0]["reply_markup"].inline_keyboard
        self.assertEqual(keyboard[0][0].text, "🎛 1. Women of Punk")
        self.assertEqual(keyboard[0][1].text, "📺 2. SANSAE Live Session Vol.3 - Melon")
        record_mixed.assert_called_once()

    async def test_youtube_lookup_uses_fallback_when_metadata_fails(self) -> None:
        videos = await _lookup_youtube_videos(
            FailingYouTubeClientStub(),
            ["https://youtu.be/abc123"],
        )

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0].title, "YouTube video")
        self.assertEqual(videos[0].author, "YouTube")

    async def test_playlist_lookup_uses_fallback_when_metadata_fails(self) -> None:
        playlists = await _lookup_playlists(
            FailingPlaylistClientStub(),
            ["https://open.spotify.com/playlist/abc"],
        )

        self.assertEqual(len(playlists), 1)
        self.assertEqual(playlists[0].title, "Spotify playlist")
        self.assertEqual(playlists[0].platform, "Spotify")

    async def test_artist_lookup_uses_fallback_when_metadata_fails(self) -> None:
        artists = await _lookup_artists(
            FailingArtistClientStub(),
            ["https://open.spotify.com/artist/abc"],
        )

        self.assertEqual(len(artists), 1)
        self.assertEqual(artists[0].title, "Spotify artist")
        self.assertEqual(artists[0].platform, "Spotify")

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
