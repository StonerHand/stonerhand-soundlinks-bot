import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.bot import (
    MAX_BUTTON_TEXT_LENGTH,
    PUBLIC_BOT_COMMANDS,
    _build_collection_keyboard,
    _build_inline_result,
    _build_artist_keyboard,
    _build_error_keyboard,
    _build_intro_keyboard,
    _build_link_keyboard,
    _build_mixed_collection_keyboard,
    _build_nts_keyboard,
    _build_playlist_keyboard,
    _build_platform_order,
    _build_podcast_fallback,
    _build_youtube_keyboard,
    _format_not_found_message,
    _format_service_unavailable_message,
    _lookup_nts_radios,
    _lookup_playlists,
    _lookup_artists,
    _lookup_tracks,
    _lookup_youtube_videos,
    _message_text,
    _menu_text,
    _should_include_channel_button,
    _should_include_hashtags,
    _split_source_urls,
    _send_track_result,
    track_lookup_message,
)
from music_links_bot.artist import ArtistLookupError
from music_links_bot.models import (
    ArtistMatch,
    PlaylistMatch,
    RadioMatch,
    TrackMatch,
    VideoMatch,
)
from music_links_bot.nts import NTSLookupError
from music_links_bot.playlist import PlaylistLookupError
from music_links_bot.songlink import SonglinkError
from music_links_bot.soundcloud import SoundCloudLookupError
from music_links_bot.youtube import YouTubeLookupError


class FailingLookupClient:
    async def lookup_track(self, source_url: str) -> TrackMatch:
        del source_url
        raise SonglinkError("service down")


class SoundCloudClientStub:
    async def lookup_track(self, source_url: str) -> TrackMatch:
        return TrackMatch(
            title="Star Signs",
            artist="Bondage Fairies",
            links={"soundcloud": source_url},
            page_url=source_url,
        )


class FailingSoundCloudClientStub:
    async def lookup_track(self, source_url: str) -> TrackMatch:
        del source_url
        raise SoundCloudLookupError("metadata down")


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


class NTSClientStub:
    async def lookup_radio(self, source_url: str) -> RadioMatch:
        return RadioMatch(
            title="Dark Energy w/ Guest",
            station="NTS Radio",
            url=source_url,
        )


class FailingNTSClientStub:
    async def lookup_radio(self, source_url: str) -> RadioMatch:
        del source_url
        raise NTSLookupError("metadata down")


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
        self.chat_actions: list[dict[str, object]] = []
        self.username = "StonerHandBot"

    async def send_message(self, **kwargs: object) -> None:
        self.sent_messages.append(kwargs)

    async def send_chat_action(self, **kwargs: object) -> None:
        self.chat_actions.append(kwargs)


class ContextStub:
    def __init__(
        self,
        *,
        songlink_client: object | None = None,
        youtube_client: object | None = None,
        nts_client: object | None = None,
        soundcloud_client: object | None = None,
        playlist_client: object | None = None,
        artist_client: object | None = None,
        ui_mode: str = "stonerhand",
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
                    "nts_client": nts_client or NTSClientStub(),
                    "soundcloud_client": soundcloud_client or SoundCloudClientStub(),
                    "playlist_client": playlist_client or PlaylistClientStub(),
                    "artist_client": artist_client or ArtistClientStub(),
                    "ui_mode": ui_mode,
                }
            },
        )()


class EditableReplyStub:
    """Mimics the Message a real reply returns: editable in place, like the
    loading placeholder that gets edited into the final post."""

    def __init__(self, owner: "ChannelMessageStub", index: int) -> None:
        self.chat_id = owner.chat_id
        self._owner = owner
        self._index = index

    async def edit_text(self, text: str, **kwargs: object) -> "EditableReplyStub":
        self._owner.replies[self._index] = text
        self._owner.reply_kwargs[self._index] = kwargs
        return self


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

    async def reply_text(self, text: str, **kwargs: object) -> EditableReplyStub:
        self.replies.append(text)
        self.reply_kwargs.append(kwargs)
        return EditableReplyStub(self, len(self.replies) - 1)


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


