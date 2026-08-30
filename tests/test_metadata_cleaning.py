import unittest

from music_links_bot.draft_model import normalize_track_draft
from music_links_bot.formatter import format_track_message
from music_links_bot.metadata_cleaning import clean_spotify_metadata_title
from music_links_bot.models import TrackMatch


class SpotifyMetadataCleaningTests(unittest.TestCase):
    def test_album_seo_title_keeps_only_release_name(self) -> None:
        self.assertEqual(
            clean_spotify_metadata_title(
                "Czarface Meets Frankie Pulitzer - Album by CZARFACE | Spotify"
            ),
            "Czarface Meets Frankie Pulitzer",
        )

    def test_other_spotify_entity_titles_are_cleaned(self) -> None:
        cases = {
            "Dove - song and lyrics by Karmanjakah | Spotify": "Dove",
            "New Noise - Single by Refused — Spotify": "New Noise",
            "Heavy Rotation - Playlist by Artem - Spotify": "Heavy Rotation",
            "CZARFACE | Spotify": "CZARFACE",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(clean_spotify_metadata_title(value), expected)

    def test_non_spotify_titles_are_not_rewritten(self) -> None:
        for value in ("Spotify Dreams", "Album by Album", "Dove - Single by Night"):
            with self.subTest(value=value):
                self.assertEqual(clean_spotify_metadata_title(value), value)

    def test_track_model_cleans_legacy_cached_metadata(self) -> None:
        track = TrackMatch(
            title="Czarface Meets Frankie Pulitzer - Album by CZARFACE | Spotify",
            artist="CZARFACE",
            links={"spotify": "https://open.spotify.com/album/abc"},
            kind="album",
        )

        self.assertEqual(track.title, "Czarface Meets Frankie Pulitzer")
        self.assertNotIn("Album by", format_track_message(track))
        self.assertNotIn("| Spotify", format_track_message(track))

    def test_legacy_draft_is_upgraded_without_spotify_copy(self) -> None:
        draft = normalize_track_draft(
            {
                "type": "track",
                "item": {
                    "title": (
                        "Czarface Meets Frankie Pulitzer - Album by CZARFACE | Spotify"
                    ),
                    "artist": "CZARFACE",
                    "links": {
                        "spotify": "https://open.spotify.com/album/abc",
                    },
                },
            }
        )

        self.assertIsNotNone(draft)
        assert draft is not None
        self.assertEqual(draft["item"]["title"], "Czarface Meets Frankie Pulitzer")
