import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.formatter import (
    format_collection_message,
    format_track_message,
    format_video_collection_message,
    format_video_message,
    pick_track_emoji,
    prepend_user_text,
)
from music_links_bot.models import TrackMatch, VideoMatch
from music_links_bot.phrases import pick_phrase


class FormatterTests(unittest.TestCase):
    def test_format_track_message_includes_heading_and_hashtag(self) -> None:
        track = TrackMatch(
            title="Song",
            artist="Artist",
            links={"spotify": "https://open.spotify.com/track/1"},
            release_year="2006",
        )

        self.assertEqual(
            format_track_message(track),
            f"{pick_track_emoji(track)} · <b>Artist</b> - Song\n\n"
            f"<i>{pick_phrase('track_cta', 'Artist:Song:song')}</i>\n\n#stonerhand #track",
        )

    def test_format_track_message_omits_missing_year(self) -> None:
        track = TrackMatch(
            title="Song",
            artist="Artist",
            links={"spotify": "https://open.spotify.com/track/1"},
        )

        self.assertEqual(
            format_track_message(track),
            f"{pick_track_emoji(track)} · <b>Artist</b> - Song\n\n"
            f"<i>{pick_phrase('track_cta', 'Artist:Song:song')}</i>\n\n#stonerhand #track",
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
            "💿 · <b>Artist</b> - Album\n\n"
            f"<i>{pick_phrase('album_cta', 'Artist:Album:album')}</i>\n\n#stonerhand #album",
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
            "💿 · <b>Artist</b> - EP\n\n"
            f"<i>{pick_phrase('album_cta', 'Artist:EP:album')}</i>\n\n#stonerhand #album #ep",
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
            "🎙️ · <b>Podcast Show</b> - Episode\n\n"
            f"<i>{pick_phrase('podcast_cta', 'Podcast Show:Episode:podcast')}</i>\n\n#stonerhand #podcast",
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
            "🎙️ · <b>Spotify</b> - Podcast show\n\n"
            f"<i>{pick_phrase('podcast_cta', 'Spotify:Podcast show:podcast')}</i>\n\n#stonerhand #podcast #show",
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
            "@username: Твой текст\n\n",
        )

    def test_prepend_user_text_escapes_html(self) -> None:
        self.assertEqual(
            prepend_user_text("<b>text</b>", author_label="@username"),
            "@username: &lt;b&gt;text&lt;/b&gt;\n\n",
        )

    def test_format_video_message_uses_youtube_style(self) -> None:
        video = VideoMatch(
            title="SANSAE Live Session Vol.3 - Melon",
            author="SANSAE",
            url="https://www.youtube.com/watch?v=abc",
        )

        self.assertEqual(
            format_video_message(video),
            "📺 · <b>SANSAE Live Session Vol.3 - Melon</b>\n"
            "канал: SANSAE\n\n"
            "<i>видео на месте, можно смотреть</i>\n\n"
            "#stonerhand #video",
        )

    def test_format_video_collection_message_lists_videos(self) -> None:
        videos = [
            VideoMatch(title="First", author="One", url="https://youtu.be/1"),
            VideoMatch(title="Second", author="Two", url="https://youtu.be/2"),
        ]

        self.assertEqual(
            format_video_collection_message(videos),
            "сегодня на экране:\n\n"
            "1. 📺 · <b>First</b>\n"
            "2. 📺 · <b>Second</b>\n\n"
            "<i>выбирай, что включить первым</i>\n\n"
            "#stonerhand #collection #video",
        )


if __name__ == "__main__":
    unittest.main()
