import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.formatter import (
    format_artist_collection_message,
    format_artist_message,
    format_collection_message,
    format_mixed_collection_message,
    format_playlist_collection_message,
    format_playlist_message,
    format_radio_collection_message,
    format_radio_message,
    format_track_message,
    format_video_collection_message,
    format_video_message,
    genre_hashtags,
    prepend_user_html,
)
from music_links_bot.models import (
    ArtistMatch,
    PlaylistMatch,
    RadioMatch,
    TrackMatch,
    VideoMatch,
)


class FormatterTests(unittest.TestCase):
    def test_genre_hashtags_normalize_itunes_genres(self) -> None:
        self.assertEqual(genre_hashtags("Heavy Metal"), ["#heavymetal"])
        self.assertEqual(genre_hashtags("Hip-Hop/Rap"), ["#hiphop"])
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

    def test_unverified_genre_falls_back_to_structural_tags(self) -> None:
        from music_links_bot.formatter import build_auto_hashtags

        track = TrackMatch(
            title="Don't Reach For Me",
            artist="Knocked Loose",
            links={},
            genre=None,
        )

        self.assertEqual(build_auto_hashtags(track), "#stonerhand #track")

    def test_track_genre_is_a_hashtag_not_visible_metadata(self) -> None:
        track = TrackMatch(
            title="Rickets",
            artist="Deftones",
            links={"spotify": "https://open.spotify.com/track/1"},
            genre="Hard Rock",
        )

        message = format_track_message(track)

        self.assertEqual(
            message,
            "<b>Deftones — Rickets</b>\n\n🎧 Трек\n\n#stonerhand #track #hardrock",
        )

    def test_track_heading_stays_plain_when_release_hub_exists(self) -> None:
        track = TrackMatch(
            title="Paranoid",
            artist="Black Sabbath",
            links={},
            page_url="https://song.link/paranoid",
        )

        message = format_track_message(track, include_hashtags=False)

        self.assertNotIn("<a href=", message)
        self.assertIn("<b>Black Sabbath — Paranoid</b>\n\n🎧 Трек", message)

    def test_format_track_message_shows_verified_year_and_genre(self) -> None:
        track = TrackMatch(
            title="Song",
            artist="Artist",
            links={"spotify": "https://open.spotify.com/track/1"},
            release_year="2006",
            release_format="single",
            genre="Hard Rock",
        )

        self.assertEqual(
            format_track_message(track),
            "<b>Artist — Song</b>\n\n🎧 Трек · 2006\n\n#stonerhand #track #single #hardrock",
        )

    def test_format_track_message_without_metadata_stays_compact(self) -> None:
        track = TrackMatch(
            title="Song",
            artist="Artist",
            links={"spotify": "https://open.spotify.com/track/1"},
        )

        self.assertEqual(
            format_track_message(track),
            "<b>Artist — Song</b>\n\n🎧 Трек\n\n#stonerhand #track",
        )

    def test_format_track_message_normalizes_untrusted_metadata(self) -> None:
        track = TrackMatch(
            title="Song\nwith     broken spacing " + "x" * 240,
            artist="Artist\nName",
            links={},
        )

        message = format_track_message(track)

        self.assertIn("<b>Artist Name — Song with broken spacing", message)
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
            "<b>Artist — Song</b>\n\n🎧 Трек",
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
            "<b>Artist — Album</b>\n\n💿 Альбом · 2007\n\n#stonerhand #album",
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
            "<b>Artist — EP</b>\n\n💿 EP\n\n#stonerhand #ep",
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
            "<b>Podcast Show — Episode</b>\n\n🎙️ Подкаст\n\n#stonerhand #podcast",
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
            "<b>Spotify — Podcast show</b>\n\n🎙️ Подкаст\n\n#stonerhand #podcast #show",
        )

    def test_format_collection_message_lists_tracks(self) -> None:
        tracks = [
            TrackMatch(title="Song", artist="Artist", links={}, release_year="2006"),
            TrackMatch(title="Album", artist="Band", links={}, kind="album"),
        ]

        self.assertEqual(
            format_collection_message(tracks),
            (
                "🎶 <b>Подборка</b>\n1 трек · 1 альбом\n\n"
                "<code>01</code> · <b>Artist</b> — Song\n"
                "<code>02</code> · <b>Band</b> — Album\n\n"
                "#stonerhand #collection #track #album"
            ),
        )

    def test_collection_keeps_artist_and_title_on_one_logical_line(self) -> None:
        tracks = [
            TrackMatch(title="A Torinói Ló", artist="Kokomo", links={}),
            TrackMatch(
                title="The Lonesome Foghorn Blows",
                artist="Kokomo",
                links={},
            ),
        ]

        message = format_collection_message(tracks)

        self.assertIn("<b>Kokomo</b>\n", message)
        self.assertIn("<code>01</code> · A Torinói Ló", message)
        self.assertIn("<code>02</code> · The Lonesome Foghorn Blows", message)
        self.assertEqual(message.count("<b>Kokomo</b>"), 1)

    def test_collection_keeps_release_count_and_preserves_remaster_suffixes(
        self,
    ) -> None:
        tracks = [
            TrackMatch(
                title="There's No Other Way - 2012 Remaster",
                artist="Blur",
                links={},
            ),
            TrackMatch(title="Fool (Remastered 2012)", artist="Blur", links={}),
        ]

        message = format_collection_message(tracks, title="Подборка · 2 релиза")

        # One artist goes into the heading; the generated title (which already
        # carries the count) becomes the details line.
        self.assertIn("🎶 <b>Blur</b>\nПодборка · 2 релиза\n\n", message)
        self.assertIn(
            "<code>01</code> · There&#x27;s No Other Way - 2012 Remaster\n<code>02</code> · Fool (Remastered 2012)",
            message,
        )
        self.assertIn("Remaster", message)
        self.assertNotIn("🎧", message)

    def test_format_collection_message_includes_release_format_tags(self) -> None:
        tracks = [
            TrackMatch(
                title="Song", artist="Artist", links={}, release_format="single"
            ),
            TrackMatch(
                title="Album",
                artist="Band",
                links={},
                kind="album",
                release_format="ep",
            ),
        ]

        message = format_collection_message(tracks)

        self.assertIn("#stonerhand #collection #track #ep", message)

    def test_collection_editor_formats_groups_notes_and_custom_copy(self) -> None:
        tracks = [
            TrackMatch(
                title="One",
                artist="Sleep",
                links={},
                page_url="https://song.link/one",
            ),
            TrackMatch(
                title="Two",
                artist="Kyuss",
                links={},
                page_url="https://song.link/two",
            ),
        ]

        message = format_collection_message(
            tracks,
            title="Тяжёлый <вечер>",
            intro="Два важных релиза",
            outro="Слушать по порядку",
            hashtags="#stonerhand #doom",
            item_sections=["Новинки", "Финал"],
            item_notes=["Начинаем отсюда", "Закрывает сет"],
        )

        self.assertIn("<b>Тяжёлый &lt;вечер&gt;</b>", message)
        self.assertIn("<b>Новинки</b>", message)
        self.assertIn("<i>↳ Начинаем отсюда</i>", message)
        self.assertIn("<b>Финал</b>", message)
        self.assertIn("<i>Слушать по порядку</i>", message)
        self.assertTrue(message.endswith("#stonerhand #doom"))

    def test_prepend_user_html_keeps_safe_generated_markup(self) -> None:
        self.assertEqual(
            prepend_user_html(
                "<b>Жирный</b> и <i>курсив</i>",
                author_label="@username",
            ),
            ("<blockquote>@username:\n<b>Жирный</b> и <i>курсив</i></blockquote>\n\n"),
        )

    def test_format_video_message_uses_youtube_style(self) -> None:
        video = VideoMatch(
            title="SANSAE Live Session Vol.3 - Melon",
            author="SANSAE",
            url="https://www.youtube.com/watch?v=abc",
        )
        self.assertEqual(
            format_video_message(video),
            "<b>SANSAE Live Session Vol.3 - Melon</b>\n\n"
            "🎤 Live · YouTube · SANSAE\n\n"
            "#stonerhand #video",
        )

    def test_format_radio_message_uses_nts_style(self) -> None:
        radio = RadioMatch(
            title="Dark Energy w/ Guest",
            station="NTS Radio",
            url="https://www.nts.live/shows/example",
        )
        self.assertEqual(
            format_radio_message(radio),
            "<b>Dark Energy w/ Guest</b>\n\n📻 Радио · NTS Radio\n\n#stonerhand #radio",
        )

    def test_format_playlist_message_uses_playlist_style(self) -> None:
        playlist = PlaylistMatch(
            title="Women of Punk",
            platform="Spotify",
            url="https://open.spotify.com/playlist/abc",
        )
        self.assertEqual(
            format_playlist_message(playlist),
            "<b>Women of Punk</b>\n\n🎛 Плейлист · Spotify\n\n#stonerhand #playlist",
        )

    def test_format_artist_message_uses_artist_style(self) -> None:
        artist = ArtistMatch(
            title="1.Kla$",
            platform="Spotify",
            url="https://open.spotify.com/artist/abc",
        )
        self.assertEqual(
            format_artist_message(artist),
            "<b>1.Kla$</b>\n\n🧬 Исполнитель · Spotify\n\n#stonerhand #artist",
        )

    def test_format_playlist_collection_message_lists_playlists(self) -> None:
        playlists = [
            PlaylistMatch(
                title="Women of Punk",
                platform="Spotify",
                url="https://open.spotify.com/playlist/1",
            ),
            PlaylistMatch(
                title="Dark Wave",
                platform="Spotify",
                url="https://open.spotify.com/playlist/2",
            ),
        ]
        self.assertEqual(
            format_playlist_collection_message(playlists),
            "🎛 <b>Подборка</b>\n2 плейлиста\n\n"
            "<code>01</code> · 🎛 Women of Punk\n"
            "<code>02</code> · 🎛 Dark Wave\n\n"
            "#stonerhand #collection #playlist",
        )

    def test_format_artist_collection_message_lists_artists(self) -> None:
        artists = [
            ArtistMatch(
                title="1.Kla$",
                platform="Spotify",
                url="https://open.spotify.com/artist/1",
            ),
            ArtistMatch(
                title="Hotbox",
                platform="Spotify",
                url="https://open.spotify.com/artist/2",
            ),
        ]
        self.assertEqual(
            format_artist_collection_message(artists),
            "🧬 <b>Подборка</b>\n2 артиста\n\n"
            "<code>01</code> · 🧬 1.Kla$\n"
            "<code>02</code> · 🧬 Hotbox\n\n"
            "#stonerhand #collection #artist",
        )

    def test_format_video_collection_message_lists_videos(self) -> None:
        videos = [
            VideoMatch(title="First", author="One", url="https://youtu.be/1"),
            VideoMatch(title="Second", author="Two", url="https://youtu.be/2"),
        ]
        self.assertEqual(
            format_video_collection_message(videos),
            "📺 <b>Подборка</b>\n2 видео\n\n"
            "<code>01</code> · 📺 First\n"
            "<code>02</code> · 📺 Second\n\n"
            "#stonerhand #collection #video",
        )

    def test_format_radio_collection_message_lists_radios(self) -> None:
        radios = [
            RadioMatch(title="First", station="NTS Radio", url="https://nts.live/1"),
            RadioMatch(title="Second", station="NTS Radio", url="https://nts.live/2"),
        ]
        self.assertEqual(
            format_radio_collection_message(radios),
            "📻 <b>Подборка</b>\n2 радиошоу\n\n"
            "<code>01</code> · 📻 First\n"
            "<code>02</code> · 📻 Second\n\n"
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

        self.assertIn("<b>Песня + live</b>", message)
        self.assertIn("<b>Artist</b> — Song", message)
        self.assertIn("🎤 · <b>Live</b>", message)
        self.assertNotIn("<a href=", message)
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

        self.assertIn("· 🎛 Women of Punk", message)
        self.assertIn("· 🎤 Live", message)
        self.assertNotIn("<a href=", message)
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

        self.assertIn("· 🧬 1.Kla$", message)
        self.assertIn("· 🎤 Live", message)
        self.assertNotIn("<a href=", message)
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

        self.assertIn("· 📻 Dark Energy", message)
        self.assertIn("· 🎤 Live", message)
        self.assertNotIn("<a href=", message)
        self.assertIn("#stonerhand #collection #radio #video", message)


class ArtistRunTests(unittest.TestCase):
    def test_runs_that_cover_the_whole_list_get_artist_headings(self) -> None:
        tracks = [
            TrackMatch(artist="MSI", title="Pay For It", links={}),
            TrackMatch(artist="MSI", title="1989", links={}),
            TrackMatch(artist="Kyuss", title="Green Machine", links={}),
            TrackMatch(artist="Kyuss", title="Gardenia", links={}),
        ]

        message = format_collection_message(tracks, include_hashtags=False)

        self.assertIn(
            "<b>MSI</b>\n<code>01</code> · Pay For It\n<code>02</code> · 1989\n\n"
            "<b>Kyuss</b>\n<code>03</code> · Green Machine\n<code>04</code> · Gardenia",
            message,
        )

    def test_partial_runs_keep_one_flat_style(self) -> None:
        tracks = [
            TrackMatch(artist="NONCONS", title="Dance", links={}),
            TrackMatch(artist="NONCONS", title="Born Dead Fighter", links={}),
            TrackMatch(artist="The Growlers", title="Dope on a Rope", links={}),
        ]

        message = format_collection_message(
            tracks, title="Подборка · 3 релиза", include_hashtags=False
        )

        self.assertTrue(message.startswith("🎶 <b>Подборка</b>\n3 трека\n\n"))
        self.assertIn("<code>01</code> · <b>NONCONS</b> — Dance", message)
        self.assertIn("<code>03</code> · <b>The Growlers</b> — Dope on a Rope", message)


if __name__ == "__main__":
    unittest.main()
