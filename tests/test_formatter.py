import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from music_links_bot.formatter import (
    format_collection_message,
    format_track_message,
    pick_track_emoji,
    prepend_user_text,
)
from music_links_bot.models import TrackMatch
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

    def test_prepend_user_text_formats_username_prefix(self) -> None:
        self.assertEqual(
            prepend_user_text("Твой текст", author_label="@username"),
            "@username: «Твой текст»\n\n",
        )

    def test_prepend_user_text_escapes_html(self) -> None:
        self.assertEqual(
            prepend_user_text("<b>text</b>", author_label="@username"),
            "@username: «&lt;b&gt;text&lt;/b&gt;»\n\n",
        )


if __name__ == "__main__":
    unittest.main()