class ReplaceableMessageStub(GroupMessageStub):
    def __init__(self) -> None:
        super().__init__()
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


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


class PrivateNTSMessageStub(PrivateMessageStub):
    text = "https://www.nts.live/shows/example"


class PrivateSpotifyTrackMessageStub(PrivateMessageStub):
    text = "https://open.spotify.com/track/abc"


class PrivateSoundCloudMessageStub(PrivateMessageStub):
    text = "https://soundcloud.com/bondage-fairies/star-signs"


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


class PrivateMixedNTSMessageStub(PrivateMessageStub):
    text = (
        "радио и видео "
        "https://www.nts.live/shows/example "
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
                ("start", "меню и быстрый старт"),
                ("help", "как пользоваться"),
                ("guide", "для групп и каналов"),
                ("platforms", "сервисы и типы ссылок"),
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
        self.assertEqual(keyboard.inline_keyboard[0][0].api_kwargs, {"style": "success"})

    def test_release_keyboard_uses_two_columns(self) -> None:
        keyboard = _build_link_keyboard(
            {
                "spotify": "https://open.spotify.com/track/1",
                "appleMusic": "https://music.apple.com/song/1",
                "soundcloud": "https://soundcloud.com/artist/track",
                "deezer": "https://deezer.example/track/1",
                "tidal": "https://tidal.example/track/1",
            },
            include_channel_button=False,
        )

        rows = keyboard.inline_keyboard
        self.assertEqual(rows[0][0].text, "🟢 Spotify")
        self.assertEqual(rows[0][1].text, "⚪ Apple")
        self.assertEqual(rows[1][0].text, "🟠 SoundCloud")
        self.assertEqual(rows[1][1].text, "🟦 Deezer")
        self.assertEqual(rows[2][0].text, "⚫ Tidal")
        self.assertEqual(rows[0][0].api_kwargs, {"style": "success"})
        self.assertEqual(rows[0][1].api_kwargs, {"style": "primary"})
        self.assertEqual(rows[1][0].api_kwargs, {"style": "primary"})
        self.assertEqual(rows[1][1].api_kwargs, {"style": "primary"})
        self.assertEqual(rows[2][0].api_kwargs, {"style": "primary"})

    def test_release_keyboard_adds_songlink_hub_button(self) -> None:
        keyboard = _build_link_keyboard(
            {
                "spotify": "https://open.spotify.com/track/1",
                "appleMusic": "https://music.apple.com/song/1",
            },
            include_channel_button=False,
            release_page_url="https://song.link/transitions",
        )

        rows = keyboard.inline_keyboard
        self.assertEqual(rows[0][0].text, "🟢 Spotify")
        self.assertEqual(rows[0][1].text, "⚪ Apple")
        self.assertEqual(rows[1][0].text, "🪩 Все платформы")
        self.assertEqual(rows[1][0].url, "https://song.link/transitions")
        self.assertEqual(rows[1][0].api_kwargs, {"style": "danger"})

    def test_minimal_ui_mode_strips_platform_button_emoji(self) -> None:
        keyboard = _build_link_keyboard(
            {
                "spotify": "https://open.spotify.com/track/1",
                "appleMusic": "https://music.apple.com/song/1",
            },
            context=ContextStub(ui_mode="minimal"),
            include_channel_button=False,
            release_page_url="https://song.link/transitions",
        )

        rows = keyboard.inline_keyboard
        self.assertEqual(rows[0][0].text, "Spotify")
        self.assertEqual(rows[0][1].text, "Apple")
        self.assertEqual(rows[1][0].text, "Все платформы")
        self.assertEqual(rows[1][0].api_kwargs, {"style": "danger"})

    def test_editorial_ui_mode_uses_livelier_hub_copy(self) -> None:
        keyboard = _build_link_keyboard(
            {"spotify": "https://open.spotify.com/album/1"},
            context=ContextStub(ui_mode="editorial"),
            include_channel_button=False,
            release_page_url="https://album.link/release",
            release_kind="album",
        )

        self.assertEqual(keyboard.inline_keyboard[1][0].text, "💿 слушать целиком")

    def test_album_release_keyboard_uses_release_hub_label(self) -> None:
        keyboard = _build_link_keyboard(
            {"spotify": "https://open.spotify.com/album/1"},
            include_channel_button=False,
            release_page_url="https://album.link/release",
            release_kind="album",
        )

        self.assertEqual(keyboard.inline_keyboard[1][0].text, "💿 Весь релиз")

    def test_podcast_release_keyboard_uses_podcast_hub_label(self) -> None:
        keyboard = _build_link_keyboard(
            {"applePodcasts": "https://podcasts.apple.com/show/1"},
            include_channel_button=False,
            release_page_url="https://podcasts.apple.com/show/1",
            release_kind="podcast",
        )

        self.assertEqual(keyboard.inline_keyboard[1][0].text, "🎙 Все площадки")

    def test_error_keyboard_points_to_supported_services(self) -> None:
        keyboard = _build_error_keyboard("StonerHandBot")

        self.assertEqual(keyboard.inline_keyboard[0][0].text, "Что поддерживается")
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "menu:platforms")
        self.assertEqual(keyboard.inline_keyboard[1][0].text, "🪨 Открыть канал")
        self.assertEqual(keyboard.inline_keyboard[1][1].text, "Поделиться ботом")

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
        self.assertEqual(keyboard.inline_keyboard[0][0].api_kwargs, {"style": "primary"})

    def test_youtube_keyboard_can_hide_channel_button(self) -> None:
        keyboard = _build_youtube_keyboard(
            "https://www.youtube.com/watch?v=abc",
            include_channel_button=False,
        )

        button_texts = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(button_texts, ["📺 Смотреть на YouTube"])
        self.assertEqual(keyboard.inline_keyboard[0][0].api_kwargs, {"style": "danger"})

    def test_nts_keyboard_can_hide_channel_button(self) -> None:
        keyboard = _build_nts_keyboard(
            "https://www.nts.live/shows/example",
            include_channel_button=False,
        )

        button_texts = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(button_texts, ["📡 Открыть на NTS"])
        self.assertEqual(keyboard.inline_keyboard[0][0].api_kwargs, {"style": "primary"})

    def test_playlist_keyboard_can_hide_channel_button(self) -> None:
        keyboard = _build_playlist_keyboard(
            "https://open.spotify.com/playlist/abc",
            include_channel_button=False,
        )

        button_texts = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(button_texts, ["🎛 Открыть плейлист"])
        self.assertEqual(keyboard.inline_keyboard[0][0].api_kwargs, {"style": "primary"})

    def test_artist_keyboard_can_hide_channel_button(self) -> None:
        keyboard = _build_artist_keyboard(
            "https://open.spotify.com/artist/abc",
            include_channel_button=False,
        )

        button_texts = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertEqual(button_texts, ["🧬 Открыть артиста"])
        self.assertEqual(keyboard.inline_keyboard[0][0].api_kwargs, {"style": "primary"})

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
        self.assertEqual(rows[0][0].api_kwargs, {"style": "primary"})
        self.assertEqual(rows[0][1].text, "📺 2. Live Session")
        self.assertEqual(rows[0][1].url, "https://youtu.be/1")
        self.assertEqual(rows[0][1].api_kwargs, {"style": "danger"})

    def test_mixed_collection_keyboard_lists_radio_buttons(self) -> None:
        keyboard = _build_mixed_collection_keyboard(
            [],
            [VideoMatch(title="Live Session", author="Channel", url="https://youtu.be/1")],
            radios=[
                RadioMatch(
                    title="Dark Energy",
                    station="NTS Radio",
                    url="https://www.nts.live/shows/example",
                )
            ],
            include_channel_button=False,
        )

        rows = keyboard.inline_keyboard
        self.assertEqual(rows[0][0].text, "📡 1. Dark Energy")
        self.assertEqual(rows[0][0].url, "https://www.nts.live/shows/example")
        self.assertEqual(rows[0][0].api_kwargs, {"style": "primary"})
        self.assertEqual(rows[0][1].text, "📺 2. Live Session")
        self.assertEqual(rows[0][1].api_kwargs, {"style": "danger"})

    def test_channel_button_is_hidden_only_in_stonerhand_channel(self) -> None:
        self.assertFalse(_should_include_channel_button(ChannelMessageStub()))
        self.assertTrue(_should_include_channel_button(GroupMessageStub()))

    def test_hashtags_are_hidden_only_in_private_chats(self) -> None:
        self.assertFalse(_should_include_hashtags(PrivateMessageStub()))
        self.assertTrue(_should_include_hashtags(GroupMessageStub()))

    def test_intro_keyboard_uses_menu_rows_and_action_row(self) -> None:
        keyboard = _build_intro_keyboard("StonerHandBot")

        rows = keyboard.inline_keyboard
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0][0].text, "🚀 Быстрый старт")
        self.assertEqual(rows[0][1].text, "📖 Как пользоваться")
        self.assertEqual(rows[1][0].text, "🎛 Сервисы")
        self.assertEqual(rows[1][1].text, "📣 Для каналов")
        self.assertEqual(rows[2][0].text, "🧪 Пример поста")
        self.assertEqual(rows[3][0].text, "🪨 Открыть канал")
        self.assertEqual(rows[3][1].text, "Поделиться ботом")
        self.assertEqual(rows[3][0].api_kwargs, {"style": "primary"})
        self.assertEqual(rows[3][1].api_kwargs, {"style": "primary"})

    def test_intro_keyboard_marks_active_menu_item(self) -> None:
        keyboard = _build_intro_keyboard("StonerHandBot", active="menu:platforms")

        self.assertEqual(keyboard.inline_keyboard[1][0].text, "• 🎛 Сервисы")
        self.assertEqual(
            keyboard.inline_keyboard[1][0].api_kwargs,
            {"style": "success"},
        )
        self.assertEqual(
            keyboard.inline_keyboard[0][0].api_kwargs,
            {"style": "primary"},
        )

    def test_menu_text_uses_compact_html_headings(self) -> None:
        self.assertTrue(_menu_text("menu:start").startswith("🎧 <b>"))
        self.assertTrue(_menu_text("menu:help").startswith("<b>Как пользоваться</b>"))

    def test_demo_menu_shows_example_post_and_cta(self) -> None:
        demo_text = _menu_text("menu:demo")

        self.assertTrue(demo_text.startswith("<b>Пример поста</b>"))
        self.assertIn("<blockquote>", demo_text)
        self.assertIn("#stonerhand", demo_text)
        self.assertIn("пришли", demo_text.casefold())

    def test_build_platform_order_moves_primary_platform_first(self) -> None:
        order = _build_platform_order("yandexMusic")

        self.assertEqual(order[0], "yandexMusic")
        self.assertIn("spotify", order)

    def test_build_platform_order_accepts_soundcloud_as_primary(self) -> None:
        order = _build_platform_order("soundcloud")

        self.assertEqual(order[0], "soundcloud")
        self.assertIn("spotify", order)

    def test_build_platform_order_accepts_human_platform_aliases(self) -> None:
        self.assertEqual(_build_platform_order("Spotify")[0], "spotify")
        self.assertEqual(_build_platform_order("apple")[0], "appleMusic")
        self.assertEqual(_build_platform_order("yt music")[0], "youtubeMusic")
        self.assertEqual(_build_platform_order("yandex")[0], "yandexMusic")

    def test_split_source_urls_separates_special_links_from_music(self) -> None:
        (
            artist_urls,
            playlist_urls,
            youtube_urls,
            nts_urls,
            music_urls,
        ) = _split_source_urls(
            [
                "https://open.spotify.com/artist/abc",
                "https://open.spotify.com/playlist/abc",
                "https://youtu.be/video",
                "https://www.nts.live/shows/example",
                "https://open.spotify.com/track/123",
            ]
        )

        self.assertEqual(artist_urls, ["https://open.spotify.com/artist/abc"])
        self.assertEqual(playlist_urls, ["https://open.spotify.com/playlist/abc"])
        self.assertEqual(youtube_urls, ["https://youtu.be/video"])
        self.assertEqual(nts_urls, ["https://www.nts.live/shows/example"])
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

    def test_message_text_falls_back_to_caption(self) -> None:
        message = type("MessageStub", (), {"text": None, "caption": "caption link"})()

        self.assertEqual(_message_text(message), "caption link")

    def test_not_found_message_uses_editorial_copy(self) -> None:
        message = _format_not_found_message(["https://example.com/release"])

        self.assertNotIn("Проверьте", message)

    def test_not_found_message_does_not_repeat_recovery_hint(self) -> None:
        with patch(
            "music_links_bot.bot.pick_phrase",
            return_value="ссылки не собрались - проверь, что это трек или альбом",
        ):
            message = _format_not_found_message(["https://example.com/release"])

        self.assertEqual(
            message,
            "ссылки не собрались - проверь, что это трек или альбом",
        )

    def test_not_found_message_adds_detail_when_phrase_has_no_hint(self) -> None:
        with patch(
            "music_links_bot.bot.pick_phrase",
            return_value="ничего подходящего не собралось",
        ):
            message = _format_not_found_message(["https://example.com/release"])

        self.assertIn(
            "Проверь, что это ссылка на трек, альбом, плейлист, артиста, "
            "подкаст, YouTube-видео или NTS Radio",
            message,
        )

    def test_service_unavailable_message_adds_next_step(self) -> None:
        message = _format_service_unavailable_message("https://open.spotify.com/track/1")

        self.assertIn("Попробуй еще раз чуть позже", message)


class InlineModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_inline_track_result_builds_full_post_with_buttons(self) -> None:
        result = await _build_inline_result(
            "https://open.spotify.com/track/abc",
            ContextStub(),
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.title, "Youth Code — Transitions")
        self.assertEqual(len(result.id), 32)
        self.assertIn("<b>Youth Code</b>", result.input_message_content.message_text)
        keyboard = result.reply_markup.inline_keyboard
        self.assertEqual(keyboard[0][0].text, "🟢 Spotify")

    async def test_inline_youtube_result_uses_video_card(self) -> None:
        result = await _build_inline_result(
            "https://www.youtube.com/watch?v=abc123",
            ContextStub(),
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.title, "SANSAE Live Session Vol.3 - Melon")
        keyboard = result.reply_markup.inline_keyboard
        self.assertEqual(keyboard[0][0].text, "📺 Смотреть на YouTube")

    async def test_inline_playlist_result_uses_playlist_card(self) -> None:
        result = await _build_inline_result(
            "https://open.spotify.com/playlist/37i9dQZF1DX51TD2wakW3K",
            ContextStub(),
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.title, "Women of Punk")
        keyboard = result.reply_markup.inline_keyboard
        self.assertEqual(keyboard[0][0].text, "🎛 Открыть плейлист")


class BotLookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_post_is_deleted_only_after_result_is_sent(self) -> None:
        message = ReplaceableMessageStub()
        bot = BotStub()

        await _send_track_result(
            bot,
            message,
            "готовый пост",
            preview_url=None,
            reply_markup=None,
        )

        self.assertEqual(len(bot.sent_messages), 1)
        self.assertTrue(message.deleted)
        self.assertEqual(message.replies, [])

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
        self.assertIn("Пришли ссылку на трек, альбом, плейлист", message.replies[0])
        keyboard = message.reply_kwargs[0]["reply_markup"].inline_keyboard
        self.assertEqual(keyboard[0][0].text, "Что поддерживается")
        self.assertEqual(context.bot.sent_messages, [])
        self.assertEqual(context.bot.chat_actions, [])

    async def test_youtube_video_links_use_video_post(self) -> None:
        message = PrivateYouTubeMessageStub()
        context = ContextStub()

        with patch("music_links_bot.bot.record_videos") as record_videos:
            await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(len(message.replies), 1)
        self.assertIn("📺 · <b>SANSAE Live Session Vol.3 - Melon</b>", message.replies[0])
        self.assertIn("канал: SANSAE", message.replies[0])
        self.assertNotIn("#stonerhand", message.replies[0])
        # Private chats show an editable loading placeholder instead of a
        # typing action, so no chat action is expected here.
        self.assertEqual(context.bot.chat_actions, [])
        keyboard = message.reply_kwargs[0]["reply_markup"].inline_keyboard
        preview_options = message.reply_kwargs[0]["link_preview_options"]
        self.assertEqual(keyboard[0][0].text, "📺 Смотреть на YouTube")
        self.assertEqual(keyboard[0][0].url, "https://www.youtube.com/watch?v=abc123")
        self.assertTrue(preview_options.prefer_large_media)
        self.assertFalse(preview_options.prefer_small_media)
        self.assertTrue(preview_options.show_above_text)
        record_videos.assert_called_once()

    async def test_nts_links_use_radio_post(self) -> None:
        message = PrivateNTSMessageStub()
        context = ContextStub()

        with patch("music_links_bot.bot.record_radios") as record_radios:
            await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(len(message.replies), 1)
        self.assertIn("📡 · <b>Dark Energy w/ Guest</b>", message.replies[0])
        self.assertIn("станция: NTS Radio", message.replies[0])
        self.assertNotIn("#stonerhand", message.replies[0])
        keyboard = message.reply_kwargs[0]["reply_markup"].inline_keyboard
        preview_options = message.reply_kwargs[0]["link_preview_options"]
        self.assertEqual(keyboard[0][0].text, "📡 Открыть на NTS")
        self.assertEqual(keyboard[0][0].url, "https://www.nts.live/shows/example")
        self.assertTrue(preview_options.prefer_large_media)
        self.assertFalse(preview_options.prefer_small_media)
        self.assertTrue(preview_options.show_above_text)
        record_radios.assert_called_once()

    async def test_spotify_track_links_request_large_preview_above_text(self) -> None:
        message = PrivateSpotifyTrackMessageStub()
        context = ContextStub()

        with patch("music_links_bot.bot.record_matches") as record_matches:
            await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(len(message.replies), 1)
        self.assertIn("<b>Youth Code</b>\nTransitions", message.replies[0])
        keyboard = message.reply_kwargs[0]["reply_markup"].inline_keyboard
        self.assertEqual(keyboard[0][0].text, "🟢 Spotify")
        self.assertEqual(keyboard[1][0].text, "🪩 Все платформы")
        self.assertEqual(keyboard[1][0].url, "https://song.link/transitions")
        preview_options = message.reply_kwargs[0]["link_preview_options"]
        self.assertTrue(preview_options.prefer_large_media)
        self.assertFalse(preview_options.prefer_small_media)
        self.assertTrue(preview_options.show_above_text)
        record_matches.assert_called_once()

    async def test_soundcloud_links_use_soundcloud_fallback_post(self) -> None:
        message = PrivateSoundCloudMessageStub()
        context = ContextStub(songlink_client=FailingLookupClient())

        with patch("music_links_bot.bot.record_matches") as record_matches:
            await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(len(message.replies), 1)
        self.assertIn("<b>Bondage Fairies</b>\nStar Signs", message.replies[0])
        keyboard = message.reply_kwargs[0]["reply_markup"].inline_keyboard
        self.assertEqual(keyboard[0][0].text, "🟠 SoundCloud")
        self.assertEqual(keyboard[0][0].url, "https://soundcloud.com/bondage-fairies/star-signs")
        self.assertEqual(keyboard[1][0].text, "🪩 Все платформы")
        self.assertEqual(keyboard[1][0].url, "https://soundcloud.com/bondage-fairies/star-signs")
        preview_options = message.reply_kwargs[0]["link_preview_options"]
        self.assertTrue(preview_options.prefer_large_media)
        self.assertTrue(preview_options.show_above_text)
        record_matches.assert_called_once()

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
        preview_options = message.reply_kwargs[0]["link_preview_options"]
        self.assertTrue(preview_options.prefer_large_media)
        self.assertFalse(preview_options.prefer_small_media)
        self.assertTrue(preview_options.show_above_text)
        record_playlists.assert_called_once()

    async def test_spotify_artist_links_use_artist_post(self) -> None:
        message = PrivateSpotifyArtistMessageStub()
        context = ContextStub()

        with patch("music_links_bot.bot.record_artists") as record_artists:
            await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(len(message.replies), 1)
        self.assertIn("🧬 · <b>1.Kla$</b>", message.replies[0])
        self.assertIn("профиль: Spotify", message.replies[0])
        self.assertNotIn("#stonerhand #artist", message.replies[0])
        keyboard = message.reply_kwargs[0]["reply_markup"].inline_keyboard
        self.assertEqual(keyboard[0][0].text, "🧬 Открыть артиста")
        self.assertEqual(
            keyboard[0][0].url,
            "https://open.spotify.com/artist/2KbKmQQgFN6MabWViBVlO6?si=123",
        )
        preview_options = message.reply_kwargs[0]["link_preview_options"]
        self.assertTrue(preview_options.prefer_large_media)
        self.assertFalse(preview_options.prefer_small_media)
        self.assertTrue(preview_options.show_above_text)
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
        preview_options = message.reply_kwargs[0]["link_preview_options"]
        self.assertEqual(keyboard[0][0].text, "🎧 1. Youth Code - Transitions")
        self.assertEqual(keyboard[0][1].text, "📺 2. SANSAE Live Session Vol.3 - Melon")
        self.assertTrue(preview_options.prefer_large_media)
        self.assertFalse(preview_options.prefer_small_media)
        self.assertTrue(preview_options.show_above_text)
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

    async def test_mixed_nts_and_youtube_links_keep_both_items(self) -> None:
        message = PrivateMixedNTSMessageStub()
        context = ContextStub()

        with patch("music_links_bot.bot.record_mixed") as record_mixed:
            await track_lookup_message(UpdateStub(message), context)

        self.assertEqual(len(message.replies), 1)
        self.assertTrue(message.replies[0].startswith("<blockquote>радио и видео</blockquote>\n\n"))
        self.assertIn("📡 · <b>Dark Energy w/ Guest</b>", message.replies[0])
        self.assertIn("📺 · <b>SANSAE Live Session Vol.3 - Melon</b>", message.replies[0])
        self.assertNotIn("#radio #video", message.replies[0])
        keyboard = message.reply_kwargs[0]["reply_markup"].inline_keyboard
        self.assertEqual(keyboard[0][0].text, "📡 1. Dark Energy w/ Guest")
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

    async def test_nts_lookup_uses_fallback_when_metadata_fails(self) -> None:
        radios = await _lookup_nts_radios(
            FailingNTSClientStub(),
            ["https://www.nts.live/shows/example"],
        )

        self.assertEqual(len(radios), 1)
        self.assertEqual(radios[0].title, "NTS Radio")
        self.assertEqual(radios[0].station, "NTS Radio")

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

    async def test_lookup_tracks_uses_soundcloud_metadata_fallback(self) -> None:
        tracks, unavailable_urls = await _lookup_tracks(
            FailingLookupClient(),
            ["https://soundcloud.com/bondage-fairies/star-signs"],
            soundcloud_client=SoundCloudClientStub(),
        )

        self.assertEqual(unavailable_urls, [])
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].artist, "Bondage Fairies")
        self.assertEqual(tracks[0].title, "Star Signs")
        self.assertEqual(
            tracks[0].links,
            {"soundcloud": "https://soundcloud.com/bondage-fairies/star-signs"},
        )

    async def test_lookup_tracks_keeps_generic_soundcloud_fallback_when_metadata_fails(self) -> None:
        tracks, unavailable_urls = await _lookup_tracks(
            FailingLookupClient(),
            ["https://soundcloud.com/bondage-fairies/star-signs"],
            soundcloud_client=FailingSoundCloudClientStub(),
        )

        self.assertEqual(unavailable_urls, [])
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].artist, "SoundCloud")
        self.assertEqual(tracks[0].title, "SoundCloud")
        self.assertEqual(
            tracks[0].links,
            {"soundcloud": "https://soundcloud.com/bondage-fairies/star-signs"},
        )


if __name__ == "__main__":
    unittest.main()
