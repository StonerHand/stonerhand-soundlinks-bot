import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.formatter import (
    ARTIST_COLLECTION_SIGNATURES,
    ARTIST_SIGNATURES,
    PLAYLIST_COLLECTION_SIGNATURES,
    PLAYLIST_SIGNATURES,
    RADIO_COLLECTION_SIGNATURES,
    RADIO_SIGNATURES,
    VIDEO_COLLECTION_SIGNATURES,
    VIDEO_SIGNATURES,
    _pick_signature,
    format_collection_message,
    format_artist_collection_message,
    format_artist_message,
    format_mixed_collection_message,
    format_playlist_collection_message,
    format_playlist_message,
    format_radio_collection_message,
    format_radio_message,
    format_track_message,
    genre_hashtags,
    format_video_collection_message,
    format_video_message,
    pick_track_emoji,
    prepend_user_text,
    prepend_user_html,
)
from music_links_bot.models import (
    ArtistMatch,
    PlaylistMatch,
    RadioMatch,
    TrackMatch,
    VideoMatch,
)
from music_links_bot.phrases import pick_phrase


class FormatterTests(unittest.TestCase):
    def test_genre_hashtags_normalize_itunes_genres(self) -> None:
        self.assertEqual(genre_hashtags("Heavy Metal"), ["#heavymetal"])
        self.assertEqual(genre_hashtags("Hip-Hop/Rap"), ["#hiphop", "#rap"])
        self.assertEqual(genre_hashtags("R&B/Soul"), ["#rnb", "#soul"])
        self.assertEqual(genre_hashtags("Music"), [])
        self.assertEqual(genre_hashtags(None), [])

    def test_track_hashtags_include_genre(self) -> None:
        from music_links_bot.formatter import build_auto_hashtags

        track = TrackMatch(
            title="Paranoid",
            artist="Black Sabbath",
            links={},
            genre="Heavy Metal",
        )

        self.assertEqual(build_auto_hashtags(track), "#stonerhand #track #heavymetal")

    def test_track_cta_links_to_release_hub(self) -> None:
        track = TrackMatch(
            title="Paranoid",
            artist="Black Sabbath",
            links={},
            page_url="https://song.link/paranoid",
        )

        message = format_track_message(track, include_hashtags=False)

        self.assertIn('<a href="https://song.link/paranoid">', message)

    def test_format_track_message_includes_heading_and_hashtag(self) -> None:
        track = TrackMatch(
            title="Song",
            artist="Artist",
            links={"spotify": "https://open.spotify.com/track/1"},
            release_year="2006",
        )

        self.assertEqual(
            format_track_message(track),
            f"{pick_track_emoji(track)} · <b>Artist</b>\n"
            "Song\n\n"
            f"<i>{pick_phrase('track_cta', 'Artist:Song:song')}</i>\n\n"
            "#stonerhand #track",
        )

    def test_format_track_message_omits_missing_year(self) -> None:
        track = TrackMatch(
            title="Song",
            artist="Artist",
            links={"spotify": "https://open.spotify.com/track/1"},
        )

        self.assertEqual(
            format_track_message(track),
            f"{pick_track_emoji(track)} · <b>Artist</b>\n"
            "Song\n\n"
            f"<i>{pick_phrase('track_cta', 'Artist:Song:song')}</i>\n\n"
            "#stonerhand #track",
        )

    def test_format_track_message_normalizes_untrusted_metadata(self) -> None:
        track = TrackMatch(
            title="Song\nwith     broken spacing " + "x" * 240,
            artist="Artist\nName",
            links={},
        )

        message = format_track_message(track)

        self.assertIn("<b>Artist Name</b>\nSong with broken spacing", message)
        self.assertIn("…", message)
        self.assertNotIn("Song\nwith", message)

    def test_format_track_message_can_hide_hashtags(self) -> None:
        track = TrackMatch(
            title="Song",
            artist="Artist",
            links={"spotify": "https://open.spotify.com/track/1"},
        )

        self.assertEqual(
            format_track_message(track, include_hashtags=False),
            f"{pick_track_emoji(track)} · <b>Artist</b>\n"
            "Song\n\n"
            f"<i>{pick_phrase('track_cta', 'Artist:Song:song')}</i>",
        )

    def test_format_track_message_marks_album(self) -> None:
        track = TrackMatch(
            title="Album",
            artist="Artist",
            links={"spotify": "https://open.spotify.com/album/1"},
            release_year="2007",
            kind="album",
        )

        self.assertEqual(
            format_track_message(track),
            "💿 · <b>Artist</b>\nAlbum\n\n"
            f"<i>{pick_phrase('album_cta', 'Artist:Album:album')}</i>\n\n"
            "#stonerhand #album",
        )

    def test_format_track_message_marks_ep(self) -> None:
        track = TrackMatch(
            title="EP",
            artist="Artist",
            links={"spotify": "https://open.spotify.com/album/1"},
            kind="album",
            release_format="ep",
        )

        self.assertEqual(
            format_track_message(track),
            "💿 · <b>Artist</b>\nEP\n\n"
            f"<i>{pick_phrase('album_cta', 'Artist:EP:album')}</i>\n\n"
            "#stonerhand #album #ep",
        )

    def test_format_track_message_marks_podcast(self) -> None:
        track = TrackMatch(
            title="Episode",
            artist="Podcast Show",
            links={"spotify": "https://open.spotify.com/episode/1"},
            kind="podcast",
        )

        self.assertEqual(
            format_track_message(track),
            "🎙️ · <b>Podcast Show</b>\nвыпуск: Episode\n\n"
            f"<i>{pick_phrase('podcast_cta', 'Podcast Show:Episode:podcast')}</i>\n\n"
            "#stonerhand #podcast",
        )

    def test_format_track_message_marks_podcast_show(self) -> None:
        track = TrackMatch(
            title="Podcast show",
            artist="Spotify",
            links={"spotify": "https://open.spotify.com/show/1"},
            kind="podcast",
            release_format="show",
        )

        self.assertEqual(
            format_track_message(track),
            "🎙️ · <b>Spotify</b>\nшоу: Podcast show\n\n"
            f"<i>{pick_phrase('podcast_cta', 'Spotify:Podcast show:podcast')}</i>\n\n"
            "#stonerhand #podcast #show",
        )

    def test_format_collection_message_lists_tracks(self) -> None:
        tracks = [
            TrackMatch(title="Song", artist="Artist", links={}, release_year="2006"),
            TrackMatch(title="Album", artist="Band", links={}, kind="album"),
        ]

        self.assertEqual(
            format_collection_message(tracks),
            (
                f"{pick_phrase('collection_intro', 'Artist:Song:song|Band:Album:album')}\n\n"
                f"1. {pick_track_emoji(tracks[0])} · <b>Artist</b> - Song\n"
                "2. 💿 · <b>Band</b> - Album\n\n"
                f"<i>{pick_phrase('collection_cta', 'Artist:Song:song|Band:Album:album')}</i>\n\n"
                "#stonerhand #collection #track #album"
            ),
        )

    def test_format_collection_message_includes_release_format_tags(self) -> None:
        tracks = [
            TrackMatch(title="Song", artist="Artist", links={}, release_format="single"),
            TrackMatch(title="Album", artist="Band", links={}, kind="album", release_format="ep"),
        ]

        message = format_collection_message(tracks)

        self.assertIn("#stonerhand #collection #track #album #single #ep", message)

    def test_prepend_user_text_formats_username_prefix(self) -> None:
        self.assertEqual(
            prepend_user_text("Твой текст", author_label="@username"),
            "<blockquote>@username:\nТвой текст</blockquote>\n\n",
        )

    def test_prepend_user_text_escapes_html(self) -> None:
        self.assertEqual(
            prepend_user_text("<b>text</b>", author_label="@username"),
            "<blockquote>@username:\n&lt;b&gt;text&lt;/b&gt;</blockquote>\n\n",
        )

    def test_prepend_user_text_preserves_paragraphs_and_spacing(self) -> None:
        self.assertEqual(
            prepend_user_text(
                "Первый абзац\n\n  - пункт один\n  - пункт два",
                author_label="@username",
            ),
            (
                "<blockquote>@username:\nПервый абзац\n\n"
                "  - пункт один\n  - пункт два</blockquote>\n\n"
            ),
        )

    def test_prepend_user_html_keeps_safe_generated_markup(self) -> None:
        self.assertEqual(
            prepend_user_html(
                "<b>Жирный</b> и <i>курсив</i>",
                author_label="@username",
            ),
            (
                "<blockquote>@username:\n"
                "<b>Жирный</b> и <i>курсив</i></blockquote>\n\n"
            ),
        )

    def test_format_video_message_uses_youtube_style(self) -> None:
        video = VideoMatch(
            title="SANSAE Live Session Vol.3 - Melon",
            author="SANSAE",
            url="https://www.youtube.com/watch?v=abc",
        )
        signature = _pick_signature(
            VIDEO_SIGNATURES,
            "SANSAE:SANSAE Live Session Vol.3 - Melon:https://www.youtube.com/watch?v=abc",
        )

        self.assertEqual(
            format_video_message(video),
            "📺 · <b>SANSAE Live Session Vol.3 - Melon</b>\n"
            "канал: SANSAE\n\n"
            f"<i>{signature}</i>\n\n"
            "#stonerhand #video",
        )

    def test_format_radio_message_uses_nts_style(self) -> None:
        radio = RadioMatch(
            title="Dark Energy w/ Guest",
            station="NTS Radio",
            url="https://www.nts.live/shows/example",
        )
        signature = _pick_signature(
            RADIO_SIGNATURES,
            "NTS Radio:Dark Energy w/ Guest:https://www.nts.live/shows/example",
        )

        self.assertEqual(
            format_radio_message(radio),
            "📡 · <b>Dark Energy w/ Guest</b>\n"
            "станция: NTS Radio\n\n"
            f"<i>{signature}</i>\n\n"
            "#stonerhand #radio",
        )

    def test_format_playlist_message_uses_playlist_style(self) -> None:
        playlist = PlaylistMatch(
            title="Women of Punk",
            platform="Spotify",
            url="https://open.spotify.com/playlist/abc",
        )
        signature = _pick_signature(
            PLAYLIST_SIGNATURES,
            "Spotify:Women of Punk:https://open.spotify.com/playlist/abc",
        )

        self.assertEqual(
            format_playlist_message(playlist),
            "🎛 · <b>Women of Punk</b>\n"
            "платформа: Spotify\n\n"
            f"<i>{signature}</i>\n\n"
            "#stonerhand #playlist",
        )

    def test_format_artist_message_uses_artist_style(self) -> None:
        artist = ArtistMatch(
            title="1.Kla$",
            platform="Spotify",
            url="https://open.spotify.com/artist/abc",
        )
        signature = _pick_signature(
            ARTIST_SIGNATURES,
            "Spotify:1.Kla$:https://open.spotify.com/artist/abc",
        )

        self.assertEqual(
            format_artist_message(artist),
            "🧬 · <b>1.Kla$</b>\n"
            "профиль: Spotify\n\n"
            f"<i>{signature}</i>\n\n"
            "#stonerhand #artist",
        )

    def test_format_playlist_collection_message_lists_playlists(self) -> None:
        playlists = [
            PlaylistMatch(title="Women of Punk", platform="Spotify", url="https://open.spotify.com/playlist/1"),
            PlaylistMatch(title="Dark Wave", platform="Spotify", url="https://open.spotify.com/playlist/2"),
        ]
        signature = _pick_signature(
            PLAYLIST_COLLECTION_SIGNATURES,
            "https://open.spotify.com/playlist/1|https://open.spotify.com/playlist/2",
        )

        self.assertEqual(
            format_playlist_collection_message(playlists),
            "сегодня в плейлистах:\n\n"
            "1. 🎛 · <b>Women of Punk</b>\n"
            "2. 🎛 · <b>Dark Wave</b>\n\n"
            f"<i>{signature}</i>\n\n"
            "#stonerhand #collection #playlist",
        )

    def test_format_artist_collection_message_lists_artists(self) -> None:
        artists = [
            ArtistMatch(title="1.Kla$", platform="Spotify", url="https://open.spotify.com/artist/1"),
            ArtistMatch(title="Hotbox", platform="Spotify", url="https://open.spotify.com/artist/2"),
        ]
        signature = _pick_signature(
            ARTIST_COLLECTION_SIGNATURES,
            "https://open.spotify.com/artist/1|https://open.spotify.com/artist/2",
        )

        self.assertEqual(
            format_artist_collection_message(artists),
            "сегодня по артистам:\n\n"
            "1. 🧬 · <b>1.Kla$</b>\n"
            "2. 🧬 · <b>Hotbox</b>\n\n"
            f"<i>{signature}</i>\n\n"
            "#stonerhand #collection #artist",
        )

    def test_format_video_collection_message_lists_videos(self) -> None:
        videos = [
            VideoMatch(title="First", author="One", url="https://youtu.be/1"),
            VideoMatch(title="Second", author="Two", url="https://youtu.be/2"),
        ]
        signature = _pick_signature(
            VIDEO_COLLECTION_SIGNATURES,
            "https://youtu.be/1|https://youtu.be/2",
        )

        self.assertEqual(
            format_video_collection_message(videos),
            "сегодня на экране:\n\n"
            "1. 📺 · <b>First</b>\n"
            "2. 📺 · <b>Second</b>\n\n"
            f"<i>{signature}</i>\n\n"
            "#stonerhand #collection #video",
        )

    def test_format_radio_collection_message_lists_radios(self) -> None:
        radios = [
            RadioMatch(title="First", station="NTS Radio", url="https://nts.live/1"),
            RadioMatch(title="Second", station="NTS Radio", url="https://nts.live/2"),
        ]
        signature = _pick_signature(
            RADIO_COLLECTION_SIGNATURES,
            "https://nts.live/1|https://nts.live/2",
        )

        self.assertEqual(
            format_radio_collection_message(radios),
            "сегодня на NTS:\n\n"
            "1. 📡 · <b>First</b>\n"
            "2. 📡 · <b>Second</b>\n\n"
            f"<i>{signature}</i>\n\n"
            "#stonerhand #collection #radio",
        )

    def test_format_mixed_collection_message_lists_tracks_and_videos(self) -> None:
        tracks = [
            TrackMatch(title="Song", artist="Artist", links={}),
        ]
        videos = [
            VideoMatch(title="Live", author="Channel", url="https://youtu.be/1"),
        ]

        message = format_mixed_collection_message(tracks, videos)

        self.assertIn(f"1. {pick_track_emoji(tracks[0])} · <b>Artist</b> - Song", message)
        self.assertIn("2. 📺 · <b>Live</b>", message)
        self.assertIn("#stonerhand #collection #track #video", message)

    def test_format_mixed_collection_message_lists_playlists(self) -> None:
        playlists = [
            PlaylistMatch(
                title="Women of Punk",
                platform="Spotify",
                url="https://open.spotify.com/playlist/1",
            )
        ]
        videos = [
            VideoMatch(title="Live", author="Channel", url="https://youtu.be/1"),
        ]

        message = format_mixed_collection_message([], videos, playlists)

        self.assertIn("1. 🎛 · <b>Women of Punk</b>", message)
        self.assertIn("2. 📺 · <b>Live</b>", message)
        self.assertIn("#stonerhand #collection #playlist #video", message)

    def test_format_mixed_collection_message_lists_artists(self) -> None:
        artists = [
            ArtistMatch(
                title="1.Kla$",
                platform="Spotify",
                url="https://open.spotify.com/artist/1",
            )
        ]
        videos = [
            VideoMatch(title="Live", author="Channel", url="https://youtu.be/1"),
        ]

        message = format_mixed_collection_message([], videos, artists=artists)

        self.assertIn("1. 🧬 · <b>1.Kla$</b>", message)
        self.assertIn("2. 📺 · <b>Live</b>", message)
        self.assertIn("#stonerhand #collection #artist #video", message)

    def test_format_mixed_collection_message_lists_radios(self) -> None:
        radios = [
            RadioMatch(
                title="Dark Energy",
                station="NTS Radio",
                url="https://nts.live/1",
            )
        ]
        videos = [
            VideoMatch(title="Live", author="Channel", url="https://youtu.be/1"),
        ]

        message = format_mixed_collection_message([], videos, radios=radios)

        self.assertIn("1. 📡 · <b>Dark Energy</b>", message)
        self.assertIn("2. 📺 · <b>Live</b>", message)
        self.assertIn("#stonerhand #collection #radio #video", message)


if __name__ == "__main__":
    unittest.main()
